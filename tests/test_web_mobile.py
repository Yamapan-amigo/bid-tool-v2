"""モバイル対応（レスポンシブデザイン）のテスト

スマホで見やすく表示されることを検証する。
既存のデスクトップ表示を壊さず、media queryで追加対応する方針。
"""

from __future__ import annotations

import pytest

from src.web import _render_html


@pytest.fixture
def empty_html() -> str:
    """案件ゼロでレンダリングしたHTML（Gemini呼び出しを回避）"""
    return _render_html([], raw_count=0, award_count=0, matched_count=0)


def test_viewport_meta_exists(empty_html: str) -> None:
    """viewportメタタグが設定されている"""
    assert 'name="viewport"' in empty_html
    assert "width=device-width" in empty_html
    assert "initial-scale=1" in empty_html


def test_media_query_for_mobile_exists(empty_html: str) -> None:
    """モバイル向けのmedia queryが存在する"""
    assert "@media" in empty_html
    # 768px以下のブレイクポイントが必要
    assert "max-width: 768px" in empty_html or "max-width:768px" in empty_html


def test_mobile_table_responsive(empty_html: str) -> None:
    """テーブルがモバイルで横スクロール or カード化される"""
    # モバイル対応: 重要でない列を非表示にする OR カードレイアウトに切り替える
    # どちらかの戦略を許容する
    has_column_hiding = (
        "display: none" in empty_html or "display:none" in empty_html
    )
    has_card_layout = "display: block" in empty_html or "display:block" in empty_html
    assert has_column_hiding or has_card_layout, (
        "モバイルでテーブルの非重要列を非表示にするか、カード化する必要あり"
    )


def test_mobile_header_padding_reduced(empty_html: str) -> None:
    """モバイルではヘッダーの余白を縮小する"""
    # @media セクション内で padding 調整がある
    import re

    media_sections = re.findall(
        r"@media[^{]+\{((?:[^{}]|\{[^{}]*\})*)\}",
        empty_html,
        re.DOTALL,
    )
    assert media_sections, "media queryブロックがない"
    combined = "".join(media_sections)
    assert "padding" in combined, "モバイル版でpadding調整がない"


def test_desktop_styles_preserved(empty_html: str) -> None:
    """既存のデスクトップスタイルが保持されている（回帰防止）"""
    # 既存のキー要素が残っていること
    assert ".header" in empty_html
    assert ".stats" in empty_html
    assert ".stat-card" in empty_html
    assert ".filters" in empty_html
    assert "linear-gradient(135deg, #1a73e8, #0d47a1)" in empty_html
    # モーダル
    assert ".modal" in empty_html
    assert ".overlay" in empty_html
