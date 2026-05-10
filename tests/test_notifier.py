"""LINE通知機能のユニットテスト（外部API呼び出しなし）"""

from unittest.mock import patch

from src.core.models import BidProject
from src.core.notifier import _format_message, notify_new_projects

SAMPLE = BidProject(
    title="広報誌印刷",
    organization="東京都",
    category="印刷・製本",
    bid_type="一般競争入札",
    deadline="2026-06-30",
    score=4.5,
    eligibility_overall="◎",
)


def test_format_message_basic() -> None:
    msg = _format_message([SAMPLE])
    assert "新規案件 1件" in msg
    assert "広報誌印刷" in msg
    assert "★★★" in msg
    assert "2026-06-30" in msg


def test_format_message_two_star() -> None:
    p = SAMPLE.__class__(**{**SAMPLE.__dict__, "score": 4.0})
    msg = _format_message([p])
    assert "★★" in msg
    assert "★★★" not in msg


def test_format_message_truncates_at_10() -> None:
    projects = [SAMPLE] * 15
    msg = _format_message(projects)
    assert "他 5件" in msg


def test_notify_skips_without_env(monkeypatch: object) -> None:
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)  # type: ignore[attr-defined]
    monkeypatch.delenv("LINE_USER_ID", raising=False)  # type: ignore[attr-defined]
    notify_new_projects([SAMPLE])  # エラーなく終わること


def test_notify_calls_line_api(monkeypatch: object) -> None:
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "test-token")  # type: ignore[attr-defined]
    monkeypatch.setenv("LINE_USER_ID", "Utest123")  # type: ignore[attr-defined]
    with patch("urllib.request.urlopen") as mock_open:
        notify_new_projects([SAMPLE])
        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert "Bearer test-token" in req.get_header("Authorization")
