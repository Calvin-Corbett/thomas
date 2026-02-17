import asyncio
import json
import pytest

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, TaskResult


class Planner:
    agent_id = "planner"
    def __init__(self, graph_obj): self.graph_obj = graph_obj
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        s = json.dumps(self.graph_obj)
        await emit_text(s)
        return TaskResult(ok=True, output=s)


class ToolCaller:
    def __init__(self, agent_id): self.agent_id = agent_id
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        await emit_text("call tool\n")
        # mark as mutating explicitly
        await call_tool("write_file", {"path": f"x/{task.id}.txt", "content": "hi"}, mutates_fs=True)
        return TaskResult(ok=True, output="ok")


class Reviewer:
    agent_id = "reviewer"
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        return TaskResult(ok=True, output="final")


@pytest.mark.asyncio
async def test_fs_mutating_tools_are_serialized():
    graph = {
        "version": 1,
        "goal": "test",
        "summary": "",
        "tasks": [
            {"id": "A", "title": "A", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
            {"id": "B", "title": "B", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
        ],
    }

    in_tool = {"active": False, "violations": 0}

    async def tool_call(name, args):
        if in_tool["active"]:
            in_tool["violations"] += 1
        in_tool["active"] = True
        await asyncio.sleep(0.02)
        in_tool["active"] = False
        return {"ok": True}

    orch = SwarmOrchestrator(run_id="run_tools", config=SwarmConfig(max_parallel_tasks=2), tool_call=tool_call)
    subagents = {"planner": Planner(graph), "coder": ToolCaller("coder"), "reviewer": Reviewer()}

    async for _ in orch.astream(user_request="x", subagents=subagents):
        pass

    assert in_tool["violations"] == 0
