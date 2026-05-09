"""等級・地域要件の後処理エンリッチャー

初回フェッチで「不明」になった案件に対して、PDFや詳細ページHTMLから
等級・地域要件を補完する後処理モジュール。

Phase 1: spec_url が PDF → pdfplumber でテキスト化 → extract_eligibility()
Phase 2: source == "e-Tokyo" → detail_url の HTML を取得 → extract_eligibility()
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.core.extractor import extract_eligibility
from src.core.models import BidProject

logger = logging.getLogger(__name__)

_CACHE_ROOT = Path(__file__).parent.parent.parent / ".cache"
_PDF_CACHE_DIR = _CACHE_ROOT / "pdf_text"
_ETOKYO_CACHE_DIR = _CACHE_ROOT / "etokyo_detail"

_PDF_DOWNLOAD_TIMEOUT = 20
_ETOKYO_DETAIL_TIMEOUT = 15
_PDF_TEXT_MAX_CHARS = 8000
_ETOKYO_ALLOWED_DOMAIN = "www.e-tokyo.lg.jp"

_ETOKYO_ELIGIBILITY_LABELS = [
    "参加資格",
    "入札参加資格",
    "競争参加資格",
    "等級",
    "格付",
    "地域",
    "所在地",
    "資格要件",
]

_GRADE_NOT_KNOWN = ("不明", "不明（全省庁統一資格）", "")


# ============================================================
# ユーティリティ
# ============================================================


def _url_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _is_safe_url(url: str) -> bool:
    """http/https かつパストラバーサル文字を含まないことを確認する"""
    if not url.startswith(("http://", "https://")):
        return False
    decoded = url.replace("%2e", ".").replace("%2E", ".")
    if ".." in decoded:
        return False
    return True


def _is_etokyo_url(url: str) -> bool:
    try:
        return urlparse(url).netloc == _ETOKYO_ALLOWED_DOMAIN
    except Exception:
        return False


def _looks_like_pdf_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf/" in path


def _needs_grade_enrichment(project: BidProject) -> bool:
    return project.eligibility_grade in _GRADE_NOT_KNOWN


# ============================================================
# Phase 1: PDF テキスト抽出
# ============================================================


def _fetch_pdf_text(url: str) -> str | None:
    """PDF をダウンロードしてテキストを返す。キャッシュがあれば即返す。"""
    if not _is_safe_url(url):
        logger.debug("安全でないURL（スキップ）: %s", url[:80])
        return None

    key = _url_cache_key(url)
    cache_path = _PDF_CACHE_DIR / f"{key}.txt"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    try:
        response = requests.get(
            url,
            timeout=_PDF_DOWNLOAD_TIMEOUT,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BidBot/2.0)"},
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "application/pdf" not in content_type:
            logger.debug("PDF以外のContent-Type (%s): %s", content_type, url[:80])
            return None

        content = response.content

    except requests.exceptions.RequestException as e:
        logger.warning("PDFダウンロード失敗 (%s): %s", url[:80], e)
        return None

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        text = "\n".join(pages_text)[:_PDF_TEXT_MAX_CHARS]

    except Exception as e:
        logger.warning("PDFパース失敗 (%s): %s", url[:80], e)
        return None

    try:
        _PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
    except OSError as e:
        logger.warning("PDFキャッシュ書き込み失敗: %s", e)

    return text


def _enrich_from_pdf(project: BidProject) -> BidProject:
    """spec_url または detail_url が PDF の案件に対して等級・地域情報を補完する

    spec_url は仕様書PDFのため等級要件が書かれていないことが多い。
    detail_url（KKJ の ExternalDocumentURI）が公告PDFを直接指す場合もある。
    """
    # 試みる順: detail_url → spec_url（公告PDFが先の方が等級情報を含む可能性が高い）
    pdf_urls = []
    if project.detail_url and _looks_like_pdf_url(project.detail_url):
        pdf_urls.append(project.detail_url)
    if project.spec_url and _looks_like_pdf_url(project.spec_url):
        pdf_urls.append(project.spec_url)

    for pdf_url in pdf_urls:
        text = _fetch_pdf_text(pdf_url)
        if not text:
            continue

        combined = (project.description + "\n" + text).strip()
        info = extract_eligibility(combined, project.organization)

        if info.grade_text not in _GRADE_NOT_KNOWN or info.region_text not in ("不明", "制限なし"):
            return dataclasses.replace(
                project,
                eligibility_overall=info.overall,
                eligibility_grade=info.grade_text,
                eligibility_region=info.region_text,
                eligibility_method=info.submission_method or project.eligibility_method,
                eligibility_contact=info.contact or project.eligibility_contact,
            )

    return project


# ============================================================
# Phase 2: eTokyo 詳細ページ HTML スクレイピング
# ============================================================


def _fetch_etokyo_detail_html(url: str) -> str | None:
    """eTokyo 詳細ページの HTML を取得する。キャッシュがあれば即返す。"""
    if not _is_safe_url(url) or not _is_etokyo_url(url):
        logger.debug("eTokyo以外のURL（スキップ）: %s", url[:80])
        return None

    key = _url_cache_key(url)
    cache_path = _ETOKYO_CACHE_DIR / f"{key}.html"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    try:
        session = requests.Session()
        response = session.get(
            url,
            timeout=_ETOKYO_DETAIL_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BidBot/2.0)"},
        )
        response.raise_for_status()

        # Shift-JIS / UTF-8 どちらも対応
        try:
            html = response.content.decode("shift_jis")
        except UnicodeDecodeError:
            html = response.content.decode("utf-8", errors="replace")

    except requests.exceptions.RequestException as e:
        logger.warning("eTokyo詳細取得失敗 (%s): %s", url[:80], e)
        return None

    try:
        _ETOKYO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html, encoding="utf-8")
    except OSError as e:
        logger.warning("eTokyo HTMLキャッシュ書き込み失敗: %s", e)

    return html


def _parse_etokyo_detail(html: str) -> str:
    """詳細ページHTMLから参加資格テキストを抽出する"""
    soup = BeautifulSoup(html, "lxml")

    parts: list[str] = []

    # テーブルの th/td ペアからラベルでフィルタ
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        if any(kw in label for kw in _ETOKYO_ELIGIBILITY_LABELS):
            value = cells[1].get_text(separator=" ", strip=True)
            if value:
                parts.append(f"{label}: {value}")

    if parts:
        return "\n".join(parts)

    # ラベルが見つからない場合は全テキストをフォールバック
    return soup.get_text(separator="\n", strip=True)[:_PDF_TEXT_MAX_CHARS]


def _enrich_from_etokyo_detail(project: BidProject) -> BidProject:
    """eTokyo 案件の詳細ページを参照して等級・地域情報を補完する"""
    if not project.detail_url:
        return project

    html = _fetch_etokyo_detail_html(project.detail_url)
    if not html:
        return project

    text = _parse_etokyo_detail(html)
    if not text:
        return project

    info = extract_eligibility(text, project.organization)

    if info.grade_text in _GRADE_NOT_KNOWN and info.region_text in ("不明", "制限なし"):
        return project

    return dataclasses.replace(
        project,
        description=text[:2000] if not project.description else project.description,
        eligibility_overall=info.overall,
        eligibility_grade=info.grade_text,
        eligibility_region=info.region_text,
        eligibility_method=info.submission_method or project.eligibility_method,
        eligibility_contact=info.contact or project.eligibility_contact,
    )


# ============================================================
# エントリポイント
# ============================================================


def enrich_eligibility(
    projects: list[BidProject],
    *,
    enable_pdf: bool = True,
    enable_etokyo_detail: bool = True,
    max_enrich_per_run: int = 20,
) -> list[BidProject]:
    """等級・地域情報が「不明」の案件を後処理で補完する

    Args:
        projects: フィルタ前の全案件リスト
        enable_pdf: PDF取得補完を有効にするか
        enable_etokyo_detail: eTokyo詳細ページ補完を有効にするか
        max_enrich_per_run: 1回の実行で補完する上限（初回タイムアウト防止）
    """
    enriched: list[BidProject] = []
    pdf_count = 0
    etokyo_count = 0
    total_enriched = 0

    for project in projects:
        result = project

        if total_enriched >= max_enrich_per_run:
            enriched.append(result)
            continue

        try:
            # Phase 1: spec_url または detail_url が PDF の場合
            has_pdf_url = (result.spec_url and _looks_like_pdf_url(result.spec_url)) or (
                result.detail_url and _looks_like_pdf_url(result.detail_url)
            )
            if enable_pdf and _needs_grade_enrichment(result) and has_pdf_url:
                before = result.eligibility_grade
                result = _enrich_from_pdf(result)
                if result.eligibility_grade != before:
                    pdf_count += 1
                    total_enriched += 1

            # Phase 2: eTokyo 詳細ページ
            if (
                enable_etokyo_detail
                and project.source == "e-Tokyo"
                and _needs_grade_enrichment(result)
                and total_enriched < max_enrich_per_run
            ):
                before = result.eligibility_grade
                result = _enrich_from_etokyo_detail(result)
                if result.eligibility_grade != before:
                    etokyo_count += 1
                    total_enriched += 1

        except Exception as e:
            logger.warning("Enricherエラー（スキップ）: %s", e)
            result = project

        enriched.append(result)

    if pdf_count or etokyo_count:
        logger.info("Enricher完了: PDF補完=%d件, eTokyo詳細=%d件", pdf_count, etokyo_count)

    return enriched
