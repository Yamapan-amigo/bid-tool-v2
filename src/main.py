"""メインエントリポイント — 入札情報収集 V2

原則:
1. 一次情報を取得する（元サイトから直接読み取る）
2. AIよりアルゴリズムを先に使う（BeautifulSoup + 正規表現 + XMLパーサー）
3. ヘッダーは config.py の1箇所のみで定義
"""

from __future__ import annotations

import argparse
import logging

from src.core.dedup import deduplicate
from src.core.filter import apply_filters
from src.core.models import BidProject
from src.core.scorer import score_projects
from src.core.writer import write_log, write_projects
from src.sources.etokyo import fetch_etokyo_projects
from src.sources.kkj import fetch_kkj_projects


def _sanitize_error(e: Exception, max_len: int = 200) -> str:
    """エラーメッセージをサニタイズ・切り詰めする"""
    msg = str(e)[:max_len]
    # URL中のクエリパラメータ（認証情報等）を除去
    if "?" in msg:
        msg = msg.split("?")[0] + "?..."
    return msg

logger = logging.getLogger(__name__)


def run(sources: list[str] | None = None) -> None:
    """入札情報を収集してSpreadsheetに書き込む

    Args:
        sources: 取得するソースのリスト（None=全ソース）
                 指定可能: "kkj", "etokyo"
    """
    if sources is None:
        sources = ["kkj", "etokyo"]

    all_projects: list[BidProject] = []

    # === 1. データ取得 ===
    if "kkj" in sources:
        logger.info("=== 官公需API 取得開始 ===")
        try:
            kkj_projects = fetch_kkj_projects()
            all_projects.extend(kkj_projects)
            write_log("官公需", "成功", len(kkj_projects))
        except Exception as e:
            logger.error("官公需API エラー: %s", e, exc_info=True)
            try:
                write_log("官公需", "失敗", 0, _sanitize_error(e))
            except Exception:
                logger.warning("ログ書き込み失敗（スキップ）", exc_info=True)

    if "etokyo" in sources:
        logger.info("=== e-Tokyo 取得開始 ===")
        try:
            etokyo_projects = fetch_etokyo_projects()
            all_projects.extend(etokyo_projects)
            write_log("e-Tokyo", "成功", len(etokyo_projects))
        except Exception as e:
            logger.error("e-Tokyo エラー: %s", e, exc_info=True)
            try:
                write_log("e-Tokyo", "失敗", 0, _sanitize_error(e))
            except Exception:
                logger.warning("ログ書き込み失敗（スキップ）", exc_info=True)

    if not all_projects:
        logger.info("取得案件なし。終了します。")
        return

    logger.info("取得合計: %d件", len(all_projects))

    # === 2. フィルタ ===
    filtered = apply_filters(all_projects)
    logger.info("フィルタ後: %d件", len(filtered))

    # === 3. 重複排除 ===
    unique = deduplicate(filtered)
    logger.info("重複排除後: %d件", len(unique))

    # === 4. スコアリング ===
    scored = score_projects(unique)

    # スコア降順でソート
    scored.sort(key=lambda p: p.score, reverse=True)

    # === 5. Spreadsheet書き込み ===
    new_count = write_projects(scored)
    logger.info("=== 完了: %d件の新規案件を追加 ===", new_count)


def main() -> None:
    parser = argparse.ArgumentParser(description="入札情報収集ツール V2")
    parser.add_argument(
        "--source",
        choices=["kkj", "etokyo"],
        action="append",
        default=None,
        help="取得するソース（複数指定可、省略時は全ソース）",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログを表示")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    run(sources=args.source)


if __name__ == "__main__":
    main()
