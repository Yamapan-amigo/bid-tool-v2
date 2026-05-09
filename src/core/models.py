"""データモデル定義

全データソース共通の案件データ構造を定義する。
frozen=True により不変性を保証。
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class BidProject:
    """入札案件"""

    title: str
    organization: str  # 発注元
    bid_type: str = "不明"
    publish_date: str = ""  # YYYY-MM-DD
    deadline: str = ""  # YYYY-MM-DD
    detail_url: str = ""
    source: str = ""  # データソース名（官公需 / e-Tokyo）
    description: str = ""  # 案件説明文（公告全文）
    spec_url: str = ""  # 仕様書URL
    eligibility_overall: str = "○"  # 参加可否 ◎/○/×
    eligibility_grade: str = ""  # 等級要件テキスト
    eligibility_region: str = ""  # 地域要件テキスト
    eligibility_method: str = ""  # 提出方法
    eligibility_contact: str = ""  # 連絡先
    category: str = "その他"  # 分類タグ（UI絞り込み用）
    score: float = 3.0
    past_award_price: int | None = None  # 過去落札金額（円）
    past_award_winner: str = ""  # 過去落札者名
    similar_awards: tuple[tuple[str, int, str], ...] = ()  # 参考類似案件 (案件名, 金額, 落札者)

    @property
    def dedup_key(self) -> str:
        """重複排除用キー（案件名 + 発注元）"""
        return f"{self.title}|{self.organization}"

    def with_score(self, score: float) -> BidProject:
        """スコアを設定した新しいインスタンスを返す"""
        return replace(self, score=score)

    def with_past_award(self, price: int, winner: str) -> BidProject:
        """過去落札情報を設定した新しいインスタンスを返す"""
        return replace(self, past_award_price=price, past_award_winner=winner)

    def to_row(self, fetch_date: str) -> list[str]:
        """Spreadsheet書き込み用の行データに変換する（20列）"""
        from datetime import date as date_cls

        price_str = f"{self.past_award_price:,}" if self.past_award_price is not None else ""
        days_left = ""
        if self.deadline:
            try:
                days_left = str((date_cls.fromisoformat(self.deadline) - date_cls.today()).days)
            except ValueError:
                pass
        return [
            fetch_date,
            self.eligibility_overall,
            self.title,
            self.organization,
            self.category,
            self.bid_type,
            self.publish_date,
            self.deadline,
            days_left,
            self.eligibility_grade,
            self.eligibility_region,
            self.eligibility_method,
            price_str,
            self.past_award_winner,
            self.spec_url,
            self.detail_url,
            self.source,
            str(self.score),
            "",        # メモ（ユーザー入力）
            "未確認",  # ステータス
        ]


@dataclass(frozen=True)
class AwardResult:
    """落札実績（調達ポータルオープンデータ）"""

    case_id: str  # 案件番号
    title: str  # 案件名
    award_date: str  # 落札日 YYYY-MM-DD
    award_price: int  # 落札金額（円）
    cert_code: str  # 資格コード
    org_code: str  # 機関コード
    winner: str  # 落札者名
    corporate_number: str  # 法人番号
