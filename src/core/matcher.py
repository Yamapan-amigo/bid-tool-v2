"""過去落札金額マッチング

公募中案件と過去の落札実績を案件名の類似度で紐付ける。
AI不使用 — 年度表記の正規表現除去 + 文字列比較のみ。

公共入札は「毎年同じ案件名」のパターンが多い。
例: 「令和7年度 広報誌印刷」↔「令和6年度 広報誌印刷」
"""

from __future__ import annotations

import re
from dataclasses import replace

from src.config import CORE_KEYWORDS
from src.core.models import AwardResult, BidProject

# 年度表記パターン（除去用）
_FISCAL_YEAR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"令和\s*\d+\s*[～〜\-]\s*\d+\s*年度?\s*"),
    re.compile(r"令和\s*\d+\s*年度?\s*"),
    re.compile(r"平成\s*\d+\s*年度?\s*"),
    re.compile(r"R\s*\d+\s*", re.IGNORECASE),
    re.compile(r"H\s*\d+\s*", re.IGNORECASE),
    re.compile(r"20\d{2}\s*年度?\s*"),
]

# 装飾・ノイズ除去パターン
_DECORATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"【[^】]*】"),  # 【掲載期間：...】
    re.compile(r"〈[^〉]*〉"),  # 〈令和8年度〉
    re.compile(r"[（(]PDF\s*[：:]\s*[\d,]+\s*KB[）)]", re.IGNORECASE),  # (PDF : 163KB)
    re.compile(r"[（(]PDF\s+[\d,]+KB[）)]", re.IGNORECASE),  # (PDF 1,858KB)
    re.compile(r"（\d+）"),  # （7）のような年度略記（括弧必須）
]

# 汎用語（マッチング精度を下げるノイズ）
_GENERIC_WORDS = re.compile(
    r"(?:一式|単価契約|業務委託|に係る|における|について|の件|に関する|等|外\d+件)"
)

# 正規化時に除去する記号
_NOISE_PATTERN = re.compile(r"[\s　【】「」『』（）()\[\]・、。,.]+")


def _normalize_title(title: str) -> str:
    """案件名から年度表記・装飾・記号を除去して正規化する"""
    normalized = title
    for pattern in _DECORATION_PATTERNS:
        normalized = pattern.sub("", normalized)
    for pattern in _FISCAL_YEAR_PATTERNS:
        normalized = pattern.sub("", normalized)
    normalized = _GENERIC_WORDS.sub("", normalized)
    normalized = _NOISE_PATTERN.sub("", normalized)
    return normalized.strip()


def _title_similarity(title_a: str, title_b: str) -> float:
    """2つの正規化済み案件名の類似度を計算する (0.0 - 1.0)"""
    if not title_a or not title_b:
        return 0.0

    if title_a == title_b:
        return 1.0

    # 2-gramベースのJaccard係数
    bigrams_a = {title_a[i : i + 2] for i in range(len(title_a) - 1)}
    bigrams_b = {title_b[i : i + 2] for i in range(len(title_b) - 1)}

    if not bigrams_a or not bigrams_b:
        return 0.0

    intersection = len(bigrams_a & bigrams_b)
    union = len(bigrams_a | bigrams_b)
    return intersection / union if union > 0 else 0.0


def _keyword_match_score(project_title: str, result_title: str) -> float:
    """コアキーワードの共起でフォールバックスコアを計算する"""
    proj_keywords = {kw for kw in CORE_KEYWORDS if kw in project_title}
    result_keywords = {kw for kw in CORE_KEYWORDS if kw in result_title}

    if not proj_keywords or not result_keywords:
        return 0.0

    shared = proj_keywords & result_keywords
    if not shared:
        return 0.0

    # 共通キーワード数に基づくスコア（0.3〜0.5）
    return 0.3 + 0.1 * min(len(shared), 2)


def _org_name_variants(org: str) -> list[str]:
    """発注元名の照合用バリアントを生成する"""
    variants = [org]
    # 長い法人格名を除去した短縮名
    for prefix in ("国立研究開発法人", "独立行政法人", "地方独立行政法人"):
        if org.startswith(prefix):
            variants.append(org[len(prefix):])
    # 都道府県名を除去（「埼玉県川越市」→「川越市」）
    for suffix in ("都", "府", "県"):
        idx = org.find(suffix)
        if 0 < idx < 4:
            variants.append(org[idx + 1:])
    return [v for v in variants if len(v) >= 2]


def _org_boost(project_org: str, result_title: str) -> float:
    """発注元名が落札実績の案件名に含まれている場合のブーストスコア"""
    for variant in _org_name_variants(project_org):
        if variant in result_title:
            return 0.3  # 同じ発注元は大幅ブースト
    return 0.0


def match_past_results(
    projects: list[BidProject],
    results: list[AwardResult],
    threshold: float = 0.4,
) -> list[BidProject]:
    """公募中案件に過去落札金額を紐付ける

    2段階マッチング:
    1. 案件名の2-gram Jaccard類似度（閾値以上で紐付け）
    2. フォールバック: コアキーワード共起 + 発注元名マッチ
    """
    if not results:
        return list(projects)

    # 落札実績の正規化済みタイトルを事前計算
    normalized_results = [(_normalize_title(r.title), r) for r in results]

    matched_projects: list[BidProject] = []

    for project in projects:
        norm_title = _normalize_title(project.title)

        # 全候補のスコアを計算（発注元ブースト付き）
        scored_results: list[tuple[float, AwardResult]] = []
        for norm_result_title, result in normalized_results:
            similarity = _title_similarity(norm_title, norm_result_title)
            kw_score = _keyword_match_score(project.title, result.title)
            org_score = _org_boost(project.organization, result.title)
            best = max(similarity, kw_score) + org_score
            if best > 0.05:
                scored_results.append((best, result))

        scored_results.sort(key=lambda x: x[0], reverse=True)

        # 上位3件を「参考類似案件」として常にセット
        similar = tuple(
            (r.title, r.award_price, r.winner)
            for _, r in scored_results[:3]
        )

        if scored_results and scored_results[0][0] >= threshold:
            best_result = scored_results[0][1]
            matched_projects.append(
                replace(
                    project,
                    past_award_price=best_result.award_price,
                    past_award_winner=best_result.winner,
                    similar_awards=similar,
                )
            )
        else:
            matched_projects.append(
                replace(project, similar_awards=similar)
            )

    return matched_projects
