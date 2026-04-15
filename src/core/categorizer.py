"""案件の分類タグ付与

タイトル+説明文を走査し、CATEGORY_KEYWORDS で定義された
各カテゴリに最初にマッチしたラベルを返す。
どれにもマッチしなければ「その他」。
"""

from __future__ import annotations

from src.config import CATEGORY_KEYWORDS

_FALLBACK_LABEL = "その他"


def classify(title: str, description: str = "") -> str:
    """案件名と説明文から分類タグを決定する"""
    text = f"{title or ''} {description or ''}"
    for label, keywords in CATEGORY_KEYWORDS.items():
        if label == _FALLBACK_LABEL:
            continue
        if any(kw in text for kw in keywords):
            return label
    return _FALLBACK_LABEL
