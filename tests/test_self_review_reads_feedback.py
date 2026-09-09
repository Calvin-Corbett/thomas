"""The self-review report sees what the person thought of real replies (thumbs feed the loop)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from thomas.server.routes.self_review import _recent_feedback


def test_recent_feedback_lines_are_within_the_window_and_readable(tmp_path: Path) -> None:
    store = tmp_path / "feedback.jsonl"
    now = datetime.now(timezone.utc)
    rows = [
        {
            "at": (now - timedelta(hours=2)).isoformat(timespec="seconds"),
            "session_id": "chat_a",
            "message_id": "3-abc",
            "rating": "down",
            "note": "wrong file",
        },
        {
            "at": (now - timedelta(days=3)).isoformat(timespec="seconds"),
            "session_id": "chat_b",
            "message_id": "1-def",
            "rating": "up",
            "note": "",
        },
        {
            "at": (now - timedelta(minutes=5)).isoformat(timespec="seconds"),
            "session_id": "chat_a",
            "message_id": "5-ghi",
            "rating": "up",
            "note": "",
        },
    ]
    store.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")

    lines = _recent_feedback(store, now - timedelta(hours=24))

    assert len(lines) == 2
    assert any("down" in line and "wrong file" in line and "chat_a" in line for line in lines)
    assert all("chat_b" not in line for line in lines)
    assert _recent_feedback(tmp_path / "missing.jsonl", now) == []
