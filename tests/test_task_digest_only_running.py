"""Thomas must not be told that finished work is still running."""

from __future__ import annotations

from thomas.server.chat_delegation_session import build_active_task_digest
from thomas.server.chat_delegation_tasks import build_active_task_digest_from_rows


def _row(execution_id: str, state: str, summary: str) -> dict:
    return {"execution_id": execution_id, "state": state, "summary": summary, "bot_id": "nova"}


def test_finished_tasks_are_not_offered_as_stoppable() -> None:
    """The digest header tells the model these can be changed or stopped. A
    completed task in that list is a standing instruction to lie -- one session
    on this machine holds 28 tasks, all finished, and every turn was told three
    were running."""
    rows = [
        _row("exec-done", "completed", "Make a chart about the Vikings"),
        _row("exec-live", "executing", "Write the report"),
        _row("exec-failed", "failed", "Broken one"),
        _row("exec-cancelled", "cancelled", "Stopped one"),
        _row("exec-verified", "verified", "Proven one"),
    ]

    digest = build_active_task_digest_from_rows(rows, limit=10, default_backend="provider_native")

    assert "exec-live" in digest
    for gone in ("exec-done", "exec-failed", "exec-cancelled", "exec-verified"):
        assert gone not in digest, f"{gone} is over and must not be offered as stoppable"


def test_a_session_whose_work_is_all_finished_says_nothing() -> None:
    """Silence is correct and free. The old digest spent ~700 tokens a turn
    describing tasks that had ended days earlier."""
    rows = [_row("exec-a", "completed", "One"), _row("exec-b", "verified", "Two")]

    assert build_active_task_digest_from_rows(rows, limit=10, default_backend="x") == ""


def test_states_that_are_still_going_are_kept() -> None:
    for live in ("requested", "executing", "queued", "blocked", "in_progress"):
        rows = [_row("exec-1", live, "Still going")]
        digest = build_active_task_digest_from_rows(rows, limit=5, default_backend="x")
        assert "exec-1" in digest, f"{live} is not a finished state"


def test_the_session_level_digest_filters_too(monkeypatch) -> None:
    """Both digest builders are reachable from chat; fixing one is not enough."""
    import thomas.server.chat_delegation_session as sess

    monkeypatch.setattr(
        sess,
        "session_active_delegations",
        lambda session_id, repo_root=None: [
            _row("exec-old", "completed", "Finished days ago"),
            _row("exec-now", "executing", "Actually running"),
        ],
    )
    digest = build_active_task_digest("sid", limit=10)

    assert "exec-now" in digest
    assert "exec-old" not in digest
