"""LINE Messaging API による新規案件通知"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from src.core.models import BidProject

logger = logging.getLogger(__name__)
_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def notify_new_projects(projects: list[BidProject]) -> None:
    """新規案件をLINEに通知する。環境変数未設定なら何もしない。"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not token or not user_id:
        logger.info("LINE通知: 環境変数未設定のためスキップ")
        return

    text = _format_message(projects)
    payload = json.dumps(
        {"to": user_id, "messages": [{"type": "text", "text": text}]},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        _LINE_PUSH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        logger.info("LINE通知: %d件を送信", len(projects))
    except urllib.error.HTTPError as e:
        logger.error("LINE通知 HTTPError: %s %s", e.code, e.read().decode())
    except Exception as e:
        logger.error("LINE通知 失敗: %s", e)


def _format_message(projects: list[BidProject]) -> str:
    def stars(s: float) -> str:
        if s >= 4.5:
            return "★★★"
        if s >= 3.5:
            return "★★"
        return "★"

    lines = [f"【入札】新規案件 {len(projects)}件（本日）"]
    for i, p in enumerate(projects[:10], 1):
        lines += [
            "━━━━━━━━━━━━━━",
            f"{i}. {p.title}",
            f"◎ {stars(p.score)} | 締切 {p.deadline or '未定'}",
            f"{p.category} | {p.bid_type or '不明'}",
        ]
        if p.detail_url:
            lines.append(p.detail_url)
    if len(projects) > 10:
        lines += ["━━━━━━━━━━━━━━", f"他 {len(projects) - 10}件"]
    lines += ["━━━━━━━━━━━━━━", "↓ 全件確認（GitHub Pages）"]
    return "\n".join(lines)
