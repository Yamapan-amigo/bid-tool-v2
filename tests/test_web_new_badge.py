"""新着バッジのテスト

公告日から3日以内の案件に「NEW」バッジを表示する。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.core.models import BidProject
from src.web import _render_html


def _make_project(publish_date: str, title: str = "テスト案件") -> BidProject:
    return BidProject(
        title=title,
        organization="テスト機関",
        bid_type="一般競争入札",
        publish_date=publish_date,
        deadline="2026-05-01",
        source="官公需",
    )


@pytest.fixture
def html_with_dates() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    projects = [
        _make_project(today, title="本日公告"),
        _make_project(
            (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
            title="2日前公告",
        ),
        _make_project(
            (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
            title="3日前公告",
        ),
        _make_project(
            (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d"),
            title="4日前公告",
        ),
        _make_project(
            (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
            title="10日前公告",
        ),
    ]
    with patch("src.web._extract_summary", return_value="テスト要約"):
        return _render_html(projects, raw_count=5, award_count=0, matched_count=0)


def test_new_badge_css_exists(html_with_dates: str) -> None:
    """新着バッジ用のCSSが定義されている"""
    assert ".badge-new" in html_with_dates


def test_new_badge_has_color(html_with_dates: str) -> None:
    """新着バッジが目立つ色を持つ"""
    import re

    match = re.search(r"\.badge-new\s*\{[^}]*\}", html_with_dates)
    assert match, ".badge-new のCSS定義がない"
    style = match.group()
    assert "background" in style


def test_today_has_new_badge(html_with_dates: str) -> None:
    """本日公告の案件にNEWバッジが付く"""
    lines = html_with_dates.split("\n")
    for i, line in enumerate(lines):
        if "本日公告" in line:
            block = "\n".join(lines[max(0, i - 2): i + 10])
            assert "badge-new" in block, "本日公告の行にbadge-newがない"
            return
    pytest.fail("本日公告の行が見つからない")


def test_2days_ago_has_new_badge(html_with_dates: str) -> None:
    """2日前公告の案件にNEWバッジが付く"""
    lines = html_with_dates.split("\n")
    for i, line in enumerate(lines):
        if "2日前公告" in line:
            block = "\n".join(lines[max(0, i - 2): i + 10])
            assert "badge-new" in block, "2日前公告の行にbadge-newがない"
            return
    pytest.fail("2日前公告の行が見つからない")


def test_3days_ago_has_new_badge(html_with_dates: str) -> None:
    """3日前公告の案件にNEWバッジが付く（3日以内＝当日含め3日間）"""
    lines = html_with_dates.split("\n")
    for i, line in enumerate(lines):
        if "3日前公告" in line:
            block = "\n".join(lines[max(0, i - 2): i + 10])
            assert "badge-new" in block, "3日前公告の行にbadge-newがない"
            return
    pytest.fail("3日前公告の行が見つからない")


def test_4days_ago_no_badge(html_with_dates: str) -> None:
    """4日前公告の案件にはNEWバッジなし"""
    lines = html_with_dates.split("\n")
    for i, line in enumerate(lines):
        if "4日前公告" in line:
            block = "\n".join(lines[max(0, i - 2): i + 10])
            assert "badge-new" not in block
            return
    pytest.fail("4日前公告の行が見つからない")


def test_10days_ago_no_badge(html_with_dates: str) -> None:
    """10日前公告の案件にはNEWバッジなし"""
    lines = html_with_dates.split("\n")
    for i, line in enumerate(lines):
        if "10日前公告" in line:
            block = "\n".join(lines[max(0, i - 2): i + 10])
            assert "badge-new" not in block
            return
    pytest.fail("10日前公告の行が見つからない")
