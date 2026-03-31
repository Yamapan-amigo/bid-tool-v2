"""フィルタ処理

参考資料の除外、地域フィルタ、締切フィルタを行う。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from src.core.models import BidProject

logger = logging.getLogger(__name__)

# 案件ではないもののパターン（除外対象）
_EXCLUDE_PATTERNS = [
    # 書式・テンプレート類
    r"記載例",
    r"記入例",
    r"様式",
    r"誓約書",
    r"届出書",
    r"証明書",
    r"申告書",
    r"協定書",
    r"委任状",
    r"申請書",
    r"経歴書(?!.*委託)",
    # 一覧・要綱・制度説明
    r"一覧表",
    r"公告案件一覧",
    r"要綱",
    r"要領",
    r"基準等",
    r"注意事項",
    r"作成上の注意",
    r"制度について$",
    # JV・下請関連
    r"JV",
    r"下請負者",
    r"共同請負",
]

_EXCLUDE_RE = re.compile("|".join(_EXCLUDE_PATTERNS))


def is_actual_project(title: str) -> bool:
    """案件名が実際の入札案件かどうか判定する"""
    if not title:
        return False
    return not bool(_EXCLUDE_RE.search(title))


def filter_non_projects(projects: list[BidProject]) -> list[BidProject]:
    """参考資料・テンプレートを除外する"""
    filtered = [p for p in projects if is_actual_project(p.title)]
    removed = len(projects) - len(filtered)
    if removed > 0:
        logger.info("参考資料フィルタ: %d件除外 → %d件残り", removed, len(filtered))
    return filtered


def filter_expired(projects: list[BidProject]) -> list[BidProject]:
    """締切日が過ぎた案件を除外する"""
    today = datetime.now().strftime("%Y-%m-%d")
    filtered = []
    for p in projects:
        if p.deadline and p.deadline < today:
            continue
        filtered.append(p)

    removed = len(projects) - len(filtered)
    if removed > 0:
        logger.info("締切フィルタ: %d件除外 → %d件残り", removed, len(filtered))
    return filtered


def apply_filters(projects: list[BidProject]) -> list[BidProject]:
    """全フィルタを順に適用する"""
    result = filter_non_projects(projects)
    result = filter_expired(result)
    return result
