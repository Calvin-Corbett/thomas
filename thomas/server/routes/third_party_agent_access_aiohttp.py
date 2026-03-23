from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from aiohttp import web

from thomas.marketplace.security.third_party_access import current_local_actor
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
                try:
                    await audit.log_async(
                        kind="third_party_agent_access_toggle",
                        session_id=user_id,
                        decision="DENIED",
                        reason=reason,
                        payload={"requested_enabled": enabled},
                    )
                except Exception:
                    pass
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
                try:
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
                except Exception:
                    pass
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
            try:
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
            except Exception:
                pass

        return web.json_response(
            {
                "ok": True,
                "enabled": bool(updated.advanced.security.allow_third_party_agent_access),
                "enforcement_mode": updated.advanced.security.enforcement_mode,
                "auth_verified": True,
                "reason": None,
            }
        )

    app.router.add_post("/api/security/third-party-agent-access", api_toggle)
