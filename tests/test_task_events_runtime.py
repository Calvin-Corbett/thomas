from __future__ import annotations

import pytest

from thomas.core import task_bot_runtime
from thomas.server.routes import task_events as mod


@pytest.mark.asyncio
async def test_watch_task_prefers_runtime_execution_state(tmp_path, monkeypatch):
    execution = task_bot_runtime.create_execution(
        session_id="sess-runtime",
        summary="Background research task",
        task_id="task-runtime-1",
        actor="task-manager-agent",
        repo_root=tmp_path,
    )
    execution_id = str(execution["execution_id"])
    task_bot_runtime.update_execution(
        execution_id,
        state="classified",
        progress_summary="Classified for runtime-first watching.",
        actor="task-manager-agent",
        repo_root=tmp_path,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="queued",
        progress_summary="Queued for a worker.",
        actor="task-manager-agent",
        repo_root=tmp_path,
    )
    task_bot_runtime.mark_verified(
        execution_id,
        actor="worker-1",
        summary="Proof attached and verified.",
        repo_root=tmp_path,
    )
    task_bot_runtime.complete_execution(
        execution_id,
        actor="worker-1",
        summary="Task is complete.",
        repo_root=tmp_path,
    )

    monkeypatch.setattr(mod, "_ROOT", tmp_path)
    events: list[dict[str, str]] = []

    async def _emit(event):
        events.append(event)

    await mod.watch_task(
        "task-runtime-1",
        emit_event=_emit,
        workboard_path=tmp_path / "WORKBOARD.md",
        poll_interval=0.01,
        max_duration=0.1,
    )

    assert events
    assert events[0]["type"] == "task_complete"
    assert events[0]["execution_id"] == execution_id
    assert "Task complete" in events[0]["text"]
