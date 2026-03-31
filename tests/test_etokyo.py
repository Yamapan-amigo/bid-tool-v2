"""e-Tokyo HTMLパーサーのテスト"""

from __future__ import annotations

from pathlib import Path

from src.sources.etokyo import (
    _extract_case_id,
    _format_etokyo_date,
    _parse_project_list,
    _parse_total_pages,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "etokyo_search_result.html"


def _load_fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


class TestParseProjectList:
    def test_parses_all_rows(self) -> None:
        html = _load_fixture()
        projects = _parse_project_list(html)
        assert len(projects) == 3

    def test_first_project_fields(self) -> None:
        html = _load_fixture()
        projects = _parse_project_list(html)
        p = projects[0]
        assert p.title == "広報しんじゅく印刷業務委託"
        assert p.organization == "新宿区"
        assert p.bid_type == "一般競争入札"
        assert p.publish_date == "2026-03-15"
        assert p.deadline == "2026-04-20"
        assert p.source == "e-Tokyo"

    def test_second_project_bid_type(self) -> None:
        html = _load_fixture()
        projects = _parse_project_list(html)
        assert projects[1].bid_type == "指名競争入札"

    def test_third_project_bid_type(self) -> None:
        html = _load_fixture()
        projects = _parse_project_list(html)
        assert projects[2].bid_type == "随意契約（見積競争）"

    def test_detail_url_constructed(self) -> None:
        html = _load_fixture()
        projects = _parse_project_list(html)
        assert "s=P002&a=12&n=2026:13:101:00310" in projects[0].detail_url


class TestExtractCaseId:
    def test_extracts_case_id(self) -> None:
        row = (
            '<a href="javascript:listSubmit('
            "'P002','12','2026:13:101:00310','1','FrmMain')"
            '">test</a>'
        )
        assert _extract_case_id(row) == "2026:13:101:00310"

    def test_no_match(self) -> None:
        assert _extract_case_id("<td>no link</td>") is None


class TestFormatEtokyoDate:
    def test_standard_date(self) -> None:
        assert _format_etokyo_date("2026/3/15") == "2026-03-15"

    def test_date_with_time(self) -> None:
        assert _format_etokyo_date("2026/4/20 17:00") == "2026-04-20"

    def test_empty_string(self) -> None:
        assert _format_etokyo_date("") == ""

    def test_invalid_format(self) -> None:
        assert _format_etokyo_date("not a date") == ""


class TestParseTotalPages:
    def test_single_page(self) -> None:
        html = _load_fixture()
        assert _parse_total_pages(html) == 1

    def test_multi_page(self) -> None:
        html = "全103件[1-50] 1/3ページ"
        assert _parse_total_pages(html) == 3

    def test_no_pagination(self) -> None:
        assert _parse_total_pages("<html></html>") == 1
