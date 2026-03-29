import asyncio

from thomas.agent.loop import AgentLoop
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
        yield StreamEvent(type="token", data={"text": "ok"})
        yield StreamEvent(type="done", data={})


class _DummyClarifyThenProceedLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="local",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="qwen2.5-coder:7b",
            context_window=4096,
            max_tokens=128,
        )
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(type="token", data={"text": "Which file should I edit?"})
            yield StreamEvent(type="done", data={})
            return
        yield StreamEvent(type="token", data={"text": "Proceeding with sensible defaults and implementing now."})
        yield StreamEvent(type="done", data={})


def _collect_start(prompt: str, *, autonomy_level: int):
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(cfg, _DummyLocalLLM(), tools, conversation=[], autonomy_level=autonomy_level)

    async def run_once():
        events = []
        async for ev in agent.run(prompt, tools_policy="auto"):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    return next((e for e in events if e.type == EventType.AGENT_START), None)


def test_autonomy_level_1_forces_manual_tools_policy() -> None:
    start = _collect_start("fix this bug in app.py", autonomy_level=1)
    assert start is not None
    assert start.data.get("tools_policy") == "never"
    assert int(start.data.get("autonomy_level") or 0) == 1


def test_autonomy_level_4_keeps_casual_turns_lightweight() -> None:
    start = _collect_start("hey how are you", autonomy_level=4)
    assert start is not None
    assert start.data.get("tools_policy") == "never"
    assert str(start.data.get("autonomy_name") or "").lower() == "full autonomy"


def test_autonomy_level_4_forces_full_auto_on_action_turns() -> None:
    start = _collect_start("fix this bug in app.py", autonomy_level=4)
    assert start is not None
    assert start.data.get("tools_policy") == "always"
    assert str(start.data.get("autonomy_name") or "").lower() == "full autonomy"


def test_autonomy_level_2_keeps_guarded_auto_policy() -> None:
    start = _collect_start("fix app bug", autonomy_level=2)
    assert start is not None
    assert start.data.get("tools_policy") == "auto"
    assert int(start.data.get("autonomy_level") or 0) == 2


def test_autonomy_level_4_reprompts_instead_of_stalling_on_clarifier() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    llm = _DummyClarifyThenProceedLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run("fix this bug in app.py", tools_policy="auto"):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    assert llm.calls >= 2

    text_events = [e for e in events if e.type == EventType.TEXT_DELTA]
    combined = "".join(str(e.data.get("text") or "") for e in text_events)
    assert "Which file should I edit?" not in combined
    assert "Proceeding with sensible defaults" in combined

    token_report = done.data.get("token_report") or {}
    continuity = token_report.get("continuity") or {}
    assert int(continuity.get("full_auto_reprompt_count") or 0) >= 1


def test_ack_turn_detection_ignores_explanatory_continue_sentence() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_DummyTool())
    agent = AgentLoop(cfg, _DummyLocalLLM(), tools, conversation=[], autonomy_level=4)
    assert agent._is_ack_turn("continue") is True
    assert agent._is_ack_turn("continue about what I said before, I am just talking to you right now") is False
