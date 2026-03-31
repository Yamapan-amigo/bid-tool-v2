"""Google Spreadsheet 書き込み

gspread + Service Account でSpreadsheetに案件データを書き込む。
ヘッダーは config.py の PROJECT_HEADERS で一元管理。
"""

from __future__ import annotations

import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from src.config import (
    GOOGLE_CREDENTIALS_PATH,
    LOG_HEADERS,
    PROJECT_HEADERS,
    SHEET_LOG,
    SHEET_PROJECTS,
    SPREADSHEET_ID,
)
from src.core.models import BidProject

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def _get_client() -> gspread.Client:
    """認証済みgspreadクライアントを取得する"""
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    return gspread.Client(auth=creds)


def _get_spreadsheet() -> gspread.Spreadsheet:
    """対象のスプレッドシートを取得する"""
    if not SPREADSHEET_ID:
        raise RuntimeError(
            "SPREADSHEET_ID が未設定です。環境変数に設定してください。\n"
            "export SPREADSHEET_ID='your-spreadsheet-id'"
        )
    return _get_client().open_by_key(SPREADSHEET_ID)


def _get_or_create_sheet(
    ss: gspread.Spreadsheet,
    name: str,
    headers: list[str],
) -> gspread.Worksheet:
    """シートを取得（なければ作成してヘッダーを設定）"""
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.update("A1", [headers])
        last_col = chr(64 + len(headers))
        ws.format(
            f"A1:{last_col}1",
            {
                "backgroundColor": {"red": 0.26, "green": 0.52, "blue": 0.96},
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                },
            },
        )
        ws.freeze(rows=1)
    return ws


def get_existing_project_keys() -> set[str]:
    """既存の案件キー（案件名|発注元）を取得する"""
    ss = _get_spreadsheet()
    ws = _get_or_create_sheet(ss, SHEET_PROJECTS, PROJECT_HEADERS)
    rows = ws.get_all_values()

    keys: set[str] = set()
    for row in rows[1:]:
        if len(row) >= 3:
            keys.add(f"{row[1]}|{row[2]}")
    return keys


def write_projects(projects: list[BidProject]) -> int:
    """案件を書き込む（重複チェック付き）

    Returns:
        新規追加件数
    """
    if not projects:
        return 0

    ss = _get_spreadsheet()
    ws = _get_or_create_sheet(ss, SHEET_PROJECTS, PROJECT_HEADERS)
    # 既存キーをインラインで取得（二重接続を回避）
    rows = ws.get_all_values()
    existing_keys: set[str] = {f"{r[1]}|{r[2]}" for r in rows[1:] if len(r) >= 3}
    today = datetime.now().strftime("%Y-%m-%d")

    new_rows: list[list[str]] = []
    for p in projects:
        if p.dedup_key in existing_keys:
            continue
        new_rows.append(p.to_row(today))

    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")

    logger.info("Spreadsheet書き込み: %d件の新規案件を追加", len(new_rows))
    return len(new_rows)


def write_log(source: str, status: str, count: int, error_msg: str = "") -> None:
    """実行ログを書き込む"""
    ss = _get_spreadsheet()
    ws = _get_or_create_sheet(ss, SHEET_LOG, LOG_HEADERS)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([now, source, status, count, error_msg])
