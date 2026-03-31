"""官公需情報ポータルサイト API連携

https://www.kkj.go.jp/api/ の検索APIを使用して
国・自治体の入札案件（印刷関連）を取得する。

API仕様: https://www.kkj.go.jp/doc/ja/api_guide.pdf
"""

from __future__ import annotations

import logging
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

    procedure_code = _text(item, "ProcedureType") or ""
    bid_type = KKJ_PROCEDURE_TYPES.get(procedure_code, procedure_code or "不明")

    publish_date = _text(item, "CftIssueDate") or ""
    if publish_date:
        publish_date = publish_date[:10]
    if deadline:
        deadline = deadline[:10]

    detail_url = _text(item, "ExternalDocumentURI") or ""

    # 発注元: OrganizationName を優先、なければ PrefectureName
    organization = org if org else prefecture

    return BidProject(
        title=title.strip(),
        organization=organization.strip(),
        bid_type=bid_type,
        publish_date=publish_date,
        deadline=deadline,
        detail_url=detail_url,
        source=KKJ_SOURCE_NAME,
    )


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
