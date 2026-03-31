"""Spreadsheet書き込みのテスト（gspreadモック）"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.models import BidProject
from src.core.writer import write_log, write_projects


class TestWriteProjects:
    @patch("src.core.writer._get_spreadsheet")
    def test_writes_new_projects(self, mock_ss: MagicMock) -> None:
        """新規案件が書き込まれる"""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [["取得日", "案件名", "発注元"]]  # ヘッダーのみ
        mock_ss.return_value.worksheet.return_value = mock_ws

        projects = [
            BidProject(title="印刷業務", organization="東京都", source="官公需", score=4.0),
        ]
        count = write_projects(projects)
        assert count == 1
        mock_ws.append_rows.assert_called_once()

    @patch("src.core.writer._get_spreadsheet")
    def test_skips_duplicates(self, mock_ss: MagicMock) -> None:
        """既存案件は書き込まれない"""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["取得日", "案件名", "発注元"],
            ["2026-04-01", "印刷業務", "東京都"],  # 既存データ
        ]
        mock_ss.return_value.worksheet.return_value = mock_ws

        projects = [
            BidProject(title="印刷業務", organization="東京都"),
        ]
        count = write_projects(projects)
        assert count == 0
        mock_ws.append_rows.assert_not_called()

    def test_empty_projects(self) -> None:
        """空リストは0を返す"""
        count = write_projects([])
        assert count == 0


class TestWriteLog:
    @patch("src.core.writer._get_spreadsheet")
    def test_writes_log_entry(self, mock_ss: MagicMock) -> None:
        mock_ws = MagicMock()
        mock_ss.return_value.worksheet.return_value = mock_ws

        write_log("官公需", "成功", 5)
        mock_ws.append_row.assert_called_once()
        args = mock_ws.append_row.call_args[0][0]
        assert args[1] == "官公需"
        assert args[2] == "成功"
        assert args[3] == 5
