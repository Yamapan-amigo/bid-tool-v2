"""官公需APIパーサーのテスト"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from src.sources.kkj import _find_all_items, _parse_project, _text

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "kkj_response.xml"


def _load_fixture() -> ET.Element:
    return ET.parse(str(FIXTURE_PATH)).getroot()


class TestText:
    def test_existing_tag(self) -> None:
        root = _load_fixture()
        items = _find_all_items(root)
        assert _text(items[0], "ProjectName") == "令和7年度 広報誌印刷業務"

    def test_missing_tag(self) -> None:
        root = _load_fixture()
        items = _find_all_items(root)
        assert _text(items[0], "NonExistentTag") is None


class TestFindAllItems:
    def test_finds_all_search_results(self) -> None:
        root = _load_fixture()
        items = _find_all_items(root)
        assert len(items) == 5


class TestParseProject:
    def test_valid_tokyo_project(self) -> None:
        root = _load_fixture()
        items = _find_all_items(root)
        project = _parse_project(items[0])
        assert project is not None
        assert project.title == "令和7年度 広報誌印刷業務"
        assert project.organization == "東京都総務局"
        assert project.bid_type == "一般競争入札"
        assert project.publish_date == "2026-03-15"
        assert project.deadline == "2026-04-30"
        assert project.source == "官公需"

    def test_valid_saitama_project(self) -> None:
        root = _load_fixture()
        items = _find_all_items(root)
        project = _parse_project(items[1])
        assert project is not None
        assert project.organization == "埼玉県教育委員会"

    def test_central_government_empty_prefecture(self) -> None:
        """PrefectureName空欄（中央省庁）は地域フィルタを通過する"""
        root = _load_fixture()
        items = _find_all_items(root)
        project = _parse_project(items[2])
        # 道路が除外キーワードに含まれるため除外される
        assert project is None

    def test_excluded_by_region(self) -> None:
        """対象地域外（北海道）は除外される"""
        root = _load_fixture()
        items = _find_all_items(root)
        project = _parse_project(items[3])
        assert project is None

    def test_excluded_by_deadline(self) -> None:
        """締切済み案件は除外される"""
        root = _load_fixture()
        items = _find_all_items(root)
        project = _parse_project(items[4])
        assert project is None
