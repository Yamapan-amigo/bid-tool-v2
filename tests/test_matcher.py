"""過去金額マッチングのテスト"""

from __future__ import annotations

from src.core.matcher import _normalize_title, _title_similarity, match_past_results
from src.core.models import AwardResult, BidProject


class TestNormalizeTitle:
    def test_removes_reiwa_year(self) -> None:
        assert _normalize_title("令和7年度 広報誌印刷") == "広報誌印刷"

    def test_removes_heisei_year(self) -> None:
        assert _normalize_title("平成31年 パンフレット作成") == "パンフレット作成"

    def test_removes_western_year(self) -> None:
        assert _normalize_title("2025年度 封筒印刷") == "封筒印刷"

    def test_removes_bracket_decorations(self) -> None:
        # 【...】内のテキスト全体が除去される
        assert _normalize_title("【関東地方整備局】印刷業務") == "印刷業務"

    def test_removes_generic_words(self) -> None:
        # 「業務委託」等の汎用語が除去される
        assert _normalize_title("広報誌印刷業務委託") == "広報誌印刷"

    def test_removes_pdf_size(self) -> None:
        assert _normalize_title("事務用消耗品の購入（PDF 1,858KB）") == "事務用消耗品の購入"


class TestTitleSimilarity:
    def test_identical_titles(self) -> None:
        assert _title_similarity("広報誌印刷", "広報誌印刷") == 1.0

    def test_completely_different(self) -> None:
        sim = _title_similarity("広報誌印刷", "システム開発")
        assert sim < 0.3

    def test_similar_titles(self) -> None:
        sim = _title_similarity("広報誌印刷業務委託", "広報誌印刷業務")
        assert sim > 0.7

    def test_empty_strings(self) -> None:
        assert _title_similarity("", "test") == 0.0
        assert _title_similarity("test", "") == 0.0


class TestMatchPastResults:
    def _make_project(self, title: str, org: str = "東京都") -> BidProject:
        return BidProject(title=title, organization=org)

    def _make_result(
        self,
        title: str,
        price: int = 1_000_000,
        winner: str = "テスト印刷",
    ) -> AwardResult:
        return AwardResult(
            case_id="001",
            title=title,
            award_date="2025-04-01",
            award_price=price,
            cert_code="S1",
            org_code="8002010",
            winner=winner,
            corporate_number="111",
        )

    def test_exact_match_different_year(self) -> None:
        projects = [self._make_project("令和7年度 広報誌印刷業務")]
        results = [self._make_result("令和6年度 広報誌印刷業務", price=800_000, winner="A社")]

        matched = match_past_results(projects, results)

        assert len(matched) == 1
        assert matched[0].past_award_price == 800_000
        assert matched[0].past_award_winner == "A社"

    def test_no_match_below_threshold(self) -> None:
        projects = [self._make_project("封筒印刷")]
        results = [self._make_result("システム開発業務")]

        matched = match_past_results(projects, results)

        assert matched[0].past_award_price is None

    def test_empty_results(self) -> None:
        projects = [self._make_project("印刷業務")]
        matched = match_past_results(projects, [])

        assert len(matched) == 1
        assert matched[0].past_award_price is None

    def test_best_match_selected(self) -> None:
        projects = [self._make_project("令和7年度 広報誌印刷")]
        results = [
            self._make_result("令和6年度 広報誌印刷", price=900_000, winner="A社"),
            self._make_result("令和6年度 チラシ印刷", price=500_000, winner="B社"),
        ]

        matched = match_past_results(projects, results)

        assert matched[0].past_award_price == 900_000
        assert matched[0].past_award_winner == "A社"

    def test_preserves_original_when_no_match(self) -> None:
        projects = [self._make_project("特殊業務")]
        results = [self._make_result("全く別の案件")]

        matched = match_past_results(projects, results)

        assert matched[0].title == "特殊業務"
        assert matched[0].past_award_price is None
