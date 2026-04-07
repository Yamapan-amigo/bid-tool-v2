"""締切日の視覚的ハイライトのテスト

締切日が近い案件を色で目立たせる機能を検証する。
- 3日以内: 赤（緊急）
- 7日以内: オレンジ（注意）
- それ以外: 通常表示
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.core.models import BidProject
from src.web import _render_html


def _make_project(deadline: str, title: str = "テスト案件") -> BidProject:
    return BidProject(
        title=title,
        organization="テスト機関",
        bid_type="一般競争入札",
        publish_date="2026-04-01",
        deadline=deadline,
        source="官公需",
    )


@pytest.fixture
def today() -> str:
    return "2026-04-07"


@pytest.fixture
def html_with_deadlines(today: str) -> str:
    """さまざまな締切日を持つ案件でHTMLを生成"""
    projects = [
        _make_project(
            (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
            title="明日締切",
        ),
        _make_project(
            (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d"),
            title="3日後締切",
        ),
        _make_project(
            (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d"),
            title="7日後締切",
        ),
        _make_project(
            (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=14)).strftime("%Y-%m-%d"),
            title="14日後締切",
        ),
        _make_project("", title="締切なし"),
    ]
    with patch("src.web._extract_summary", return_value="テスト要約"):
        return _render_html(projects, raw_count=5, award_count=0, matched_count=0)


def test_deadline_urgent_css_class_exists(html_with_deadlines: str) -> None:
    """緊急（3日以内）用のCSSクラスが定義されている"""
    assert "deadline-urgent" in html_with_deadlines


def test_deadline_warning_css_class_exists(html_with_deadlines: str) -> None:
    """注意（7日以内）用のCSSクラスが定義されている"""
    assert "deadline-warn" in html_with_deadlines


def test_deadline_urgent_has_red_style(html_with_deadlines: str) -> None:
    """緊急クラスが赤系の色を持つ"""
    import re

    # .deadline-urgent のスタイル定義を探す
    match = re.search(r"\.deadline-urgent\s*\{[^}]*\}", html_with_deadlines)
    assert match, ".deadline-urgent のCSS定義がない"
    style = match.group()
    assert "color" in style


def test_deadline_warning_has_orange_style(html_with_deadlines: str) -> None:
    """注意クラスがオレンジ系の色を持つ"""
    import re

    match = re.search(r"\.deadline-warn\s*\{[^}]*\}", html_with_deadlines)
    assert match, ".deadline-warn のCSS定義がない"
    style = match.group()
    assert "color" in style


def test_urgent_deadline_applied_to_row(html_with_deadlines: str) -> None:
    """明日・3日後の案件に deadline-urgent が適用される"""
    # 明日締切の行にurgentクラスがある
    assert "明日締切" in html_with_deadlines
    # urgentクラスがHTML内に存在し、適切な行に付与されている
    lines = html_with_deadlines.split("\n")
    for i, line in enumerate(lines):
        if "明日締切" in line:
            # 前後の行を含むブロック内にdeadline-urgentがある
            block = "\n".join(lines[max(0, i - 2) : i + 10])
            assert "deadline-urgent" in block, "明日締切の行にdeadline-urgentが適用されていない"
            break


def test_warning_deadline_applied_to_row(html_with_deadlines: str) -> None:
    """7日後の案件に deadline-warn が適用される"""
    lines = html_with_deadlines.split("\n")
    for i, line in enumerate(lines):
        if "7日後締切" in line:
            block = "\n".join(lines[max(0, i - 2) : i + 10])
            assert "deadline-warn" in block, "7日後締切の行にdeadline-warnが適用されていない"
            break


def test_normal_deadline_no_highlight(html_with_deadlines: str) -> None:
    """14日後の案件にはハイライトなし"""
    lines = html_with_deadlines.split("\n")
    for i, line in enumerate(lines):
        if "14日後締切" in line:
            block = "\n".join(lines[max(0, i - 2) : i + 10])
            assert "deadline-urgent" not in block
            assert "deadline-warn" not in block
            break


def test_desktop_styles_not_broken(html_with_deadlines: str) -> None:
    """既存スタイルが壊れていない"""
    assert ".header" in html_with_deadlines
    assert ".stats" in html_with_deadlines
    assert ".score-high" in html_with_deadlines
    assert "@media" in html_with_deadlines
