"""調達ポータル落札実績取得のテスト"""

from __future__ import annotations

import csv
import io
import zipfile
from unittest.mock import MagicMock, patch

from src.sources.pportal import (
    _fetch_single_year,
    _is_printing_related,
    _parse_row,
)


class TestIsPrintingRelated:
    def test_printing_keyword_match(self) -> None:
        assert _is_printing_related("広報誌印刷業務") is True
        assert _is_printing_related("パンフレット作成") is True
        assert _is_printing_related("封筒印刷") is True
        assert _is_printing_related("冊子製本") is True

    def test_excluded_keyword(self) -> None:
        assert _is_printing_related("道路印刷物") is False
        assert _is_printing_related("清掃パンフレット") is False

    def test_no_keyword_match(self) -> None:
        assert _is_printing_related("システム開発") is False
        assert _is_printing_related("事務用品の購入") is False


class TestParseRow:
    def test_valid_printing_row(self) -> None:
        row = [
            "0000000000000511841",
            "省名封筒の印刷（単価契約）",
            "2025-04-01",
            "2247800.00",
            "S1",
            "8002010",
            "株式会社山口封筒店",
            "4010001059279",
        ]
        result = _parse_row(row)
        assert result is not None
        assert result.title == "省名封筒の印刷（単価契約）"
        assert result.award_price == 2247800
        assert result.winner == "株式会社山口封筒店"
        assert result.award_date == "2025-04-01"

    def test_non_printing_row_returns_none(self) -> None:
        row = [
            "0000000000000443261",
            "技術管理支援業務請負",
            "2025-04-01",
            "2961000.00",
            "S1",
            "8002010",
            "鹿児島綜合警備保障株式会社",
            "7340001000891",
        ]
        assert _parse_row(row) is None

    def test_too_low_price_excluded(self) -> None:
        row = [
            "001",
            "複写製本等",
            "2025-04-01",
            "147.00",
            "S1",
            "8002010",
            "株式会社テスト",
            "1234567890123",
        ]
        assert _parse_row(row) is None

    def test_too_high_price_excluded(self) -> None:
        row = [
            "001",
            "大型印刷機械の購入",
            "2025-04-01",
            "50000000.00",
            "S1",
            "8002010",
            "株式会社テスト",
            "1234567890123",
        ]
        assert _parse_row(row) is None

    def test_short_row_returns_none(self) -> None:
        assert _parse_row(["001", "印刷"]) is None


class TestFetchAwardResults:
    def _make_csv_zip(self, rows: list[list[str]]) -> bytes:
        """テスト用のCSV ZIPバイトデータを生成する"""
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(row)
        csv_bytes = buf.getvalue().encode("utf-8-sig")

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("test.csv", csv_bytes)
        return zip_buf.getvalue()

    @patch("src.sources.pportal.requests.get")
    def test_fetches_and_filters(self, mock_get: MagicMock) -> None:
        rows = [
            [
                "001",
                "広報誌印刷業務",
                "2025-04-01",
                "1000000.00",
                "S1",
                "8002010",
                "テスト印刷",
                "111",
            ],
            ["002", "システム開発", "2025-04-01", "5000000.00", "S1", "8002010", "テストIT", "222"],
            ["003", "封筒印刷", "2025-04-01", "500000.00", "S1", "8002010", "テスト封筒", "333"],
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = self._make_csv_zip(rows)
        mock_get.return_value = mock_resp

        results = _fetch_single_year(2025)

        assert len(results) == 2  # 印刷関連のみ
        assert results[0].title == "広報誌印刷業務"
        assert results[0].award_price == 1000000
        assert results[1].title == "封筒印刷"

    @patch("src.sources.pportal.requests.get")
    def test_handles_download_error(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        results = _fetch_single_year(2025)
        assert results == []
