import asyncio

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _AuditSink:
    def __init__(self) -> None:
        self.events = []

    async def log_async(self, **kwargs):  # noqa: ANN003
        self.events.append(kwargs)


class _EchoTool(Tool):
    name = "echo.tool"
    category = "test"
    description = "echoes input"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"text": str(args.get("text", ""))})


class _SingleToolLLM:
    def __init__(self, arguments: str):
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
        self._arguments = arguments
        self._step = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        if self._step == 0:
            self._step += 1
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "echo.tool"})
            yield StreamEvent(
                type="tool_call_end",
                data={"id": "t1", "name": "echo.tool", "arguments": self._arguments},
            )
            yield StreamEvent(type="done", data={})
            return
        yield StreamEvent(type="token", data={"text": "done"})
        yield StreamEvent(type="done", data={})


def _base_config() -> AppConfig:
    return AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")


def test_action_audit_logs_tool_start_and_result() -> None:
    tools = ToolRegistry()
    tools.register(_EchoTool())
    audit = _AuditSink()
    agent = AgentLoop(
        _base_config(),
        _SingleToolLLM(arguments='{"text":"hi"}'),
        tools,
        conversation=[],
        action_audit=audit,
    )

    async def run_once():
        return [ev async for ev in agent.run("run the tool", tools_policy="always")]

    events = asyncio.run(run_once())
    tool_results = [ev for ev in events if ev.type == EventType.TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].data.get("ok") is True

    kinds = [str(e.get("kind")) for e in audit.events]
    assert "tool_action_start" in kinds
    assert "tool_action_result" in kinds


def test_action_audit_logs_invalid_tool_args() -> None:
    tools = ToolRegistry()
    tools.register(_EchoTool())
    audit = _AuditSink()
    agent = AgentLoop(
        _base_config(),
        _SingleToolLLM(arguments="{not json"),
        tools,
        conversation=[],
        action_audit=audit,
    )

    async def run_once():
        return [ev async for ev in agent.run("run the tool", tools_policy="always")]

    events = asyncio.run(run_once())
    tool_results = [ev for ev in events if ev.type == EventType.TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].data.get("ok") is False

    kinds = [str(e.get("kind")) for e in audit.events]
    assert "tool_action_invalid_args" in kinds
