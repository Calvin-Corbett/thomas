import asyncio

from thomas.agent.loop import AgentLoop
from thomas.agent.routing import IntentRouter
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _DummyTool(Tool):
    name = "dummy.echo"
    category = "test"
    description = "echo"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"ok": True})


class _DummyLocalLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="local",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="qwen2.5-coder:7b",
            context_window=4096,
            max_tokens=128,
        )

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        yield StreamEvent(type="token", data={"text": "hi"})
        yield StreamEvent(type="done", data={})


class _DummyRemoteLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="openai",
            provider="openai_compat",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            context_window=128000,
            max_tokens=256,
        )

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        yield StreamEvent(type="token", data={"text": "hi"})
        yield StreamEvent(type="done", data={})


class _NeverCalledLLM(_DummyLocalLLM):
    async def stream_chat(self, messages, tools):  # noqa: ANN001
        raise AssertionError("LLM should not be called for direct tool-usage introspection")


def test_select_tools_keeps_local_casual_turns_lightweight() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(cfg, _DummyLocalLLM(), tools, conversation=[])
    route = IntentRouter().decide("hey, how are you?")

    specs = agent._select_tools("hey, how are you?", policy="auto", route=route)
    assert specs is None


def test_select_tools_keeps_remote_casual_turns_lightweight() -> None:
    cfg = AppConfig(models={"openai": ModelConfig(name="openai", model="dummy")}, default_model="openai")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(cfg, _DummyRemoteLLM(), tools, conversation=[])
    route = IntentRouter().decide("hey, how are you?")

    specs = agent._select_tools("hey, how are you?", policy="auto", route=route)
    assert specs is None


def test_select_tools_stays_available_for_remote_project_tasks() -> None:
    cfg = AppConfig(models={"openai": ModelConfig(name="openai", model="dummy")}, default_model="openai")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(cfg, _DummyRemoteLLM(), tools, conversation=[])
    route = IntentRouter().decide("fix this repo bug in app.py")

    specs = agent._select_tools("fix this repo bug in app.py", policy="auto", route=route)
    assert isinstance(specs, list)
    assert specs


def test_remote_profiles_keep_casual_turns_on_never_tools_policy() -> None:
    cfg = AppConfig(models={"openai": ModelConfig(name="openai", model="dummy")}, default_model="openai")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(cfg, _DummyRemoteLLM(), tools, conversation=[])

    async def run_once():
        events = []
        async for ev in agent.run("hey, how are you?", tools_policy="auto"):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    start = next((e for e in events if e.type == EventType.AGENT_START), None)
    assert start is not None
    assert start.data.get("tools_policy") == "never"


def test_project_related_prompt_overrides_route_never_tools_policy() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(cfg, _DummyLocalLLM(), tools, conversation=[])

    async def run_once():
        events = []
        async for ev in agent.run("how should you program and fix this repo bug?", tools_policy="auto"):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    start = next((e for e in events if e.type == EventType.AGENT_START), None)
    assert start is not None
    assert start.data.get("tools_policy") == "auto"


def test_tool_usage_questions_are_answered_from_recorded_context() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(
        cfg,
        _NeverCalledLLM(),
        tools,
        conversation=[],
    )

    async def run_once():
        events = []
        async for ev in agent.run("what tools did you use in this conversation?", tools_policy="auto"):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    assert int(done.data.get("tool_calls") or 0) == 0
    assert "recorded tool calls" in str(done.data.get("text") or "").lower()
