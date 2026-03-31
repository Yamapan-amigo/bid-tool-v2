"""重複排除

案件名 + 発注元をキーとして、複数データソース間の重複を排除する。
"""

from __future__ import annotations

import logging

from src.core.models import BidProject

logger = logging.getLogger(__name__)


def deduplicate(projects: list[BidProject]) -> list[BidProject]:
    """案件リストの重複を排除する

    同じ案件名+発注元のペアは最初に出現したものを残す。
    """
    seen: set[str] = set()
    unique: list[BidProject] = []

    for p in projects:
        key = p.dedup_key
        if key not in seen:
            seen.add(key)
            unique.append(p)

    removed = len(projects) - len(unique)
    if removed > 0:
        logger.info("重複排除: %d件除外 → %d件残り", removed, len(unique))
    return unique
