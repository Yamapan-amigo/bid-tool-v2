"""Gemini要約モジュールのテスト"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.summarizer import summarize_description, _cache_key, _load_cache, _save_cache


class TestCacheKey:
    def test_same_text_same_key(self) -> None:
        assert _cache_key("テスト") == _cache_key("テスト")

    def test_different_text_different_key(self) -> None:
        assert _cache_key("テストA") != _cache_key("テストB")

    def test_key_is_16_chars(self) -> None:
        assert len(_cache_key("任意のテキスト")) == 16


class TestLoadCache:
    def test_returns_empty_dict_if_no_file(self, tmp_path: Path) -> None:
        from src.core import summarizer
        original = summarizer._CACHE_PATH
        summarizer._CACHE_PATH = tmp_path / "nonexistent.json"
        try:
            result = _load_cache()
            assert result == {}
        finally:
            summarizer._CACHE_PATH = original

    def test_loads_existing_cache(self, tmp_path: Path) -> None:
        from src.core import summarizer
        original = summarizer._CACHE_PATH
        cache_file = tmp_path / "summaries.json"
        cache_file.write_text(json.dumps({"abc123": "要約テスト"}), encoding="utf-8")
        summarizer._CACHE_PATH = cache_file
        try:
            result = _load_cache()
            assert result["abc123"] == "要約テスト"
        finally:
            summarizer._CACHE_PATH = original

    def test_returns_empty_dict_on_corrupt_json(self, tmp_path: Path) -> None:
        from src.core import summarizer
        original = summarizer._CACHE_PATH
        cache_file = tmp_path / "summaries.json"
        cache_file.write_text("invalid json", encoding="utf-8")
        summarizer._CACHE_PATH = cache_file
        try:
            result = _load_cache()
            assert result == {}
        finally:
            summarizer._CACHE_PATH = original


class TestSummarizeDescription:
    def test_empty_text_returns_title(self) -> None:
        result = summarize_description("", "広報誌印刷業務")
        assert result == "広報誌印刷業務"

    def test_no_api_key_returns_title(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GEMINI_API_KEY", None)
            result = summarize_description("公告全文テキスト", "広報誌印刷業務")
            assert result == "広報誌印刷業務"

    def test_returns_cached_summary(self, tmp_path: Path) -> None:
        from src.core import summarizer
        original = summarizer._CACHE_PATH

        text = "公告全文テキスト"
        key = _cache_key(text)
        cache_file = tmp_path / "summaries.json"
        cache_file.write_text(json.dumps({key: "キャッシュ済み要約"}), encoding="utf-8")
        summarizer._CACHE_PATH = cache_file

        try:
            result = summarize_description(text, "タイトル")
            assert result == "キャッシュ済み要約"
        finally:
            summarizer._CACHE_PATH = original

    @patch("src.core.summarizer._save_cache")
    @patch("src.core.summarizer._load_cache")
    def test_calls_gemini_and_caches(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_load.return_value = {}

        mock_response = MagicMock()
        mock_response.text = "**調達内容**\n広報誌を1000部印刷する。"

        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
                result = summarize_description("公告テキスト詳細", "広報誌印刷業務")

        assert "広報誌" in result
        mock_save.assert_called_once()

    @patch("src.core.summarizer._load_cache")
    def test_gemini_error_falls_back_to_title(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {}

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.side_effect = RuntimeError("API error")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
                result = summarize_description("公告テキスト", "広報誌印刷業務")

        assert result == "広報誌印刷業務"
