import asyncio
import json

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, TaskResult


class Planner:
    agent_id = "planner"
    def __init__(self, graph_obj):
        self.graph_obj = graph_obj

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        # emit JSON in chunks to exercise parser
        s = json.dumps(self.graph_obj)
        for i in range(0, len(s), 20):
            await emit_text(s[i:i+20])
            await asyncio.sleep(0)
        return TaskResult(ok=True, output=s)


class ConcurrencyAgent:
    def __init__(self, agent_id, active_counter, max_seen, gate_evt, release_evt):
        self.agent_id = agent_id
        self.active_counter = active_counter
        self.max_seen = max_seen
        self.gate_evt = gate_evt
        self.release_evt = release_evt

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        # increment active count
        self.active_counter[0] += 1
        self.max_seen[0] = max(self.max_seen[0], self.active_counter[0])
        # signal once we hit desired concurrency
        if self.active_counter[0] >= 2:
            self.gate_evt.set()
        # wait until released (or cancelled)
        done, _ = await asyncio.wait(
            [asyncio.create_task(self.release_evt.wait()), asyncio.create_task(cancel_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_event.is_set():
            self.active_counter[0] -= 1
            return TaskResult(ok=False, error="cancelled")
        self.active_counter[0] -= 1
        return TaskResult(ok=True, output=f"done {task.id}")


class Reviewer:
    agent_id = "reviewer"
    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        return TaskResult(ok=True, output="final")


def test_max_parallel_tasks_enforced():
    async def _run() -> None:
        graph = {
            "version": 1,
            "goal": "test",
            "summary": "",
            "tasks": [
                {"id": "A", "title": "A", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
                {"id": "B", "title": "B", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
                {"id": "C", "title": "C", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
                {"id": "D", "title": "D", "agent": "coder", "deps": [], "prompt": "", "acceptance": [], "meta": {}},
            ],
        }

        active = [0]
        max_seen = [0]
        gate = asyncio.Event()
        release = asyncio.Event()

        orch = SwarmOrchestrator(run_id="run_parallel", config=SwarmConfig(max_parallel_tasks=2))
        subagents = {
            "planner": Planner(graph),
            "coder": ConcurrencyAgent("coder", active, max_seen, gate, release),
            "reviewer": Reviewer(),
        }

        events = []

        async def consume():
            async for e in orch.astream(user_request="x", subagents=subagents):
                events.append(e)

        t = asyncio.create_task(consume())
        await gate.wait()  # at least 2 running
        # Give scheduler a chance to try to exceed limit
        await asyncio.sleep(0.05)
        assert max_seen[0] == 2
        release.set()
        await t

        # Ensure swarm_done happened
        assert any(e["type"] == "swarm_done" for e in events)

    asyncio.run(_run())
