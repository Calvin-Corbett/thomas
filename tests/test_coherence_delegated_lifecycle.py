from __future__ import annotations

from thomas.core import task_bot_runtime
from thomas.marketplace.orchestrator import brain
from thomas.server.chat_delegation_session import apply_task_update, session_active_delegations


def _start_execution(tmp_path, *, session_id: str, summary: str) -> dict:
    record = task_bot_runtime.create_execution(
        session_id=session_id,
        summary=summary,
        task_id=f"task-{summary.split()[0].lower()}",
        intent="task.execute",
        scope=["workspace"],
        actor="thomas",
        repo_root=tmp_path,
    )
    for state in ("classified", "queued", "claimed", "executing"):
        record = task_bot_runtime.update_execution(
            record["execution_id"],
            state=state,
            actor="worker",
            repo_root=tmp_path,
        )
    return record


def test_delegated_work_can_be_steered_and_cancelled_from_the_durable_ledger(tmp_path) -> None:
    session_id = "owner-session"
    record = _start_execution(tmp_path, session_id=session_id, summary="Draft launch brief")
    execution_id = record["execution_id"]

    steered = apply_task_update(
        session_id,
        execution_id,
        "Use the burnt-orange brand palette.",
        repo_root=tmp_path,
    )
    assert steered["ok"] is True
    assert steered["receipt"]["kind"] == "delegated"
    assert steered["receipt"]["interruptible"] is True
    assert steered["receipt"]["evidence"]["pending_instruction_count"] == 1
    assert task_bot_runtime.take_pending_instructions(execution_id, repo_root=tmp_path) == [
        "Use the burnt-orange brand palette."
    ]

    cancelled = apply_task_update(session_id, execution_id, cancel=True, repo_root=tmp_path)
    assert cancelled["ok"] is True
    assert cancelled["receipt"]["evidence"]["cancel_requested"] is True

    # Rebuild from disk, as a restarted server would. No process-local task object is used.
    reloaded = session_active_delegations(session_id, repo_root=tmp_path)
    assert reloaded[0]["execution_id"] == execution_id
    assert reloaded[0]["cancel_requested"] is True
    assert reloaded[0]["receipt"]["evidence"]["cancel_requested"] is True


def test_artifact_backed_completion_is_reported_once_across_restart(tmp_path, monkeypatch) -> None:
    session_id = "owner-session"
    record = _start_execution(tmp_path, session_id=session_id, summary="Build owner report")
    execution_id = record["execution_id"]
    task_bot_runtime.attach_proof(
        execution_id,
        artifacts=[{"path": "artifacts/owner-report.md", "kind": "document"}],
        summary="Verified owner report at artifacts/owner-report.md.",
        status="attached",
        actor="worker",
        repo_root=tmp_path,
    )
    task_bot_runtime.complete_execution(
        execution_id,
        summary="Verified owner report at artifacts/owner-report.md.",
        actor="worker",
        repo_root=tmp_path,
    )

    reloaded = session_active_delegations(session_id, repo_root=tmp_path)
    receipt = reloaded[0]["receipt"]
    assert receipt["ok"] is True
    assert receipt["interruptible"] is False
    assert receipt["evidence"]["proof"]["artifacts"] == [{"path": "artifacts/owner-report.md", "kind": "document"}]
    assert "Verified owner report" in brain._completion_detail(reloaded[0])

    # Completion acknowledgement is stored in the same disk ledger. Clearing the
    # process-local cache simulates a restart; the completion must not be repeated.
    monkeypatch.setattr(task_bot_runtime, "ROOT", tmp_path)
    brain._reported_completions.clear()
    fresh = brain._collect_unreported_completions(session_id, reloaded)
    assert [row["execution_id"] for row in fresh] == [execution_id]
    brain._mark_completions_reported(session_id, fresh)
    assert task_bot_runtime.get_execution(execution_id, tmp_path)["reported_to_chat_at"]

    brain._reported_completions.clear()
    after_restart = session_active_delegations(session_id, repo_root=tmp_path)
    assert brain._collect_unreported_completions(session_id, after_restart) == []
