import asyncio

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _AlwaysToolCallingLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="dummy",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=8192,
            max_tokens=256,
        )
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self.calls += 1
        tool_id = f"tool_{self.calls}"
        yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "dummy.needs_int"})
        yield StreamEvent(
            type="tool_call_end",
            data={
                "id": tool_id,
                "name": "dummy.needs_int",
                "arguments": '{"n":"not_an_int"}',
            },
        )
        yield StreamEvent(type="done", data={})


class _NeedsIntTool(Tool):
    name = "dummy.needs_int"
    category = "test"
    description = "fails validation when n is not an integer"
    parameters = {
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
            },
        },
        "required": ["n"],
    }

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"n": args["n"]})


class _NoopTool(Tool):
    name = "dummy.noop"
    category = "test"
    description = "always succeeds"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):  # noqa: ANN001
        _ = args
        return ToolResult(ok=True, data={"ok": True})


class _FastLoopLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="dummy",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=8192,
            max_tokens=256,
        )
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self.calls += 1
        tool_id = f"noop_{self.calls}"
        yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "dummy.noop"})
        yield StreamEvent(
            type="tool_call_end",
            data={
                "id": tool_id,
                "name": "dummy.noop",
                "arguments": "{}",
            },
        )
        yield StreamEvent(type="done", data={})


class _ToolThenAnswerFastLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="dummy",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=8192,
            max_tokens=256,
        )
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self.calls += 1
        if self.calls == 1:
            tool_id = "noop_first"
            yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "dummy.noop"})
            yield StreamEvent(
                type="tool_call_end",
                data={
                    "id": tool_id,
                    "name": "dummy.noop",
                    "arguments": "{}",
                },
            )
            yield StreamEvent(type="done", data={})
            return
        yield StreamEvent(type="token", data={"text": "DONE_FAST"})
        yield StreamEvent(type="done", data={})


class _UsageHeavyAnthropicLLM:
    def __init__(self, prompt_tokens_per_call: int = 10_000) -> None:
        self.config = ModelConfig(
            name="anthropic",
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-sonnet",
            context_window=200_000,
            max_tokens=512,
        )
        self.prompt_tokens_per_call = int(prompt_tokens_per_call)
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self.calls += 1
        tool_id = f"noop_{self.calls}"
        yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "dummy.noop"})
        yield StreamEvent(
            type="tool_call_end",
            data={
                "id": tool_id,
                "name": "dummy.noop",
                "arguments": "{}",
            },
        )
        yield StreamEvent(
            type="usage",
            data={
                "usage": {
                    "prompt_tokens": self.prompt_tokens_per_call,
                    "completion_tokens": 20,
                    "total_tokens": self.prompt_tokens_per_call + 20,
                }
            },
        )
        yield StreamEvent(type="done", data={})


class _UsageHeavyOpenAICompatLLM:
    def __init__(self, prompt_tokens_per_call: int = 30_000) -> None:
        self.config = ModelConfig(
            name="openai",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=200_000,
            max_tokens=512,
        )
        self.prompt_tokens_per_call = int(prompt_tokens_per_call)
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self.calls += 1
        tool_id = f"needs_int_{self.calls}"
        yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "dummy.needs_int"})
        yield StreamEvent(
            type="tool_call_end",
            data={
                "id": tool_id,
                "name": "dummy.needs_int",
                "arguments": '{"n":"not_an_int"}',
            },
        )
        yield StreamEvent(
            type="usage",
            data={
                "usage": {
                    "prompt_tokens": self.prompt_tokens_per_call,
                    "completion_tokens": 20,
                    "total_tokens": self.prompt_tokens_per_call + 20,
                }
            },
        )
        yield StreamEvent(type="done", data={})


def test_agent_loop_stops_repeated_failing_tool_loop() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NeedsIntTool())
    llm = _AlwaysToolCallingLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "fix this repo issue in code",
            tools_policy="always",
            mode="auto",
            max_iterations=12,
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert errors
    assert any("prevent token waste" in str(e.data.get("error") or "").lower() for e in errors)

    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    assert int(done.data.get("iterations") or 0) < 12
    token_report = done.data.get("token_report") or {}
    run_budget = token_report.get("run_budget") or {}
    assert bool(run_budget.get("runaway_guard_triggered")) is True


def test_fast_mode_l4_uses_configured_iteration_budget() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=20,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _FastLoopLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "fix this repo issue in code",
            tools_policy="always",
            mode="fast",
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    assert int(done.data.get("iterations") or 0) == 20
    assert llm.calls == 20


def test_token_economy_budget_metadata_is_reported() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=20,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _FastLoopLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "fix this repo issue in code",
            tools_policy="always",
            mode="thinking",
            token_economy="cheap",
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None

    token_report = done.data.get("token_report") or {}
    token_economy = token_report.get("token_economy") or {}
    assert str(token_economy.get("applied") or "") == "cheap"
    run_budget = token_report.get("run_budget") or {}
    assert str(run_budget.get("token_economy") or "") == "cheap"
    assert int(run_budget.get("hard_context_budget") or 0) == 250_000


def test_fast_mode_allows_tool_then_answer_completion() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=10,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _ToolThenAnswerFastLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=3)

    async def run_once():
        events = []
        async for ev in agent.run(
            "run a quick command and summarize",
            tools_policy="always",
            mode="fast",
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    assert int(done.data.get("iterations") or 0) >= 2
    assert "DONE_FAST" in str(done.data.get("text") or "")


def test_provider_tpm_guard_blocks_before_429(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_HEADROOM", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT_ANTHROPIC", raising=False)
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=12,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _UsageHeavyAnthropicLLM(prompt_tokens_per_call=10_000)
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "continue running tools until done",
            tools_policy="always",
            mode="auto",
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert errors
    assert any("provider rate-limit failure" in str(e.data.get("error") or "").lower() for e in errors)

    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    token_report = done.data.get("token_report") or {}
    run_budget = token_report.get("run_budget") or {}
    assert bool(run_budget.get("runaway_guard_triggered")) is True
    assert int(run_budget.get("provider_tpm_limit") or 0) == 30_000
    assert int(run_budget.get("provider_tpm_budget") or 0) == 27_000
    assert llm.calls <= 2


def test_iteration_prompt_spend_guard_blocks_non_anthropic_high_spend_loops(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_HEADROOM", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT_OPENAI_COMPAT", raising=False)
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=12,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NeedsIntTool())
    llm = _UsageHeavyOpenAICompatLLM(prompt_tokens_per_call=30_000)
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "continue running tools until done",
            tools_policy="always",
            mode="auto",
            token_economy="optimal",
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert errors
    assert any("high prompt-token spend per iteration" in str(e.data.get("error") or "").lower() for e in errors)

    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    token_report = done.data.get("token_report") or {}
    run_budget = token_report.get("run_budget") or {}
    assert bool(run_budget.get("runaway_guard_triggered")) is True
    assert int(run_budget.get("max_iteration_prompt_spend") or 0) >= 30_000
    assert int(run_budget.get("iteration_prompt_warn_cap") or 0) > 0
    assert llm.calls <= 3
