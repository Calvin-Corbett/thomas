from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from thomas.agent.loop_tool_exec import _is_write_tool, _sanitize_write_tool_path, execute_tools
from thomas.core.events import EventType
from thomas.tools.base import ToolResult


class _SpyRunner:
    def __init__(self) -> None:
        self.no_human_mode_inputs: list[str | None] = []

    async def run(
        self,
        *,
        executor,
        tool_call,
        run_id: str,
        session_id: str,
        iteration: int,
        cwd: str,
        sandbox_root: str,
        runtime_root: str,
        conversation_summary: str,
        emit_event,
        no_human_mode=None,
    ) -> dict:
        self.no_human_mode_inputs.append(no_human_mode)
        return await executor(tool_call)


class _StaticGuardedRunner:
    def __init__(self, guarded: dict[str, Any]) -> None:
        self.guarded = guarded

    async def run(
        self,
        *,
        executor,  # noqa: ARG002
        tool_call,  # noqa: ARG002
        run_id: str,  # noqa: ARG002
        session_id: str,  # noqa: ARG002
        iteration: int,  # noqa: ARG002
        cwd: str,  # noqa: ARG002
        sandbox_root: str,  # noqa: ARG002
        runtime_root: str,  # noqa: ARG002
        conversation_summary: str,  # noqa: ARG002
        emit_event,  # noqa: ARG002
        no_human_mode=None,  # noqa: ARG002
    ) -> dict[str, Any]:
        return self.guarded


class _ToolRegistryStub:
    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:  # noqa: ARG002
        return ToolResult(ok=True, data={"ok": True, "tool": name})


class _LoopStub:
    def __init__(self, *, autonomy_level: int, runner: Any) -> None:
        self._autonomy_level = autonomy_level
        self._run_id = "run-1"
        self._session_id = "sess-1"
        self._guarded_tool_runner = runner
        self._tool_timeout_s = None
        self._max_parallel_tools = None
        self._conversation = []
        self.tools = _ToolRegistryStub()
        self.config = SimpleNamespace(
            tools=SimpleNamespace(sandbox_path="/tmp/sandbox"),
            memory=SimpleNamespace(root_path="/tmp/memory"),
        )

    async def _audit_action(
        self,
        *,
        kind: str,
        tool_call_id: str = "",
        tool_name: str = "",
        decision: str = "",
        reason: str = "",
        payload: object = None,
    ) -> None:
        return None


async def _run_execute_tools(loop: _LoopStub, tool_calls: list[dict[str, Any]]) -> list:
    events = []
    async for ev in execute_tools(
        loop,
        tool_calls,
        0,
        file_audit_module=None,
    ):
        events.append(ev)
    return events


def test_execute_tools_level_4_passes_no_human_mode_allow() -> None:
    runner = _SpyRunner()
    loop = _LoopStub(autonomy_level=4, runner=runner)
    events = asyncio.run(_run_execute_tools(loop, [{"id": "t1", "name": "dummy.echo", "arguments": "{}"}]))

    assert runner.no_human_mode_inputs == ["allow"]
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT


def test_execute_tools_level_3_does_not_override_no_human_mode() -> None:
    runner = _SpyRunner()
    loop = _LoopStub(autonomy_level=3, runner=runner)
    events = asyncio.run(_run_execute_tools(loop, [{"id": "t1", "name": "dummy.echo", "arguments": "{}"}]))

    assert runner.no_human_mode_inputs == [None]
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT


def test_execute_tools_rejects_parent_traversal_in_write_path() -> None:
    runner = _SpyRunner()
    loop = _LoopStub(autonomy_level=4, runner=runner)
    events = asyncio.run(
        _run_execute_tools(
            loop,
            [
                {
                    "id": "t1",
                    "name": "fs.write_file",
                    "arguments": {"path": "../secrets.txt", "content": "oops"},
                }
            ],
        )
    )

    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].data["ok"] is False
    assert "Invalid file path argument" in str(events[0].data["result_text"])
    assert "path traversal" in str(events[0].data["result_text"])


def test_is_write_tool_logs_file_audit_checker_failure_and_falls_back(caplog) -> None:
    class BrokenFileAudit:
        @staticmethod
        def is_write_tool(_name: str) -> bool:
            raise RuntimeError("checker unavailable")

    with caplog.at_level(logging.DEBUG, logger="thomas.agent.loop_tool_exec"):
        assert _is_write_tool("fs.write_file", BrokenFileAudit) is True

    assert any(
        record.exc_info
        and record.message == "file_audit.is_write_tool checker failed for tool 'fs.write_file'; using fallback"
        for record in caplog.records
    )


def test_guarded_result_data_serialization_failure_logs_and_falls_back(caplog) -> None:
    circular: list[Any] = []
    circular.append(circular)
    runner = _StaticGuardedRunner({"ok": True, "data": circular})
    loop = _LoopStub(autonomy_level=4, runner=runner)

    with caplog.at_level(logging.DEBUG, logger="thomas.agent.loop_tool_exec"):
        events = asyncio.run(_run_execute_tools(loop, [{"id": "t1", "name": "dummy.echo", "arguments": "{}"}]))

    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].data["ok"] is True
    assert events[0].data["result_text"] == "[[...]]"
    assert any(
        record.exc_info and record.message == "guarded tool result data serialization failed; using string fallback"
        for record in caplog.records
    )


def test_self_development_guard_blocks_runaway_inspection_before_write() -> None:
    runner = _SpyRunner()
    loop = _LoopStub(autonomy_level=4, runner=runner)
    loop._current_job_type = "self_development"
    loop._self_development_write_guard = {"inspection_count": 6, "write_seen": False, "limit": 6}

    events = asyncio.run(_run_execute_tools(loop, [{"id": "t1", "name": "fs.list_dir", "arguments": "{}"}]))

    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].data["ok"] is False
    assert "Self-development write-first guard" in str(events[0].data["result_text"])
    assert "fs.write_file" in str(events[0].data["result_text"])


def test_self_development_guard_allows_first_write_tool() -> None:
    runner = _SpyRunner()
    loop = _LoopStub(autonomy_level=4, runner=runner)
    loop._current_job_type = "self_development"
    loop._self_development_write_guard = {"inspection_count": 10, "write_seen": False, "limit": 6}

    event = asyncio.run(
        execute_tools(
            loop,
            [{"id": "t1", "name": "fs.write_file", "arguments": {"path": "probe.txt", "content": "x"}}],
            0,
            file_audit_module=None,
        ).__anext__()
    )

    assert loop._self_development_write_guard["write_seen"] is True
    assert event.type == EventType.TOOL_RESULT


def test_self_development_guard_treats_diff_create_as_write_tool() -> None:
    runner = _SpyRunner()
    loop = _LoopStub(autonomy_level=4, runner=runner)
    loop._current_job_type = "self_development"
    loop._self_development_write_guard = {"inspection_count": 10, "write_seen": False, "limit": 2}

    event = asyncio.run(
        execute_tools(
            loop,
            [
                {
                    "id": "t1",
                    "name": "diff.create",
                    "arguments": {"path": "probe.txt", "old_str": "a", "new_str": "b"},
                }
            ],
            0,
            file_audit_module=None,
        ).__anext__()
    )

    assert loop._self_development_write_guard["write_seen"] is True
    assert event.type == EventType.TOOL_RESULT


def test_sanitize_write_tool_path_allows_and_rejects_extended_keys() -> None:
    assert _sanitize_write_tool_path({"file_path": "auth/store.json"}, require_path=True) == (
        "auth/store.json",
        None,
    )
    assert _sanitize_write_tool_path({"auth_path": "auth/credentials.json"}, require_path=True) == (
        "auth/credentials.json",
        None,
    )

    rejected_path, error = _sanitize_write_tool_path({"source_path": "../bad.txt"}, require_path=True)
    assert rejected_path is None
    assert error is not None
    assert "path traversal" in error


def test_sanitize_write_tool_path_restricts_benchmark_relative_paths(tmp_path: Path) -> None:
    sandbox_root = tmp_path
    benchmark_root = tmp_path / "output" / "benchmarks" / "snake" / "run-1" / "thomas"
    benchmark_root.mkdir(parents=True)

    approved, approved_error = _sanitize_write_tool_path(
        {"path": "output/benchmarks/snake/run-1/thomas/index.html"},
        require_path=True,
        sandbox_root=sandbox_root,
        benchmark_root=benchmark_root,
    )
    blocked, blocked_error = _sanitize_write_tool_path(
        {"path": "README.md"},
        require_path=True,
        sandbox_root=sandbox_root,
        benchmark_root=benchmark_root,
    )

    assert approved == "output/benchmarks/snake/run-1/thomas/index.html"
    assert approved_error is None
    assert blocked is None
    assert blocked_error is not None
    assert "outside the benchmark root" in blocked_error


def test_sanitize_write_tool_path_allows_benchmark_absolute_paths(tmp_path: Path) -> None:
    sandbox_root = tmp_path
    benchmark_root = tmp_path / "output" / "benchmarks" / "snake" / "run-1" / "thomas"
    benchmark_root.mkdir(parents=True)
    target = benchmark_root / "proof.json"

    approved, error = _sanitize_write_tool_path(
        {"path": str(target)},
        require_path=True,
        sandbox_root=sandbox_root,
        benchmark_root=benchmark_root,
    )

    assert approved == str(target.resolve())
    assert error is None
