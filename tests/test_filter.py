"""フィルタ・スコアリング・重複排除のテスト"""

from __future__ import annotations

from src.core.dedup import deduplicate
from src.core.filter import apply_filters, is_actual_project
from src.core.models import BidProject
from src.core.scorer import calculate_score

# ============================================================
# フィルタテスト
# ============================================================


class TestIsActualProject:
    def test_valid_project(self) -> None:
        assert is_actual_project("広報誌印刷業務委託") is True

    def test_empty_title(self) -> None:
        assert is_actual_project("") is False

    def test_template_excluded(self) -> None:
        assert is_actual_project("入札参加申請書") is False

    def test_jv_excluded(self) -> None:
        assert is_actual_project("JV向け共同請負") is False

    def test_guideline_excluded(self) -> None:
        assert is_actual_project("入札参加要綱") is False

    def test_list_excluded(self) -> None:
        assert is_actual_project("公告案件一覧") is False


class TestApplyFilters:
    def test_removes_expired_and_non_projects(self) -> None:
        projects = [
            BidProject(title="広報誌印刷", organization="東京都", deadline="2099-12-31"),
            BidProject(title="申請書様式", organization="東京都", deadline="2099-12-31"),
            BidProject(title="封筒印刷", organization="千葉県", deadline="2020-01-01"),
        ]
        result = apply_filters(projects)
        assert len(result) == 1
        assert result[0].title == "広報誌印刷"


# ============================================================
# スコアリングテスト
# ============================================================


class TestCalculateScore:
    def test_base_score(self) -> None:
        p = BidProject(title="事務用品納入", organization="神奈川県")
        score = calculate_score(p)
        assert score == 3.0

    def test_core_keyword_bonus(self) -> None:
        p = BidProject(title="広報誌印刷業務", organization="神奈川県")
        score = calculate_score(p)
        assert score >= 4.0  # base(3) + core(1)

    def test_general_bid_bonus(self) -> None:
        p = BidProject(
            title="事務用品納入",
            organization="神奈川県",
            bid_type="一般競争入札",
        )
        score = calculate_score(p)
        assert score == 4.0  # base(3) + bid(1)

    def test_tokyo_bonus(self) -> None:
        p = BidProject(title="事務用品納入", organization="東京都総務局")
        score = calculate_score(p)
        assert score == 3.5  # base(3) + tokyo(0.5)

    def test_penalty_keyword(self) -> None:
        p = BidProject(title="情報システム開発業務", organization="東京都")
        score = calculate_score(p)
        assert score == 1.5  # base(3) + tokyo(0.5) - penalty(2)

    def test_max_score_capped_at_5(self) -> None:
        p = BidProject(
            title="広報誌印刷業務",
            organization="東京都総務局",
            bid_type="一般競争入札",
            deadline="2099-12-31",
        )
        score = calculate_score(p)
        assert score == 5.0

    def test_min_score_capped_at_1(self) -> None:
        p = BidProject(title="システム工事清掃", organization="神奈川県")
        score = calculate_score(p)
        assert score == 1.0  # base(3) - penalty(2)*multiple, but capped


# ============================================================
# 重複排除テスト
# ============================================================


class TestDeduplicate:
    def test_removes_duplicates(self) -> None:
        projects = [
            BidProject(title="印刷業務", organization="東京都", source="官公需"),
            BidProject(title="印刷業務", organization="東京都", source="e-Tokyo"),
            BidProject(title="製本業務", organization="千葉県", source="官公需"),
        ]
        result = deduplicate(projects)
        assert len(result) == 2

    def test_keeps_first_occurrence(self) -> None:
        projects = [
            BidProject(title="印刷業務", organization="東京都", source="官公需"),
            BidProject(title="印刷業務", organization="東京都", source="e-Tokyo"),
        ]
        result = deduplicate(projects)
        assert result[0].source == "官公需"

    def test_no_duplicates(self) -> None:
        projects = [
            BidProject(title="印刷業務", organization="東京都"),
            BidProject(title="製本業務", organization="千葉県"),
        ]
        result = deduplicate(projects)
        assert len(result) == 2


# ============================================================
# モデルテスト
# ============================================================


class TestBidProject:
    def test_dedup_key(self) -> None:
        p = BidProject(title="印刷業務", organization="東京都")
        assert p.dedup_key == "印刷業務|東京都"

    def test_with_score_returns_new_instance(self) -> None:
        p = BidProject(title="印刷業務", organization="東京都", score=3.0)
        p2 = p.with_score(5.0)
        assert p.score == 3.0  # 元のインスタンスは変わらない
        assert p2.score == 5.0

    def test_to_row(self) -> None:
        p = BidProject(
            title="印刷業務",
            organization="東京都",
            bid_type="一般競争入札",
            publish_date="2026-03-15",
            deadline="2026-04-30",
            detail_url="https://example.com",
            source="官公需",
            score=4.5,
        )
        row = p.to_row("2026-04-01")
        assert row[0] == "2026-04-01"  # 取得日
        assert row[1] == "印刷業務"  # 案件名
        assert row[2] == "東京都"  # 発注元
        assert row[6] == ""  # 過去落札金額（未設定）
        assert row[7] == ""  # 過去落札者（未設定）
        assert row[10] == "4.5"  # スコア
        assert row[12] == "未確認"  # ステータス
        assert len(row) == 13  # 13列

    def test_to_row_with_past_award(self) -> None:
        p = BidProject(
            title="印刷業務",
            organization="東京都",
            score=4.0,
            past_award_price=1_000_000,
            past_award_winner="株式会社テスト印刷",
        )
        row = p.to_row("2026-04-01")
        assert row[6] == "1,000,000"  # 過去落札金額
        assert row[7] == "株式会社テスト印刷"  # 過去落札者
