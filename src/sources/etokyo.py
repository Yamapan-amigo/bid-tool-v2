"""e-Tokyo（東京電子自治体共同運営）入札情報取得

セッションベースのJSPアプリケーションに対して
requests.Session() でCookie自動管理 + multipart/form-data POSTで
検索→結果一覧を取得し、BeautifulSoupで案件データを抽出する。
"""

from __future__ import annotations

import logging
import re
import time

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from src.config import (
    CRAWL,
    ETOKYO_BASE_URL,
    ETOKYO_BID_TYPE_MAP,
    ETOKYO_CITY_CODES,
    ETOKYO_ENCODING,
    ETOKYO_SOURCE_NAME,
    ETOKYO_WARD_CODES,
    SEARCH_KEYWORDS,
)
from src.core.models import BidProject

logger = logging.getLogger(__name__)

# ============================================================
# セッション管理
# ============================================================


def _create_session() -> requests.Session:
    """リクエストセッションを作成する"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": CRAWL.user_agent,
        "Accept-Language": "ja,en;q=0.9",
    })
    return session


def _init_session(session: requests.Session) -> bool:
    """e-Tokyoのセッションを初期化する

    フレームセット構造のため、初期ページ→左フレーム→メインフレーム→
    検索画面の順にアクセスしてセッションを確立する。
    """
    try:
        # 1. 初期ページ
        resp = session.get(ETOKYO_BASE_URL, timeout=CRAWL.timeout_sec)
        if resp.status_code != 200:
            logger.warning("e-Tokyo: 初期アクセス失敗 HTTP %d", resp.status_code)
            return False

        # 2. 左フレーム初期化
        _post_multipart(session, {"s": "P001", "a": "1"})
        time.sleep(0.3)

        # 3. メインフレーム初期化
        _post_multipart(session, {"s": "P001", "a": "2"})
        time.sleep(0.3)

        # 4. 検索画面（物品カテゴリ）
        _post_multipart(session, {"s": "P002", "a": "2"})

        logger.info("e-Tokyo: セッション初期化完了")
        return True

    except requests.RequestException as e:
        logger.warning("e-Tokyo: セッション初期化エラー: %s", e)
        return False


# ============================================================
# HTTP通信
# ============================================================


def _post_multipart(
    session: requests.Session,
    params: dict[str, str | list[str]],
) -> str | None:
    """e-TokyoにPOSTリクエストを送信する（multipart/form-data）

    govCode等の配列パラメータに対応するため、
    requests-toolbelt等は使わず手動でmultipartを構築する。
    """
    # multipart fields を構築（同名キーの配列対応）
    fields: list[tuple[str, str]] = []
    for key, value in params.items():
        if isinstance(value, list):
            for v in value:
                fields.append((key, v))
        else:
            fields.append((key, value))

    # requests の files パラメータで multipart/form-data を送信
    # (None, value) でファイルではないフィールドとして送信
    files_param = [(key, (None, val)) for key, val in fields]

    try:
        resp = session.post(
            ETOKYO_BASE_URL,
            files=files_param,
            timeout=CRAWL.timeout_sec,
        )
        if resp.status_code != 200:
            logger.warning("e-Tokyo POST失敗: HTTP %d", resp.status_code)
            return None

        # Windows-31J → UTF-8
        resp.encoding = ETOKYO_ENCODING
        return resp.text

    except requests.RequestException as e:
        logger.warning("e-Tokyo POSTエラー: %s", e)
        return None


def _is_session_timeout(html: str) -> bool:
    """セッションタイムアウトかどうか判定する"""
    return "セッションタイムアウト" in html or "セッションが切れ" in html


# ============================================================
# 検索ロジック
# ============================================================


def _build_search_params(keyword: str) -> dict[str, str | list[str]]:
    """検索パラメータを構築する"""
    gov_codes = ETOKYO_WARD_CODES + ETOKYO_CITY_CODES
    return {
        "s": "P002",
        "a": "8",
        "govCode": gov_codes,
        "year": "",
        "itemCode": "",
        "itemNm": "",
        "itemKbnCd": "",
        "selectItem": "",
        "bidWayCode": "",
        "pubStDate": "",
        "pubEndDate": "",
        "kiboStDate": "",
        "kiboEndDate": "",
        "ankenName": keyword,
        "dispKind1": "2",
        "dispOrder1": "1",
        "dispKind2": "1",
        "dispOrder2": "0",
        "TextsyumokuCd": "---",
    }


def _search_keyword(
    session: requests.Session,
    keyword: str,
) -> list[BidProject] | None:
    """指定キーワードで検索し、全ページの結果を取得する

    Returns:
        案件リスト。タイムアウト時は None を返す。
    """
    # 検索画面をリセット
    _post_multipart(session, {"s": "P002", "a": "2"})
    time.sleep(0.5)

    # 検索実行
    search_params = _build_search_params(keyword)
    html = _post_multipart(session, search_params)
    if html is None:
        return None

    if "該当する案件はありませんでした" in html:
        return []

    if _is_session_timeout(html):
        logger.warning("e-Tokyo: セッションタイムアウト (keyword=%s)", keyword)
        return None

    # 1ページ目をパース
    projects = _parse_project_list(html)
    total_pages = _parse_total_pages(html)

    if total_pages <= 1:
        return projects

    # 残りのページを取得
    max_pages = min(total_pages, CRAWL.max_pages_per_keyword)
    for page in range(2, max_pages + 1):
        time.sleep(CRAWL.request_interval_sec)

        next_html = _post_multipart(session, {"s": "P002", "a": "10"})
        if next_html is None:
            break

        if _is_session_timeout(next_html):
            logger.warning("e-Tokyo: ページ取得中にタイムアウト (page=%d)", page)
            break

        page_projects = _parse_project_list(next_html)
        if not page_projects:
            break

        projects.extend(page_projects)
        logger.debug("e-Tokyo: ページ %d/%d 取得完了", page, max_pages)

    return projects


# ============================================================
# HTMLパース
# ============================================================


def _parse_project_list(html: str) -> list[BidProject]:
    """検索結果HTMLから案件一覧を抽出する"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="list-table")
    if table is None:
        return []

    projects: list[BidProject] = []
    rows = table.find_all("tr")

    # 最初の行はヘッダーなのでスキップ
    for row in rows[1:]:
        project = _parse_project_row(row)
        if project is not None:
            projects.append(project)

    return projects


def _parse_project_row(row: Tag) -> BidProject | None:
    """テーブル行から案件情報を抽出する"""
    cells = row.find_all("td")
    if len(cells) < 8:
        return None

    title = _cell_text(cells[1])
    if not title:
        return None

    municipality = _cell_text(cells[0])
    bid_type_short = _cell_text(cells[6])
    bid_type = ETOKYO_BID_TYPE_MAP.get(bid_type_short, bid_type_short or "不明")

    publish_date = _format_etokyo_date(_cell_text(cells[3]))
    deadline = _format_etokyo_date(_cell_text(cells[4]))

    # 案件ID抽出（JavaScript listSubmit から）
    row_html = str(row)
    case_id = _extract_case_id(row_html)
    detail_url = ""
    if case_id:
        detail_url = f"{ETOKYO_BASE_URL}?s=P002&a=12&n={case_id}"

    return BidProject(
        title=title,
        organization=municipality,
        bid_type=bid_type,
        publish_date=publish_date,
        deadline=deadline,
        detail_url=detail_url,
        source=ETOKYO_SOURCE_NAME,
    )


def _cell_text(cell: Tag) -> str:
    """BeautifulSoupのセル要素からテキストを取得する"""
    text = cell.get_text(strip=True)
    # 連続空白を整理
    return re.sub(r"\s+", " ", text)


_CASE_ID_PATTERN = re.compile(r"^\d{4}:\d+:\d+:\d+$")


def _extract_case_id(row_html: str) -> str | None:
    """行HTMLから案件IDを抽出する

    パターン: listSubmit('P002','12','2026:13:118:00210','1','FrmMain')
    案件IDは YYYY:NN:NNN:NNNNN 形式のみ許可（formula injection防止）。
    """
    match = re.search(r"listSubmit\('P002','12','([^']+)'", row_html)
    if not match:
        return None
    case_id = match.group(1)
    if not _CASE_ID_PATTERN.match(case_id):
        return None
    return case_id


def _format_etokyo_date(date_str: str) -> str:
    """e-Tokyoの日付文字列をYYYY-MM-DD形式に変換する

    入力例: "2026/3/27 20:00" → "2026-03-27"
    """
    if not date_str:
        return ""
    match = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", date_str)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _parse_total_pages(html: str) -> int:
    """ページネーション情報から総ページ数を取得する

    パターン: 全103件[1-50] 1/3ページ
    """
    match = re.search(r"(\d+)/(\d+)\s*(?:ペ|ﾍﾟ)", html)
    if match:
        return int(match.group(2))
    return 1


# ============================================================
# メインエントリポイント
# ============================================================


def fetch_etokyo_projects() -> list[BidProject]:
    """e-Tokyoから印刷関連の入札案件を取得する

    セッションタイムアウト時は自動再初期化（最大3回）。
    """
    session = _create_session()

    for attempt in range(CRAWL.retry_count + 1):
        if not _init_session(session):
            logger.warning("e-Tokyo: セッション初期化失敗 (attempt %d)", attempt + 1)
            if attempt < CRAWL.retry_count:
                time.sleep(CRAWL.retry_delay_sec)
                session = _create_session()
            continue

        all_projects: list[BidProject] = []
        seen_keys: set[str] = set()
        timeout_detected = False

        for keyword in SEARCH_KEYWORDS:
            logger.info("e-Tokyo: キーワード「%s」で検索中...", keyword)
            result = _search_keyword(session, keyword)

            if result is None:
                timeout_detected = True
                break

            for p in result:
                if p.dedup_key not in seen_keys:
                    seen_keys.add(p.dedup_key)
                    all_projects.append(p)

            logger.info("e-Tokyo: 「%s」→ %d件", keyword, len(result))
            time.sleep(CRAWL.request_interval_sec)

        if not timeout_detected:
            logger.info("e-Tokyo: %d件取得（重複除去済み）", len(all_projects))
            return all_projects

        # タイムアウトで中断した場合はリトライ
        logger.warning("e-Tokyo: タイムアウトでリトライ (attempt %d)", attempt + 1)
        session = _create_session()

    logger.error("e-Tokyo: 全リトライ失敗")
    return []
