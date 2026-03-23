from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from thomas.agent.loop_tool_exec import _sanitize_write_tool_path, execute_tools
from thomas.core.events import EventType


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


class _LoopStub:
    def __init__(self, *, autonomy_level: int, runner: _SpyRunner) -> None:
        self._autonomy_level = autonomy_level
        self._run_id = "run-1"
        self._session_id = "sess-1"
        self._guarded_tool_runner = runner
        self._tool_timeout_s = None
        self._max_parallel_tools = None
        self._conversation = []
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
