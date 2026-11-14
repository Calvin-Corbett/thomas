"""A Work update must reach the active worker, not wait for a retry/new task.

Two halves of the same chain, because either one alone is silent:

1. Down: the ledger is the queue of record, and the adapter the agent loop polls
   must drain exactly one execution's updates.
2. Up: when the loop accepts an update at its next safe boundary it says so with
   a STATUS event. That event was dropped by the worker event seam, so a steer
   that genuinely landed produced nothing any surface could show -- the task row
   stayed on "Update queued for this task" for the rest of the run. What goes up
   is what was written for a person: the envelope checkpoint and the mid-run
   check-in carry counters aimed at the model, and stay in the log.
"""

from __future__ import annotations

from queue import Empty
from types import SimpleNamespace

import pytest

from tests.test_agent_worker_parity import _app_with_model, _FakeLLM
from thomas.core import task_bot_runtime
from thomas.core.events import EventType
from thomas.server import app_helpers, worker_runtime
from thomas.server.chat_delegation_steering import DurableSteeringQueue
from thomas.tools.registry import ToolRegistry


def test_durable_steering_queue_drains_one_execution_without_mixing_tasks(tmp_path):
    def start(summary):
        record = task_bot_runtime.create_execution(
            session_id="work-session",
            summary=summary,
            task_id="work-check",
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

    first = start("Finish the invoice report")
    second = start("Check the calendar")
    first_id = first["execution_id"]
    second_id = second["execution_id"]
    task_bot_runtime.steer_execution(first_id, "Use the March data", repo_root=tmp_path)
    task_bot_runtime.steer_execution(first_id, "Do not send it yet", repo_root=tmp_path)
    task_bot_runtime.steer_execution(second_id, "Use tomorrow", repo_root=tmp_path)

    queue = DurableSteeringQueue(first_id, tmp_path)
    assert queue.get_nowait() == "Use the March data\nDo not send it yet"
    with pytest.raises(Empty):
        queue.get_nowait()
    assert task_bot_runtime.take_pending_instructions(second_id, repo_root=tmp_path) == ["Use tomorrow"]


@pytest.mark.asyncio
async def test_worker_seam_carries_the_steer_acknowledgement_and_the_queue(monkeypatch, tmp_path):
    """The loop's own words about the update reach the surface as progress."""

    class StatusLoop:
        built_with: dict = {}

        def __init__(self, _cfg, llm, _tools, **kwargs):
            type(self).built_with = dict(kwargs)
            self.llm = llm

        async def run(self, _prompt, **_kwargs):
            yield SimpleNamespace(
                type=EventType.STATUS,
                data={"message": "Received your update. Continuing this task."},
            )
            # Empty status lines must not become blank progress rows.
            yield SimpleNamespace(type=EventType.STATUS, data={"message": "   "})
            # Written for the model, not for a person: counters must not replace
            # the meaningful status line on the card.
            yield SimpleNamespace(
                type=EventType.STATUS,
                data={
                    "message": "Checkpoint 3: 12000 tokens used of 50000 — summarize progress so far.",
                    "constraint_checkpoint": {"checkpoint_index": 3},
                },
            )
            yield SimpleNamespace(
                type=EventType.STATUS,
                data={
                    "message": "Check-in #2: 4 tool step(s), ~12,000 tokens, 90s since last check-in.",
                    "checkin": {"sequence": 2, "ack_required": False},
                },
            )
            # A gate that stops the run dead is the one check-in worth saying.
            yield SimpleNamespace(
                type=EventType.STATUS,
                data={
                    "message": "Check-in #3: ... Paused — acknowledge to continue.",
                    "checkin": {"sequence": 3, "ack_required": True},
                },
            )
            yield SimpleNamespace(type=EventType.AGENT_DONE, data={"text": "Done."})

    monkeypatch.setattr(worker_runtime, "LLMClient", _FakeLLM)
    monkeypatch.setattr(worker_runtime, "AgentLoop", StatusLoop)
    monkeypatch.setattr(app_helpers, "_build_tools", lambda *_args, **_kwargs: ToolRegistry())
    app = _app_with_model("openai", "fixture", "worker")
    steering = DurableSteeringQueue("exec-steered", tmp_path)
    events = [
        event
        async for event in worker_runtime.run_agent_worker_events(
            app,
            prompt="check project",
            instructions="Read only",
            work_dir=tmp_path,
            profile="worker",
            steering_queue=steering,
        )
    ]

    progress = [str(event.get("text") or "") for event in events if event.get("type") == "progress"]
    assert "Received your update. Continuing this task." in progress
    assert "" not in progress and "   " not in progress
    assert not [line for line in progress if line.startswith(("Checkpoint 3:", "Check-in #2:"))]
    assert "Thomas paused this task for a check-in and needs your acknowledgement to continue." in progress
    assert events[-1]["type"] == "done"
    # The same queue the ledger feeds is the one the loop polls between steps.
    assert StatusLoop.built_with["message_queue"] is steering
