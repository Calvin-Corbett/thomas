import asyncio

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _EchoTool(Tool):
    name = "dummy.echo"
    category = "test"
    description = "echo"
    parameters = {"type": "object", "properties": {"message": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"message": str(args.get("message", ""))})


class _TwoStepLLM:
    def __init__(self, args_text: str) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
        self._args_text = str(args_text)
        self._step = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        if self._step == 0:
            self._step += 1
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "dummy.echo"})
            yield StreamEvent(
                type="tool_call_end",
                data={"id": "t1", "name": "dummy.echo", "arguments": self._args_text},
            )
            yield StreamEvent(type="done", data={})
            return

        yield StreamEvent(type="token", data={"text": "done"})
        yield StreamEvent(type="done", data={})


def _run_with_args(args_text: str):
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_EchoTool())
    agent = AgentLoop(cfg, _TwoStepLLM(args_text), tools, conversation=[])

    async def run_once():
        events = []
        async for ev in agent.run("run tool", tools_policy="always"):
            events.append(ev)
        return events

    return asyncio.run(run_once())


def test_agent_loop_accepts_code_fenced_tool_json_args() -> None:
    events = _run_with_args('```json\n{"message":"ok"}\n```')
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert results[0].data.get("ok") is True
    assert "ok" in str(results[0].data.get("result_text", ""))


def test_agent_loop_accepts_python_style_tool_args() -> None:
    events = _run_with_args("{'message': 'ok'}")
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert results[0].data.get("ok") is True
    assert "ok" in str(results[0].data.get("result_text", ""))
