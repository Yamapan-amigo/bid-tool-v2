"""Gemini Flash による公告テキスト要約

無料枠（1,500回/日）で公告テキストを3行程度の概要に要約する。
APIキーが未設定の場合はフォールバックとしてタイトルのみ返す。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

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

3行以内の要約:"""


def summarize_description(text: str, title: str) -> str:
    """公告テキストをGemini Flashで要約する

    APIキー未設定やエラー時はタイトルをそのまま返す。
    """
    if not text:
        return title

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.debug("GEMINI_API_KEY未設定、タイトルをフォールバック")
        return title

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        # テキストが長すぎる場合は先頭3000文字に制限
        truncated = text[:3000]
        prompt = _PROMPT.format(text=truncated)

        response = model.generate_content(prompt)
        summary = response.text.strip()

        if summary:
            return summary

    except Exception as e:
        logger.warning("Gemini要約エラー（タイトルにフォールバック）: %s", e)

    return title
