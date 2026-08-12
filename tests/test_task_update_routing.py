"""Model-driven task-update routing.

Thomas was bad at follow-ups ("actually make it blue") — with only send_task he'd spawn
a wrong NEW task or do nothing. The update_task skill lets the chat MODEL pick the right
RUNNING task by ref (from the background-work digest) and steer/cancel it. These lock in
the resolver + the apply step so an update lands on the intended task, not a guess.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from thomas.core import task_bot_runtime
from thomas.server import chat_delegation as cd


def _mk(repo: Path, session: str, summary: str) -> str:
    ex = task_bot_runtime.create_execution(
        session_id=session,
        summary=summary,
        intent="chat_task",
        scope=["reasoning"],
        visibility="background",
        bot_id="nova",
        actor="thomas-worker",
        backend_type="provider_native",
        repo_root=repo,
    )
    eid = str(ex.get("execution_id") or "")
    for st in ("classified", "queued", "claimed", "executing"):
        task_bot_runtime.update_execution(eid, state=st, actor="nova", repo_root=repo)
    return eid


def test_resolve_requires_an_exact_structured_reference() -> None:
    rows = [
        {"execution_id": "exec-aaaa1111", "state": "completed"},
        {"execution_id": "exec-bbbb2222", "state": "executing"},
    ]
    with patch.object(cd, "session_active_delegations", return_value=rows):
        # A guessed suffix is not promoted to a task selection.
        assert cd.resolve_active_task_ref("s", "bbbb2222") is None
        # The exact raw execution id is accepted.
        assert cd.resolve_active_task_ref("s", "exec-bbbb2222") == "exec-bbbb2222"
        # The bracketed digest form is accepted.
        assert cd.resolve_active_task_ref("s", "[task exec-bbbb2222]") == "exec-bbbb2222"
        # No plausible match returns None (caller tells the user instead of guessing).
        assert cd.resolve_active_task_ref("s", "zzz999") is None


def test_apply_update_steers_the_running_task(tmp_path: Path) -> None:
    session = "sess-update"
    eid = _mk(tmp_path, session, "Build a Pong game")
    rows = [{"execution_id": eid, "state": "executing"}]
    with patch.object(cd, "session_active_delegations", return_value=rows):
        result = cd.apply_task_update(session, eid, "make the paddles blue", repo_root=tmp_path)
    assert result["ok"] is True and result["action"] == "steer"
    # The instruction is queued for the worker to drain.
    pending = task_bot_runtime.take_pending_instructions(eid, repo_root=tmp_path)
    assert any("paddles blue" in p for p in pending)


def test_apply_update_refuses_a_terminal_task(tmp_path: Path) -> None:
    session = "sess-term"
    eid = _mk(tmp_path, session, "Build a thing")
    task_bot_runtime.update_execution(eid, state="failed", actor="nova", repo_root=tmp_path)
    rows = [{"execution_id": eid, "state": "failed"}]
    with patch.object(cd, "session_active_delegations", return_value=rows):
        result = cd.apply_task_update(session, eid, "tweak it", repo_root=tmp_path)
    assert result["ok"] is False
    assert "terminal" in result["error"].lower()


def test_apply_update_cancel(tmp_path: Path) -> None:
    session = "sess-cancel"
    eid = _mk(tmp_path, session, "Long task")
    rows = [{"execution_id": eid, "state": "executing"}]
    with patch.object(cd, "session_active_delegations", return_value=rows):
        result = cd.apply_task_update(session, eid, "", cancel=True, repo_root=tmp_path)
    assert result["ok"] is True and result["action"] == "cancel"
    assert task_bot_runtime.is_cancel_requested(eid, repo_root=tmp_path) is True


def test_apply_update_no_match_is_a_clean_error(tmp_path: Path) -> None:
    with patch.object(cd, "session_active_delegations", return_value=[]):
        result = cd.apply_task_update("s", "exec-nope", "change", repo_root=tmp_path)
    assert result["ok"] is False and "no running task" in result["error"].lower()


def test_digest_exposes_task_refs(tmp_path: Path) -> None:
    session = "sess-digest"
    eid = _mk(tmp_path, session, "Build a Pong game")
    rows = [{"execution_id": eid, "state": "executing", "bot_id": "nova", "last_progress": "working"}]
    with patch.object(cd, "session_active_delegations", return_value=rows):
        digest = cd.build_active_task_digest(session, repo_root=tmp_path)
    assert f"[task {eid}]" in digest
    assert "update_task" in digest
