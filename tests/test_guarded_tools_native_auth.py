from __future__ import annotations

from typing import Any

import pytest

from thomas.agent.approval import ApprovalBroker
from thomas.agent.guarded_tools import GuardedToolRunner
from thomas.policy import PolicyDecision, PolicyDecisionType
from thomas.policy.redact import Redactor


class _RequireApprovalPolicy:
    def evaluate(self, _ctx: Any) -> PolicyDecision:
        return PolicyDecision(
            type=PolicyDecisionType.REQUIRE_APPROVAL,
            reason="destructive tool action",
            meta={},
        )


@pytest.mark.asyncio
async def test_guarded_tool_runner_requires_native_auth_in_no_human_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def _fake_native_auth(_action: str, _reason: str, *, session_expiry_s: int = 300) -> bool:
        _ = session_expiry_s
        return True

    monkeypatch.setattr("thomas.agent.guarded_tools.request_native_authorization", _fake_native_auth)

    async def _emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    runner = GuardedToolRunner(
        policy=_RequireApprovalPolicy(),
        approvals=ApprovalBroker(),
        redactor=Redactor(),
        no_human_mode="allow",
    )

    result = await runner.run(
        executor=lambda _tool_call: {"ok": True, "result": "done"},
        tool_call={"id": "tool-1", "name": "fs.delete", "args": {"path": "tmp.txt"}},
        run_id="run-1",
        session_id="session-1",
        iteration=1,
        cwd="C:/Users/corbe/Thomas",
        sandbox_root="C:/Users/corbe/Thomas",
        runtime_root="C:/Users/corbe/Thomas/runtime",
        conversation_summary="delete tmp.txt",
        emit_event=_emit,
    )

    assert result["ok"] is True
    required = [payload for kind, payload in events if kind == "TOOL_APPROVAL_REQUIRED"]
    resolved = [payload for kind, payload in events if kind == "TOOL_APPROVAL_RESOLVED"]
    assert required
    assert resolved
    assert required[0]["decision"] == "NATIVE_AUTH_REQUIRED"
    assert resolved[0]["decision"] == "NATIVE_AUTH_APPROVED"
    assert resolved[0]["approved"] is True


@pytest.mark.asyncio
async def test_guarded_tool_runner_denies_when_native_auth_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def _fake_native_auth(_action: str, _reason: str, *, session_expiry_s: int = 300) -> bool:
        _ = session_expiry_s
        return False

    monkeypatch.setattr("thomas.agent.guarded_tools.request_native_authorization", _fake_native_auth)

    async def _emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    runner = GuardedToolRunner(
        policy=_RequireApprovalPolicy(),
        approvals=ApprovalBroker(),
        redactor=Redactor(),
        no_human_mode="allow",
    )

    result = await runner.run(
        executor=lambda _tool_call: {"ok": True, "result": "done"},
        tool_call={"id": "tool-1", "name": "fs.delete", "args": {"path": "tmp.txt"}},
        run_id="run-1",
        session_id="session-1",
        iteration=1,
        cwd="C:/Users/corbe/Thomas",
        sandbox_root="C:/Users/corbe/Thomas",
        runtime_root="C:/Users/corbe/Thomas/runtime",
        conversation_summary="delete tmp.txt",
        emit_event=_emit,
    )

    assert result["ok"] is False
    assert "Native operating-system authorization was not granted" in str(result["error"])
    resolved = [payload for kind, payload in events if kind == "TOOL_APPROVAL_RESOLVED"]
    assert resolved[0]["decision"] == "NATIVE_AUTH_DENIED"
