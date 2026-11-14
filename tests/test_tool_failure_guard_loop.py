"""The guard end to end through the real AgentLoop.

Held apart from the unit tests because it needs the guard block in
thomas/agent/loop_execution.py, which lands with codex's batch (2026-09-05).
"""

from __future__ import annotations

# ── End to end through the real AgentLoop (regression lock for the wiring;
#    the RED/GREEN cycles above and in test_agent_loop_tool_exec cover the parts) ──
import asyncio
import json
from pathlib import Path

from thomas.agent import loop_completion
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _GitStatusOutsideRepo(Tool):
    name = "git.status"
    category = "git"
    description = "always fails the same way"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, args):  # noqa: ANN001, ARG002
        self.calls += 1
        return ToolResult(ok=False, error="fatal: not a git repository")


class _RepeatingLLM:
    """Calls git.status ``repeats`` times, then says done. Records tool results it was shown."""

    def __init__(self, repeats: int) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._left = repeats
        self.tool_results: list[str] = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001, ARG002
        for m in messages:
            if m.get("role") == "tool":
                self.tool_results.append(str(m.get("content", "")))
        if self._left > 0:
            self._left -= 1
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "git.status"})
            yield StreamEvent(
                type="tool_call_end", data={"id": "t1", "name": "git.status", "arguments": json.dumps({})}
            )
        else:
            yield StreamEvent(type="token", data={"text": "Done without git."})
        yield StreamEvent(type="done", data={})

    async def chat(self, messages):  # noqa: ANN001, ARG002
        return {"text": "", "tool_calls": [], "usage": None}


def _drive(repeats: int, tmp_path: Path, monkeypatch) -> tuple[list, _GitStatusOutsideRepo, _RepeatingLLM]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "0")
    monkeypatch.setattr(
        loop_completion, "evaluate_rules", lambda **kwargs: {"passed": True, "job_type": "coding", "checks": []}
    )
    tool = _GitStatusOutsideRepo()
    llm = _RepeatingLLM(repeats)
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(tool)
    agent = AgentLoop(cfg, llm, tools, conversation=[])

    async def _collect():
        out = []
        async for event in agent.run("Check the repo state, then say done.", tools_policy="always"):
            out.append(event)
        return out

    return asyncio.run(_collect()), tool, llm


def test_a_run_survives_three_identical_failures_and_finishes(tmp_path: Path, monkeypatch) -> None:
    events, tool, llm = _drive(4, tmp_path, monkeypatch)

    texts = " ".join(str(e.data.get("text") or e.data.get("message") or e.data.get("error") or "") for e in events)
    assert "Tool loop stability issue" not in texts
    assert "Done without git." in texts
    assert tool.calls == 3
    assert any("disabled" in r for r in llm.tool_results)


def test_a_model_that_keeps_hammering_a_disabled_call_is_stopped_with_the_reason(tmp_path: Path, monkeypatch) -> None:
    events, tool, _llm = _drive(12, tmp_path, monkeypatch)

    texts = " ".join(str(e.data.get("text") or e.data.get("message") or e.data.get("error") or "") for e in events)
    assert "Tool loop stability issue" in texts
    assert "git.status" in texts
    assert tool.calls == 3
