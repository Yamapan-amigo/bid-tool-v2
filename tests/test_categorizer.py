"""分類タグ付与ロジックのテスト"""

from __future__ import annotations

import pytest

from src.core.categorizer import classify


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("令和7年度 広報誌の印刷業務", "", "印刷・製本"),
        ("パンフレット作成一式", "", "印刷・製本"),
        ("名刺印刷", "", "印刷・製本"),
        ("コピー用紙購入", "", "用紙・消耗品"),
        ("トナーカートリッジ購入", "", "用紙・消耗品"),
        ("販促ノベルティ購入", "", "販促・ノベルティ"),
        ("記念品購入一式", "", "販促・ノベルティ"),
        ("ホームページリニューアル業務", "", "Web・広告"),
        ("広報用動画制作", "", "Web・広告"),
        ("事務用品購入", "", "事務用品"),
        ("体育館耐震工事", "", "その他"),
    ],
)
def test_classify_by_title(title: str, description: str, expected: str) -> None:
    assert classify(title, description) == expected


def test_classify_uses_description_as_fallback() -> None:
    # タイトルにはキーワードがないが説明文にはある場合
    assert classify("令和7年度 業務委託", "封筒の印刷を含む") == "印刷・製本"


def test_classify_empty_returns_other() -> None:
    assert classify("", "") == "その他"


def test_classify_first_match_wins() -> None:
    # 印刷 + コピー用紙 両方含む → 辞書順で先の「印刷・製本」が優先
    assert classify("印刷とコピー用紙一式", "") == "印刷・製本"
