"""aiohttp route registration for the isolated desktop setup under ``/api/onboarding/desktop``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.desktop_operator.host_service import get_global_desktop_host_service
from thomas.preferences.store import PreferencesPatch, PreferencesStore, get_db_path

RequireAccessFn = Callable[[web.Request], None]


def _prefs_store() -> PreferencesStore:
    return PreferencesStore(db_path=get_db_path())


def _user_id(request: web.Request) -> str:
    raw = str(request.headers.get("X-User-Id") or "").strip()
    return raw or "default"


def _patch_desktop_preferences(request: web.Request, posture: dict[str, Any], *, enabled: bool) -> None:
    store = _prefs_store()
    user_id = _user_id(request)
    patch = PreferencesPatch(
        advanced={
            "runtime": {
                "isolated_desktop_enabled": bool(enabled),
                "isolated_desktop_trust_mode": str(posture.get("trust_mode") or "ask_every_time"),
                "isolated_desktop_hidden_by_default": True,
            }
        },
        onboarding={
            "isolated_desktop_enabled": bool(enabled),
            "isolated_desktop_installation_state": str(posture.get("installation_state") or "not_enabled"),
            "isolated_desktop_next_action": str(posture.get("next_action") or ""),
            "isolated_desktop_reboot_required": bool(posture.get("reboot_required")),
            "isolated_desktop_relogin_required": bool(posture.get("relogin_required")),
        },
    )
    store.patch(patch=patch, user_id=user_id, thread_id=None)


def register_desktop_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
) -> None:
    async def api_onboarding_desktop_status(request: web.Request) -> web.Response:
        require_api_access(request)
        posture = get_global_desktop_host_service().status().to_dict()
        return web.json_response({"ok": True, "isolated_desktop": posture})

    async def api_onboarding_desktop_opt_in(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await request.json() if request.can_read_body else {}
        enabled = bool(body.get("enabled", True))
        hidden_by_default = bool(body.get("hidden_by_default", True))
        service = get_global_desktop_host_service()
        posture = service.request_opt_in(hidden_by_default=hidden_by_default) if enabled else service.disable()
        payload = posture.to_dict()
        _patch_desktop_preferences(request, payload, enabled=enabled)
        return web.json_response({"ok": True, "isolated_desktop": payload})

    async def api_onboarding_desktop_trust(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await request.json() if request.can_read_body else {}
        trust_mode = str(body.get("trust_mode") or "ask_every_time").strip()
        posture = get_global_desktop_host_service().set_remote_trust_mode(trust_mode)
        payload = posture.to_dict()
        _patch_desktop_preferences(request, payload, enabled=bool(payload.get("enabled")))
        return web.json_response({"ok": True, "isolated_desktop": payload})

    async def api_onboarding_desktop_vm_source(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await request.json() if request.can_read_body else {}
        service = get_global_desktop_host_service()
        posture = service.configure_local_vm_source(
            source_type=str(body.get("source_type") or "unconfigured"),
            vm_name=str(body.get("vm_name") or ""),
            template_vhdx=str(body.get("template_vhdx") or ""),
            switch_name=str(body.get("switch_name") or ""),
        )
        payload = posture.to_dict()
        _patch_desktop_preferences(request, payload, enabled=bool(payload.get("enabled")))
        return web.json_response({"ok": True, "isolated_desktop": payload})

    async def api_onboarding_desktop_install(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await request.json() if request.can_read_body else {}
        enabled = bool(body.get("enabled", True))
        service = get_global_desktop_host_service()
        if enabled:
            service.request_opt_in(hidden_by_default=bool(body.get("hidden_by_default", True)))
        launch = service.launch_host_service_install()
        payload = dict(launch.get("posture") or service.status().to_dict())
        _patch_desktop_preferences(request, payload, enabled=enabled)
        return web.json_response({"ok": True, "install_launch": launch, "isolated_desktop": payload})

    async def api_onboarding_desktop_open_viewer(request: web.Request) -> web.Response:
        require_api_access(request)
        launch = get_global_desktop_host_service().launch_viewer()
        return web.json_response({"ok": True, "viewer_launch": launch})

    app.router.add_get("/api/onboarding/desktop/status", api_onboarding_desktop_status)
    app.router.add_post("/api/onboarding/desktop/opt-in", api_onboarding_desktop_opt_in)
    app.router.add_post("/api/onboarding/desktop/trust", api_onboarding_desktop_trust)
    app.router.add_post("/api/onboarding/desktop/vm-source", api_onboarding_desktop_vm_source)
    app.router.add_post("/api/onboarding/desktop/install", api_onboarding_desktop_install)
    app.router.add_post("/api/onboarding/desktop/open-viewer", api_onboarding_desktop_open_viewer)
