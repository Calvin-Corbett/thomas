"""Integration test: plugin hooks actually fire during tool execution.

Drives the real ``execute_tools`` pipeline with a stub loop that carries a
``_plugin_hook_runner`` closure (the same attribute the server wires) and a
stub tool registry. Asserts ``before_tool`` AND ``after_tool`` fire with the
right tool name and payload — proving the audit finding (hooks defined but
never invoked) is fixed at the agent-loop boundary.

Mirrors the loop/registry stub style of tests/test_agent_loop_tool_exec.py.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from thomas.agent.loop_core import AgentLoop
from thomas.agent.loop_tool_exec import execute_tools
from thomas.core.events import EventType
from thomas.tools.base import ToolResult


class _StubRegistry:
    """Minimal async tool registry: execute() returns a fixed ToolResult."""

    def __init__(self, result_text: str = "stub-result", ok: bool = True) -> None:
        self._result_text = result_text
        self._ok = ok
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.calls.append((name, dict(args)))
        return ToolResult(ok=self._ok, data=self._result_text)


class _HookLoopStub:
    """Loop stub exposing exactly what execute_tools / _run_plugin_hook touch."""

    def __init__(self, hook_runner) -> None:
        self._autonomy_level = 3
        self._run_id = "run-hooks"
        self._session_id = "sess-hooks"
        self._guarded_tool_runner = None
        self._tool_timeout_s = None
        self._max_parallel_tools = 1
        self._conversation: list[dict[str, Any]] = []
        self._plugin_hook_runner = hook_runner
        self.tools = _StubRegistry()
        self.config = SimpleNamespace(
            tools=SimpleNamespace(sandbox_path="/tmp/sandbox"),
            memory=SimpleNamespace(root_path="/tmp/memory"),
        )

    # Reuse the real, decoupled hook invoker from AgentLoop so we test the
    # actual code path (try/except + no-op-when-None) rather than a re-impl.
    _run_plugin_hook = AgentLoop._run_plugin_hook

    async def _audit_action(self, **_kwargs: Any) -> None:
        return None


async def _drive(loop: _HookLoopStub, tool_calls: list[dict[str, Any]]) -> list:
    events = []
    async for ev in execute_tools(loop, tool_calls, 0, file_audit_module=None):
        events.append(ev)
    return events


def test_before_and_after_tool_hooks_fire() -> None:
    recorded: list[tuple[str, dict[str, Any]]] = []

    async def _hook_runner(name: str, payload: dict[str, Any]) -> None:
        recorded.append((name, payload))

    loop = _HookLoopStub(_hook_runner)
    events = asyncio.run(_drive(loop, [{"id": "t1", "name": "demo.echo", "arguments": {"text": "hi"}}]))

    # The tool ran and produced a result event.
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].data["ok"] is True

    hook_names = [n for n, _ in recorded]
    assert "before_tool" in hook_names, f"before_tool did not fire; got {hook_names}"
    assert "after_tool" in hook_names, f"after_tool did not fire; got {hook_names}"
    # Ordering: before_tool precedes after_tool.
    assert hook_names.index("before_tool") < hook_names.index("after_tool")

    before_payload = next(p for n, p in recorded if n == "before_tool")
    after_payload = next(p for n, p in recorded if n == "after_tool")

    assert before_payload["name"] == "demo.echo"
    assert before_payload["args"] == {"text": "hi"}

    assert after_payload["name"] == "demo.echo"
    assert after_payload["ok"] is True
    assert "result_text" in after_payload


def test_no_hook_runner_is_noop() -> None:
    # hook_runner=None must not break tool execution.
    loop = _HookLoopStub(None)
    events = asyncio.run(_drive(loop, [{"id": "t1", "name": "demo.echo", "arguments": {"text": "hi"}}]))
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].data["ok"] is True


def test_hook_exception_does_not_break_turn() -> None:
    async def _exploding_hook(name: str, payload: dict[str, Any]) -> None:
        raise RuntimeError(f"plugin blew up on {name}")

    loop = _HookLoopStub(_exploding_hook)
    # Tool execution must still complete despite the hook raising.
    events = asyncio.run(_drive(loop, [{"id": "t1", "name": "demo.echo", "arguments": {"text": "hi"}}]))
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].data["ok"] is True
