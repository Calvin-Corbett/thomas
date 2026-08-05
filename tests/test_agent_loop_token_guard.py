import asyncio

from thomas.agent.loop import AgentLoop
from thomas.agent.loop_streaming import build_token_report
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import LLMError, StreamEvent
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


class _UsageHeavyThenAnswerLLM(_UsageHeavyOpenAICompatLLM):
    async def stream_chat(self, messages, tools):  # noqa: ANN001
        if self.calls:
            self.calls += 1
            yield StreamEvent(type="token", data={"text": "HEAVY_RUN_DONE"})
            yield StreamEvent(type="done", data={})
            return
        async for event in super().stream_chat(messages, tools):
            yield event


class _RateLimitedThenAnswerLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="rate-limited",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=8_000,
            max_tokens=256,
        )
        self.calls = 0

    def _rate_limit_remaining(self, _config) -> float:  # noqa: ANN001
        return 0.0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self.calls += 1
        if self.calls == 1:
            raise LLMError("HTTP 429 rate limited", status=429, retryable=True)
        yield StreamEvent(type="token", data={"text": "RATE_LIMIT_RESUMED"})
        yield StreamEvent(type="done", data={})


class _ContextPressureThenAnswerLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="openai",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=8_000,
            max_tokens=256,
        )
        self.calls = 0
        self.message_snapshots: list[list[dict]] = []

    async def chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        return {"text": "- Preserved the earlier decisions and unresolved work."}

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = tools
        self.calls += 1
        self.message_snapshots.append([dict(message) for message in messages])
        if self.calls <= 5:
            tool_id = f"pressure_{self.calls}"
            yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "dummy.noop"})
            yield StreamEvent(
                type="tool_call_end",
                data={"id": tool_id, "name": "dummy.noop", "arguments": "{}"},
            )
        else:
            yield StreamEvent(type="token", data={"text": "CONTEXT_PRESSURE_RUN_DONE"})
        yield StreamEvent(
            type="usage",
            data={
                "usage": {
                    "prompt_tokens": 20_000,
                    "completion_tokens": 20,
                    "total_tokens": 20_020,
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
    assert done is None
    assert llm.calls < 12


def test_optimal_effort_exhaustion_is_incomplete_not_done() -> None:
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
    assert done is None
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    # 15 was the old "optimal" ration. Passes are no longer rationed, so exhaustion
    # now only happens at the runaway guard -- far above any real task. What this
    # test still protects is the important half: when the guard DOES fire, the run
    # must not claim it finished.
    assert any("pass budget exhausted" in str(e.data.get("error") or "").lower() for e in errors)


def test_token_economy_budget_metadata_is_reported() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=20,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _ToolThenAnswerFastLLM()
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
    assert run_budget.get("hard_context_budget") is None
    assert run_budget.get("iteration_prompt_hard_cap") is None


def test_missing_provider_tpm_limit_disables_local_throttle(monkeypatch) -> None:  # noqa: ANN001
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=10,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _ToolThenAnswerFastLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)
    monkeypatch.setattr(agent, "_provider_tpm_limit", lambda: None)

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
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert not any("NoneType" in str(e.data.get("error") or "") for e in errors)
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    run_budget = (done.data.get("token_report") or {}).get("run_budget") or {}
    assert run_budget.get("provider_tpm_limit") is None
    assert run_budget.get("provider_tpm_budget") is None


def test_missing_provider_tpm_headroom_uses_safe_default(monkeypatch) -> None:  # noqa: ANN001
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=10,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _ToolThenAnswerFastLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)
    monkeypatch.setattr(agent, "_provider_tpm_limit", lambda: 30_000)
    monkeypatch.setattr(agent, "_provider_tpm_headroom", lambda: None)

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
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert not any("NoneType" in str(e.data.get("error") or "") for e in errors)
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    run_budget = (done.data.get("token_report") or {}).get("run_budget") or {}
    assert int(run_budget.get("provider_tpm_limit") or 0) == 30_000
    assert int(run_budget.get("provider_tpm_budget") or 0) == 27_000


def test_token_report_tolerates_missing_context_window() -> None:
    class AgentStub:
        _context_window = None

    report = build_token_report(
        AgentStub(),  # type: ignore[arg-type]
        prompt_text="summarize",
        usage_obj={"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
        mode="auto",
        iterations=1,
        peak_context_tokens=1000,
        avg_context_tokens=1000,
        memory_tokens=0,
        tool_chars_total=0,
        tool_chars_kept=0,
    )

    assert report["total_tokens"] == 1100
    assert not any(flag.get("kind") == "context_pressure" for flag in report["flags"])


def test_max_effort_tool_loop_has_no_hard_context_budget_crash(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_HEADROOM", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT_OPENAI_COMPAT", raising=False)
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=4,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _UsageHeavyThenAnswerLLM(prompt_tokens_per_call=1_000)
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "keep using the tool for a few passes",
            tools_policy="always",
            mode="auto",
            token_economy="max",
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert not any("NoneType" in str(e.data.get("error") or "") for e in errors)
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    run_budget = (done.data.get("token_report") or {}).get("run_budget") or {}
    assert run_budget.get("hard_context_budget") is None


def test_long_multi_pass_run_compacts_context_without_raw_token_abort(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_HEADROOM", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT_OPENAI", raising=False)
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=8,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _ContextPressureThenAnswerLLM()
    seeded_conversation = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"Earlier project decision {index}: " + ("context " * 115),
        }
        for index in range(40)
    ]
    agent = AgentLoop(cfg, llm, tools, conversation=seeded_conversation, autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "keep using the tool across several passes, preserve context, and finish",
            tools_policy="always",
            mode="auto",
            token_economy="max",
            max_iterations=8,
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())

    assert llm.calls == 6
    assert agent._last_compaction_result is not None
    assert agent._last_compaction_result.tokens_saved > 0
    assert any("[context-summary]" in str(message.get("content") or "") for message in agent._conversation)
    assert any(
        "earlier messages trimmed to fit context window" in str(message.get("content") or "")
        for message in llm.message_snapshots[1]
    )
    errors = [event for event in events if event.type == EventType.AGENT_ERROR]
    assert not errors
    done = next((event for event in events if event.type == EventType.AGENT_DONE), None)
    assert done is not None
    assert done.data.get("text") == "CONTEXT_PRESSURE_RUN_DONE"
    run_budget = (done.data.get("token_report") or {}).get("run_budget") or {}
    assert run_budget.get("hard_context_budget") is None
    assert run_budget.get("iteration_prompt_hard_cap") is None


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


def test_provider_tpm_guess_is_disabled_without_explicit_configuration(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_HEADROOM", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT_ANTHROPIC", raising=False)
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=12,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    agent = AgentLoop(cfg, _UsageHeavyAnthropicLLM(), ToolRegistry(), conversation=[], autonomy_level=4)

    assert agent._provider_tpm_limit() == 0


def test_explicit_local_tpm_estimate_never_terminates_a_large_request(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_PROVIDER_TPM_LIMIT", "1000")
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=4,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    llm = _ToolThenAnswerFastLLM()
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for event in agent.run(
            "run the tool and then answer with enough detail to exceed the local estimate " + ("context " * 1_500),
            tools_policy="always",
            max_iterations=4,
        ):
            events.append(event)
        return events

    events = asyncio.run(run_once())

    assert not [event for event in events if event.type == EventType.AGENT_ERROR]
    assert any("deferring enforcement to the provider" in str(event.data.get("message") or "") for event in events)
    assert next(event for event in events if event.type == EventType.AGENT_DONE).data.get("text") == "DONE_FAST"


def test_real_provider_429_resumes_in_the_same_task(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT", raising=False)
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=3,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    llm = _RateLimitedThenAnswerLLM()
    agent = AgentLoop(cfg, llm, ToolRegistry(), conversation=[], autonomy_level=4)

    async def run_once():
        events = []
        async for ev in agent.run(
            "answer after the provider permits the request",
            tools_policy="never",
            mode="auto",
            max_iterations=3,
        ):
            events.append(ev)
        return events

    events = asyncio.run(run_once())
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert not errors
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    assert done.data.get("text") == "RATE_LIMIT_RESUMED"
    assert llm.calls == 2
    assert any("rate limit cleared" in str(e.data.get("message") or "").lower() for e in events)


def test_high_iteration_prompt_spend_warns_without_stopping(monkeypatch) -> None:  # noqa: ANN001
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
    llm = _UsageHeavyThenAnswerLLM(prompt_tokens_per_call=30_000)
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
    done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
    assert done is not None
    token_report = done.data.get("token_report") or {}
    run_budget = token_report.get("run_budget") or {}
    assert bool(run_budget.get("runaway_guard_triggered")) is False
    assert int(run_budget.get("max_iteration_prompt_spend") or 0) >= 30_000
    assert int(run_budget.get("iteration_prompt_warn_cap") or 0) > 0
    assert run_budget.get("iteration_prompt_hard_cap") is None
    assert any(flag.get("kind") == "iteration_prompt_spend" for flag in token_report.get("flags") or [])
    assert llm.calls == 2
