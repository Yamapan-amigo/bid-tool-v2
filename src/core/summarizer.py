"""Gemini Flash による公告テキスト要約

無料枠（1,500回/日）で公告テキストを3行程度の概要に要約する。
APIキーが未設定の場合はフォールバックとしてタイトルのみ返す。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_PROMPT = """以下は日本の公共入札の公告全文です。印刷業者が一目で内容を判断できるよう、3行以内で簡潔に要約してください。

要約に含めるべき情報（あれば）:
- 何を調達するか（品名・数量）
- 納入場所・履行期間
- 契約方法（単価契約 等）

不要な情報: 法律条文、資格要件、入札方法の詳細
「大島さん」等の呼びかけは不要。事実だけ書いてください。

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
