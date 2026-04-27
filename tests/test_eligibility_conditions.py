"""応募条件チェック（資本金・従業員数・年商・資格・創業年数）のテスト"""

from __future__ import annotations

from src.core.extractor import extract_eligibility


class TestCapitalRequirement:
    def test_capital_too_low(self) -> None:
        """資本金要件が会社の資本金を超える → NG"""
        text = "資本金が1000万円以上の者であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False
        assert "資本金" in info.region_text

    def test_capital_ok(self) -> None:
        """資本金要件が会社の資本金以下 → 通過"""
        text = "資本金が300万円以上の者であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is not False or "資本金" not in info.region_text

    def test_capital_okuyen(self) -> None:
        """1億円以上の資本金要件 → NG（500万円）"""
        text = "資本の額が1億円以上であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False
        assert "資本金" in info.region_text


class TestEmployeeRequirement:
    def test_employees_too_few(self) -> None:
        """従業員数要件が1名を超える → NG"""
        text = "常時雇用する従業員が5名以上であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False
        assert "従業員" in info.region_text

    def test_employees_ok(self) -> None:
        """1名以上の要件 → 通過"""
        text = "常時従業員を1名以上雇用していること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is not False or "従業員" not in info.region_text

    def test_employees_10_ng(self) -> None:
        """従業員10名以上 → NG"""
        text = "従業員数が10名以上の事業者であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False


class TestRevenueRequirement:
    def test_revenue_too_low(self) -> None:
        """年商2億円以上の要件 → NG（1億円）"""
        text = "直近3年間の年間売上高が2億円以上の者"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False
        assert "年商" in info.region_text

    def test_revenue_ok(self) -> None:
        """年商5000万円以上 → 通過（1億円）"""
        text = "年間売上高が5000万円以上であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is not False or "年商" not in info.region_text

    def test_revenue_senman(self) -> None:
        """年商3000万円以上 → 通過"""
        text = "年商が3000万円以上の事業者であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is not False or "年商" not in info.region_text


class TestCertificationRequirement:
    def test_iso_required_no_cert(self) -> None:
        """ISO認証が要件 → 保有なしのためNG"""
        text = "ISO9001認証を取得していること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False
        assert "資格" in info.region_text

    def test_fsc_required(self) -> None:
        """FSC認証が要件 → NG"""
        text = "FSC認証を取得している事業者であること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False

    def test_no_cert_required(self) -> None:
        """資格要件なし → 通過"""
        text = "入札参加要件を満たす者であること"
        info = extract_eligibility(text, "東京都")
        assert "資格" not in info.region_text


class TestFoundingYearsRequirement:
    def test_founding_years_ok(self) -> None:
        """設立3年以上 → 通過（10年）"""
        text = "設立から3年以上経過していること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is not False or "設立" not in info.region_text

    def test_founding_years_ng(self) -> None:
        """設立15年以上 → NG（10年）"""
        text = "設立後15年以上経過していること"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is False
        assert "設立" in info.region_text
