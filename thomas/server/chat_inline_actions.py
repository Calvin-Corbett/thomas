"""Governed, reversible actions Thomas may perform inside V2 conversation.

The chat model never receives the full tool registry. This controller exposes a
small product-owned action vocabulary and translates it to existing tools behind
the same policy, approval, audit, and redaction runner used by the agent loop.
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Awaitable, Callable

from thomas.core.action_receipt import ActionReceipt
from thomas.tools.base import ToolResult

EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]

_ACTION_TO_TOOL = {
    "preferences.get": "preferences_get",
    "preferences.list": "preferences_list",
    "preferences.set": "preferences_set",
}
_MUTATING_ACTIONS = {"preferences.set"}


InlineActionReceipt = ActionReceipt


class ChatInlineOperator:
    """Execute only Thomas-owned, bounded actions with readback proof."""

    def __init__(
        self,
        *,
        tools: Any,
        guarded_runner: Any,
        config: Any,
        session_id: str,
        autonomy_level: int,
        user_prompt: str,
        emit_event: EventEmitter,
    ) -> None:
        self._tools = tools
        self._guarded_runner = guarded_runner
        self._config = config
        self._session_id = str(session_id or "")
        self._autonomy_level = int(autonomy_level or 0)
        self._user_prompt = str(user_prompt or "")
        self._emit_event = emit_event

    async def execute(self, *, action: str, key: str = "", value: Any = None) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        action_id = f"inline-{secrets.token_urlsafe(8)}"

        if normalized not in _ACTION_TO_TOOL:
            return await self._reject(
                action_id,
                normalized or "unknown",
                "That action is outside Thomas's bounded inline-action allowlist.",
            )

        tool_name = _ACTION_TO_TOOL[normalized]
        if self._tools is None or not hasattr(self._tools, "get") or self._tools.get(tool_name) is None:
            return await self._reject(action_id, normalized, f"Required tool '{tool_name}' is unavailable.")

        args: dict[str, Any] = {}
        if normalized in {"preferences.get", "preferences.set"}:
            clean_key = str(key or "").strip()
            if not clean_key:
                return await self._reject(action_id, normalized, "A preference key is required.")
            args["key"] = clean_key
        if normalized == "preferences.set":
            args["value"] = value

        await self._emit(
            {
                "type": "operator_action",
                "state": "started",
                "action_id": action_id,
                "action": normalized,
            }
        )

        if normalized in _MUTATING_ACTIONS:
            receipt = await self._execute_mutation(action_id, normalized, tool_name, args)
        else:
            result = await self._execute_registry_tool(tool_name, args)
            receipt = InlineActionReceipt(
                action_id=action_id,
                session_id=self._session_id,
                action=normalized,
                ok=bool(result.get("ok")),
                evidence={"observed": result.get("data")},
                error=str(result.get("error") or ""),
            )

        payload = receipt.to_dict()
        await self._emit({"type": "operator_action", "state": "completed", **payload})
        return payload

    async def _execute_mutation(
        self,
        action_id: str,
        action: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> InlineActionReceipt:
        if self._autonomy_level < 2:
            return InlineActionReceipt(
                action_id=action_id,
                session_id=self._session_id,
                action=action,
                ok=False,
                error="Assist autonomy or higher is required for an inline mutation.",
                reversible=True,
                approval="unavailable",
            )
        if self._guarded_runner is None:
            return InlineActionReceipt(
                action_id=action_id,
                session_id=self._session_id,
                action=action,
                ok=False,
                error="Guardrails are unavailable, so Thomas refused to mutate state.",
                reversible=True,
                approval="unavailable",
            )

        key = str(args.get("key") or "")
        before = await self._execute_registry_tool("preferences_get", {"key": key})
        previous_value = self._extract_preference_value(before)

        async def _executor(call: dict[str, Any]) -> dict[str, Any]:
            return await self._execute_registry_tool(str(call.get("name") or ""), call.get("args") or {})

        async def _guard_event(event_type: str, payload: dict[str, Any]) -> None:
            await self._emit({"type": str(event_type or "").lower(), **dict(payload or {})})

        config_tools = getattr(self._config, "tools", None)
        config_memory = getattr(self._config, "memory", None)
        guarded = await self._guarded_runner.run(
            executor=_executor,
            tool_call={"id": action_id, "name": tool_name, "args": args},
            run_id=action_id,
            session_id=self._session_id,
            iteration=1,
            cwd=os.getcwd(),
            sandbox_root=str(getattr(config_tools, "sandbox_path", "") or ""),
            runtime_root=str(getattr(config_memory, "root_path", "") or ""),
            conversation_summary=self._user_prompt[:1024],
            emit_event=_guard_event,
            no_human_mode="allow" if self._autonomy_level >= 4 else None,
        )
        guarded_ok = bool(guarded.get("ok")) if isinstance(guarded, dict) else False
        guarded_error = str(guarded.get("error") or "") if isinstance(guarded, dict) else "Invalid guarded result."
        if not guarded_ok:
            return InlineActionReceipt(
                action_id=action_id,
                session_id=self._session_id,
                action=action,
                ok=False,
                evidence={"previous_value": previous_value},
                error=guarded_error or "The guarded action did not execute.",
                reversible=True,
                approval="denied_or_failed",
            )

        after = await self._execute_registry_tool("preferences_get", {"key": key})
        observed_value = self._extract_preference_value(after)
        verified = bool(after.get("ok")) and observed_value == args.get("value")
        error = "" if verified else "The mutation returned success, but post-action readback did not match."
        return InlineActionReceipt(
            action_id=action_id,
            session_id=self._session_id,
            action=action,
            ok=verified,
            evidence={
                "key": key,
                "requested_value": args.get("value"),
                "previous_value": previous_value,
                "observed_value": observed_value,
                "rollback": {"action": "preferences.set", "key": key, "value": previous_value},
            },
            error=error,
            reversible=True,
            approval="policy_checked",
        )

    async def _execute_registry_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._tools.execute(tool_name, args)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "data": None, "error": str(exc)}
        if isinstance(result, ToolResult):
            return {"ok": bool(result.ok), "data": result.data, "error": result.error}
        if isinstance(result, dict):
            return {
                "ok": bool(result.get("ok")),
                "data": result.get("data"),
                "error": result.get("error"),
            }
        return {"ok": False, "data": None, "error": "Tool returned an unsupported result."}

    @staticmethod
    def _extract_preference_value(result: dict[str, Any]) -> Any:
        data = result.get("data")
        return data.get("value") if isinstance(data, dict) else None

    async def _reject(self, action_id: str, action: str, error: str) -> dict[str, Any]:
        receipt = InlineActionReceipt(
            action_id=action_id,
            session_id=self._session_id,
            action=action,
            state="rejected",
            ok=False,
            error=error,
        )
        payload = receipt.to_dict()
        await self._emit({"type": "operator_action", "state": "rejected", **payload})
        return payload

    async def _emit(self, event: dict[str, Any]) -> None:
        await self._emit_event(event)


__all__ = ["ChatInlineOperator", "InlineActionReceipt"]
