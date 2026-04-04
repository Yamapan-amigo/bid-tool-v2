"""仕様書URL抽出のテスト"""

from src.sources.kkj import _extract_spec_url_from_text


class TestExtractSpecUrlFromText:
    def test_extracts_url_with_shiyousho_label(self) -> None:
        text = "仕様書 https://example.com/spec.pdf を参照"
        assert _extract_spec_url_from_text(text) == "https://example.com/spec.pdf"

    def test_extracts_url_with_setsumei_label(self) -> None:
        text = "入札説明書はhttps://example.com/doc.pdfからダウンロード"
        assert _extract_spec_url_from_text(text) == "https://example.com/doc.pdf"

    def test_extracts_url_with_spec_in_path(self) -> None:
        text = "詳細は https://example.com/shiyou/doc.pdf を参照"
        assert _extract_spec_url_from_text(text) == "https://example.com/shiyou/doc.pdf"

    def test_returns_empty_when_no_urls(self) -> None:
        text = "仕様書は現地にて配布"
        assert _extract_spec_url_from_text(text) == ""

    def test_ignores_portal_generic_url(self) -> None:
        text = "仕様書 https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101"
        assert _extract_spec_url_from_text(text) == ""

    def test_validates_url_scheme(self) -> None:
        text = "仕様書 javascript:alert(1)"
        assert _extract_spec_url_from_text(text) == ""

    def test_does_not_extract_unrelated_pdf(self) -> None:
        """国会要覧のケース: 「仕様書のとおり」の後にある無関係PDFを誤抽出しない"""
        text = (
            "（２）仕様仕様書のとおり（３）納入期限 仕様書のとおり "
            "お知らせ１ 当省のホームページ "
            "（https://www.maff.go.jp/j/supply/sonota/pdf/260403_jigyousya.pdf）をご覧下さい"
        )
        assert _extract_spec_url_from_text(text) == ""

    def test_does_not_fallback_to_random_pdf(self) -> None:
        """仕様書と無関係なPDFは返さない"""
        text = "資料はhttps://example.com/random.pdfを参照"
        assert _extract_spec_url_from_text(text) == ""
