"""フィルタ・スコアリング・重複排除のテスト"""

from __future__ import annotations

from src.core.dedup import deduplicate
from src.core.filter import apply_filters, filter_by_business_keywords, filter_designated_bids, is_actual_project
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

    def test_removes_designated_bids(self) -> None:
        projects = [
            BidProject(title="広報誌印刷", organization="東京都", bid_type="一般競争入札"),
            BidProject(title="封筒印刷", organization="東京都", bid_type="指名競争入札"),
        ]
        result = apply_filters(projects)
        assert len(result) == 1
        assert result[0].bid_type == "一般競争入札"


class TestFilterDesignatedBids:
    def test_removes_designated(self) -> None:
        projects = [
            BidProject(title="広報誌印刷", organization="東京都", bid_type="一般競争入札"),
            BidProject(title="流山市ブランド映像", organization="千葉県流山市", bid_type="指名競争入札"),
        ]
        result = filter_designated_bids(projects)
        assert len(result) == 1
        assert result[0].bid_type == "一般競争入札"

    def test_keeps_all_other_bid_types(self) -> None:
        projects = [
            BidProject(title="印刷A", organization="東京都", bid_type="一般競争入札"),
            BidProject(title="印刷B", organization="東京都", bid_type="公募型プロポーザル"),
            BidProject(title="印刷C", organization="東京都", bid_type="随意契約"),
        ]
        result = filter_designated_bids(projects)
        assert len(result) == 3


# ============================================================
# スコアリングテスト
# ============================================================


class TestCalculateScore:
    def test_base_score(self) -> None:
        p = BidProject(title="事務用品納入", organization="神奈川県")
        score = calculate_score(p)
        assert score == 2.5  # 印刷キーワードなし → cap 2.5

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
        # base(3) + bid(1) = 4.0 → 印刷キーワードなしでcap 2.5
        assert score == 2.5

    def test_tokyo_bonus(self) -> None:
        p = BidProject(title="事務用品納入", organization="東京都総務局")
        score = calculate_score(p)
        assert score == 2.5  # base(3) + tokyo(0.5) → cap 2.5（印刷キーワードなし）

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

    def test_proposal_penalty(self) -> None:
        p = BidProject(
            title="広報誌印刷業務",
            organization="東京都",
            bid_type="公募型プロポーザル",
        )
        score = calculate_score(p)
        # base(3) + high_kw(広報誌=2) + tokyo(0.5) - proposal(1.5) = 4.0
        assert score == 4.0

    def test_ineligible_forces_score_1(self) -> None:
        """eligibility_overall=× は他の加点に関わらず強制的に1.0"""
        p = BidProject(
            title="広報誌印刷業務",
            organization="東京都総務局",
            bid_type="一般競争入札",
            eligibility_overall="×",
        )
        assert calculate_score(p) == 1.0

    def test_invalid_deadline_does_not_crash(self) -> None:
        """不正な締切日形式はエラーを出さずスキップ"""
        p = BidProject(
            title="事務用品納入",
            organization="東京都",
            deadline="invalid-date",
        )
        score = calculate_score(p)
        assert score == 2.5  # base(3) + tokyo(0.5) → cap 2.5（印刷キーワードなし）

    def test_high_award_price_penalty(self) -> None:
        """過去落札金額が300万超はスコア上限1.5に打ち切り"""
        p = BidProject(
            title="事務用品納入",
            organization="神奈川県",
            past_award_price=5_000_000,
        )
        score = calculate_score(p)
        assert score == 1.5  # base(3) → min(3.0, 1.5) = 1.5 (高額打ち切り)

    def test_target_award_price_bonus(self) -> None:
        """50万〜150万の落札実績は強ボーナス+1.5"""
        p = BidProject(
            title="封筒印刷購入",
            organization="神奈川県",
            past_award_price=1_000_000,
        )
        score = calculate_score(p)
        # base(3) + mid_kw(封筒=1.0) + price_bonus(1.5) = 5.5 → capped 5.0
        assert score == 5.0


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
        assert row[1] == "○"           # 応募可否
        assert row[2] == "印刷業務"    # 案件名
        assert row[3] == "東京都"      # 発注元
        assert row[12] == ""           # 過去落札金額（未設定）
        assert row[13] == ""           # 過去落札者（未設定）
        assert row[17] == "4.5"        # スコア
        assert row[19] == "未確認"     # ステータス
        assert len(row) == 20          # 20列

    def test_to_row_with_past_award(self) -> None:
        p = BidProject(
            title="印刷業務",
            organization="東京都",
            score=4.0,
            past_award_price=1_000_000,
            past_award_winner="株式会社テスト印刷",
        )
        row = p.to_row("2026-04-01")
        assert row[12] == "1,000,000"          # 過去落札金額
        assert row[13] == "株式会社テスト印刷"  # 過去落札者


# ============================================================
# 業種フィルタテスト
# ============================================================


class TestFilterByBusinessKeywords:
    def test_excludes_ship_parts(self) -> None:
        p = BidProject(title="左舷船尾管整備部品購入", organization="国土交通省")
        assert filter_by_business_keywords([p]) == []

    def test_excludes_battery(self) -> None:
        p = BidProject(title="蓄電池ユニット購入", organization="東京都")
        assert filter_by_business_keywords([p]) == []

    def test_excludes_detector(self) -> None:
        p = BidProject(title="Ge検出器購入", organization="環境省")
        assert filter_by_business_keywords([p]) == []

    def test_excludes_laptop(self) -> None:
        p = BidProject(title="ノートパソコン調達", organization="東京都")
        assert filter_by_business_keywords([p]) == []

    def test_keeps_print_project(self) -> None:
        p = BidProject(title="広報誌印刷業務委託", organization="東京都")
        assert len(filter_by_business_keywords([p])) == 1

    def test_keeps_design_project(self) -> None:
        p = BidProject(title="チラシ・ポスターデザイン制作", organization="東京都")
        assert len(filter_by_business_keywords([p])) == 1

    def test_empty_list(self) -> None:
        assert filter_by_business_keywords([]) == []

    def test_apply_filters_excludes_hardware(self) -> None:
        p = BidProject(title="整備部品購入", organization="東京都", bid_type="一般競争入札", deadline="2099-12-31")
        assert apply_filters([p]) == []

    def test_apply_filters_keeps_print(self) -> None:
        p = BidProject(title="広報誌印刷", organization="東京都", bid_type="一般競争入札", deadline="2099-12-31")
        assert len(apply_filters([p])) == 1


class TestNonPrintScoreCap:
    def test_non_print_capped_at_2_5(self) -> None:
        """印刷キーワードなし案件はスコア上限2.5（閾値3.0未満）"""
        p = BidProject(title="事務用品納入", organization="東京都", bid_type="一般競争入札")
        assert calculate_score(p) == 2.5

    def test_print_keyword_not_capped(self) -> None:
        """印刷キーワードあり案件はcap適用外"""
        p = BidProject(title="広報誌印刷", organization="東京都", bid_type="一般競争入札")
        assert calculate_score(p) > 2.5
