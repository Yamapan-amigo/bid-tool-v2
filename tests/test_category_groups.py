"""カテゴリグループ・対象業種設定のテスト"""

from src.config import (
    CATEGORY_GROUPS,
    CATEGORY_KEYWORDS,
    COMPANY_TARGET_CATEGORIES,
)
from src.core.models import BidProject
from src.core.scorer import calculate_score


def test_all_group_members_in_keywords() -> None:
    valid = set(CATEGORY_KEYWORDS.keys())
    for group_name, members in CATEGORY_GROUPS.items():
        for m in members:
            assert m in valid, f"{group_name} の '{m}' は CATEGORY_KEYWORDS に未定義"


def test_target_categories_matches_group() -> None:
    assert COMPANY_TARGET_CATEGORIES == set(CATEGORY_GROUPS["印刷業種すべて"])


def test_publishing_keywords_in_print_category() -> None:
    keywords = CATEGORY_KEYWORDS["印刷・製本"]
    assert "出版物" in keywords
    assert "書籍" in keywords
    assert "刊行物" in keywords
    assert "図書" in keywords


def test_non_target_category_score_capped() -> None:
    """対象外カテゴリの案件はスコアが1.5以下になる"""
    project = BidProject(
        title="コピー用紙購入",
        organization="東京都",
        bid_type="一般競争入札",
        category="用紙・消耗品",
        eligibility_overall="◎",
    )
    score = calculate_score(project)
    assert score <= 1.5, f"対象外カテゴリのスコアが1.5超: {score}"


def test_target_category_score_not_capped() -> None:
    """対象カテゴリの案件はスコアが1.5を超えられる"""
    project = BidProject(
        title="広報誌印刷",
        organization="東京都",
        bid_type="一般競争入札",
        category="印刷・製本",
        eligibility_overall="◎",
    )
    score = calculate_score(project)
    assert score > 1.5, f"対象カテゴリのスコアが1.5以下: {score}"


def test_ng_eligibility_overrides_category_cap() -> None:
    """eligibility=×は対象カテゴリでも強制1.0"""
    project = BidProject(
        title="広報誌印刷",
        organization="東京都",
        bid_type="一般競争入札",
        category="印刷・製本",
        eligibility_overall="×",
    )
    score = calculate_score(project)
    assert score == 1.0
