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
        """Spreadsheet書き込み用の行データに変換する"""
        price_str = f"{self.past_award_price:,}" if self.past_award_price is not None else ""
        return [
            fetch_date,
            self.title,
            self.organization,
            self.bid_type,
            self.publish_date,
            self.deadline,
            price_str,
            self.past_award_winner,
            self.detail_url,
            self.source,
            str(self.score),
            "",  # メモ（ユーザー入力）
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
