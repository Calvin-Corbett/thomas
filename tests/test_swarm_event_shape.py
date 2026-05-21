import asyncio
import json

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, TaskResult


class Planner:
    agent_id = "planner"

    def __init__(self, graph_obj):
        self.graph_obj = graph_obj

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        s = json.dumps(self.graph_obj)
        await emit_text(s)
        return TaskResult(ok=True, output=s)


class Agent:
    def __init__(self, agent_id):
        self.agent_id = agent_id

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        await emit_text("hello\n")
        return TaskResult(ok=True, output="ok")


class Reviewer:
    agent_id = "reviewer"

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        return TaskResult(ok=True, output="final")


def test_event_shape_includes_required_fields():
    async def _run() -> None:
        graph = {
            "version": 1,
            "goal": "test",
            "summary": "",
            "tasks": [
                {"id": "A", "title": "A", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
            ],
        }
        orch = SwarmOrchestrator(run_id="run_shape", config=SwarmConfig(max_parallel_tasks=1))
        subagents = {"planner": Planner(graph), "coder": Agent("coder"), "reviewer": Reviewer()}

        events = []
        async for e in orch.astream(user_request="x", subagents=subagents):
            events.append(e)

        assert events
        for e in events:
            assert isinstance(e.get("type"), str)
            assert e.get("run_id") == "run_shape"
            assert isinstance(e.get("agent_id"), str) and e["agent_id"]
            assert isinstance(e.get("task_id"), str) and e["task_id"]
            assert isinstance(e.get("seq"), int) and e["seq"] >= 1
            assert isinstance(e.get("ts"), str) and e["ts"]

    asyncio.run(_run())
