from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import lru_cache
from typing import Any

from aiohttp import web
from scripts.breakglass_auth import authorize_breakglass_toggle

from thomas.marketplace.security.third_party_access import current_local_actor
from thomas.preferences.guardrails_policy import guardrails_posture_requires_auth, normalize_guardrails_posture
from thomas.preferences.store import PreferencesStore, get_db_path
from thomas.server.app_keys import APP_ACTION_AUDIT, APP_LOCAL_STEP_UP_AUTH_PROVIDER, APP_PROTECTED_INTERNALS_GATE

RequireAccessFn = Callable[[web.Request], None]
RequireLoopbackFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]
log = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _store_for_path(db_path: str) -> PreferencesStore:
    return PreferencesStore(db_path=db_path)


def _get_store() -> PreferencesStore:
    return _store_for_path(get_db_path())


def _get_user_id(request: web.Request) -> str:
    raw = str(request.headers.get("X-User-Id") or "").strip()
    return raw if raw else "default"


def _security_payload(security: Any) -> dict[str, Any]:
    if security is None:
        return {}
    if hasattr(security, "model_dump"):
        try:
            dumped = security.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except (AttributeError, TypeError, ValueError):
            return {}
    if isinstance(security, dict):
        return dict(security)
    return {}


def register_third_party_agent_access_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    require_loopback: RequireLoopbackFn,
    read_json: ReadJsonFn,
) -> None:
    async def api_toggle(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        if "enabled" not in payload or not isinstance(payload.get("enabled"), bool):
            raise web.HTTPBadRequest(text="enabled must be a boolean")

        enabled = bool(payload.get("enabled"))
        store = _get_store()
        user_id = _get_user_id(request)
        current = store.get(user_id=user_id)
        provider = request.app.get(APP_LOCAL_STEP_UP_AUTH_PROVIDER)
        audit = request.app.get(APP_ACTION_AUDIT)
        action_label = "enable_third_party_agent_access" if enabled else "disable_third_party_agent_access"

        if provider is None:
            reason = "local_step_up_auth_unavailable"
            if audit is not None:
                with suppress(Exception):
                    await audit.log_async(
                        kind="third_party_agent_access_toggle",
                        session_id=user_id,
                        decision="DENIED",
                        reason=reason,
                        payload={"requested_enabled": enabled},
                    )
            return web.json_response(
                {
                    "ok": False,
                    "enabled": bool(current.advanced.security.allow_third_party_agent_access),
                    "enforcement_mode": current.advanced.security.enforcement_mode,
                    "auth_verified": False,
                    "reason": reason,
                },
                status=503,
            )

        auth_result = provider.authorize(
            action=action_label,
            reason=(
                "Thomas will change whether third-party agents can access Thomas internals. "
                "This always requires a fresh local authorization check."
            ),
        )
        if not auth_result.authorized:
            if audit is not None:
                with suppress(Exception):
                    await audit.log_async(
                        kind="third_party_agent_access_toggle",
                        session_id=user_id,
                        decision="DENIED",
                        reason=auth_result.error_code or "auth_denied",
                        payload={
                            "requested_enabled": enabled,
                            "auth_method": auth_result.method,
                            "auth_platform": auth_result.platform,
                        },
                    )
            return web.json_response(
                {
                    "ok": False,
                    "enabled": bool(current.advanced.security.allow_third_party_agent_access),
                    "enforcement_mode": current.advanced.security.enforcement_mode,
                    "auth_verified": False,
                    "reason": auth_result.error_code or "auth_denied",
                },
                status=403,
            )

        updated = store.set_third_party_agent_access(
            enabled,
            user_id=user_id,
            changed_by=current_local_actor(),
        )
        gate = request.app.get(APP_PROTECTED_INTERNALS_GATE)
        if gate is not None and hasattr(gate, "set_allow_third_party_access"):
            try:
                gate.set_allow_third_party_access(enabled)
            except Exception as exc:
                log.warning("Could not refresh protected internals gate: %s", exc)

        if audit is not None:
            with suppress(Exception):
                await audit.log_async(
                    kind="third_party_agent_access_toggle",
                    session_id=user_id,
                    decision="ALLOWED",
                    reason="toggle_applied",
                    payload={
                        "requested_enabled": enabled,
                        "auth_method": auth_result.method,
                        "auth_platform": auth_result.platform,
                        "last_changed_at": updated.advanced.security.last_changed_at,
                        "last_changed_by": updated.advanced.security.last_changed_by,
                    },
                )

        return web.json_response(
            {
                "ok": True,
                "enabled": bool(updated.advanced.security.allow_third_party_agent_access),
                "enforcement_mode": updated.advanced.security.enforcement_mode,
                "auth_verified": True,
                "reason": None,
                "security": _security_payload(updated.advanced.security),
            }
        )

    async def api_breakglass_opt_in(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        if "enabled" not in payload or not isinstance(payload.get("enabled"), bool):
            raise web.HTTPBadRequest(text="enabled must be a boolean")

        enabled = bool(payload.get("enabled"))
        store = _get_store()
        user_id = _get_user_id(request)
        current = store.get(user_id=user_id)
        audit = request.app.get(APP_ACTION_AUDIT)
        auth_result = authorize_breakglass_toggle(enabled=enabled)
        if not auth_result.ok:
            reason = "auth_cancelled" if auth_result.cancelled else "auth_denied"
            if auth_result.method == "unsupported-platform":
                reason = "unsupported_platform"
            if audit is not None:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    await audit.log_async(
                        kind="human_breakglass_toggle",
                        session_id=user_id,
                        decision="DENIED",
                        reason=reason,
                        payload={
                            "requested_enabled": enabled,
                            "auth_method": auth_result.method,
                            "auth_platform": "windows"
                            if auth_result.method == "windows-credential-dialog"
                            else "unknown",
                        },
                    )
            return web.json_response(
                {
                    "ok": False,
                    "enabled": bool(current.advanced.security.human_breakglass_enabled),
                    "auth_verified": False,
                    "reason": reason,
                    "security": _security_payload(current.advanced.security),
                },
                status=403,
            )

        try:
            updated = store.set_human_breakglass_enabled(
                enabled,
                user_id=user_id,
                changed_by=current_local_actor(),
                authorization_receipt=auth_result.receipt,
            )
        except PermissionError:
            if audit is not None:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    await audit.log_async(
                        kind="human_breakglass_toggle",
                        session_id=user_id,
                        decision="DENIED",
                        reason="auth_receipt_invalid",
                        payload={"requested_enabled": enabled},
                    )
            return web.json_response(
                {
                    "ok": False,
                    "enabled": bool(current.advanced.security.human_breakglass_enabled),
                    "auth_verified": False,
                    "reason": "auth_receipt_invalid",
                    "security": _security_payload(current.advanced.security),
                },
                status=403,
            )

        if audit is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                await audit.log_async(
                    kind="human_breakglass_toggle",
                    session_id=user_id,
                    decision="ALLOWED",
                    reason="toggle_applied",
                    payload={
                        "requested_enabled": enabled,
                        "auth_method": auth_result.method,
                        "auth_platform": "windows" if auth_result.method == "windows-credential-dialog" else "unknown",
                        "changed_at": updated.advanced.security.human_breakglass_changed_at,
                        "changed_by": updated.advanced.security.human_breakglass_changed_by,
                    },
                )

        return web.json_response(
            {
                "ok": True,
                "enabled": bool(updated.advanced.security.human_breakglass_enabled),
                "auth_verified": True,
                "reason": None,
                "security": _security_payload(updated.advanced.security),
            }
        )

    async def api_guardrails_posture(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")

        target_posture = normalize_guardrails_posture(payload.get("posture"))
        store = _get_store()
        user_id = _get_user_id(request)
        current = store.get(user_id=user_id)
        current_posture = normalize_guardrails_posture(current.advanced.security.guardrails_posture)
        requires_auth = guardrails_posture_requires_auth(current_posture, target_posture)
        provider = request.app.get(APP_LOCAL_STEP_UP_AUTH_PROVIDER)
        audit = request.app.get(APP_ACTION_AUDIT)
        auth_verified = False

        if requires_auth:
            if provider is None:
                reason = "local_step_up_auth_unavailable"
                if audit is not None:
                    with suppress(Exception):
                        await audit.log_async(
                            kind="guardrails_posture_change",
                            session_id=user_id,
                            decision="DENIED",
                            reason=reason,
                            payload={
                                "current_posture": current_posture,
                                "requested_posture": target_posture,
                            },
                        )
                return web.json_response(
                    {
                        "ok": False,
                        "posture": current_posture,
                        "auth_verified": False,
                        "reason": reason,
                        "security": _security_payload(current.advanced.security),
                    },
                    status=503,
                )

            auth_result = provider.authorize(
                action=f"weaken_guardrails_to_{target_posture}",
                reason=("Thomas will reduce guardrail protections. This requires a fresh local authorization check."),
            )
            if not auth_result.authorized:
                if audit is not None:
                    with suppress(Exception):
                        await audit.log_async(
                            kind="guardrails_posture_change",
                            session_id=user_id,
                            decision="DENIED",
                            reason=auth_result.error_code or "auth_denied",
                            payload={
                                "current_posture": current_posture,
                                "requested_posture": target_posture,
                                "auth_method": auth_result.method,
                                "auth_platform": auth_result.platform,
                            },
                        )
                return web.json_response(
                    {
                        "ok": False,
                        "posture": current_posture,
                        "auth_verified": False,
                        "reason": auth_result.error_code or "auth_denied",
                        "security": _security_payload(current.advanced.security),
                    },
                    status=403,
                )
            auth_verified = True

        updated = store.set_guardrails_posture(
            target_posture,
            user_id=user_id,
            changed_by=current_local_actor(),
        )
        if audit is not None:
            with suppress(Exception):
                await audit.log_async(
                    kind="guardrails_posture_change",
                    session_id=user_id,
                    decision="ALLOWED",
                    reason="posture_applied",
                    payload={
                        "current_posture": current_posture,
                        "requested_posture": target_posture,
                        "auth_verified": auth_verified,
                        "changed_at": updated.advanced.security.guardrails_posture_changed_at,
                        "changed_by": updated.advanced.security.guardrails_posture_changed_by,
                    },
                )

        return web.json_response(
            {
                "ok": True,
                "posture": normalize_guardrails_posture(updated.advanced.security.guardrails_posture),
                "auth_verified": auth_verified,
                "reason": None,
                "security": _security_payload(updated.advanced.security),
                "preferences": updated.model_dump(),
            }
        )

    app.router.add_post("/api/security/third-party-agent-access", api_toggle)
    app.router.add_post("/api/security/breakglass-opt-in", api_breakglass_opt_in)
    app.router.add_post("/api/security/guardrails-posture", api_guardrails_posture)
