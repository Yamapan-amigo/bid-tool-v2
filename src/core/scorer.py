"""ルールベーススコアリング

AIを使わず、キーワードマッチング + 入札方式 + 地域 + 締切で
1-5のスコアを算出する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.config import (
    AWARD_PRICE_TARGET_MAX,
    AWARD_PRICE_TARGET_MIN,
    COMPANY_TARGET_CATEGORIES,
    HIGH_VALUE_KEYWORDS,
    MID_VALUE_KEYWORDS,
    SCORE_PENALTY_KEYWORDS,
)
from src.core.models import BidProject

_JST = timezone(timedelta(hours=9))


def calculate_score(project: BidProject) -> float:
    """案件のスコアを計算する（1.0〜5.0）

    キーワード3段階:
    - 広報誌・チラシ等の印刷物本体: +2.0
    - 製本・冊子・封筒等の関連物: +1.0
    - 「印刷」単独のみ: +0.3
    その他加点:
    - 一般競争入札: +1.0
    - 東京都内: +0.5
    - 締切7日以上: +0.5
    - 狙い目金額帯(50〜150万): +1.5
    減点:
    - プロポーザル/企画競争: -1.5
    - 除外ワード(システム,工事,清掃): -2.0
    - 高額案件(300万超): スコア上限1.5に打ち切り
    """
    score = 3.0
    title = project.title

    # キーワード3段階ボーナス（最初にマッチした段階のみ加算）
    if any(kw in title for kw in HIGH_VALUE_KEYWORDS):
        score += 2.0
    elif any(kw in title for kw in MID_VALUE_KEYWORDS):
        score += 1.0
    elif "印刷" in title:
        score += 0.3

    # 一般競争入札ボーナス
    if project.bid_type == "一般競争入札":
        score += 1.0

    # プロポーザル・企画競争はハードルが高い（プレゼン等が必要、億単位になりやすい）
    if project.bid_type in ("公募型プロポーザル", "企画競争"):
        score -= 1.5

    # 東京エリアボーナス（東京都直轄 or e-Tokyo=23区・市部）
    _is_tokyo = "東京" in project.organization or project.source == "e-Tokyo"
    if _is_tokyo:
        score += 0.5

    # 締切まで7日以上ボーナス
    if project.deadline:
        try:
            deadline_date = datetime.strptime(project.deadline, "%Y-%m-%d")
            days_left = (deadline_date - datetime.now(_JST).replace(tzinfo=None)).days
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
            score += 1.5  # 狙い目の金額帯（強ボーナス）
        elif project.past_award_price > 3_000_000:
            score = min(score, 1.5)  # 高額案件は上限打ち切り（手に負えないサイズ）
        elif project.past_award_price < 300_000:
            score -= 0.5  # 小額すぎ（単価納品程度）

    # 対象外カテゴリはスコア上限1.5（MIN_SCORE_THRESHOLD=3.0未満で実質非表示）
    # 「その他」（未分類）は対象外ではなく、印刷キーワードなし→cap 2.5で制御
    # 誤分類による見落としを防ぐため完全除外ではなくスコア制限で対応
    if project.category and project.category != "その他" and project.category not in COMPANY_TARGET_CATEGORIES:
        score = min(score, 1.5)

    # 印刷関連キーワードが一切ない場合はスコア上限2.5（MIN_SCORE_THRESHOLD未満でシート非表示）
    _has_print_keyword = (
        any(kw in title for kw in HIGH_VALUE_KEYWORDS)
        or any(kw in title for kw in MID_VALUE_KEYWORDS)
        or "印刷" in title
    )
    if not _has_print_keyword:
        score = min(score, 2.5)

    # 参加不可（×）は強制的に1.0
    if project.eligibility_overall == "×":
        return 1.0

    # clamp 1.0〜5.0
    return max(1.0, min(5.0, score))


def score_projects(projects: list[BidProject]) -> list[BidProject]:
    """全案件にスコアを付与する"""
    return [p.with_score(calculate_score(p)) for p in projects]
