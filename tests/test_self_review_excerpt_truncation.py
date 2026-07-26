"""A self-review must not invent defects out of its own excerpting."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from thomas.server.routes.self_review import (
    _MAX_MSG_CHARS,
    _REVIEW_SYSTEM,
    _recent_session_excerpts,
)


def _session(tmp_path: Path, reply: str) -> Path:
    payload = {
        "session_id": "sess-ira",
        "messages": [
            {"role": "user", "content": "whats the difference between a roth and a traditional ira"},
            {"role": "assistant", "content": reply},
        ],
    }
    path = tmp_path / "chat_sess-ira.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_shortened_excerpt_says_it_was_shortened(tmp_path: Path) -> None:
    """The false finding this prevents.

    A complete ~1,200-character answer about IRAs was cut to 300 with no
    marker, so the reviewing model saw it stop at "...may trigger tax plus" and
    reported "the response terminated mid-answer" as a real product failure,
    quoting the cut point as evidence.
    """
    reply = "The main difference is when you pay taxes. " + ("Traditional IRA detail. " * 60)
    _session(tmp_path, reply)

    excerpts = _recent_session_excerpts(tmp_path, datetime.now(timezone.utc) - timedelta(hours=24))

    assert excerpts, "expected the session to be picked up"
    body = excerpts[0]
    assert "more chars…]" in body
    assert f"[+{len(' '.join(reply.split())) - _MAX_MSG_CHARS} more chars…]" in body


def test_a_short_reply_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """No marker on a message that was never cut, or every reply looks partial."""
    reply = "Going well on my end. How are you holding up?"
    _session(tmp_path, reply)

    body = _recent_session_excerpts(tmp_path, datetime.now(timezone.utc) - timedelta(hours=24))[0]

    assert reply in body
    assert "more chars" not in body


def test_the_reviewer_is_told_what_the_marker_means() -> None:
    """The marker only helps if the model knows not to read it as a defect."""
    text = _REVIEW_SYSTEM.lower()

    assert "length-capped" in text
    assert "more chars" in text
    assert "never report a truncated excerpt as an" in text


def test_the_cut_keeps_the_budget(tmp_path: Path) -> None:
    """The marker must not become a way to smuggle the whole message through."""
    reply = "x" * 5000
    _session(tmp_path, reply)

    body = _recent_session_excerpts(tmp_path, datetime.now(timezone.utc) - timedelta(hours=24))[0]

    assert body.count("x") == _MAX_MSG_CHARS
