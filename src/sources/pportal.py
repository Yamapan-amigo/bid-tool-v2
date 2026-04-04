"""調達ポータル 落札実績オープンデータ取得

https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201 から
落札実績CSVをダウンロードし、印刷関連の過去落札結果を取得する。

CSVフォーマット（ヘッダーなし、UTF-8 BOM付き）:
  Col 0: 案件番号
  Col 1: 案件名
  Col 2: 落札日 (YYYY-MM-DD)
  Col 3: 落札金額 (円, 小数点付き)
  Col 4: 資格コード
  Col 5: 機関コード
  Col 6: 落札者名
  Col 7: 法人番号
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime

import requests

from src.config import (
    AWARD_PRICE_MAX,
    CRAWL,
    EXCLUDE_KEYWORDS,
    PPORTAL_BASE_URL,
    SEARCH_KEYWORDS,
)
from src.core.models import AwardResult

logger = logging.getLogger(__name__)

# 単価契約等の極端に低い金額を除外する閾値
_MIN_VALID_PRICE = 10_000  # 1万円未満は単価と判断


def _build_download_url(fiscal_year: int) -> str:
    """年度全件データのダウンロードURLを構築する"""
    return (
        f"{PPORTAL_BASE_URL}"
        f"?fileversion=v001"
        f"&filename=successful_bid_record_info_all_{fiscal_year}.zip"
    )


def _download_csv(url: str) -> str | None:
    """ZIPファイルをダウンロードしてCSVテキストを返す"""
    try:
        response = requests.get(
            url,
            timeout=CRAWL.timeout_sec * 2,
            headers={"User-Agent": CRAWL.user_agent},
        )
        if response.status_code != 200:
            logger.warning("調達ポータル HTTP %d: %s", response.status_code, url)
            return None

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_names:
                logger.warning("ZIPにCSVファイルなし")
                return None
            return zf.read(csv_names[0]).decode("utf-8-sig")

    except (requests.RequestException, zipfile.BadZipFile) as e:
        logger.error("調達ポータル ダウンロードエラー: %s", e)
        return None


def _is_printing_related(title: str) -> bool:
    """案件名が印刷関連かどうかを判定する"""
    if any(kw in title for kw in EXCLUDE_KEYWORDS):
        return False
    return any(kw in title for kw in SEARCH_KEYWORDS)


def _parse_row(row: list[str]) -> AwardResult | None:
    """CSVの1行をAwardResultに変換する"""
    if len(row) < 8:
        return None

    title = row[1].strip()
    if not title:
        return None

    if not _is_printing_related(title):
        return None

    try:
        price = int(float(row[3]))
    except (ValueError, IndexError):
        return None

    if price < _MIN_VALID_PRICE:
        return None

    if price > AWARD_PRICE_MAX:
        return None

    return AwardResult(
        case_id=row[0].strip(),
        title=title,
        award_date=row[2].strip()[:10],
        award_price=price,
        cert_code=row[4].strip(),
        org_code=row[5].strip(),
        winner=row[6].strip(),
        corporate_number=row[7].strip(),
    )


def _fetch_single_year(fiscal_year: int) -> list[AwardResult]:
    """1年度分の落札実績を取得する"""
    url = _build_download_url(fiscal_year)
    logger.info("調達ポータル: %d年度の落札実績をダウンロード中...", fiscal_year)

    csv_text = _download_csv(url)
    if csv_text is None:
        return []

    results: list[AwardResult] = []
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        result = _parse_row(row)
        if result is not None:
            results.append(result)

    logger.info(
        "調達ポータル: %d年度 印刷関連落札実績 %d件",
        fiscal_year,
        len(results),
    )
    return results


def fetch_award_results(years: int = 5) -> list[AwardResult]:
    """調達ポータルから複数年度の印刷関連落札実績を取得する

    Args:
        years: 取得する年数（デフォルト2年分）

    Returns:
        印刷関連・金額フィルタ済みの落札実績リスト
    """
    now = datetime.now()
    base_year = now.year - 1 if now.month >= 4 else now.year - 2

    all_results: list[AwardResult] = []
    for offset in range(years):
        year = base_year - offset
        all_results.extend(_fetch_single_year(year))

    logger.info(
        "調達ポータル: 合計 %d件（%d年分、金額%d万円以下）",
        len(all_results),
        years,
        AWARD_PRICE_MAX // 10_000,
    )
    return all_results
