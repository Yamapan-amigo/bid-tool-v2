"""Gemini Flash による公告テキスト要約

無料枠（1,500回/日）で公告テキストを3行程度の概要に要約する。
APIキーが未設定の場合はフォールバックとしてタイトルのみ返す。

キャッシュ: 一度要約した案件はローカルJSONに保存し、2回目以降はAPIを叩かない。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent.parent / ".cache" / "summaries.json"

_PROMPT = """以下は日本の公共入札の公告全文です。印刷業者が「この案件に入札するか」を判断できるよう、要点を整理してください。

出力フォーマット（Markdown、5〜8行程度）:

**調達内容**
具体的に何を作るのか。印刷物の種類・サイズ・数量・仕様を書く。

**納入条件**
納入先、納入期限、契約方法（単価・総価等）を1〜2行で。

**補足**
予定価格、特記事項があれば1行で。なければ省略。

---
ルール:
- 法律条文、資格要件、入札手続きの詳細は書かない
- 前置きや呼びかけは不要
- 簡潔だが具体的に（「一式」だけでなく内容を書く）

公告全文:
{text}

要約:"""


def _cache_key(text: str) -> str:
    """テキストのSHA256ハッシュをキャッシュキーにする"""
    return hashlib.sha256(text[:3000].encode()).hexdigest()[:16]


def _load_cache() -> dict[str, str]:
    """キャッシュファイルを読み込む"""
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    """キャッシュファイルに保存する"""
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_description(text: str, title: str) -> str:
    """公告テキストをGemini Flashで要約する（キャッシュ付き）

    1回目: Gemini APIを呼んで要約 → キャッシュに保存
    2回目以降: キャッシュから即座に返す
    """
    if not text:
        return title

    # キャッシュチェック
    key = _cache_key(text)
    cache = _load_cache()
    if key in cache:
        return cache[key]

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.debug("GEMINI_API_KEY未設定、タイトルをフォールバック")
        return title

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        truncated = text[:3000]
        prompt = _PROMPT.format(text=truncated)

        response = model.generate_content(prompt)
        summary = response.text.strip()

        if summary:
            # キャッシュに保存
            cache[key] = summary
            _save_cache(cache)
            logger.info("Gemini要約: キャッシュ保存 (key=%s)", key)
            return summary

    except Exception as e:
        logger.warning("Gemini要約エラー（タイトルにフォールバック）: %s", e)

    return title
