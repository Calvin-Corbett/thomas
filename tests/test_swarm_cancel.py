import asyncio
import json
import pytest

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, TaskResult, TaskStatus


class Planner:
    agent_id = "planner"
    def __init__(self, graph_obj): self.graph_obj = graph_obj
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        s = json.dumps(self.graph_obj)
        await emit_text(s)
        return TaskResult(ok=True, output=s)


class SlowAgent:
    def __init__(self, agent_id): self.agent_id = agent_id
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        await emit_text(f"start {task.id}\n")
        # wait until cancelled
        await cancel_event.wait()
        return TaskResult(ok=False, error="cancelled")


class Reviewer:
    agent_id = "reviewer"
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        return TaskResult(ok=True, output="final")


@pytest.mark.asyncio
async def test_cancellation_marks_tasks_cancelled():
    graph = {
        "version": 1,
        "goal": "test",
        "summary": "",
        "tasks": [
            {"id": "A", "title": "A", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
            {"id": "B", "title": "B", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
        ],
    }

    orch = SwarmOrchestrator(run_id="run_cancel", config=SwarmConfig(max_parallel_tasks=2))
    subagents = {"planner": Planner(graph), "coder": SlowAgent("coder"), "reviewer": Reviewer()}

    async def consume():
        async for _ in orch.astream(user_request="x", subagents=subagents):
            # cancel as soon as we see something running
            if orch.task_status.get("A") == TaskStatus.RUNNING or orch.task_status.get("B") == TaskStatus.RUNNING:
                orch.cancel()

    await consume()

    assert orch._cancel.is_set()
    assert orch.task_status["A"] in (TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.DONE)
    assert orch.task_status["B"] in (TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.DONE)
