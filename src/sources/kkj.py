"""官公需情報ポータルサイト API連携

https://www.kkj.go.jp/api/ の検索APIを使用して
国・自治体の入札案件（印刷関連）を取得する。

API仕様: https://www.kkj.go.jp/doc/ja/api_guide.pdf
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import defusedxml.ElementTree as DefusedET
import requests

from src.config import (
    CRAWL,
    EXCLUDE_KEYWORDS,
    KKJ_API_URL,
    KKJ_PROCEDURE_TYPES,
    KKJ_SOURCE_NAME,
    KKJ_TARGET_CATEGORIES,
    SEARCH_KEYWORDS,
    TARGET_PREFECTURES,
)
from src.core.extractor import extract_eligibility
from src.core.models import BidProject

logger = logging.getLogger(__name__)


def _build_date_range(days: int = 30) -> str:
    """直近N日間の日付範囲文字列を構築する（API用）"""
    start = datetime.now() - timedelta(days=days)
    return f"{start.strftime('%Y-%m-%d')}/"


def _fetch_xml(keyword: str, category: str, date_range: str) -> ET.Element | None:
    """官公需APIからXMLを取得する"""
    params = {
        "Query": keyword,
        "Category": category,
        "CFT_Issue_Date": date_range,
        "Count": "100",
    }

    for attempt in range(CRAWL.retry_count + 1):
        try:
            response = requests.get(
                KKJ_API_URL,
                params=params,
                timeout=CRAWL.timeout_sec,
                headers={"User-Agent": CRAWL.user_agent},
            )
            if response.status_code == 200:
                return DefusedET.fromstring(response.content)
            logger.warning("KKJ API HTTP %d: keyword=%s", response.status_code, keyword)
        except (requests.RequestException, ET.ParseError) as e:
            logger.warning("KKJ API エラー (attempt %d): %s", attempt + 1, e)
            if attempt < CRAWL.retry_count:
                time.sleep(CRAWL.retry_delay_sec)

    return None


def _parse_project(item: ET.Element) -> BidProject | None:
    """XML要素から BidProject を生成する"""
    title = _text(item, "ProjectName")
    if not title:
        return None

    org = _text(item, "OrganizationName") or ""
    prefecture = _text(item, "PrefectureName") or ""

    # 地域フィルタ: 対象都道府県 or 空欄（中央省庁）
    if prefecture and not any(pref in prefecture for pref in TARGET_PREFECTURES):
        return None

    # D等級チェック（クライアント側）: Certificationフィールドがある場合のみ
    cert = _text(item, "Certification") or ""
    if cert and "D" not in cert.upper():
        return None

    # 案件名に印刷関連キーワードが含まれない場合は除外
    # （APIは説明文中の「納入印刷物」等でもヒットするため、タイトルで再フィルタ）
    _TITLE_KEYWORDS = [
        *SEARCH_KEYWORDS,  # 印刷,製本,広報誌,パンフレット,チラシ,ポスター,冊子,封筒
        "用紙", "図書", "トナー", "インク", "刷成", "名刺",
        "カタログ", "リーフレット", "白書", "概要", "年報",
        "複写", "コピー", "プリント",
    ]
    if not any(kw in title for kw in _TITLE_KEYWORDS):
        return None

    # 除外キーワードチェック
    if any(kw in title for kw in EXCLUDE_KEYWORDS):
        return None

    # 締切チェック
    deadline = _text(item, "PeriodEndTime") or ""
    if deadline:
        try:
            deadline_date = datetime.strptime(deadline[:10], "%Y-%m-%d")
            if deadline_date < datetime.now():
                return None
        except ValueError:
            pass

    description = _text(item, "ProjectDescription") or ""

    procedure_code = _text(item, "ProcedureType") or ""
    bid_type = KKJ_PROCEDURE_TYPES.get(procedure_code, procedure_code or "")

    # XMLに入札方式がない場合、説明文やタイトルから抽出
    if not bid_type:
        bid_type = _extract_bid_type(title, description)

    publish_date = _text(item, "CftIssueDate") or ""
    if publish_date:
        publish_date = publish_date[:10]
    if deadline:
        deadline = deadline[:10]

    detail_url = _text(item, "ExternalDocumentURI") or ""
    # URL検証: http/httpsのみ許可（javascript:等のインジェクション防止）
    if detail_url and not detail_url.startswith(("http://", "https://")):
        detail_url = ""

    # 締切日がXMLにない場合、descriptionから抽出を試みる
    if not deadline and description:
        deadline = _extract_deadline_from_text(description)

    # 他の日付フィールドも試す
    if not deadline:
        for tag in ("TenderSubmissionDeadline", "OpeningTendersEvent"):
            val = _text(item, tag) or ""
            if val:
                deadline = val[:10]
                break

    # 仕様書URLを添付ファイルから抽出、なければテキストからフォールバック
    spec_url = _extract_spec_url(item)
    if not spec_url:
        spec_url = _extract_spec_url_from_text(description)

    # 発注元: OrganizationName を優先、なければ PrefectureName
    organization = org if org else prefecture

    # 応募条件を公告テキストから抽出
    eligibility = extract_eligibility(description, organization.strip())

    return BidProject(
        title=title.strip(),
        organization=organization.strip(),
        bid_type=bid_type,
        publish_date=publish_date,
        deadline=deadline,
        detail_url=detail_url,
        spec_url=spec_url,
        source=KKJ_SOURCE_NAME,
        description=description,
        eligibility_overall=eligibility.overall,
        eligibility_grade=eligibility.grade_text,
        eligibility_region=eligibility.region_text,
        eligibility_method=eligibility.submission_method,
        eligibility_contact=eligibility.contact,
    )


# 入札方式の抽出（完全一致優先、部分一致フォールバック）
_BID_TYPE_EXACT: list[tuple[str, str]] = [
    ("一般競争入札", "一般競争入札"),
    ("指名競争入札", "指名競争入札"),
    ("条件付き一般競争入札", "条件付一般競争入札"),
    ("希望制指名競争入札", "希望制指名競争入札"),
    ("随意契約", "随意契約"),
    ("公募型プロポーザル", "公募型プロポーザル"),
    ("企画競争", "企画競争"),
    ("見積合わせ", "見積合わせ"),
]

_BID_TYPE_PARTIAL: list[tuple[str, str]] = [
    ("一般競争", "一般競争入札"),
    ("プロポーザル", "公募型プロポーザル"),
    ("見積", "見積合わせ"),
    ("公募", "公募"),
]


def _extract_bid_type(title: str, description: str) -> str:
    """タイトルと説明文から入札方式を抽出する"""
    text = title + " " + description

    # 完全一致を優先
    for keyword, label in _BID_TYPE_EXACT:
        if keyword in text:
            return label

    # 部分一致フォールバック
    for keyword, label in _BID_TYPE_PARTIAL:
        if keyword in text:
            return label

    return "不明"


# 締切日抽出用パターン（優先度順）
_DEADLINE_PATTERNS: list[re.Pattern[str]] = [
    # 入札書の受付/提出期限
    re.compile(
        r"入札(?:書)?の?(?:受付|提出)(?:期限|締切).*?"
        r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日"
    ),
    # 入札日時
    re.compile(
        r"入札[日時]*\s*[：:]?\s*令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日"
    ),
    # 提出/受付/申請の期限・締切
    re.compile(
        r"(?:提出|受付|申請|申込).{0,15}?(?:期限|締切|まで).{0,20}?"
        r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日"
    ),
    # 締切日/締切：
    re.compile(
        r"締切\s*[日：:].{0,20}?令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日"
    ),
    # 応募/願い出/参加申請の期間・期限
    re.compile(
        r"(?:応募|願い出|参加申請|参加資格申請|入札参加).{0,15}?"
        r"(?:期間|期限|まで).{0,30}?"
        r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日"
    ),
    # 開札日（入札の結果発表日＝入札締切の参考）
    re.compile(
        r"開札.{0,10}?令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日"
    ),
]

# 最終フォールバック: 本文中の全日付を抽出して最も未来のものを返す
_DATE_GENERIC = re.compile(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")


def _reiwa_to_date(reiwa_year: int, month: int, day: int) -> datetime | None:
    """令和年をdatetimeに変換（無効な日付はNone）"""
    try:
        return datetime(reiwa_year + 2018, month, day)
    except ValueError:
        return None


def _extract_deadline_from_text(text: str) -> str:
    """説明文から締切日を正規表現で抽出する

    明確なキーワード（入札書提出期限、開札日等）に隣接する日付のみ抽出。
    汎用フォールバック（全日付から最近のもの）は廃止 — 契約期間を誤抽出するため。
    """
    for pattern in _DEADLINE_PATTERNS:
        m = pattern.search(text)
        if m:
            dt = _reiwa_to_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if dt:
                return dt.strftime("%Y-%m-%d")

    return ""


def _text(element: ET.Element, tag: str) -> str | None:
    """XML要素から子要素のテキストを取得する（名前空間対応）"""
    # 名前空間なし
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()

    # 名前空間付きで探索
    for child in element:
        local_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local_name == tag and child.text:
            return child.text.strip()

    return None


def _extract_spec_url(item: ET.Element) -> str:
    """添付ファイルから仕様書URLを抽出する"""
    for attachment in item.iter():
        tag = attachment.tag.split("}")[-1] if "}" in attachment.tag else attachment.tag
        if tag == "Attachment":
            name = ""
            uri = ""
            for child in attachment:
                child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_tag == "Name" and child.text:
                    name = child.text.strip()
                elif child_tag == "Uri" and child.text:
                    uri = child.text.strip()
            if uri and uri.startswith(("http://", "https://")):
                if "仕様" in name or "仕様書" in name:
                    return uri
    return ""


# テキスト内URL抽出用
_URL_PATTERN = re.compile(r"https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&'*+,;=%]+")
_PORTAL_GENERIC = "pps-web-biz/"

# URL自体またはURLの直前ラベルに含まれるべきキーワード
_SPEC_URL_KEYWORDS = ["仕様書", "shiyou", "spec"]
# URLの直前に「仕様書」ラベルがある場合のパターン
_SPEC_LABEL_PATTERN = re.compile(
    r"(?:仕様書|入札説明書)\s*(?:[（(][^）)]*[）)])?[\s：:はを]*"
    r"(https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&'*+,;=%]+)"
)


def _extract_spec_url_from_text(text: str) -> str:
    """公告テキストからURLを抽出し、仕様書らしきものを返す

    厳格なルール:
    - URLのパス/ファイル名に「仕様」「spec」が含まれる、または
    - URLの直前に「仕様書」「入札説明書」というラベルがある
    - 汎用PDFや無関係なURLは返さない
    """
    if not text:
        return ""

    # 方法1: 「仕様書 https://...」のようにラベル直後にURLがあるパターン
    m = _SPEC_LABEL_PATTERN.search(text)
    if m:
        url = m.group(1)
        if url.startswith(("http://", "https://")) and _PORTAL_GENERIC not in url:
            return url

    # 方法2: URL自体に仕様書関連のキーワードが含まれる
    urls = _URL_PATTERN.findall(text)
    for url in urls:
        if _PORTAL_GENERIC in url:
            continue
        if not url.startswith(("http://", "https://")):
            continue
        url_lower = url.lower()
        if any(kw in url_lower for kw in _SPEC_URL_KEYWORDS):
            return url

    # 仕様書と明確に紐付けられないURLは返さない
    return ""


def _find_all_items(root: ET.Element) -> list[ET.Element]:
    """ルート要素から案件要素のリストを取得する（名前空間対応）"""
    # 直接子要素を探す
    items = root.findall(".//SearchResult")
    if items:
        return items

    # 名前空間付きで探索
    items = []
    for elem in root.iter():
        local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local_name == "SearchResult":
            items.append(elem)

    return items


def fetch_kkj_projects() -> list[BidProject]:
    """官公需APIから印刷関連の入札案件を取得する

    キーワード × カテゴリの組み合わせで複数回APIを呼び出し、
    地域・除外・締切フィルタを適用して返す。
    """
    date_range = _build_date_range(30)
    all_projects: list[BidProject] = []
    seen_keys: set[str] = set()

    for keyword in SEARCH_KEYWORDS:
        for category in KKJ_TARGET_CATEGORIES:
            root = _fetch_xml(keyword, category, date_range)
            if root is None:
                continue

            items = _find_all_items(root)
            for item in items:
                project = _parse_project(item)
                if project is None:
                    continue

                if project.dedup_key not in seen_keys:
                    seen_keys.add(project.dedup_key)
                    all_projects.append(project)

            time.sleep(CRAWL.request_interval_sec)

    logger.info("官公需API: %d件取得（フィルタ済み）", len(all_projects))
    return all_projects
