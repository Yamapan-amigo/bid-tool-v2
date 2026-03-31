"""メインエントリポイントのテスト"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.models import BidProject
from src.main import run


class TestRun:
    @patch("src.main.write_projects")
    @patch("src.main.write_log")
    @patch("src.main.fetch_etokyo_projects")
    @patch("src.main.fetch_kkj_projects")
    def test_full_pipeline(
        self,
        mock_kkj: MagicMock,
        mock_etokyo: MagicMock,
        mock_log: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        """KKJ + e-Tokyo → フィルタ → スコアリング → 書き込みの統合テスト"""
        mock_kkj.return_value = [
            BidProject(
                title="広報誌印刷業務",
                organization="東京都総務局",
                bid_type="一般競争入札",
                deadline="2099-12-31",
                source="官公需",
            ),
        ]
        mock_etokyo.return_value = [
            BidProject(
                title="区報製本業務",
                organization="新宿区",
                bid_type="指名競争入札",
                deadline="2099-12-31",
                source="e-Tokyo",
            ),
        ]
        mock_write.return_value = 2

        run()

        # write_projects が呼ばれ、2件のスコア付き案件が渡される
        mock_write.assert_called_once()
        written_projects = mock_write.call_args[0][0]
        assert len(written_projects) == 2
        # スコアが付与されている
        assert all(p.score > 0 for p in written_projects)
        # スコア降順
        assert written_projects[0].score >= written_projects[1].score

    @patch("src.main.write_log")
    @patch("src.main.fetch_kkj_projects")
    def test_single_source(
        self,
        mock_kkj: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """単一ソース指定"""
        mock_kkj.return_value = []
        run(sources=["kkj"])
        mock_kkj.assert_called_once()

    @patch("src.main.write_log")
    @patch("src.main.fetch_kkj_projects")
    def test_handles_source_error(
        self,
        mock_kkj: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """ソースエラー時もログが書かれて続行"""
        mock_kkj.side_effect = RuntimeError("API error")
        run(sources=["kkj"])
        # エラーログが書き込まれる
        mock_log.assert_called()
        log_args = mock_log.call_args[0]
        assert log_args[1] == "失敗"

    @patch("src.main.write_projects")
    @patch("src.main.write_log")
    @patch("src.main.fetch_kkj_projects")
    def test_deduplication_across_sources(
        self,
        mock_kkj: MagicMock,
        mock_log: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        """同じ案件が複数ソースから来た場合は重複排除"""
        same_project = BidProject(
            title="広報誌印刷",
            organization="東京都",
            deadline="2099-12-31",
            source="官公需",
        )
        mock_kkj.return_value = [same_project, same_project]
        mock_write.return_value = 1

        run(sources=["kkj"])
        written = mock_write.call_args[0][0]
        assert len(written) == 1
