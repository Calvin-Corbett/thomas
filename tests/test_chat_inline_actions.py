from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from thomas.server.chat_inline_actions import ChatInlineOperator
from thomas.tools.base import ToolResult


class _Registry:
    def __init__(self) -> None:
        self.preferences: dict[str, Any] = {"theme": "light"}
        self.available = {"preferences_get", "preferences_list", "preferences_set"}

    def get(self, name: str) -> object | None:
        return object() if name in self.available else None

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        if name == "preferences_get":
            key = str(args.get("key") or "")
            return ToolResult(ok=True, data={"key": key, "value": self.preferences.get(key)})
        if name == "preferences_list":
            return ToolResult(ok=True, data={"preferences": dict(self.preferences)})
        if name == "preferences_set":
            key = str(args.get("key") or "")
            self.preferences[key] = args.get("value")
            return ToolResult(ok=True, data={"set": True, "key": key})
        return ToolResult(ok=False, error=f"Unknown tool: {name}")


class _GuardedRunner:
    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, executor, tool_call, emit_event, **kwargs):
        self.calls.append({"tool_call": dict(tool_call), **kwargs})
        await emit_event("TOOL_POLICY", {"decision": "allow" if self.allow else "deny"})
        if not self.allow:
            return {"ok": False, "error": "denied by policy"}
        return await executor(tool_call)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        tools=SimpleNamespace(sandbox_path="workspace"),
        memory=SimpleNamespace(root_path="runtime"),
    )


def _operator(
    registry: _Registry,
    events: list[dict[str, Any]],
    *,
    autonomy: int = 3,
    guarded_runner: _GuardedRunner | None = None,
) -> ChatInlineOperator:
    async def emit(event: dict[str, Any]) -> None:
        events.append(dict(event))

    return ChatInlineOperator(
        tools=registry,
        guarded_runner=guarded_runner,
        config=_config(),
        session_id="session-1",
        autonomy_level=autonomy,
        user_prompt="Set my Thomas theme to dark.",
        emit_event=emit,
    )


@pytest.mark.asyncio
async def test_read_action_runs_inline_and_returns_observation() -> None:
    registry = _Registry()
    events: list[dict[str, Any]] = []

    receipt = await _operator(registry, events, autonomy=1).execute(action="preferences.get", key="theme")

    assert receipt["ok"] is True
    assert receipt["receipt_id"] == receipt["action_id"]
    assert receipt["session_id"] == "session-1"
    assert receipt["kind"] == "inline"
    assert receipt["state"] == "completed"
    assert receipt["evidence"]["observed"] == {"key": "theme", "value": "light"}
    assert [event["state"] for event in events if event["type"] == "operator_action"] == [
        "started",
        "completed",
    ]


@pytest.mark.asyncio
async def test_mutation_requires_assist_autonomy_and_guardrails() -> None:
    registry = _Registry()

    low = await _operator(registry, [], autonomy=1, guarded_runner=_GuardedRunner()).execute(
        action="preferences.set",
        key="theme",
        value="dark",
    )
    assert low["ok"] is False
    assert "Assist autonomy" in low["error"]
    assert registry.preferences["theme"] == "light"

    unguarded = await _operator(registry, [], autonomy=3, guarded_runner=None).execute(
        action="preferences.set",
        key="theme",
        value="dark",
    )
    assert unguarded["ok"] is False
    assert "Guardrails are unavailable" in unguarded["error"]
    assert registry.preferences["theme"] == "light"


@pytest.mark.asyncio
async def test_mutation_is_policy_checked_and_read_back_with_rollback_evidence() -> None:
    registry = _Registry()
    guarded = _GuardedRunner()
    events: list[dict[str, Any]] = []

    receipt = await _operator(registry, events, autonomy=3, guarded_runner=guarded).execute(
        action="preferences.set",
        key="theme",
        value="dark",
    )

    assert receipt["ok"] is True
    assert receipt["approval"] == "policy_checked"
    assert receipt["reversible"] is True
    assert receipt["evidence"] == {
        "key": "theme",
        "requested_value": "dark",
        "previous_value": "light",
        "observed_value": "dark",
        "rollback": {"action": "preferences.set", "key": "theme", "value": "light"},
    }
    assert guarded.calls[0]["tool_call"]["name"] == "preferences_set"
    assert any(event["type"] == "tool_policy" for event in events)


@pytest.mark.asyncio
async def test_unknown_and_policy_denied_actions_fail_without_effect() -> None:
    registry = _Registry()
    events: list[dict[str, Any]] = []

    unknown = await _operator(registry, events, guarded_runner=_GuardedRunner()).execute(action="shell.run")
    assert unknown["ok"] is False
    assert "outside" in unknown["error"]

    denied = await _operator(registry, events, guarded_runner=_GuardedRunner(allow=False)).execute(
        action="preferences.set",
        key="theme",
        value="dark",
    )
    assert denied["ok"] is False
    assert denied["error"] == "denied by policy"
    assert registry.preferences["theme"] == "light"
