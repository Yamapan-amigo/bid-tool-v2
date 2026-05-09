"""URLバリデーションのテスト（TDD: テストファースト）"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.url_checker import check_url, filter_broken_urls


class TestCheckUrl:
    """単一URLの有効性チェック"""

    @patch("src.core.url_checker.requests.head")
    def test_valid_url_returns_true(self, mock_head: MagicMock) -> None:
        mock_head.return_value.status_code = 200
        assert check_url("https://example.com/tender/123") is True

    @patch("src.core.url_checker.requests.head")
    def test_404_returns_false(self, mock_head: MagicMock) -> None:
        mock_head.return_value.status_code = 404
        assert check_url("https://example.com/expired") is False

    @patch("src.core.url_checker.requests.head")
    def test_500_returns_false(self, mock_head: MagicMock) -> None:
        mock_head.return_value.status_code = 500
        assert check_url("https://example.com/error") is False

    @patch("src.core.url_checker.requests.head")
    def test_timeout_returns_false(self, mock_head: MagicMock) -> None:
        import requests as req
        mock_head.side_effect = req.exceptions.Timeout()
        assert check_url("https://example.com/slow") is False

    @patch("src.core.url_checker.requests.head")
    def test_connection_error_returns_false(self, mock_head: MagicMock) -> None:
        import requests as req
        mock_head.side_effect = req.exceptions.ConnectionError()
        assert check_url("https://example.com/gone") is False

    def test_empty_url_returns_false(self) -> None:
        assert check_url("") is False

    def test_non_http_url_returns_false(self) -> None:
        assert check_url("javascript:void(0)") is False

    @patch("src.core.url_checker.requests.head")
    def test_redirect_to_top_page_returns_false(self, mock_head: MagicMock) -> None:
        """ポータルのトップページにリダイレクトされた場合は無効とみなす"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://www.kkj.go.jp/"  # トップページにリダイレクト
        mock_head.return_value = mock_resp
        assert check_url("https://www.kkj.go.jp/api/detail?id=12345") is False


class TestFilterBrokenUrls:
    """案件リストからリンク切れ案件を検出する"""

    @patch("src.core.url_checker.check_url")
    def test_marks_broken_links(self, mock_check: MagicMock) -> None:
        from src.core.models import BidProject

        mock_check.side_effect = lambda url: url != "https://broken.example.com"

        projects = [
            BidProject(title="有効な案件", organization="東京都", detail_url="https://valid.example.com"),
            BidProject(title="リンク切れ案件", organization="厚生労働省", detail_url="https://broken.example.com"),
            BidProject(title="URL無し案件", organization="国交省", detail_url=""),
        ]

        result = filter_broken_urls(projects)

        valid = [p for p in result if "リンク切れ" not in p.title]
        assert len(valid) == 2  # URL無しは通す（リンク切れとは別）

    @patch("src.core.url_checker.check_url")
    def test_empty_url_passes_through(self, mock_check: MagicMock) -> None:
        """URL未設定は check_url を呼ばない"""
        from src.core.models import BidProject

        projects = [
            BidProject(title="URL無し", organization="東京都", detail_url=""),
        ]
        result = filter_broken_urls(projects)
        mock_check.assert_not_called()
        assert len(result) == 1
