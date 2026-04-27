"""URLの有効性チェック

案件詳細URLが実際にアクセス可能かを確認する。
KKJ等の入札ポータルは案件終了後にURLが無効化またはトップページにリダイレクトされることがある。
"""

from __future__ import annotations

import logging
from dataclasses import replace

import requests

from src.core.models import BidProject

logger = logging.getLogger(__name__)

# ポータルのトップページURL（これらにリダイレクトされた場合はリンク切れと判定）
_PORTAL_TOP_PAGES = {
    "https://www.kkj.go.jp/",
    "https://www.kkj.go.jp",
    "https://www.e-tokyo.lg.jp/",
    "https://www.e-tokyo.lg.jp",
}

_REQUEST_TIMEOUT = 10


def check_url(url: str) -> bool:
    """URLが有効かどうかを確認する

    Returns:
        True: 200系レスポンス かつ ポータルトップへのリダイレクトなし
        False: 4xx/5xx、タイムアウト、接続エラー、リダイレクト先がトップページ
    """
    if not url or not url.startswith(("http://", "https://")):
        return False

    try:
        resp = requests.head(
            url,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BidToolV2/2.0)"},
        )

        if resp.status_code >= 400:
            return False

        # リダイレクト先がポータルトップページの場合は無効
        final_url = resp.url
        if final_url in _PORTAL_TOP_PAGES:
            return False

        return True

    except requests.exceptions.RequestException as e:
        logger.debug("URL check failed for %s: %s", url, e)
        return False


def filter_broken_urls(projects: list[BidProject]) -> list[BidProject]:
    """リンク切れ案件を検出し、detail_url を空にして返す

    URL未設定の案件はそのまま通す（リンク切れとは別の状態）。
    """
    result: list[BidProject] = []
    for p in projects:
        if not p.detail_url:
            result.append(p)
            continue

        if check_url(p.detail_url):
            result.append(p)
        else:
            logger.info("リンク切れ検出: %s (%s)", p.title, p.detail_url)
            result.append(replace(p, detail_url=""))

    return result
