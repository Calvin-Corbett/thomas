from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from thomas.policy import PolicyContext, PolicyDecisionType, PolicyEngine
from thomas.policy.redact import Redactor

from .approval import ApprovalBroker

ToolExecutor = Callable[[dict[str, Any]], Any]


def _pretty_args(args: dict[str, Any], max_len: int = 4000) -> Any:
    try:
        s = json.dumps(args, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        s = str(args)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


@dataclass
class GuardedToolRunner:
    policy: PolicyEngine
    approvals: ApprovalBroker
    redactor: Redactor
    audit: Any | None = None  # AuditLog
    approval_timeout_s: int = 60
    no_human_mode: str = "human"

    @staticmethod
    def _normalize_no_human_mode(value: str | None) -> str:
        mode = str(value or "human").strip().lower()
        if mode in {"human", "allow", "deny"}:
            return mode
        return "human"

    async def run(
        self,
        *,
        executor: ToolExecutor,
        tool_call: dict[str, Any],
        run_id: str,
        session_id: str,
        iteration: int,
        cwd: str,
        sandbox_root: str,
        runtime_root: str,
        conversation_summary: str,
        emit_event: Callable[[str, dict[str, Any]], Awaitable[None]],
        no_human_mode: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate policy, potentially require approval, execute tool, redact outputs.

        `tool_call` is expected to contain at least:
          - id (tool_call_id)
          - name (tool_name)
          - args (dict)
        """
        tool_call_id = str(tool_call.get("id") or tool_call.get("tool_call_id") or "")
        tool_name = str(tool_call.get("name") or tool_call.get("tool_name") or "")
        args = tool_call.get("args") or tool_call.get("arguments") or {}
        if not isinstance(args, dict):
            # If args arrives as JSON string, best-effort parse
            try:
                import json as _json

                args = _json.loads(args)
            except Exception:
                args = {"_raw": str(args)}

        ctx = PolicyContext(
            tool_name=tool_name,
            args=args,
            cwd=cwd,
            sandbox_root=sandbox_root,
            iteration=iteration,
            conversation_summary=conversation_summary[:1024],
            run_id=run_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            runtime_root=runtime_root,
        )
        decision = self.policy.evaluate(ctx)

        # Audit policy decision
        if self.audit:
            try:
                await self.audit.log_async(
                    kind="policy_decision",
                    run_id=run_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    decision=decision.type.value,
                    reason=decision.reason,
                    payload={"meta": decision.meta, "args_preview": self.redactor.redact_obj(args)},
                )
            except Exception:
                pass

        if decision.type == PolicyDecisionType.DENY:
            await emit_event(
                "TOOL_RESULT",
                {
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "ok": False,
                    "error": self.redactor.redact_text(decision.reason),
                },
            )
            return {
                "ok": False,
                "error": self.redactor.redact_text(decision.reason),
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
            }

        if decision.type == PolicyDecisionType.REQUIRE_APPROVAL:
            effective_no_human_mode = GuardedToolRunner._normalize_no_human_mode(
                self.no_human_mode if no_human_mode is None else no_human_mode,
            )

            if effective_no_human_mode == "allow":
                await emit_event(
                    "TOOL_APPROVAL_REQUIRED",
                    {
                        "run_id": run_id,
                        "tool_call_id": tool_call_id,
                        "session_id": session_id,
                        "tool_name": tool_name,
                        "args": self.redactor.redact_obj(args),
                        "args_pretty": _pretty_args(self.redactor.redact_obj(args)),
                        "reason": self.redactor.redact_text(
                            f"Auto-approved by no-human mode (allow) for tool: {tool_name}"
                        ),
                        "iteration": iteration,
                        "decision": "AUTO_APPROVED_NO_HUMAN",
                        "no_human_mode": effective_no_human_mode,
                    },
                )
                await emit_event(
                    "TOOL_APPROVAL_RESOLVED",
                    {
                        "run_id": run_id,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "approved": True,
                        "auto": True,
                        "no_human_mode": effective_no_human_mode,
                    },
                )
                approved = True
            elif effective_no_human_mode == "deny":
                await emit_event(
                    "TOOL_APPROVAL_RESOLVED",
                    {
                        "run_id": run_id,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "approved": False,
                        "auto": True,
                        "no_human_mode": effective_no_human_mode,
                    },
                )
                err = "Tool execution denied by no-human policy (no-human mode=deny)."
                await emit_event(
                    "TOOL_RESULT",
                    {
                        "run_id": run_id,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "ok": False,
                        "error": err,
                    },
                )
                return {
                    "ok": False,
                    "error": err,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                }
            else:
                # Emit approval request
                payload = {
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "args": self.redactor.redact_obj(args),
                    "args_pretty": _pretty_args(self.redactor.redact_obj(args)),
                    "reason": self.redactor.redact_text(decision.reason),
                    "iteration": iteration,
                }
                await emit_event("TOOL_APPROVAL_REQUIRED", payload)
                approved = await self.approvals.require(
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    args_preview=self.redactor.redact_obj(args),
                    reason=decision.reason,
                    timeout_s=self.approval_timeout_s,
                )

            await emit_event(
                "TOOL_APPROVAL_RESOLVED",
                {
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "approved": bool(approved),
                },
            )

            if self.audit:
                try:
                    await self.audit.log_async(
                        kind="approval_resolved",
                        run_id=run_id,
                        session_id=session_id,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        decision="APPROVED" if approved else "DENIED",
                        reason=decision.reason,
                        payload={},
                    )
                except Exception:
                    pass

            if not approved:
                err = "Tool execution denied (approval required)."
                await emit_event(
                    "TOOL_RESULT",
                    {
                        "run_id": run_id,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "ok": False,
                        "error": err,
                    },
                )
                return {"ok": False, "error": err, "tool_name": tool_name, "tool_call_id": tool_call_id}

        # Execute tool
        exec_result = executor({"id": tool_call_id, "name": tool_name, "args": args})
        if inspect.isawaitable(exec_result):
            result = await exec_result
        else:
            result = exec_result
        redacted = self.redactor.redact_obj(result)

        if self.audit:
            try:
                await self.audit.log_async(
                    kind="tool_result",
                    run_id=run_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    decision="EXECUTED",
                    reason="",
                    payload=redacted,
                )
            except Exception:
                pass
        return redacted
