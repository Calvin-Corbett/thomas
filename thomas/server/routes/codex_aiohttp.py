"""aiohttp routes for Codex bridge auth/model endpoints."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)


def register_codex_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    codex_bridge_key: Any,
) -> None:
    bridge_ref: dict[str, Any]
    existing = app.get(codex_bridge_key)
    if isinstance(existing, dict) and "bridge" in existing:
        bridge_ref = existing
    else:
        bridge_ref = {"bridge": existing}
        app[codex_bridge_key] = bridge_ref

    async def _ensure_bridge() -> Any:
        bridge = bridge_ref.get("bridge")
        if bridge is not None:
            return bridge
        from thomas.codex.bridge import CodexBridge

        bridge = CodexBridge()
        await bridge.start()
        bridge_ref["bridge"] = bridge
        return bridge

    async def api_codex_status(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            bridge = await _ensure_bridge()
            acct = await bridge.check_auth()
            return web.json_response(
                {
                    "logged_in": acct.logged_in,
                    "email": acct.email,
                    "display_name": acct.display_name,
                    "avatar_url": acct.avatar_url,
                    "plan_type": acct.plan_type,
                    "auth_type": acct.auth_type,
                }
            )
        except Exception as e:
            return web.json_response({"logged_in": False, "error": str(e)})

    async def api_codex_login(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            bridge = await _ensure_bridge()
            acct = await bridge.check_auth()
            if acct.logged_in:
                return web.json_response(
                    {
                        "ok": True,
                        "already": True,
                        "email": acct.email,
                        "display_name": acct.display_name,
                        "avatar_url": acct.avatar_url,
                        "plan_type": acct.plan_type,
                    }
                )
            acct = await bridge.login_chatgpt()
            return web.json_response(
                {
                    "ok": True,
                    "already": False,
                    "email": acct.email,
                    "display_name": acct.display_name,
                    "avatar_url": acct.avatar_url,
                    "plan_type": acct.plan_type,
                }
            )
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_codex_logout(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            bridge = bridge_ref.get("bridge")
            if bridge is not None:
                await bridge.logout()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_codex_models(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            bridge = await _ensure_bridge()
            models_found = await bridge.list_models()
            return web.json_response(
                {
                    "models": [
                        {
                            "id": m.id,
                            "display_name": m.display_name,
                            "is_default": m.is_default,
                        }
                        for m in models_found
                    ]
                }
            )
        except Exception as e:
            return web.json_response({"models": [], "error": str(e)})

    async def on_codex_cleanup(app_: web.Application) -> None:
        bridge = bridge_ref.get("bridge")
        if bridge is None:
            return
        try:
            await bridge.stop()
            bridge_ref["bridge"] = None
        except Exception as e:
            log.debug("Failed to stop Codex bridge during cleanup: %s", e)

    app.router.add_get("/api/codex/status", api_codex_status)
    app.router.add_post("/api/codex/login", api_codex_login)
    app.router.add_post("/api/codex/logout", api_codex_logout)
    app.router.add_get("/api/codex/models", api_codex_models)
    app.on_cleanup.append(on_codex_cleanup)
