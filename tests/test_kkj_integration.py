"""官公需API統合テスト（ネットワークモック）"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.sources.kkj import _build_date_range, fetch_kkj_projects

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "kkj_response.xml"


class TestBuildDateRange:
    def test_returns_date_format(self) -> None:
        result = _build_date_range(30)
        assert result.endswith("/")
        # YYYY-MM-DD/ 形式
        assert len(result) == 11


class TestFetchKkjProjects:
    @patch("src.sources.kkj.time.sleep")
    @patch("src.sources.kkj.requests.get")
    def test_fetches_and_filters(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        """XMLフィクスチャを返すモックでフィルタ動作を確認"""
        xml_content = FIXTURE_PATH.read_bytes()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = xml_content
        mock_get.return_value = mock_response

        projects = fetch_kkj_projects()

        # 5件中: 東京(OK), 埼玉(OK), 中央省庁(除外:道路), 北海道(除外:地域外), 締切済(除外)
        # → 2件が残る
        assert len(projects) == 2
        assert projects[0].title == "令和7年度 広報誌印刷業務"
        assert projects[1].title == "パンフレット製本委託"

    @patch("src.sources.kkj.time.sleep")
    @patch("src.sources.kkj.requests.get")
    def test_handles_api_failure(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        """API失敗時は空リストを返す"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        projects = fetch_kkj_projects()
        assert projects == []

    @patch("src.sources.kkj.time.sleep")
    @patch("src.sources.kkj.requests.get")
    def test_handles_network_error(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        """ネットワークエラー時は空リストを返す"""
        import requests as req

        mock_get.side_effect = req.ConnectionError("Connection refused")
        projects = fetch_kkj_projects()
        assert projects == []
