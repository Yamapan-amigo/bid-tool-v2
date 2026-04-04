"""仕様書URL抽出のテスト（TDD: RED → GREEN）"""

from src.sources.kkj import _extract_spec_url_from_text


class TestExtractSpecUrlFromText:
    def test_extracts_url_with_shiyousho_keyword(self) -> None:
        text = "詳細は仕様書（https://example.com/spec.pdf）を参照"
        assert _extract_spec_url_from_text(text) == "https://example.com/spec.pdf"

    def test_extracts_url_with_setsumei_keyword(self) -> None:
        text = "入札説明書はhttps://example.com/doc.pdfからダウンロード"
        assert _extract_spec_url_from_text(text) == "https://example.com/doc.pdf"

    def test_prefers_shiyousho_over_other_urls(self) -> None:
        text = (
            "公告 https://example.com/notice.html "
            "仕様書 https://example.com/spec.pdf "
            "様式 https://example.com/form.pdf"
        )
        assert _extract_spec_url_from_text(text) == "https://example.com/spec.pdf"

    def test_returns_first_pdf_url_as_fallback(self) -> None:
        text = "資料はhttps://example.com/doc1.pdfおよびhttps://example.com/doc2.pdf"
        result = _extract_spec_url_from_text(text)
        assert result == "https://example.com/doc1.pdf"

    def test_returns_empty_when_no_urls(self) -> None:
        text = "仕様書は現地にて配布"
        assert _extract_spec_url_from_text(text) == ""

    def test_ignores_portal_generic_url(self) -> None:
        text = "調達ポータル（https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101）をご覧下さい"
        assert _extract_spec_url_from_text(text) == ""

    def test_validates_url_scheme(self) -> None:
        text = "仕様書 javascript:alert(1)"
        assert _extract_spec_url_from_text(text) == ""

    def test_real_rinya_case(self) -> None:
        text = (
            "入札説明書の交付 電子調達システム"
            "（https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101）のほか"
            "上記交付場所において無料にて交付 調達資料"
            "１ ダウンロードURL 調達資料２-調達資料３-調達資料４-調達資料５-"
            " https://www.rinya.maff.go.jp/j/kouhou/cyotatu_nyusatu/attach/pdf/index"
        )
        result = _extract_spec_url_from_text(text)
        assert "rinya.maff.go.jp" in result
