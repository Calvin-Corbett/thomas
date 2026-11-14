"""Boards with a message section, shared by the board archiver tests."""

from __future__ import annotations

from pathlib import Path

from tests._workboard_message_fakes import _write_workboard

NOW = "2026-10-02T00:00:00+00:00"
NOW_ARGS = ["--now", NOW]
# The original suite pins the strict rule (every unacked row stays); the 14-day default has its own tests.
BASE_ARGS = [*NOW_ARGS, "--strict"]


def msg(
    msg_id: str,
    *,
    state: str = "acked",
    created: str = "2026-06-10T12:00:00+00:00",
    sender: str = "Codex 1",
    to: str = "Claude",
    task: str = "none",
    updated: str = "",
    summary: str = "",
    priority: str = "p1",
) -> str:
    text = summary or f"note {msg_id}"
    return (
        f"- msg_id={msg_id}; from={sender}; to={to}; task_id={task}; kind=coordination; priority={priority}; "
        f"state={state}; summary={text}; requested_action=none; decision=none; "
        f"created_at={created}; updated_at={updated or created}; updated_by={sender}"
    )


def make_board(tmp_path: Path, rows: list[str], *, eol: str = "\n", live_tasks: str = "- none") -> Path:
    """A board the repo's own gate accepts, with these message rows spliced in."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = _write_workboard(tmp_path, active_tasks_block=live_tasks)
    text = path.read_text(encoding="utf-8")
    section = "## Agent Message Traffic\n\n<!-- test board -->\n\n" + "\n".join(rows) + "\n\n"
    marker = "## Supporting Docs"
    text = text.replace(marker, section + marker)
    path.write_bytes(text.replace("\n", eol).encode("utf-8"))
    return path


def mixed_history() -> list[str]:
    """Old and new rows across four months with kept rows between archived runs."""
    return [
        msg("msg-a1", created="2026-05-20T10:00:00+00:00"),
        msg("msg-a2", created="2026-05-21T10:00:00+00:00", state="resolved"),
        msg("msg-open-old", created="2026-05-22T10:00:00+00:00", state="open", sender="Bot"),
        msg("msg-b1", created="2026-06-01T10:00:00+00:00"),
        msg("msg-b2", created="2026-06-02T10:00:00+00:00", sender="Bot"),
        msg("msg-c1", created="2026-07-03T10:00:00+00:00"),
        msg("msg-c2", created="2026-07-04T10:00:00+00:00", state="resolved"),
        msg("msg-recent", created="2026-09-30T10:00:00+00:00"),
        msg("msg-d1", created="2026-07-05T10:00:00+00:00"),
        msg("msg-last", created="2026-09-01T10:00:00+00:00", sender="Newest", to="Bot"),
    ]


def append_row(board: Path, row: str) -> None:
    """Add one message row at the end of the message section, keeping the board's line endings."""
    data = board.read_bytes()
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    head, tail = data.split(b"## Supporting", 1)
    board.write_bytes(head.rstrip(b"\r\n") + eol + row.encode() + eol + eol + b"## Supporting" + tail)


def cli_args(board: Path, *extra: str) -> list[str]:
    """Arguments that keep the lock file, the root and the clock inside the test."""
    return ["--board", str(board), "--root", str(board.parent), "--lock-file", str(board.parent / "t.lock"), *extra]
