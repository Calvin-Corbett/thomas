"""A task the user STOPPED must end its watcher, not time out as "still running".

`task_events.watch_task` is the bridge that streams task-bot lifecycle events
into the chat. It polls the runtime record and breaks out of the loop once the
run is over. That "is it over?" decision was spelled out inline as
`{"completed", "failed", "abandoned"}`, which predated commit c419f3b4 making
`cancelled` a real terminal state -- so the watcher and
`task_bot_runtime.TERMINAL_STATES` disagreed about exactly one word.

Measured by driving the real `watch_task` against a real runtime record, with
`max_duration` scaled down from the shipped 600s so the test is fast:

    run ends 'completed' (control)  BEFORE 0.01s ['task_complete']
                                    AFTER  0.02s ['task_complete']
    run ends 'cancelled'            BEFORE 2.03s ['task_failed', 'task_timeout']
                                      last text: "Task <id> is still running.
                                                  Check observability for live
                                                  execution state."
                                    AFTER  0.00s ['task_failed']
                                      last text: "Task status: Stopped by you."

With the shipped defaults (`_MAX_WATCH_DURATION` 600s, `_POLL_INTERVAL` 2s) the
BEFORE row means the chat re-read the record 300 times over ten minutes and then
told the user their stopped task was still running.

The event TYPE for a cancelled run stays `task_failed`. That is not an oversight
here: commit 043d737c decided it deliberately, because the chat's result card is
binary and telling the truth about a deliberate stop needs a third result type
and a renderer that draws it. This test pins the watcher's *lifetime*, which is
wrong either way.
"""

from __future__ import annotations

import inspect

import pytest

from thomas.core import task_bot_runtime
from thomas.server.routes import task_events as mod


def _drive_to_executing(task_id: str, root):
    execution = task_bot_runtime.create_execution(
        session_id=f"sess-{task_id}",
        summary="Long background job",
        task_id=task_id,
        actor="task-manager-agent",
        repo_root=root,
    )
    execution_id = str(execution["execution_id"])
    for state in ("classified", "queued", "claimed", "executing"):
        task_bot_runtime.update_execution(
            execution_id,
            state=state,
            progress_summary=f"now {state}",
            actor="worker-1",
            repo_root=root,
        )
    return execution_id


async def _watch(task_id: str, root, monkeypatch):
    monkeypatch.setattr(mod, "_ROOT", root)
    events: list[dict] = []

    async def emit(event):
        events.append(event)

    await mod.watch_task(
        task_id,
        emit_event=emit,
        workboard_path=root / "WORKBOARD.md",
        poll_interval=0.01,
        max_duration=2.0,
    )
    return events


@pytest.mark.asyncio
async def test_watcher_for_a_stopped_task_ends_instead_of_claiming_it_still_runs(tmp_path, monkeypatch):
    execution_id = _drive_to_executing("task-stopped", tmp_path)
    task_bot_runtime.cancel_execution(
        execution_id,
        actor="user",
        summary="Stopped by you.",
        repo_root=tmp_path,
    )
    row = task_bot_runtime.find_by_task_id("task-stopped", repo_root=tmp_path)
    assert row is not None and row["state"] == "cancelled"

    events = await _watch("task-stopped", tmp_path, monkeypatch)

    types = [e["type"] for e in events]
    assert "task_timeout" not in types, f"the watcher ran to its full max_duration on a run the user stopped: {types}"
    assert not any("still running" in str(e.get("text") or "") for e in events), (
        f"the chat was told a stopped task is still running: {[e.get('text') for e in events]}"
    )
    assert events and events[-1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_control_watcher_for_a_completed_task_still_ends(tmp_path, monkeypatch):
    """Control: the same measurement on a good input, so a pass means something."""
    execution_id = _drive_to_executing("task-finished", tmp_path)
    task_bot_runtime.update_execution(
        execution_id,
        state="awaiting_proof",
        progress_summary="proof",
        actor="worker-1",
        repo_root=tmp_path,
    )
    task_bot_runtime.mark_verified(execution_id, actor="worker-1", summary="verified", repo_root=tmp_path)
    task_bot_runtime.complete_execution(
        execution_id,
        actor="worker-1",
        summary="Task is complete.",
        repo_root=tmp_path,
        verified_success=True,
    )

    events = await _watch("task-finished", tmp_path, monkeypatch)

    assert [e["type"] for e in events] == ["task_complete"]


def test_the_watcher_reads_its_terminal_set_from_the_runtime_that_writes_it():
    """Guard the fix shape: derive the predicate, do not re-spell the vocabulary.

    Re-adding a literal here would pass the two tests above today and silently
    rot again the next time a terminal state is added -- which is exactly how
    `cancelled` was missed.
    """
    source = inspect.getsource(mod.watch_task)
    assert "state in task_bot_runtime.TERMINAL_STATES" in source, (
        "watch_task must derive its terminal check from task_bot_runtime.TERMINAL_STATES"
    )
    # Comments are allowed to quote the old literal (the fix's own note does);
    # only executable code is checked.
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert '{"completed", "failed", "abandoned"}' not in code, (
        "the hand-copied terminal-state literal is back in watch_task"
    )
    # And the derivation must actually cover every ending the writer can record.
    assert {"completed", "failed", "abandoned", "cancelled"} <= task_bot_runtime.TERMINAL_STATES
    assert task_bot_runtime.TERMINAL_STATES <= task_bot_runtime.VALID_STATES
