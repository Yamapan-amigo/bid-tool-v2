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
    score: float = 3.0

    @property
    def dedup_key(self) -> str:
        """重複排除用キー（案件名 + 発注元）"""
        return f"{self.title}|{self.organization}"

    def with_score(self, score: float) -> BidProject:
        """スコアを設定した新しいインスタンスを返す"""
        return replace(self, score=score)

    def to_row(self, fetch_date: str) -> list[str]:
        """Spreadsheet書き込み用の行データに変換する"""
        return [
            fetch_date,
            self.title,
            self.organization,
            self.bid_type,
            self.publish_date,
            self.deadline,
            self.detail_url,
            self.source,
            str(self.score),
            "",  # メモ（ユーザー入力）
            "未確認",  # ステータス
        ]
