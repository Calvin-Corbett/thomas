"""Guarded, readback-verified operations for workspace-resident Thomas."""

from __future__ import annotations

import os
import secrets
from typing import Any

from thomas.core.action_receipt import ActionReceipt
from thomas.server.routes.chat_surface_namespace import normalize_workspace_context_id
from thomas.server.workspace_specialist_actions import WorkspaceActionExecutorMixin
from thomas.server.workspace_specialist_policy import (
    GUARDED_TOOL_NAMES,
    WORKSPACE_ACTION_POLICIES,
    WorkspaceActionSpec,
    workspace_key_from_context,
)
from thomas.server.workspace_specialist_validation import validate_workspace_action


class WorkspaceResidentOperator(WorkspaceActionExecutorMixin):
    """Execute one exact workspace action without exposing the global registry."""

    def __init__(
        self,
        *,
        app: Any,
        context_id: str,
        tools: Any,
        guarded_runner: Any,
        config: Any,
        session_id: str,
        autonomy_level: int,
        user_prompt: str,
        emit_event: Any,
        user_id: str = "default",
        preferences_store: Any = None,
        tool_policy: Any = None,
        office_store: Any = None,
    ) -> None:
        self.app = app
        self.context_id = normalize_workspace_context_id(context_id)
        self.workspace_key = workspace_key_from_context(self.context_id)
        self.policy = WORKSPACE_ACTION_POLICIES[self.workspace_key]
        self.tools = tools
        self.guarded_runner = guarded_runner
        self.config = config
        self.session_id = str(session_id or "")
        self.autonomy_level = int(autonomy_level or 0)
        self.user_prompt = str(user_prompt or "")
        self.emit_event = emit_event
        self.user_id = str(user_id or "default")
        self.preferences_store = preferences_store
        self.tool_policy = tool_policy
        self.office_store = office_store

    async def initial_context(self) -> dict[str, Any]:
        result = await self._perform_read("workspace.inspect", {})
        if result.get("ok"):
            return result.get("data")
        return {"workspace": self.workspace_key, "available_actions": sorted(self.policy)}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip().lower()
        action_id = f"workspace-{secrets.token_urlsafe(8)}"
        spec = self.policy.get(action)
        if spec is None:
            return await self._reject(
                action_id, action or "unknown", "Action is outside this workspace allowlist."
            )
        validation_error = validate_workspace_action(action, spec, arguments)
        if validation_error:
            return await self._reject(action_id, action, validation_error)
        await self.emit_event(
            {"type": "operator_action", "state": "started", "action_id": action_id, "action": action}
        )
        if spec.mutating:
            receipt = await self._execute_mutation(action_id, action, spec, arguments)
        else:
            result = await self._perform_read(action, arguments)
            receipt = ActionReceipt(
                action_id=action_id,
                session_id=self.session_id,
                action=action,
                ok=bool(result.get("ok")),
                evidence={"observed": result.get("data")},
                error=str(result.get("error") or ""),
            )
        payload = receipt.to_dict()
        await self.emit_event({"type": "operator_action", "state": "completed", **payload})
        return payload

    async def _execute_mutation(
        self,
        action_id: str,
        action: str,
        spec: WorkspaceActionSpec,
        arguments: dict[str, Any],
    ) -> ActionReceipt:
        denied = [
            capability
            for capability in sorted(spec.required_capabilities)
            if not bool(getattr(self.tool_policy, capability, False))
        ]
        if denied:
            return self._mutation_denial(
                action_id,
                action,
                spec,
                f"Active owner policy denied required capability: {', '.join(denied)}.",
                approval="policy_denied",
            )
        if self.autonomy_level < 2:
            return self._mutation_denial(
                action_id, action, spec, "Assist autonomy or higher is required."
            )
        if self.guarded_runner is None:
            return self._mutation_denial(
                action_id,
                action,
                spec,
                "Guardrails are unavailable, so Thomas refused to mutate workspace state.",
            )
        before = await self._readback(action, arguments)

        async def _executor(_call: dict[str, Any]) -> dict[str, Any]:
            return await self._perform_mutation(action, arguments)

        async def _guard_event(event_type: str, payload: dict[str, Any]) -> None:
            await self.emit_event({"type": str(event_type or "").lower(), **dict(payload or {})})

        config_tools = getattr(self.config, "tools", None)
        config_memory = getattr(self.config, "memory", None)
        try:
            guarded = await self.guarded_runner.run(
                executor=_executor,
                tool_call={
                    "id": action_id,
                    "name": GUARDED_TOOL_NAMES.get(action, action.replace(".", "_")),
                    "args": dict(arguments),
                },
                run_id=action_id,
                session_id=self.session_id,
                iteration=1,
                cwd=os.getcwd(),
                sandbox_root=str(getattr(config_tools, "sandbox_path", "") or ""),
                runtime_root=str(getattr(config_memory, "root_path", "") or ""),
                conversation_summary=self.user_prompt[:1024],
                emit_event=_guard_event,
                no_human_mode="allow" if self.autonomy_level >= 4 else None,
            )
        except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return ActionReceipt(
                action_id=action_id,
                session_id=self.session_id,
                action=action,
                ok=False,
                evidence={"before": before},
                error=f"Workspace mutation failed safely: {exc}",
                reversible=spec.reversible,
                approval="failed",
            )
        guarded_ok = bool(guarded.get("ok")) if isinstance(guarded, dict) else False
        if not guarded_ok:
            guarded_error = guarded.get("error") if isinstance(guarded, dict) else None
            return ActionReceipt(
                action_id=action_id,
                session_id=self.session_id,
                action=action,
                ok=False,
                evidence={"before": before},
                error=str(guarded_error or "The guarded action did not execute."),
                reversible=spec.reversible,
                approval="denied_or_failed",
            )
        after = await self._readback(action, arguments, mutation_result=guarded)
        verified = self._readback_matches(action, arguments, after)
        return ActionReceipt(
            action_id=action_id,
            session_id=self.session_id,
            action=action,
            ok=verified,
            evidence={"before": before, "after": after},
            error="" if verified else "Mutation returned success, but post-action readback did not match.",
            reversible=spec.reversible,
            approval="policy_checked",
        )

    def _mutation_denial(
        self,
        action_id: str,
        action: str,
        spec: WorkspaceActionSpec,
        error: str,
        *,
        approval: str = "unavailable",
    ) -> ActionReceipt:
        return ActionReceipt(
            action_id=action_id,
            session_id=self.session_id,
            action=action,
            ok=False,
            reversible=spec.reversible,
            approval=approval,
            error=error,
        )

    async def _reject(self, action_id: str, action: str, error: str) -> dict[str, Any]:
        payload = ActionReceipt(
            action_id=action_id,
            session_id=self.session_id,
            action=action,
            state="rejected",
            ok=False,
            error=error,
        ).to_dict()
        await self.emit_event({"type": "operator_action", "state": "rejected", **payload})
        return payload


__all__ = ["WorkspaceResidentOperator"]
