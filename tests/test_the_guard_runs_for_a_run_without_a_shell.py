"""A run that cannot run commands is not told to run one (2026-09-06).

A Build run on Thomas's own checkout is edit-only: its toolset has no
``shell.exec``. The rules of the road still required "Run `python
scripts/forge/gates/monolith_guard.py` after code mutations", so the run
finished its edits, then repeated for an hour that it was blocked because it
had no shell, until it was stopped by hand. A required command in a run that
cannot run commands is a branch whose other outcome is impossible.

The harness can run commands even when the model cannot. When the toolset has
no shell and code was written, the loop runs the guard itself and hands the
check a receipt; the check judges the receipt the way it would judge the
model's own command, and a failing guard still fails the check with its
findings. A run that does have a shell is still expected to run the guard
itself, so nothing is waived for it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.agent import loop_completion
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.core.rules_of_road import evaluate_rules
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

WRITE = {"name": "diff.create", "ok": True, "command": "", "path": "thomas/server/app.py"}
VERIFY = {"name": "fs.read_file", "ok": True, "command": "", "path": "thomas/server/app.py"}


def _guard_check(report: dict) -> dict:
    rows = [c for c in report.get("checks", []) if c.get("id") == "coding_monolith_guard"]
    assert rows, report
    return rows[0]


def _evaluate(**extra) -> dict:
    return evaluate_rules(
        route_path="coding_task",
        prompt_text="update the function in app.py",
        response_text="Done.",
        tool_events=[WRITE, VERIFY],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=False,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        attempt=0,
        **extra,
    )


def test_a_passing_harness_receipt_satisfies_the_guard_check() -> None:
    check = _guard_check(
        _evaluate(monolith_guard_receipt={"ok": True, "detail": "Monolith guard: PASS", "by": "harness"})
    )
    assert check["passed"] is True
    assert "harness" in check["detail"].lower() and "PASS" in check["detail"]


def test_a_failing_harness_receipt_fails_the_check_with_the_guard_findings() -> None:
    check = _guard_check(
        _evaluate(monolith_guard_receipt={"ok": False, "detail": "FAIL: thomas/big.py 3001 lines", "by": "harness"})
    )
    assert check["passed"] is False
    assert "3001 lines" in check["detail"]


def test_without_a_receipt_the_check_still_asks_the_model_to_run_the_guard() -> None:
    check = _guard_check(_evaluate())
    assert check["passed"] is False
    assert "monolith_guard.py" in check["detail"]


class _WriteTool(Tool):
    name = "diff.create"
    category = "test"
    description = "fake write"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"path": str(args.get("path", ""))})


class _ReadTool(Tool):
    name = "fs.read_file"
    category = "test"
    description = "fake read"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data="def app():\n    return 1\n")


class _ShellTool(Tool):
    name = "shell.exec"
    category = "test"
    description = "fake shell"
    parameters = {"type": "object", "properties": {"command": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data="ok")


class _WriteReadThenAnswerLLM:
    """Edits, reads the edit back (the verification an edit-only run can do), answers."""

    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self._calls += 1
        step = {1: "diff.create", 2: "fs.read_file"}.get(self._calls)
        if step:
            yield StreamEvent(type="tool_call_start", data={"id": f"t{self._calls}", "name": step})
            yield StreamEvent(
                type="tool_call_end",
                data={"id": f"t{self._calls}", "name": step, "arguments": '{"path":"thomas/server/app.py"}'},
            )
            yield StreamEvent(type="done", data={})
            return
        yield StreamEvent(type="token", data={"text": "Applied changes."})
        yield StreamEvent(type="done", data={})


def _run(with_shell: bool) -> list:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_WriteTool())
    tools.register(_ReadTool())
    if with_shell:
        tools.register(_ShellTool())
    agent = AgentLoop(cfg, _WriteReadThenAnswerLLM(), tools, conversation=[])

    async def _collect():
        return [ev async for ev in agent.run("fix bug in app.py", tools_policy="always", job_type="coding")]

    return asyncio.run(_collect())


def _rules_reports(events: list) -> list[dict]:
    out = []
    for ev in events:
        if ev.type in (EventType.AGENT_DONE, EventType.AGENT_ERROR):
            report = (ev.data.get("token_report") or {}).get("rules_of_road")
            if isinstance(report, dict):
                out.append(report)
    return out


def test_the_loop_runs_the_guard_for_a_run_that_has_no_shell(monkeypatch) -> None:
    calls: list[Path] = []

    def fake_guard(repo_root: Path, **_kw) -> dict:
        calls.append(Path(repo_root))
        return {"ok": True, "detail": "Monolith guard: PASS", "by": "harness"}

    monkeypatch.setattr(loop_completion, "run_monolith_guard", fake_guard)
    events = _run(with_shell=False)
    assert calls and calls[0] == Path.cwd()
    reports = _rules_reports(events)
    assert reports, [e.type for e in events]
    check = _guard_check(reports[-1])
    assert check["passed"] is True
    assert "harness" in check["detail"].lower()


def test_a_run_with_a_shell_must_run_the_guard_itself(monkeypatch) -> None:
    calls: list[Path] = []

    def fake_guard(repo_root: Path, **_kw) -> dict:
        calls.append(Path(repo_root))
        return {"ok": True, "detail": "Monolith guard: PASS", "by": "harness"}

    monkeypatch.setattr(loop_completion, "run_monolith_guard", fake_guard)
    events = _run(with_shell=True)
    assert calls == []
    # The run had a shell and never ran the guard, so nothing is waived: the
    # completion gate blocks it instead of the harness covering for it.
    assert not [e for e in events if e.type == EventType.AGENT_DONE]
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert errors and "Completion gate blocked AGENT_DONE" in str(errors[-1].data.get("error") or "")
