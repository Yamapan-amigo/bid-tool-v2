"""ルールベーススコアリング

AIを使わず、キーワードマッチング + 入札方式 + 地域 + 締切で
1-5のスコアを算出する。
"""

from __future__ import annotations

from datetime import datetime

from src.config import (
    AWARD_PRICE_TARGET_MAX,
    AWARD_PRICE_TARGET_MIN,
    CORE_KEYWORDS,
    SCORE_PENALTY_KEYWORDS,
)
from src.core.models import BidProject


def calculate_score(project: BidProject) -> float:
    """案件のスコアを計算する（1.0〜5.0）

    ルール:
    - base = 3.0
    - コアキーワード(印刷,製本,冊子,広報誌) in 案件名: +1
    - 入札方式 == 一般競争入札: +1
    - 発注元に東京が含まれる: +0.5
    - 締切まで7日以上: +0.5
    - 除外ワード(システム,工事,清掃) in 案件名: -2
    """
    score = 3.0
    title = project.title

    # コアキーワードボーナス
    if any(kw in title for kw in CORE_KEYWORDS):
        score += 1.0

    # 一般競争入札ボーナス
    if project.bid_type == "一般競争入札":
        score += 1.0

    # 東京都内ボーナス
    if "東京" in project.organization:
        score += 0.5

    # 締切まで7日以上ボーナス
    if project.deadline:
        try:
            deadline_date = datetime.strptime(project.deadline, "%Y-%m-%d")
            days_left = (deadline_date - datetime.now()).days
            if days_left >= 7:
                score += 0.5
        except ValueError:
            pass

    # 除外ワードペナルティ
    if any(kw in title for kw in SCORE_PENALTY_KEYWORDS):
        score -= 2.0

    # 過去落札金額ボーナス/ペナルティ
    if project.past_award_price is not None:
        if AWARD_PRICE_TARGET_MIN <= project.past_award_price <= AWARD_PRICE_TARGET_MAX:
            score += 1.0  # 狙い目の金額帯
        elif project.past_award_price > 3_000_000:
            score -= 1.0  # 高額案件は回避

    # 参加不可（×）は強制的に1.0
    if project.eligibility_overall == "×":
        return 1.0

    # clamp 1.0〜5.0
    return max(1.0, min(5.0, score))


def score_projects(projects: list[BidProject]) -> list[BidProject]:
    """全案件にスコアを付与する"""
    return [p.with_score(calculate_score(p)) for p in projects]
