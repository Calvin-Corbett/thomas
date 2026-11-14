"""An ack has to outlive the board being reverted underneath it.

pre-commit clears unstaged changes before it runs any hook, by checking the
whole tree back out to the index (``pre_commit/staged_files_only.py``). The
workboard ack writes ``plans/thomas/WORKBOARD.md`` on disk and never stages it,
so during a commit every gate that reads the board sees the pre-ack copy and
reports already-read mail as unread. Measured three ways on 2026-09-09: an ack
in a tracked-but-unstaged file is invisible to a hook, while the same ack in a
gitignored path or in the index survives.

These tests do not describe that; they perform it. Each one reverts the board
exactly the way pre-commit does and asserts the ack is GONE FROM THE BOARD
before asserting anything about the gate still knowing. If the board ever stops
losing it, those assertions fail and the tests say the premise died rather than
passing on a scenario that no longer exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.crew.workboard import board_io as _board_io
from scripts.crew.workboard import message as message_tool
from scripts.crew.workboard import message_receipts

AGENT = "worker"
SENDER = "coordinator"


def _board(path: Path, *, msg_id: str = "m-1", created_at: str = "2026-09-09T00:00:00+00:00") -> Path:
    claim = (
        f"- agent={AGENT}; name={AGENT}; role=solo; parent=none; scope=a.py; "
        "task=T; claimed_at=2026-09-09T00:00:00+00:00"
    )
    task = f"- task_id=T; agent={AGENT}; scope=a.py; summary=T; status=active"
    message = (
        f"- msg_id={msg_id}; from={SENDER}; to={AGENT}; task_id=T; kind=coordination; "
        "priority=p1; state=open; summary=please read this; requested_action=ack it; "
        f"decision=pending; created_at={created_at}; "
        f"updated_at={created_at}; updated_by={SENDER}"
    )
    path.write_text(
        "# Thomas Workboard\n\n"
        f"## Agent Claims (Active)\n\n{claim}\n\n"
        f"## Active Tasks\n\n{task}\n\n"
        "## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        f"## Agent Message Traffic\n\n{message}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def board(tmp_path: Path, monkeypatch) -> Path:
    """A board plus an isolated coordination dir, so receipts never touch the repo."""
    monkeypatch.setattr(_board_io, "COORDINATION_DIR", tmp_path / "coordination")
    (tmp_path / "coordination").mkdir(parents=True, exist_ok=True)
    return _board(tmp_path / "WORKBOARD.md")


def _unread_ids(board_path: Path) -> list[str]:
    ok, payload = message_tool.unread_messages(board_path, agent=AGENT)
    assert ok, payload
    return [str(row.get("msg_id")) for row in payload["messages"]]


def test_the_board_really_does_lose_an_ack_and_the_gate_still_knows(board: Path) -> None:
    """The whole point, performed rather than described."""
    before = board.read_text(encoding="utf-8")
    assert _unread_ids(board) == ["m-1"]

    ok, detail = message_tool.ack_message(board, msg_id="m-1", actor=AGENT)
    assert ok, detail
    assert _unread_ids(board) == []

    # Exactly what pre-commit does to an unstaged tracked file before hook one.
    board.write_text(before, encoding="utf-8")

    # THE LOSS, asserted first. If this stops holding, the premise is gone.
    assert "state=open" in board.read_text(encoding="utf-8"), (
        "the board no longer loses the ack -- re-derive this fix's reason to exist"
    )

    # ...and the gate must still know the agent read its mail.
    assert _unread_ids(board) == [], "a reverted board made an acked message unread again"


def test_a_receipt_does_not_suppress_a_different_message_that_reuses_the_id(board: Path) -> None:
    """Receipts are keyed to identity, not to a string an id could collide on.

    msg ids embed a timestamp and an agent, so a genuine collision is unlikely --
    but a receipt that suppresses mail nobody read is the reassuring kind of
    wrong, and 'unlikely' is not an argument against pinning it.
    """
    ok, detail = message_tool.ack_message(board, msg_id="m-1", actor=AGENT)
    assert ok, detail

    # A NEW message that happens to carry the same id: different created_at.
    _board(board, msg_id="m-1", created_at="2026-09-09T12:00:00+00:00")
    assert _unread_ids(board) == ["m-1"], "a stale receipt hid a message nobody has read"


def test_the_sender_learns_it_was_read_even_if_the_board_write_was_reverted(board: Path) -> None:
    """A receipt that only the recipient can see is half a fix.

    If the ack survives for the acking agent's gate but the board row stays open
    forever, every board-truth reader -- --inbox, --audit, the escalation clock,
    the sender -- is told the message was never read. The receipt has to heal the
    board, not just excuse the gate.
    """
    before = board.read_text(encoding="utf-8")
    ok, detail = message_tool.ack_message(board, msg_id="m-1", actor=AGENT)
    assert ok, detail
    board.write_text(before, encoding="utf-8")
    assert "state=open" in board.read_text(encoding="utf-8")

    healed = message_tool.reconcile_receipts(board, agent=AGENT)
    assert healed == ["m-1"], healed
    assert "state=acked" in board.read_text(encoding="utf-8"), (
        "the board still tells the sender its message was never read"
    )


def test_a_receipt_that_cannot_be_written_never_fails_the_ack(board: Path, monkeypatch) -> None:
    """The receipt is a durability aid. If it cannot be written the ack must
    still succeed, because a coordination tool that adds a new way to fail is a
    worse trade than the problem it solves."""

    def explode(*_args, **_kwargs):
        raise OSError("disk is gone")

    monkeypatch.setattr(message_receipts, "_write_receipt", explode)
    ok, detail = message_tool.ack_message(board, msg_id="m-1", actor=AGENT)
    assert ok, detail
    assert "state=acked" in board.read_text(encoding="utf-8")


def test_receipts_are_per_agent_and_never_speak_for_anyone_else(board: Path) -> None:
    """One agent's receipt must not mark another agent's mail as read."""
    ok, detail = message_tool.ack_message(board, msg_id="m-1", actor=AGENT)
    assert ok, detail

    receipts = message_receipts._read_receipts(board, AGENT)
    assert receipts, "no receipt was written at all"
    assert all(str(r.get("agent")) == AGENT for r in receipts)
    assert message_receipts._read_receipts(board, "someone-else") == []


def test_a_receipt_file_is_never_tracked_by_git(board: Path) -> None:
    """Receipts live under runtime/, which repo hygiene already forbids tracking.
    Pinning it here too, because the whole design rests on them being invisible
    to git -- that is what makes them survive the checkout."""
    message_tool.ack_message(board, msg_id="m-1", actor=AGENT)
    written = message_receipts._receipts_path(board, AGENT)
    assert written.exists()
    parts = [p.lower() for p in written.parts]
    assert "coordination" in parts
    rows = [json.loads(line) for line in written.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[0]["msg_id"] == "m-1"


def _two_message_board(path: Path) -> Path:
    """One board, two open messages, so 'heals the right one' is a real claim."""
    claim = (
        f"- agent={AGENT}; name={AGENT}; role=solo; parent=none; scope=a.py; "
        "task=T; claimed_at=2026-09-09T00:00:00+00:00"
    )
    task = f"- task_id=T; agent={AGENT}; scope=a.py; summary=T; status=active"
    rows = []
    for ident, stamp in (("m-1", "2026-09-09T00:00:00+00:00"), ("m-2", "2026-09-09T01:00:00+00:00")):
        rows.append(
            f"- msg_id={ident}; from={SENDER}; to={AGENT}; task_id=T; kind=coordination; "
            f"priority=p1; state=open; summary=read {ident}; requested_action=ack it; "
            f"decision=pending; created_at={stamp}; updated_at={stamp}; updated_by={SENDER}"
        )
    path.write_text(
        "# Thomas Workboard" + chr(10) * 2
        + f"## Agent Claims (Active){chr(10)*2}{claim}{chr(10)*2}"
        + f"## Active Tasks{chr(10)*2}{task}{chr(10)*2}"
        + f"## Issues / Blockers{chr(10)*2}- none{chr(10)*2}"
        + f"## Up For Grabs{chr(10)*2}- none{chr(10)*2}"
        + f"## Agent Message Traffic{chr(10)*2}" + chr(10).join(rows) + chr(10),
        encoding="utf-8",
    )
    return path


def test_reconcile_heals_only_the_message_the_receipt_names(board: Path) -> None:
    """With one open message, 'heal the first one you find' and 'heal the right
    one' are the same behaviour, so a single-message test cannot tell them apart.
    A mutation that ignored the receipt key and healed whatever came first kept
    the rest of this file green; this is the assertion that catches it."""
    _two_message_board(board)
    before = board.read_text(encoding="utf-8")

    ok, detail = message_tool.ack_message(board, msg_id="m-2", actor=AGENT)
    assert ok, detail
    board.write_text(before, encoding="utf-8")          # the revert
    assert _unread_ids(board) == ["m-1"], "only m-2 was acked"

    healed = message_tool.reconcile_receipts(board, agent=AGENT)
    assert healed == ["m-2"], healed

    text = board.read_text(encoding="utf-8")
    m1 = [ln for ln in text.splitlines() if "msg_id=m-1;" in ln][0]
    m2 = [ln for ln in text.splitlines() if "msg_id=m-2;" in ln][0]
    assert "state=open" in m1, "reconcile marked a message nobody acked as read"
    assert "state=acked" in m2, "reconcile did not heal the message the receipt named"
