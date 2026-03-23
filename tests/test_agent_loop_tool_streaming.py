import asyncio
import json

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _SlowEchoTool(Tool):
    name = "slow.echo"
    category = "test"
    description = "sleep and echo"
    parameters = {"type": "object", "properties": {"delay": {"type": "number"}}}

    async def execute(self, args):  # noqa: ANN001
        delay = float(args.get("delay", 0.0) or 0.0)
        await asyncio.sleep(delay)
        return ToolResult(ok=True, data={"delay": delay})


class _TwoToolLLM:
    def __init__(self):
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
        self._step = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        if self._step == 0:
            self._step += 1
            yield StreamEvent(
                type="tool_call_start",
                data={"id": "t_fast", "name": "slow.echo"},
            )
            yield StreamEvent(
                type="tool_call_end",
                data={
                    "id": "t_fast",
                    "name": "slow.echo",
                    "arguments": '{"delay": 0.05}',
                },
            )
            yield StreamEvent(
                type="tool_call_start",
                data={"id": "t_slow", "name": "slow.echo"},
            )
            yield StreamEvent(
                type="tool_call_end",
                data={
                    "id": "t_slow",
                    "name": "slow.echo",
                    "arguments": '{"delay": 0.20}',
                },
            )
            yield StreamEvent(type="done", data={})
            return

        yield StreamEvent(type="token", data={"text": "done"})
        yield StreamEvent(type="done", data={})


class _CoroutineStreamLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        async def _stream():
            yield StreamEvent(type="token", data={"text": "ok"})
            yield StreamEvent(type="done", data={})

        return _stream()


def test_agent_loop_streams_tool_results_as_completed() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_SlowEchoTool())
    agent = AgentLoop(cfg, _TwoToolLLM(), tools, conversation=[])

    async def run_once():
        events = []
        async for ev in agent.run("run both tools", tools_policy="always"):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    tool_results = [ev for ev in events if ev.type == EventType.TOOL_RESULT]
    assert len(tool_results) == 2
    delays = [float(json.loads(ev.data.get("result", "{}")).get("delay", 0.0)) for ev in tool_results]
    assert delays[0] < delays[1]


def test_agent_loop_coerces_coroutine_stream_chat_result() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(cfg, _CoroutineStreamLLM(), ToolRegistry(), conversation=[])

    async def run_once():
        events = []
        async for ev in agent.run("respond quickly", tools_policy="never"):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    text_events = [ev for ev in events if ev.type == EventType.TEXT_DELTA]
    done = [ev for ev in events if ev.type == EventType.AGENT_DONE]

    assert text_events
    assert done
    assert any("ok" in ev.data.get("text", "") for ev in text_events)
