"""Regressions for repeated test failures across real AgentLoop file edits."""

import asyncio
import json
from pathlib import Path

import pytest

from thomas.agent import loop_completion
from thomas.agent.loop import AgentLoop
from thomas.agent.loop_execution import _failed_tool_signature, _record_failed_tool
from thomas.agent.tool_failure_guard import ToolFailureGuard
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _ScriptTool(Tool):
    category = "code"
    description = "scripted tool for loop regression"
    parameters = {"type": "object", "properties": {"command": {"type": "string"}, "path": {"type": "string"}}}

    def __init__(self, name, responses):
        self.name = name
        self.responses = list(responses)
        self.calls = 0

    async def execute(self, args):  # noqa: ANN001, ARG002
        self.calls += 1
        response = self.responses.pop(0) if self.responses else (True, "saved")
        return ToolResult(
            ok=response[0], data=response[1] if response[0] else None, error=None if response[0] else response[1]
        )


class _ScriptLLM:
    def __init__(self, calls):
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self.calls = calls
        self.results = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001, ARG002
        self.results.extend(str(m.get("content", "")) for m in messages if m.get("role") == "tool")
        if self.calls:
            name, args = self.calls.pop(0)
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": name})
            yield StreamEvent(type="tool_call_end", data={"id": "t1", "name": name, "arguments": json.dumps(args)})
        else:
            yield StreamEvent(type="token", data={"text": "Done after tests."})
        yield StreamEvent(type="done", data={})

    async def chat(self, messages):  # noqa: ANN001, ARG002
        return {"text": "", "tool_calls": [], "usage": None}


def _drive(tmp_path, monkeypatch, calls, tools):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "0")
    monkeypatch.setattr(
        loop_completion, "evaluate_rules", lambda **kwargs: {"passed": True, "job_type": "coding", "checks": []}
    )
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    llm = _ScriptLLM(list(calls))
    agent = AgentLoop(cfg, llm, registry, conversation=[])

    async def collect():
        return [event async for event in agent.run("Fix the tests, then say done.", tools_policy="always")]

    events = asyncio.run(collect())
    text = " ".join(
        str(event.data.get("text") or event.data.get("message") or event.data.get("error") or "") for event in events
    )
    return text, llm


@pytest.mark.parametrize("edits", [True, False])
def test_three_long_failures_with_or_without_edits(tmp_path: Path, monkeypatch, edits):
    output = "x" * 600
    test_tool = _ScriptTool("shell.exec", [(False, output)] * 3)
    edit_tool = _ScriptTool("diff.create", [(True, "applied")] * 2)
    command = ("shell.exec", {"command": "pytest -q"})
    edit = ("diff.create", {"file": str(tmp_path / "sample.py"), "old_str": "a", "new_str": "b"})
    calls = [command, edit, command, edit, command] if edits else [command] * 4
    text, llm = _drive(tmp_path, monkeypatch, calls, [test_tool, edit_tool])
    assert "Tool loop stability issue" not in text
    assert "Done after tests." in text
    assert test_tool.calls == 3
    if edits:
        assert edit_tool.calls == 2
        assert not any("disabled" in result for result in llm.results)
    else:
        assert any("disabled" in result for result in llm.results)


def test_full_output_and_digit_normalization():
    assert _failed_tool_signature("shell.exec", {"command": "pytest"}, "x" * 600 + "A") != _failed_tool_signature(
        "shell.exec", {"command": "pytest"}, "x" * 600 + "B"
    )
    assert _failed_tool_signature("shell.exec", {"command": "pytest"}, "ERROR 123 in 4.5s") == (
        _failed_tool_signature("shell.exec", {"command": "pytest"}, " error 789 in 6.8S ")
    )
    counts = {}
    assert _record_failed_tool(counts, "shell.exec", {"command": "pytest"}, "x" * 600 + "A") == 1
    assert _record_failed_tool(counts, "shell.exec", {"command": "pytest"}, "x" * 600 + "B") == 1
    assert _record_failed_tool(counts, "shell.exec", {"command": "pytest"}, "ERROR 123") == 1
    assert _record_failed_tool(counts, "shell.exec", {"command": "pytest"}, "error 456") == 2


def test_write_lifts_disabled_call_and_resets_both_counters(tmp_path: Path, monkeypatch):
    output = "z" * 600
    command = ("shell.exec", {"command": "pytest -q"})
    write = ("fs.write_file", {"path": str(tmp_path / "sample.py"), "content": "fixed"})
    test_tool = _ScriptTool("shell.exec", [(False, output)] * 6)
    write_tool = _ScriptTool("fs.write_file", [(True, "saved")])
    calls = [command] * 4 + [write] + [command] * 3
    text, llm = _drive(tmp_path, monkeypatch, calls, [test_tool, write_tool])
    assert "Tool loop stability issue" not in text
    assert "Done after tests." in text
    assert test_tool.calls == 6
    assert write_tool.calls == 1
    assert any("disabled" in result for result in llm.results)


def test_failed_edit_read_and_nonwriting_shell_do_not_reset_counts(tmp_path: Path, monkeypatch):
    output = "z" * 600
    command = ("shell.exec", {"command": "pytest -q"})
    failed_edit = ("diff.create", {"file": str(tmp_path / "sample.py"), "old_str": "a", "new_str": "b"})
    read = ("fs.read_file", {"path": str(tmp_path / "sample.py")})
    inspect = ("shell.exec", {"command": "dir"})
    test_tool = _ScriptTool("shell.exec", [(False, output), (True, "listing"), (False, output), (False, output)])
    edit_tool = _ScriptTool("diff.create", [(False, "not applied")])
    read_tool = _ScriptTool("fs.read_file", [(True, "content")])
    text, llm = _drive(
        tmp_path,
        monkeypatch,
        [command, failed_edit, read, inspect, command, command, command],
        [test_tool, edit_tool, read_tool],
    )
    assert "Tool loop stability issue" not in text
    assert "Done after tests." in text
    assert test_tool.calls == 4  # three failing test runs and one inspection, not the fourth test
    assert any("disabled" in result for result in llm.results)


def test_guard_failure_count_resets_only_for_a_file_change():
    guard = ToolFailureGuard()
    args = {"command": "pytest"}
    guard.record_failure("shell.exec", args, "ERROR 123")
    guard.record_failure("shell.exec", args, "error 456")
    assert guard.record_failure("shell.exec", args, "error 789") is not None
    assert guard.check_before_call("shell.exec", args) is not None
    other_args = {"command": "pytest -v"}
    for _ in range(3):
        guard.record_failure("shell.exec", other_args, "another error")
    assert guard.check_before_call("shell.exec", other_args) is not None
    loop_counts = {"first": 2, "second": 2}
    guard.reset_after_mutation(loop_counts)
    assert not loop_counts
    assert guard.check_before_call("shell.exec", args) is None
    assert guard.check_before_call("shell.exec", other_args) is None
    assert guard.record_failure("shell.exec", args, "error 999") is None
    assert guard.record_failure("shell.exec", args, "error 000") is None
    assert guard.record_failure("shell.exec", args, "error 111") is not None
    assert guard.record_failure("shell.exec", {"command": "pytest -v"}, "error 111") is None
    assert guard.record_failure("shell.exec", args, "error different") is None
    assert guard.record_failure("shell.exec", args, "error different") is None
    assert guard.record_failure("shell.exec", args, "error different") is None
    assert guard.record_failure("shell.exec", {"command": "pytest -q"}, "x" * 600 + "A") is None
    assert guard.record_failure("shell.exec", {"command": "pytest -q"}, "x" * 600 + "B") is None
