"""応募条件抽出のテスト"""

from src.core.extractor import extract_eligibility


class TestGradeExtraction:
    def test_abcd_grade(self) -> None:
        text = "物品の販売のA、B、C又はD等級に格付けされている者"
        info = extract_eligibility(text, "厚生労働省")
        assert info.d_grade_ok is True
        assert "D" in info.grade_text

    def test_ab_only(self) -> None:
        text = "等級格付区分がA又はBの者であること"
        info = extract_eligibility(text, "群馬県")
        assert info.d_grade_ok is False
        assert "D" not in info.grade_text

    def test_a_only(self) -> None:
        text = "等級格付区分がAの者であること"
        info = extract_eligibility(text, "群馬県")
        assert info.d_grade_ok is False

    def test_bcd_grade(self) -> None:
        text = "「印刷類」又は「その他印刷類」でＢ、Ｃ又はＤ等級に格付けされ"
        info = extract_eligibility(text, "厚生労働省")
        assert info.d_grade_ok is True

    def test_fullwidth_bracket_grade(self) -> None:
        text = "「Ｃ」又は「Ｄ」の等級に格付されている者であること"
        info = extract_eligibility(text, "林野庁")
        assert info.d_grade_ok is True
        assert "D" in info.grade_text

    def test_no_grade_info(self) -> None:
        text = "入札に参加する者は次の条件を満たすこと"
        info = extract_eligibility(text, "東京都")
        assert info.d_grade_ok is None


class TestRegionExtraction:
    def test_gunma_kennnai(self) -> None:
        text = "本社又は委任先営業所の所在地が群馬県内であること"
        info = extract_eligibility(text, "群馬県")
        assert info.region_ok is False
        assert "群馬" in info.region_text

    def test_kanto_region(self) -> None:
        text = "関東・甲信越地域の競争参加資格を有する者"
        info = extract_eligibility(text, "厚生労働省")
        assert info.region_ok is True

    def test_no_region_restriction(self) -> None:
        text = "予算決算及び会計令第70条の規定に該当しない者"
        info = extract_eligibility(text, "林野庁")
        assert info.region_ok is True
        assert "制限なし" in info.region_text

    def test_tokai_is_not_region_restriction(self) -> None:
        # 「東海村」は地域制限ではなく所在地
        text = "茨城県東海村 国立研究開発法人 物品の販売のA、B、C又はD等級"
        info = extract_eligibility(text, "日本原子力研究開発機構")
        assert info.region_ok is True

    def test_shinai_kawagoe_ng(self) -> None:
        # 川越市内限定 → 大島さん（東京拠点）はNG
        text = "市内に本店又は受任支店等"
        info = extract_eligibility(text, "埼玉県川越市")
        assert info.region_ok is False

    def test_tonai_ok(self) -> None:
        # 東京都内限定 → 大島さんOK
        text = "都内に本店又は営業所を有する者"
        info = extract_eligibility(text, "東京都")
        assert info.region_ok is True


class TestSubmissionMethod:
    def test_electronic(self) -> None:
        text = "入札書の提出はぐんま電子入札共同システムによるものとする"
        info = extract_eligibility(text, "群馬県")
        assert "電子入札" in info.submission_method

    def test_mail(self) -> None:
        text = "郵便入札実施要綱による郵便入札"
        info = extract_eligibility(text, "佐野市")
        assert "郵便" in info.submission_method

    def test_multiple_methods(self) -> None:
        text = "電子入札又は持参により提出すること"
        info = extract_eligibility(text, "東京都")
        assert "電子入札" in info.submission_method
        assert "持参" in info.submission_method


class TestOverallJudgment:
    def test_eligible(self) -> None:
        text = "物品の販売のA、B、C又はD等級に格付けされている者 関東地域"
        info = extract_eligibility(text, "厚生労働省")
        assert info.overall == "◎"

    def test_not_eligible_grade(self) -> None:
        text = "等級格付区分がA又はBの者であること"
        info = extract_eligibility(text, "群馬県")
        assert info.overall == "×"

    def test_not_eligible_region(self) -> None:
        text = "本社又は委任先営業所の所在地が群馬県内であること D等級"
        info = extract_eligibility(text, "群馬県")
        assert info.overall == "×"

    def test_unknown(self) -> None:
        text = ""
        info = extract_eligibility(text, "東京都")
        assert info.overall == "○"
