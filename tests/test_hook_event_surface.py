"""Acceptance: the plugin hook surface covers the full agent-run lifecycle.

Proves CAP-024 Level-2 acceptance line — "Cover the full run, model, tool,
approval, completion, and failure event surface." A single recording hook is
registered on a loop-like stub (the same ``_run_plugin_hook`` invoker the real
``AgentLoop`` exposes), then a run/model/tool/approval/completion/failure
sequence is driven and EVERY one of the six categories is asserted to have fired
with the documented payload shape.

Dispatch paths exercised:
- tool_pre / tool_post: driven end-to-end through the real ``execute_tools``
  pipeline (identical harness to tests/test_plugin_hooks_wired.py).
- approval_requested: driven through the real ``bridge_guardrails_event`` mapper
  wired into the loop's guardrails emit callback.
- run_start / run_end / model_call / completion / failure: driven through the
  production ``emit_hook`` dispatcher with the exact payload shapes emitted at
  their real call sites (thomas/agent/loop.py, loop_execution.py,
  loop_completion.py).

Plus a coverage test asserting the event registry enumerates all six categories.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from thomas.agent.hook_events import (
    EVENT_PAYLOAD_KEYS,
    HookEvent,
    HookEventCategory,
    bridge_guardrails_event,
    category_for_name,
    category_of,
    covered_categories,
    emit_hook,
    event_names_for,
    event_surface,
)
from thomas.agent.loop_core import AgentLoop
from thomas.agent.loop_tool_exec import execute_tools
from thomas.core.events import EventType
from thomas.tools.base import ToolResult


class _StubRegistry:
    """Minimal async tool registry: execute() returns a fixed ToolResult."""

    def __init__(self, result_text: str = "stub-result", ok: bool = True) -> None:
        self._result_text = result_text
        self._ok = ok

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=self._ok, data=self._result_text)


class _RecordingLoop:
    """Loop-like stub carrying a recording plugin-hook runner.

    Uses the REAL ``AgentLoop._run_plugin_hook`` invoker (as the wired server
    does) so every dispatch flows through production isolation logic.
    """

    def __init__(self) -> None:
        self.recorded: list[tuple[str, dict[str, Any]]] = []

        async def _runner(name: str, payload: dict[str, Any]) -> None:
            self.recorded.append((name, dict(payload)))

        self._plugin_hook_runner = _runner
        # Attributes touched by execute_tools' simple (non-guarded) path.
        self._autonomy_level = 3
        self._run_id = "run-surface"
        self._session_id = "sess-surface"
        self._guarded_tool_runner = None
        self._tool_timeout_s = None
        self._max_parallel_tools = 1
        self._conversation: list[dict[str, Any]] = []
        self.tools = _StubRegistry()
        self.config = SimpleNamespace(
            tools=SimpleNamespace(sandbox_path="/tmp/sandbox"),
            memory=SimpleNamespace(root_path="/tmp/memory"),
        )

    _run_plugin_hook = AgentLoop._run_plugin_hook

    async def _audit_action(self, **_kwargs: Any) -> None:
        return None

    def names(self) -> list[str]:
        return [n for n, _ in self.recorded]

    def payload_for(self, name: str) -> dict[str, Any]:
        return next(p for n, p in self.recorded if n == name)


async def _drive_full_surface(loop: _RecordingLoop) -> None:
    # run category (loop.py run() wrapper payload shape)
    await emit_hook(
        loop,
        HookEvent.RUN_START,
        {"run_id": loop._run_id, "session_id": loop._session_id, "mode": "auto", "tools_policy": "auto"},
    )
    # model category (loop_execution.py pre-LLM payload shape)
    await emit_hook(
        loop,
        HookEvent.MODEL_CALL,
        {"messages": [{"role": "user", "content": "hi"}], "model": "test-model"},
    )

    # tool category — driven END-TO-END through the real execute_tools pipeline.
    async for ev in execute_tools(
        loop,
        [{"id": "t1", "name": "demo.echo", "arguments": {"text": "hi"}}],
        0,
        file_audit_module=None,
    ):
        assert ev.type == EventType.TOOL_RESULT
        assert ev.data["ok"] is True

    # approval category — driven through the real guardrails->hook bridge.
    await bridge_guardrails_event(
        loop,
        "TOOL_APPROVAL_REQUIRED",
        {
            "tool_name": "shell.run",
            "tool_call_id": "t2",
            "run_id": loop._run_id,
            "session_id": loop._session_id,
            "reason": "write outside sandbox",
        },
    )

    # completion category (loop_execution.py end-of-turn payload shape)
    await emit_hook(loop, HookEvent.COMPLETION, {"text": "done"})
    # failure category (loop_completion.py terminal-error payload shape)
    await emit_hook(loop, HookEvent.FAILURE, {"error": "boom", "run_id": loop._run_id})
    # run_end fires at run teardown (loop.py finally block).
    await emit_hook(loop, HookEvent.RUN_END, {"run_id": loop._run_id, "session_id": loop._session_id})


def test_full_event_surface_fires_all_six_categories() -> None:
    loop = _RecordingLoop()
    asyncio.run(_drive_full_surface(loop))

    names = loop.names()

    # Every canonical event fired.
    for event in (
        HookEvent.RUN_START,
        HookEvent.RUN_END,
        HookEvent.MODEL_CALL,
        HookEvent.TOOL_PRE,
        HookEvent.TOOL_POST,
        HookEvent.APPROVAL_REQUESTED,
        HookEvent.COMPLETION,
        HookEvent.FAILURE,
    ):
        assert event.value in names, f"{event.value} did not fire; got {names}"

    # Legacy aliases still fire (backward compatibility for existing plugins).
    assert "before_model" in names
    assert "before_tool" in names
    assert "after_tool" in names
    assert "after_response" in names

    # Ordering: tool_pre precedes tool_post.
    assert names.index("tool_pre") < names.index("tool_post")

    # Every one of the six lifecycle categories is represented.
    fired_categories = {category_for_name(n) for n in names}
    fired_categories.discard(None)
    assert fired_categories == set(HookEventCategory), (
        f"missing categories: {set(HookEventCategory) - fired_categories}"
    )

    # Documented payload shapes hold at each fired canonical event.
    for event, required_keys in EVENT_PAYLOAD_KEYS.items():
        payload = loop.payload_for(event.value)
        for key in required_keys:
            assert key in payload, f"{event.value} payload missing {key}: {payload}"

    # Specific payload assertions for the driven categories.
    assert loop.payload_for("tool_pre")["name"] == "demo.echo"
    assert loop.payload_for("tool_post")["ok"] is True
    assert loop.payload_for("approval_requested")["tool_name"] == "shell.run"
    assert loop.payload_for("failure")["error"] == "boom"


def test_bridge_ignores_unrelated_guardrails_events() -> None:
    loop = _RecordingLoop()
    asyncio.run(bridge_guardrails_event(loop, "TOOL_APPROVAL_RESOLVED", {"tool_name": "x"}))
    assert "approval_requested" not in loop.names()


def test_no_hook_runner_is_noop() -> None:
    class _Bare:
        _run_plugin_hook = AgentLoop._run_plugin_hook
        _plugin_hook_runner = None

    # Must not raise when no runner is registered.
    asyncio.run(
        emit_hook(
            _Bare(),
            HookEvent.RUN_START,
            {"run_id": "r", "session_id": "s", "mode": "m", "tools_policy": "t"},
        )
    )


def test_registry_enumerates_all_six_categories() -> None:
    # The coverage registry names exactly the six lifecycle categories.
    assert covered_categories() == set(HookEventCategory)
    assert set(HookEventCategory) == {
        HookEventCategory.RUN,
        HookEventCategory.MODEL,
        HookEventCategory.TOOL,
        HookEventCategory.APPROVAL,
        HookEventCategory.COMPLETION,
        HookEventCategory.FAILURE,
    }

    surface = event_surface()
    # Every category is present and non-empty in the documented surface.
    assert set(surface) == set(HookEventCategory)
    for category, event_names in surface.items():
        assert event_names, f"category {category} has no events"

    # Every canonical event maps to exactly one category, and every event has a
    # documented payload contract.
    for event in HookEvent:
        assert isinstance(category_of(event), HookEventCategory)
        assert event in EVENT_PAYLOAD_KEYS, f"{event} has no documented payload keys"

    # Run/tool categories expose both of their paired events.
    assert surface[HookEventCategory.RUN] == ("run_end", "run_start")
    assert surface[HookEventCategory.TOOL] == ("tool_post", "tool_pre")


def test_legacy_aliases_are_additional_not_replacements() -> None:
    assert event_names_for(HookEvent.TOOL_PRE) == ("tool_pre", "before_tool")
    assert event_names_for(HookEvent.TOOL_POST) == ("tool_post", "after_tool")
    assert event_names_for(HookEvent.MODEL_CALL) == ("model_call", "before_model")
    assert event_names_for(HookEvent.COMPLETION) == ("completion", "after_response")
    # Events without a legacy name dispatch only the canonical name.
    assert event_names_for(HookEvent.RUN_START) == ("run_start",)
    assert event_names_for(HookEvent.APPROVAL_REQUESTED) == ("approval_requested",)
    assert event_names_for(HookEvent.FAILURE) == ("failure",)
