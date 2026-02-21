import asyncio
import json

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, TaskResult, TaskStatus


class Planner:
    agent_id = "planner"
    def __init__(self, graph_obj): self.graph_obj = graph_obj
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        s = json.dumps(self.graph_obj)
        await emit_text(s)
        return TaskResult(ok=True, output=s)


class AAgent:
    agent_id = "coder"
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        await emit_text("A runs\n")
        await asyncio.sleep(0.01)
        return TaskResult(ok=False, error="boom", output="fail A")


class BAgent:
    agent_id = "tester"
    def __init__(self): self.ran = False
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        self.ran = True
        return TaskResult(ok=True, output="B should not run")


class Reviewer:
    agent_id = "reviewer"
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        return TaskResult(ok=True, output="final")


def test_failed_dep_blocks_downstream_task():
    async def _run() -> None:
        graph = {
            "version": 1,
            "goal": "test",
            "summary": "",
            "tasks": [
                {"id": "A", "title": "A", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
                {"id": "B", "title": "B", "agent": "tester", "deps": ["A"], "prompt": "", "acceptance": [], "meta": {}},
            ],
        }
        b = BAgent()
        orch = SwarmOrchestrator(run_id="run_block", config=SwarmConfig(max_parallel_tasks=2))
        subagents = {"planner": Planner(graph), "coder": AAgent(), "tester": b, "reviewer": Reviewer()}

        async for _ in orch.astream(user_request="x", subagents=subagents):
            pass

        assert b.ran is False
        assert orch.task_status["A"] == TaskStatus.FAILED
        assert orch.task_status["B"] == TaskStatus.BLOCKED

    asyncio.run(_run())
