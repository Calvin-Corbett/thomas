"""CAP-004 completion gate: block done on failed validation without a diagnosed give-up."""

import asyncio

from thomas.agent.completion_gate import (
    GATE_ALLOW,
    GATE_BLOCK,
    GATE_DEMAND_GIVE_UP,
    GATE_GIVE_UP,
    GIVE_UP_MARKER,
    MIN_GIVE_UP_FIELD_CHARS,
    build_give_up_demand_prompt,
    evaluate_completion_gate,
    parse_give_up,
)
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

_VALID_GIVE_UP = (
    "I cannot finish this task.\n"
    "\n"
    "GIVE_UP\n"
    "what_failed: the required coding verification checks never passed\n"
    "what_was_tried: edited app.py twice and re-ran every required quality check\n"
    "why_blocked: the sandbox has no test runner so the fix cannot be proven\n"
)


# -- parse_give_up ---------------------------------------------


def test_parse_give_up_accepts_complete_diagnosis() -> None:
    diagnosis = parse_give_up(_VALID_GIVE_UP)
    assert diagnosis is not None
    assert "verification checks" in diagnosis.what_failed
    assert "edited app.py" in diagnosis.what_was_tried
    assert "no test runner" in diagnosis.why_blocked


def test_parse_give_up_rejects_missing_field() -> None:
    text = (
        "GIVE_UP\n"
        "what_failed: the required coding verification checks never passed\n"
        "what_was_tried: edited app.py twice and re-ran every required quality check\n"
    )
    assert parse_give_up(text) is None


def test_parse_give_up_rejects_short_diagnosis_text() -> None:
    text = "GIVE_UP\nwhat_failed: tests\nwhat_was_tried: stuff\nwhy_blocked: dunno\n"
    assert parse_give_up(text) is None


def test_parse_give_up_requires_marker_on_its_own_line() -> None:
    text = _VALID_GIVE_UP.replace("\nGIVE_UP\n", "\nI think I should GIVE_UP here\n")
    assert parse_give_up(text) is None


def test_parse_give_up_joins_multiline_field_values() -> None:
    text = (
        "GIVE_UP\n"
        "what_failed: the required coding\n"
        "verification checks never passed\n"
        "what_was_tried: edited app.py twice and re-ran every required quality check\n"
        "why_blocked: the sandbox has no test runner so the fix cannot be proven\n"
    )
    diagnosis = parse_give_up(text)
    assert diagnosis is not None
    assert diagnosis.what_failed == "the required coding verification checks never passed"


def test_parse_give_up_ignores_plain_text_without_marker() -> None:
    assert parse_give_up("All done, everything passed.") is None
    assert parse_give_up("") is None


# -- evaluate_completion_gate ----------------------------------


def test_gate_allows_when_validation_passed() -> None:
    decision = evaluate_completion_gate(
        validation_passed=True,
        response_text="done",
        gate_active=True,
        attempt=0,
        max_retries=1,
    )
    assert decision.outcome == GATE_ALLOW
    assert decision.reason == "validation_passed"


def test_gate_allows_when_not_enforced() -> None:
    decision = evaluate_completion_gate(
        validation_passed=False,
        response_text="done",
        gate_active=False,
        attempt=5,
        max_retries=1,
    )
    assert decision.outcome == GATE_ALLOW
    assert decision.reason == "gate_not_enforced"


def test_gate_accepts_explicit_diagnosed_give_up() -> None:
    decision = evaluate_completion_gate(
        validation_passed=False,
        response_text=_VALID_GIVE_UP,
        gate_active=True,
        attempt=2,
        max_retries=1,
    )
    assert decision.outcome == GATE_GIVE_UP
    assert decision.diagnosis is not None
    payload = decision.to_payload()
    assert payload["diagnosis"]["why_blocked"].startswith("the sandbox")


def test_gate_demands_give_up_before_blocking() -> None:
    decision = evaluate_completion_gate(
        validation_passed=False,
        response_text="Done.",
        gate_active=True,
        attempt=1,
        max_retries=1,
    )
    assert decision.outcome == GATE_DEMAND_GIVE_UP


def test_gate_blocks_bare_done_after_demand_budget_exhausted() -> None:
    decision = evaluate_completion_gate(
        validation_passed=False,
        response_text="Done.",
        gate_active=True,
        attempt=2,
        max_retries=1,
    )
    assert decision.outcome == GATE_BLOCK
    assert "diagnosed give-up" in decision.reason


def test_demand_prompt_names_marker_fields_and_failures() -> None:
    report = {
        "passed": False,
        "checks": [
            {"id": "coding_verification", "title": "Verify", "detail": "no verify", "required": True, "passed": False},
            {"id": "optional_thing", "title": "Opt", "detail": "meh", "required": False, "passed": False},
        ],
    }
    prompt = build_give_up_demand_prompt(report)
    assert GIVE_UP_MARKER in prompt
    for field in ("what_failed:", "what_was_tried:", "why_blocked:"):
        assert field in prompt
    assert str(MIN_GIVE_UP_FIELD_CHARS) in prompt
    assert "Verify: no verify" in prompt
    assert "Opt: meh" not in prompt


# -- loop integration ------------------------------------------


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


class _WriteThenScriptedLLM:
    """First call writes app.py; later calls return scripted texts in order."""

    def __init__(self, texts: list[str]) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._texts = list(texts)
        self._calls = 0
        self.user_contents: list[str] = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = tools
        self._calls += 1
        users = [m for m in messages if str(m.get("role")) == "user"]
        if users:
            self.user_contents.append(str(users[-1].get("content", "")))
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
        text = self._texts.pop(0) if self._texts else "Done."
        yield StreamEvent(type="token", data={"text": text})
        yield StreamEvent(type="done", data={})


def _run_coding(llm) -> list:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_WriteTool())
    agent = AgentLoop(cfg, llm, tools, conversation=[])

    async def _collect():
        out = []
        async for ev in agent.run("fix bug in app.py", tools_policy="always", job_type="coding"):
            out.append(ev)
        return out

    return asyncio.run(_collect())


def test_loop_blocks_completion_on_failed_validation_without_give_up() -> None:
    # Acceptance line: completion is blocked on failed validation unless the
    # run returns an explicit diagnosed give-up. Here it never gives up.
    llm = _WriteThenScriptedLLM(["Applied the fix.", "Done.", "All finished."])
    events = _run_coding(llm)
    starts = [e for e in events if e.type == EventType.AGENT_START]
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    errs = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert len(done) == 0
    assert len(starts) == 3  # initial + quality retry + give-up demand pass
    assert len(errs) >= 1
    err_text = str(errs[-1].data.get("error") or "")
    assert "Completion gate blocked AGENT_DONE" in err_text
    assert "diagnosed give-up" in err_text


def test_loop_demand_pass_prompt_asks_for_fix_or_structured_give_up() -> None:
    llm = _WriteThenScriptedLLM(["Applied the fix.", "Done.", "All finished."])
    _run_coding(llm)
    demand_prompts = [c for c in llm.user_contents if GIVE_UP_MARKER in c and "Completion gate" in c]
    assert demand_prompts
    assert "what_failed:" in demand_prompts[-1]


def test_loop_accepts_diagnosed_give_up_and_marks_done_distinctly() -> None:
    llm = _WriteThenScriptedLLM(["Applied the fix.", _VALID_GIVE_UP])
    events = _run_coding(llm)
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    errs = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert len(errs) == 0
    assert len(done) == 1
    assert done[-1].data.get("gave_up") is True
    diagnosis = done[-1].data.get("give_up_diagnosis") or {}
    assert set(diagnosis) == {"what_failed", "what_was_tried", "why_blocked"}
    gate = (done[-1].data.get("token_report") or {}).get("completion_gate") or {}
    assert gate.get("outcome") == GATE_GIVE_UP


class _TextOnlyLLM:
    def __init__(self, text: str) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._text = text

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        yield StreamEvent(type="token", data={"text": self._text})
        yield StreamEvent(type="done", data={})


def test_loop_success_done_carries_no_give_up_flag() -> None:
    # A run whose validation passes completes normally and is distinguishable
    # from a diagnosed give-up: no gave_up flag, gate outcome "allow".
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(cfg, _TextOnlyLLM("Hi! How can I help?"), ToolRegistry(), conversation=[])

    async def _collect():
        out = []
        async for ev in agent.run("hello there", tools_policy="never"):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(done) == 1
    assert "gave_up" not in done[-1].data
    gate = (done[-1].data.get("token_report") or {}).get("completion_gate") or {}
    assert gate.get("outcome") == GATE_ALLOW
