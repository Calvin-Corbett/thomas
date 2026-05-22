from __future__ import annotations

import asyncio
from typing import Any

from thomas.agent.approval import ApprovalBroker
from thomas.agent.guarded_tools import GuardedToolRunner
from thomas.marketplace.policy.redact import Redactor
from thomas.marketplace.policy.types import PolicyContext, PolicyDecision


class _RequireApprovalPolicy:
    def evaluate(self, _context: PolicyContext) -> PolicyDecision:
        return PolicyDecision.require_approval("requires manual approval in policy")


class _SpyApprovalBroker(ApprovalBroker):
    def __init__(self) -> None:
        super().__init__()
        self.require_calls: list[dict[str, Any]] = []

    async def require(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        session_id: str,
        tool_name: str,
        args_preview: Any,
        reason: str,
        timeout_s: int,
    ) -> bool:
        self.require_calls.append(
            {
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "session_id": session_id,
                "tool_name": tool_name,
                "args_preview": args_preview,
                "reason": reason,
                "timeout_s": timeout_s,
            }
        )
        return True


async def _emit_event(_name: str, _payload: dict[str, Any]) -> None:
    return None


async def _run_and_collect_no_human(
    no_human_mode: str | None, *, runner_mode: str | None = None
) -> tuple[dict[str, Any], _SpyApprovalBroker]:
    # `no_human_mode=allow` routes through native OS auth. On headless
    # CI there's no GUI to bind, so the real implementation returns False
    # and the runner denies the call. Patch it to always approve in the
    # test environment — see `tests/test_guarded_tools_native_auth.py`
    # for the same pattern.
    import thomas.agent.guarded_tools as _guarded_tools_module

    _original_native_auth = _guarded_tools_module.request_native_authorization
    _guarded_tools_module.request_native_authorization = lambda *args, **kwargs: True

    broker = _SpyApprovalBroker()
    runner = GuardedToolRunner(
        policy=_RequireApprovalPolicy(),
        approvals=broker,
        redactor=Redactor(),
        approval_timeout_s=10,
        no_human_mode=runner_mode or "human",
    )

    try:
        result = await runner.run(
            executor=lambda call: {
                "ok": True,
                "result_text": f"ran {call.get('name')}",
                "tool_call_id": call.get("id"),
            },
            tool_call={"id": "tc-1", "name": "dummy.echo", "args": {"x": 1}},
            run_id="run-1",
            session_id="sess-1",
            iteration=1,
            cwd="/tmp",
            sandbox_root="/tmp",
            runtime_root="/tmp",
            conversation_summary="",
            emit_event=_emit_event,
            no_human_mode=no_human_mode,
        )
    finally:
        _guarded_tools_module.request_native_authorization = _original_native_auth
    return result, broker


def test_guarded_tool_runner_respects_no_human_override_allow() -> None:
    result, broker = asyncio.run(_run_and_collect_no_human("allow"))

    assert result.get("ok") is True
    assert result.get("result_text") == "ran dummy.echo"
    assert broker.require_calls == []


def test_guarded_tool_runner_respects_no_human_override_deny() -> None:
    result, broker = asyncio.run(_run_and_collect_no_human("deny"))

    assert result.get("ok") is False
    assert "no-human policy" in str(result.get("error") or "").lower()
    assert broker.require_calls == []


def test_guarded_tool_runner_falls_back_to_instance_no_human_mode() -> None:
    result, broker = asyncio.run(_run_and_collect_no_human(None, runner_mode="allow"))

    assert result.get("ok") is True
    assert result.get("result_text") == "ran dummy.echo"
    assert broker.require_calls == []


def test_guarded_tool_runner_human_mode_calls_approval_broker() -> None:
    result, broker = asyncio.run(_run_and_collect_no_human("human"))

    assert result.get("ok") is True
    assert len(broker.require_calls) == 1
    first = broker.require_calls[0]
    assert first["tool_call_id"] == "tc-1"
    assert first["tool_name"] == "dummy.echo"
