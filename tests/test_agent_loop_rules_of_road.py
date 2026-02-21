import asyncio

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
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
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
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
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
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

        yield StreamEvent(type="token", data={"text": "Done."})
        yield StreamEvent(type="done", data={})


def _run_once(prompt: str, *, llm=None, job_type=None):
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_WriteTool())
    agent = AgentLoop(cfg, llm or _WriteThenAnswerLLM(), tools, conversation=[])

    async def _collect():
        out = []
        async for ev in agent.run(prompt, tools_policy="always", job_type=job_type):
            out.append(ev)
        return out

    return asyncio.run(_collect())


def test_rules_of_road_report_is_attached_to_done_event() -> None:
    events = _run_once("hello there")
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert done
    token_report = done[-1].data.get("token_report", {})
    assert isinstance(token_report, dict)
    assert "rules_of_road" in token_report
    rules = token_report["rules_of_road"]
    assert isinstance(rules, dict)
    assert "passed" in rules


def test_rules_of_road_auto_retry_runs_when_required_checks_fail() -> None:
    events = _run_once("fix configuration in thomas.toml")
    starts = [e for e in events if e.type == EventType.AGENT_START]
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(starts) == 2  # initial pass + one auto-retry
    assert len(done) == 1
    rules = done[-1].data.get("token_report", {}).get("rules_of_road", {})
    assert rules.get("attempt") == 1
    assert rules.get("passed") is False


def test_rules_of_road_retry_carries_failed_write_requirements_forward() -> None:
    events = _run_once(
        "fix bug in app.py",
        llm=_WriteThenNoopRetryLLM(),
        job_type="coding",
    )
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(done) == 1
    rules = done[-1].data.get("token_report", {}).get("rules_of_road", {})
    assert rules.get("attempt") == 1
    assert rules.get("passed") is False
    failed_ids = {
        c.get("id")
        for c in list(rules.get("checks") or [])
        if c.get("required") and not c.get("passed")
    }
    assert "coding_verification" in failed_ids
