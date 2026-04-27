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
        ("議会だより印刷業務委託", "", "印刷・製本"),
        ("年次報告書作成", "", "印刷・製本"),
        ("区民要覧の印刷", "", "印刷・製本"),
        ("コピー用紙購入", "", "用紙・消耗品"),
        ("トナーカートリッジ購入", "", "用紙・消耗品"),
        ("OA消耗品購入一式", "", "用紙・消耗品"),
        ("販促ノベルティ購入", "", "販促・ノベルティ"),
        ("記念品購入一式", "", "販促・ノベルティ"),
        ("ホームページリニューアル業務", "", "Web・広告"),
        ("広報用動画制作", "", "Web・広告"),
        ("SNS運用業務委託", "", "Web・広告"),
        ("事務用品購入", "", "事務用品"),
        ("文具の購入", "", "事務用品"),
        # 新カテゴリ（他カテゴリのキーワードを含まないタイトルで検証）
        ("帳票の作成委託", "", "帳票・フォーム"),
        ("マークシートの作成一式", "", "帳票・フォーム"),
        ("横断幕制作業務", "", "大判・サイン"),
        ("のぼり旗製作一式", "", "大判・サイン"),
        ("懸垂幕作成業務", "", "大判・サイン"),
        ("DTP業務委託", "", "DTP・デザイン"),
        ("版下作成業務委託", "", "DTP・デザイン"),
        ("組版業務一式", "", "DTP・デザイン"),
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
