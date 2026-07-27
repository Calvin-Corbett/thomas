import asyncio

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _WriteTool(Tool):
    name = "diff.create"
    category = "test"
    description = "fake write"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_str": {"type": "string"},
            "new_str": {"type": "string"},
        },
    }

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"path": str(args.get("path", ""))})


class _WriteThenAnswerLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._step = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        if self._step % 2 == 0:
            self._step += 1
            yield StreamEvent(type="tool_call_start", data={"id": f"t{self._step}", "name": "diff.create"})
            yield StreamEvent(
                type="tool_call_end",
                data={
                    "id": f"t{self._step}",
                    "name": "diff.create",
                    "arguments": '{"path":"thomas.toml","old_str":"a","new_str":"b"}',
                },
            )
            yield StreamEvent(type="done", data={})
            return

        self._step += 1
        yield StreamEvent(type="token", data={"text": "Applied changes."})
        yield StreamEvent(type="done", data={})


class _WriteThenNoopRetryLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self._calls += 1
        if self._calls == 1:
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "diff.create"})
            yield StreamEvent(
                type="tool_call_end",
                data={
                    "id": "t1",
                    "name": "diff.create",
                    "arguments": '{"path":"app.py","old_str":"a","new_str":"b"}',
                },
            )
            yield StreamEvent(type="done", data={})
            return

        yield StreamEvent(
            type="token",
            data={
                "text": (
                    "I could not verify the change.\n\n"
                    "GIVE_UP\n"
                    "what_failed: coding verification checks did not pass after editing app.py\n"
                    "what_was_tried: applied the diff.create edit and re-ran the required quality checks\n"
                    "why_blocked: no verification tooling is available in this environment to prove the fix\n"
                )
            },
        )
        yield StreamEvent(type="done", data={})


class _StaticTextLLM:
    def __init__(self, text: str) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._text = str(text or "")

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        yield StreamEvent(type="token", data={"text": self._text})
        yield StreamEvent(type="done", data={})


class _InvalidThenValidCodeLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = tools
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(type="token", data={"text": "for i in range(3):\nprint(i)"})
            yield StreamEvent(type="done", data={})
            return

        last_user = [m for m in messages if str(m.get("role")) == "user"][-1]
        content = str(last_user.get("content", "")).lower()
        assert "code-output requirements" in content
        yield StreamEvent(type="token", data={"text": "    for i in range(3):\n        print(i)"})
        yield StreamEvent(type="done", data={})


class _EntryPointThenValidCodeLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self.calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = tools
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(type="token", data={"text": "    pass"})
            yield StreamEvent(type="done", data={})
            return

        last_user = [m for m in messages if str(m.get("role")) == "user"][-1]
        assert "entry point" in str(last_user.get("content", "")).lower()
        yield StreamEvent(type="token", data={"text": "    return n + 1"})
        yield StreamEvent(type="done", data={})


def _run_once(prompt: str, *, llm=None, job_type=None, non_coder_profile: bool = False):
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_WriteTool())
    agent = AgentLoop(
        cfg,
        llm or _WriteThenAnswerLLM(),
        tools,
        conversation=[],
        non_coder_profile=bool(non_coder_profile),
        profile_type="non_coder" if non_coder_profile else "adaptive",
    )

    async def _collect():
        out = []
        async for ev in agent.run(prompt, tools_policy="always", job_type=job_type):
            out.append(ev)
        return out

    return asyncio.run(_collect())


def test_rules_of_road_report_is_attached_to_done_event() -> None:
    events = _run_once("hello there", llm=_StaticTextLLM("Hello."))
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert done
    token_report = done[-1].data.get("token_report", {})
    assert isinstance(token_report, dict)
    assert "rules_of_road" in token_report
    rules = token_report["rules_of_road"]
    assert isinstance(rules, dict)
    assert "passed" in rules


def test_rules_of_road_auto_retry_runs_then_structured_gate_blocks() -> None:
    # The configured remediation pass runs exactly once. If concrete validation still
    # fails, completion is blocked without interpreting the assistant's words.
    events = _run_once("fix configuration in thomas.toml")
    starts = [e for e in events if e.type == EventType.AGENT_START]
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    errs = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert len(starts) == 2  # initial pass + one auto-retry
    assert len(done) == 0
    assert len(errs) >= 1
    assert "Completion gate blocked AGENT_DONE" in str(errs[-1].data.get("error") or "")


def test_rules_of_road_retry_does_not_accept_give_up_prose() -> None:
    # The retry response contains the old GIVE_UP control words. They are plain
    # assistant text now and cannot override failed coding verification.
    events = _run_once(
        "fix bug in app.py",
        llm=_WriteThenNoopRetryLLM(),
        job_type="coding",
    )
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    starts = [e for e in events if e.type == EventType.AGENT_START]
    assert not done
    assert len(starts) == 2
    assert errors
    assert "Completion gate blocked AGENT_DONE" in str(errors[-1].data.get("error") or "")


def test_non_coder_profile_does_not_classify_workaround_prose() -> None:
    events = _run_once(
        "fix this issue all the way through",
        llm=_StaticTextLLM("I applied a temporary workaround for now. The issue is still failing."),
        job_type="coding",
        non_coder_profile=True,
    )
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    starts = [e for e in events if e.type == EventType.AGENT_START]
    assert len(done) == 1
    assert len(starts) == 1
    assert done[-1].data["text"].startswith("I applied a temporary workaround")


def test_non_coder_profile_does_not_create_a_hidden_prose_gate() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        quality=QualityConfig(enabled=False, enforce=False, max_auto_retries=0),
    )
    tools = ToolRegistry()
    agent = AgentLoop(
        cfg,
        _StaticTextLLM("I used a workaround for now. The issue is still failing."),
        tools,
        conversation=[],
        non_coder_profile=True,
        profile_type="non_coder",
    )

    async def _collect():
        out = []
        async for ev in agent.run("fix this bug fully", tools_policy="always", job_type="coding"):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(done) == 1
    assert done[-1].data["text"].startswith("I used a workaround")


def test_code_output_guard_retries_invalid_python_then_finishes() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        quality=QualityConfig(enabled=False, enforce=False, max_auto_retries=0),
    )
    llm = _InvalidThenValidCodeLLM()
    agent = AgentLoop(
        cfg,
        llm,
        ToolRegistry(),
        conversation=[],
    )
    prompt = (
        "Return ONLY the Python code continuation. No explanations.\n"
        "---PROMPT START---\n"
        "def demo():\n"
        "---PROMPT END---\n"
    )

    async def _collect():
        out = []
        async for ev in agent.run(prompt, tools_policy="never", job_type="benchmark", max_iterations=4):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    errs = [e for e in events if e.type == EventType.AGENT_ERROR]
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(errs) == 0
    assert len(done) == 1
    assert llm.calls >= 2
    continuity = (done[-1].data.get("token_report") or {}).get("continuity") or {}
    assert int(continuity.get("code_output_guard_reprompts") or 0) >= 1
    guard_issue = str(continuity.get("code_output_guard_last_issue") or "").lower()
    assert "error" in guard_issue
    text = str(done[-1].data.get("text") or "")
    assert "    print(i)" in text
    compile("def demo():\n" + text, "<code_guard>", "exec")


def test_code_output_guard_retries_non_trivial_entry_point_continuation() -> None:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        quality=QualityConfig(enabled=False, enforce=False, max_auto_retries=0),
    )
    llm = _EntryPointThenValidCodeLLM()
    agent = AgentLoop(
        cfg,
        llm,
        ToolRegistry(),
        conversation=[],
    )
    prompt = (
        "Return ONLY the Python code continuation. No explanations.\n"
        "Entry point: increment\n"
        "---PROMPT START---\n"
        "def increment(n):\n"
        '    """Return n + 1."""\n'
        "---PROMPT END---\n"
    )

    async def _collect():
        out = []
        async for ev in agent.run(prompt, tools_policy="never", job_type="benchmark", max_iterations=4):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    errs = [e for e in events if e.type == EventType.AGENT_ERROR]
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(errs) == 0
    assert len(done) == 1
    assert llm.calls >= 2
    continuity = (done[-1].data.get("token_report") or {}).get("continuity") or {}
    assert int(continuity.get("code_output_guard_reprompts") or 0) >= 1
    assert "entry point 'increment'" in str(continuity.get("code_output_guard_last_issue") or "").lower()
    text = str(done[-1].data.get("text") or "")
    assert "    return n + 1" in text
    compile('def increment(n):\n    """Return n + 1."""\n' + text, "<entrypoint_guard>", "exec")
