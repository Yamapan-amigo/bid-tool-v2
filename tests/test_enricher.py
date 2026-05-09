"""tests/test_enricher.py — enricher モジュールのユニットテスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.enricher import (
    _enrich_from_etokyo_detail,
    _enrich_from_pdf,
    _fetch_etokyo_detail_html,
    _fetch_pdf_text,
    _is_etokyo_url,
    _is_safe_url,
    _looks_like_pdf_url,
    _needs_grade_enrichment,
    _parse_etokyo_detail,
    enrich_eligibility,
)
from src.core.models import BidProject


def _make_project(**kwargs) -> BidProject:
    defaults = dict(
        title="広報誌印刷業務",
        organization="東京都総務局",
        source="KKJ",
        eligibility_grade="不明",
        eligibility_region="制限なし",
        eligibility_overall="○",
    )
    defaults.update(kwargs)
    return BidProject(**defaults)


# ============================================================
# URL ユーティリティ
# ============================================================


class TestIsSafeUrl:
    def test_http_allowed(self) -> None:
        assert _is_safe_url("http://example.com/file.pdf")

    def test_https_allowed(self) -> None:
        assert _is_safe_url("https://example.com/file.pdf")

    def test_rejects_non_http(self) -> None:
        assert not _is_safe_url("ftp://example.com/file.pdf")
        assert not _is_safe_url("javascript:alert(1)")
        assert not _is_safe_url("file:///etc/passwd")

    def test_rejects_path_traversal(self) -> None:
        assert not _is_safe_url("https://example.com/../etc/passwd")
        assert not _is_safe_url("https://example.com/%2e%2e/etc/passwd")

    def test_rejects_empty(self) -> None:
        assert not _is_safe_url("")


class TestIsEtokyoUrl:
    def test_valid_etokyo_domain(self) -> None:
        assert _is_etokyo_url("https://www.e-tokyo.lg.jp/cgi-bin/ebid/ebid?s=P002&a=12&n=2026:13:101:00310")

    def test_rejects_other_domain(self) -> None:
        assert not _is_etokyo_url("https://evil.example.com/?redirect=etokyo")
        assert not _is_etokyo_url("https://www.kkj.go.jp/api/")

    def test_rejects_empty(self) -> None:
        assert not _is_etokyo_url("")


class TestLooksLikePdfUrl:
    def test_pdf_extension(self) -> None:
        assert _looks_like_pdf_url("https://example.com/spec.pdf")
        assert _looks_like_pdf_url("https://example.com/spec.PDF")

    def test_pdf_in_path(self) -> None:
        assert _looks_like_pdf_url("https://example.com/pdf/download?id=123")

    def test_non_pdf(self) -> None:
        assert not _looks_like_pdf_url("https://example.com/detail.html")
        assert not _looks_like_pdf_url("https://example.com/download?type=doc")


class TestNeedsGradeEnrichment:
    def test_unknown_grade_needs_enrichment(self) -> None:
        p = _make_project(eligibility_grade="不明")
        assert _needs_grade_enrichment(p)

    def test_empty_grade_needs_enrichment(self) -> None:
        p = _make_project(eligibility_grade="")
        assert _needs_grade_enrichment(p)

    def test_zensho_unknown_needs_enrichment(self) -> None:
        p = _make_project(eligibility_grade="不明（全省庁統一資格）")
        assert _needs_grade_enrichment(p)

    def test_known_grade_skips_enrichment(self) -> None:
        p = _make_project(eligibility_grade="A,B,C,D")
        assert not _needs_grade_enrichment(p)

    def test_local_registry_skips_enrichment(self) -> None:
        p = _make_project(eligibility_grade="地方自治体独自名簿")
        assert not _needs_grade_enrichment(p)


# ============================================================
# Phase 1: PDF テキスト取得
# ============================================================


class TestFetchPdfText:
    def test_cache_hit_returns_without_http(self, tmp_path: Path) -> None:
        key = "abc123def456abcd"
        cache_file = tmp_path / f"{key}.txt"
        cache_file.write_text("等級：A,B,C,D等級に格付けされた者", encoding="utf-8")

        with patch("src.core.enricher._PDF_CACHE_DIR", tmp_path):
            with patch("src.core.enricher._url_cache_key", return_value=key):
                result = _fetch_pdf_text("https://example.com/spec.pdf")

        assert result == "等級：A,B,C,D等級に格付けされた者"

    def test_non_pdf_content_type_returns_none(self) -> None:
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            with patch("src.core.enricher._PDF_CACHE_DIR", Path("/tmp/nonexistent_enricher_test")):
                result = _fetch_pdf_text("https://example.com/page.html")

        assert result is None

    def test_request_exception_returns_none(self) -> None:
        import requests as req

        with patch("requests.get", side_effect=req.exceptions.Timeout("timeout")):
            with patch("src.core.enricher._PDF_CACHE_DIR", Path("/tmp/nonexistent_enricher_test")):
                result = _fetch_pdf_text("https://example.com/spec.pdf")

        assert result is None

    def test_unsafe_url_returns_none(self) -> None:
        result = _fetch_pdf_text("javascript:alert(1)")
        assert result is None

    def test_pdf_parse_success(self, tmp_path: Path) -> None:
        pdf_text = "D等級に格付けされた者\n東京都内に本社を有する者"
        mock_page = MagicMock()
        mock_page.extract_text.return_value = pdf_text
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]

        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.content = b"%PDF-1.4 fake"
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            with patch("pdfplumber.open", return_value=mock_pdf):
                with patch("src.core.enricher._PDF_CACHE_DIR", tmp_path):
                    result = _fetch_pdf_text("https://example.com/spec.pdf")

        assert result is not None
        assert "D等級" in result


class TestEnrichFromPdf:
    def test_updates_grade_when_pdf_has_info(self) -> None:
        project = _make_project(
            spec_url="https://example.com/spec.pdf",
            description="令和8年度広報誌印刷業務",
        )
        pdf_text = "参加資格：A、B、C又はD等級に格付けされた者"

        with patch("src.core.enricher._fetch_pdf_text", return_value=pdf_text):
            result = _enrich_from_pdf(project)

        assert result.eligibility_grade == "A,B,C,D"
        assert result.eligibility_overall == "◎"

    def test_no_change_when_pdf_fetch_fails(self) -> None:
        project = _make_project(spec_url="https://example.com/spec.pdf")

        with patch("src.core.enricher._fetch_pdf_text", return_value=None):
            result = _enrich_from_pdf(project)

        assert result is project

    def test_no_change_when_pdf_has_no_grade_info(self) -> None:
        project = _make_project(spec_url="https://example.com/spec.pdf")
        pdf_text = "仕様書の概要です。印刷物の詳細仕様については担当者に問い合わせること。"

        with patch("src.core.enricher._fetch_pdf_text", return_value=pdf_text):
            result = _enrich_from_pdf(project)

        assert result is project


# ============================================================
# Phase 2: eTokyo 詳細ページ
# ============================================================


class TestFetchEtokyoDetailHtml:
    def test_cache_hit_returns_without_http(self, tmp_path: Path) -> None:
        key = "cafe1234cafe5678"
        cache_file = tmp_path / f"{key}.html"
        cache_file.write_text("<html><body>詳細</body></html>", encoding="utf-8")

        url = "https://www.e-tokyo.lg.jp/cgi-bin/ebid/ebid?s=P002&a=12&n=2026:13:101:00310"
        with patch("src.core.enricher._ETOKYO_CACHE_DIR", tmp_path):
            with patch("src.core.enricher._url_cache_key", return_value=key):
                result = _fetch_etokyo_detail_html(url)

        assert result == "<html><body>詳細</body></html>"

    def test_rejects_non_etokyo_url(self) -> None:
        result = _fetch_etokyo_detail_html("https://evil.example.com/phishing")
        assert result is None

    def test_request_exception_returns_none(self) -> None:
        import requests as req

        url = "https://www.e-tokyo.lg.jp/cgi-bin/ebid/ebid?s=P002&a=12&n=test"
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.side_effect = req.exceptions.ConnectionError("connection refused")
            with patch("src.core.enricher._ETOKYO_CACHE_DIR", Path("/tmp/nonexistent_enricher_test")):
                result = _fetch_etokyo_detail_html(url)

        assert result is None


class TestParseEtokyoDetail:
    def test_extracts_eligibility_from_table(self) -> None:
        html = """
        <html><body>
        <table>
          <tr><th>案件名</th><td>広報誌印刷業務</td></tr>
          <tr><th>入札参加資格</th><td>A又はB等級に格付けされた印刷業者</td></tr>
          <tr><th>地域要件</th><td>東京都内に本社を有すること</td></tr>
        </table>
        </body></html>
        """
        result = _parse_etokyo_detail(html)
        assert "入札参加資格" in result
        assert "A又はB等級" in result

    def test_fallback_to_full_text_when_no_labels(self) -> None:
        html = "<html><body><p>一般競争入札の公告。仕様書を参照すること。</p></body></html>"
        result = _parse_etokyo_detail(html)
        assert "一般競争入札" in result


class TestEnrichFromEtokyoDetail:
    def test_updates_grade_from_detail_page(self) -> None:
        project = _make_project(
            source="e-Tokyo",
            detail_url="https://www.e-tokyo.lg.jp/cgi-bin/ebid/ebid?s=P002&a=12&n=2026:13:101:00310",
        )
        html = """
        <table>
          <tr><th>入札参加資格</th><td>D等級に格付けされた者</td></tr>
        </table>
        """
        with patch("src.core.enricher._fetch_etokyo_detail_html", return_value=html):
            result = _enrich_from_etokyo_detail(project)

        assert result.eligibility_grade == "D"
        assert result.eligibility_overall == "◎"

    def test_no_change_when_fetch_fails(self) -> None:
        project = _make_project(
            source="e-Tokyo",
            detail_url="https://www.e-tokyo.lg.jp/cgi-bin/ebid/ebid?s=P002&a=12&n=test",
        )
        with patch("src.core.enricher._fetch_etokyo_detail_html", return_value=None):
            result = _enrich_from_etokyo_detail(project)

        assert result is project

    def test_no_change_when_no_detail_url(self) -> None:
        project = _make_project(source="e-Tokyo", detail_url="")
        result = _enrich_from_etokyo_detail(project)
        assert result is project


# ============================================================
# エントリポイント
# ============================================================


class TestEnrichEligibility:
    def test_skips_project_with_known_grade(self) -> None:
        project = _make_project(eligibility_grade="A,B,C,D", spec_url="https://example.com/spec.pdf")

        with patch("src.core.enricher._fetch_pdf_text") as mock_fetch:
            result = enrich_eligibility([project])

        mock_fetch.assert_not_called()
        assert result[0] is project

    def test_enriches_unknown_grade_pdf(self) -> None:
        project = _make_project(
            eligibility_grade="不明",
            spec_url="https://example.com/spec.pdf",
        )

        pdf_text = "A又はB等級に格付けされた者"
        with patch("src.core.enricher._fetch_pdf_text", return_value=pdf_text):
            result = enrich_eligibility([project])

        assert result[0].eligibility_grade in ("A,B", "A,B,C,D", "A", "B")

    def test_respects_max_enrich_per_run(self) -> None:
        projects = [
            _make_project(
                title=f"案件{i}",
                eligibility_grade="不明",
                spec_url=f"https://example.com/spec{i}.pdf",
            )
            for i in range(10)
        ]

        fetch_count = 0

        def mock_fetch(url: str) -> str | None:
            nonlocal fetch_count
            fetch_count += 1
            return "D等級に格付けされた者"

        with patch("src.core.enricher._fetch_pdf_text", side_effect=mock_fetch):
            enrich_eligibility(projects, max_enrich_per_run=3)

        assert fetch_count <= 3

    def test_returns_original_on_exception(self) -> None:
        project = _make_project(
            eligibility_grade="不明",
            spec_url="https://example.com/spec.pdf",
        )

        with patch("src.core.enricher._enrich_from_pdf", side_effect=RuntimeError("unexpected")):
            result = enrich_eligibility([project])

        assert result[0] is project

    def test_both_phases_disabled(self) -> None:
        project = _make_project(
            eligibility_grade="不明",
            spec_url="https://example.com/spec.pdf",
            source="e-Tokyo",
            detail_url="https://www.e-tokyo.lg.jp/cgi-bin/ebid/ebid?s=P002&a=12&n=test",
        )
        with patch("src.core.enricher._fetch_pdf_text") as mock_pdf:
            with patch("src.core.enricher._fetch_etokyo_detail_html") as mock_html:
                enrich_eligibility([project], enable_pdf=False, enable_etokyo_detail=False)

        mock_pdf.assert_not_called()
        mock_html.assert_not_called()
