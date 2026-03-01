"""aiohttp routes for companion kernel/module control plane."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.companion.audit import CompanionAuditLog
from thomas.companion.contracts import allowed_permissions
from thomas.companion.devices import DeviceRegistry
from thomas.companion.kernel import KERNEL_VERSION, CompanionKernel
from thomas.companion.network import TailscalePolicy, assert_peer_allowed
from thomas.companion.policy import (
    get_policy_profile,
    list_policy_profiles,
)
from thomas.companion.registry import ModuleRegistry
from thomas.companion.releases import ReleaseRegistry
from thomas.companion.runtime import ModuleRuntime
from thomas.companion.studio import BundleStudio
from thomas.companion.update import BundleVerifier, UpdateApplier
from thomas.server.routes.companion_device_release_aiohttp import (
    CompanionDeviceReleaseDeps,
    register_companion_device_release_routes,
)
from thomas.server.routes.companion_runtime import (
    _app_store_catalog,
    _csv_list,
    _device_capabilities,
    _int_or_none,
    _module_payload_from_bundle,
    _release_bundle_dir,
    _release_manifest,
    _run_compliance_check,
    _string_list,
    _studio_capability_catalog,
    _zip_bundle,
    run_companion_device_app_push,
    run_companion_ship,
)

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

_ENDPOINTS = [
    "GET /api/companion/v1/status",
    "GET /api/companion/v1/contract",
    "GET /api/companion/v1/studio/capabilities",
    "GET /api/companion/v1/policy/profiles",
    "GET /api/companion/v1/policy/profile/{profile_id}",
    "POST /api/companion/v1/compliance/check",
    "GET /api/companion/v1/bootstrap",
    "GET /api/companion/v1/app-store",
    "GET /api/companion/v1/modules",
    "GET /api/companion/v1/slots",
    "GET /api/companion/v1/slots/{slot}",
    "POST /api/companion/v1/modules/{module_id}/enable",
    "POST /api/companion/v1/modules/{module_id}/disable",
    "POST /api/companion/v1/studio/build-bundle",
    "POST /api/companion/v1/bundles/preview",
    "POST /api/companion/v1/bundles/verify",
    "POST /api/companion/v1/bundles/apply",
    "POST /api/companion/v1/ship",
    "GET /api/companion/v1/devices",
    "POST /api/companion/v1/devices/register",
    "POST /api/companion/v1/devices/{device_id}/heartbeat",
    "POST /api/companion/v1/devices/{device_id}/apps/{module_id}/push",
    "POST /api/companion/v1/devices/{device_id}/pin-release",
    "POST /api/companion/v1/devices/{device_id}/unpin-release",
    "POST /api/companion/v1/devices/{device_id}/updates/check",
    "GET /api/companion/v1/releases",
    "GET /api/companion/v1/releases/{release_id}",
    "GET /api/companion/v1/releases/{release_id}/manifest",
    "GET /api/companion/v1/releases/{release_id}/download",
    "POST /api/companion/v1/releases/publish",
    "POST /api/companion/v1/releases/{release_id}/rollout",
    "POST /api/companion/v1/releases/{release_id}/promote",
    "POST /api/companion/v1/releases/{release_id}/rollback",
    "GET /api/companion/v1/audit/events",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _boolish(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _resolve_peer_identity(request: web.Request) -> str:
    for header in ("X-Companion-Peer", "X-Tailscale-Identity", "X-Forwarded-For"):
        raw = str(request.headers.get(header) or "").strip()
        if not raw:
            continue
        if header == "X-Forwarded-For":
            return raw.split(",")[0].strip()
        return raw
    remote = str(request.remote or "").strip()
    if remote:
        return remote
    try:
        peer = request.transport.get_extra_info("peername")  # type: ignore[union-attr]
    except Exception:
        peer = None
    if isinstance(peer, tuple) and peer:
        return str(peer[0]).strip()
    return ""


def _tailscale_policy(kernel: CompanionKernel) -> TailscalePolicy:
    data = kernel.load_policy()
    return TailscalePolicy(
        tailscale_only=bool(data.get("tailscale_only", True)),
        allowed_tailnet_suffix=str(data.get("tailscale_suffix") or ".ts.net"),
        allow_localhost_dev=True,
    )


def _require_control_plane_identity(request: web.Request, kernel: CompanionKernel) -> str:
    peer_identity = _resolve_peer_identity(request)
    try:
        assert_peer_allowed(peer_identity, policy=_tailscale_policy(kernel))
    except PermissionError as exc:
        raise web.HTTPForbidden(text=str(exc))
    return peer_identity


def _kernel_from_config(config: Any) -> CompanionKernel:
    return CompanionKernel.from_config(config, root_override="")


def _bundle_path_from_payload(payload: Any) -> Path:
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="json body must be an object")
    raw = (
        str(payload.get("bundle_dir") or "").strip()
        or str(payload.get("bundle_path") or "").strip()
        or str(payload.get("bundle") or "").strip()
    )
    if not raw:
        raise web.HTTPBadRequest(text="missing bundle_dir")
    path = Path(raw).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise web.HTTPBadRequest(text=f"bundle_dir does not exist: {path}")
    return path


def _new_verifier(kernel: CompanionKernel) -> BundleVerifier:
    policy = kernel.load_policy()
    secret = str(os.environ.get("THOMAS_COMPANION_UPDATE_SECRET") or "").strip()
    require_signature = bool(policy.get("require_signed_updates", True))
    return BundleVerifier(kernel, secret=secret, require_signature=require_signature)


def _audit(kernel: CompanionKernel) -> CompanionAuditLog:
    return CompanionAuditLog(kernel)


def _actor_from_payload(payload: Any, *, default: str = "api") -> str:
    if not isinstance(payload, dict):
        return default
    actor = str(payload.get("actor") or "").strip()
    return actor or default


def _installed_modules_from_payload(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("installed_modules")
    if isinstance(raw, dict):
        out: dict[str, str] = {}
        for key, val in raw.items():
            module_id = str(key or "").strip()
            if not module_id:
                continue
            out[module_id] = str(val or "").strip()
        return out
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            module_id = str(item.get("module_id") or item.get("id") or "").strip()
            if not module_id:
                continue
            out[module_id] = str(item.get("version") or "").strip()
        return out
    return {}


def _companion_primary_function() -> str:
    return (
        "Thomas Companion is a mobile chat runtime and app-runtime control surface. "
        "Its primary function is creating, shipping, and pushing companion apps "
        "including websocket-backed/headless web experiences."
    )


def _companion_setup_blueprint(*, access_mode: str) -> dict[str, Any]:
    token_required = str(access_mode or "").strip().lower() == "remote"
    return {
        "token_required": token_required,
        "steps": [
            {
                "id": "install_open_companion",
                "title": "Install and open the companion app",
                "details": ("Open /companion on mobile (or install as PWA) and confirm chat is online."),
                "endpoint": "/companion",
            },
            {
                "id": "pair_device",
                "title": "Register the phone as a trusted device",
                "details": (
                    "Call devices/register with platform/channel/storefront so policy routing resolves correctly."
                ),
                "endpoint": "/api/companion/v1/devices/register",
            },
            {
                "id": "browse_apps",
                "title": "Open app catalog and pick module",
                "details": ("Use app-store catalog to see latest published modules and release constraints."),
                "endpoint": "/api/companion/v1/app-store",
            },
            {
                "id": "push_and_apply",
                "title": "Push release to phone and apply",
                "details": ("Push selected module release to the device, then check updates/apply from companion."),
                "endpoint": "/api/companion/v1/devices/{device_id}/apps/{module_id}/push",
            },
        ],
    }


def register_companion_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
    config: Any,
) -> None:
    async def api_companion_status(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        kernel_status = kernel.status()
        policy = kernel.load_policy()
        profiles = [item.to_dict() for item in list_policy_profiles()]
        access_mode = str(getattr(getattr(config, "server", None), "access_mode", "local") or "local")
        return web.json_response(
            {
                "ok": True,
                "api_version": "v1",
                "kernel": kernel_status,
                "policy": {
                    "tailscale_only": bool(policy.get("tailscale_only", True)),
                    "tailscale_suffix": str(policy.get("tailscale_suffix") or ".ts.net"),
                    "require_signed_updates": bool(policy.get("require_signed_updates", True)),
                    "default_profile_id": "strict_global",
                    "profiles_count": len(profiles),
                },
                "mission": {
                    "primary_function": _companion_primary_function(),
                    "core_capabilities": [
                        "mobile_chat_runtime",
                        "device_pairing",
                        "app_store_catalog",
                        "device_targeted_app_push",
                        "release_shipping",
                        "websocket_headless_web_modules",
                    ],
                    "setup": _companion_setup_blueprint(access_mode=access_mode),
                },
                "policy_profiles": profiles,
                "endpoints": list(_ENDPOINTS),
            }
        )

    async def api_companion_contract(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        policy = kernel.load_policy()
        access_mode = str(getattr(getattr(config, "server", None), "access_mode", "local") or "local")
        return web.json_response(
            {
                "ok": True,
                "api_version": "v1",
                "kernel_version": KERNEL_VERSION,
                "minimum_requirements": [
                    "immutable_kernel_boundary",
                    "versioned_module_contract",
                    "signed_updates_with_rollback",
                    "tailscale_identity_enforcement",
                    "store_policy_profile_enforcement",
                    "permission_allowlist",
                    "auditability",
                    "companion_app_setup_handshake",
                    "app_store_discovery",
                    "device_targeted_app_push",
                ],
                "module_contract_fields": [
                    "id",
                    "version",
                    "entrypoint",
                    "slots",
                    "permissions",
                    "ui_schema_version",
                    "display_name",
                    "description",
                ],
                "permission_allowlist": allowed_permissions(),
                "signed_updates_required": bool(policy.get("require_signed_updates", True)),
                "tailscale_only": bool(policy.get("tailscale_only", True)),
                "primary_function": _companion_primary_function(),
                "setup_blueprint": _companion_setup_blueprint(access_mode=access_mode),
                "api_endpoints": list(_ENDPOINTS),
            }
        )

    async def api_companion_studio_capabilities(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response(
            {
                "ok": True,
                "api_version": "v1",
                "generated_at": _now_iso(),
                **_studio_capability_catalog(),
            }
        )

    async def api_companion_policy_profiles(request: web.Request) -> web.Response:
        require_api_access(request)
        rows = [item.to_dict() for item in list_policy_profiles()]
        return web.json_response({"ok": True, "count": len(rows), "profiles": rows})

    async def api_companion_policy_profile_get(request: web.Request) -> web.Response:
        require_api_access(request)
        profile_id = str(request.match_info.get("profile_id") or "").strip()
        if not profile_id:
            raise web.HTTPBadRequest(text="missing profile_id")
        profile = get_policy_profile(profile_id)
        if profile.profile_id != str(profile_id).strip().lower():
            return web.json_response(
                {"ok": False, "error": f"policy profile not found: {profile_id}"},
                status=404,
            )
        return web.json_response({"ok": True, "profile": profile.to_dict()})

    async def api_companion_compliance_check(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer_identity = _require_control_plane_identity(request, kernel)
        payload = await read_json(request)
        bundle_dir = _bundle_path_from_payload(payload)
        actor = _actor_from_payload(payload)

        verifier = _new_verifier(kernel)
        verify_report = verifier.verify_bundle(bundle_dir)
        verify_payload = verify_report.to_dict()
        verify_payload["bundle_dir"] = str(bundle_dir)

        compliance = _run_compliance_check(
            kernel=kernel,
            payload=payload,
            bundle_dir=bundle_dir,
            verify_report=verify_report,
            actor=actor,
            peer_identity=peer_identity,
        )
        status = 200 if bool(compliance.get("ok")) else 400
        _audit(kernel).append(
            "compliance.check",
            actor=actor,
            peer_identity=peer_identity,
            details={
                "bundle_dir": str(bundle_dir),
                "ok": bool(compliance.get("ok")),
                "policy_profile_id": str((compliance.get("report") or {}).get("policy_profile_id") or ""),
                "report_id": str((compliance.get("report") or {}).get("report_id") or ""),
            },
        )
        return web.json_response(
            {
                "ok": bool(compliance.get("ok")),
                "bundle_dir": str(bundle_dir),
                "verify": verify_payload,
                "compliance": compliance,
            },
            status=status,
        )

    async def api_companion_bootstrap(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        runtime = ModuleRuntime(kernel)
        include_slot_payloads = _boolish(
            request.query.get("include_slot_payloads"),
            default=True,
        )
        data = runtime.bootstrap(include_slot_payloads=include_slot_payloads)
        policy = kernel.load_policy()
        device_id = str(request.query.get("device_id") or "").strip()
        device = None
        if device_id:
            row = DeviceRegistry(kernel).get(device_id)
            device = row.to_dict() if row else None
        access_mode = str(getattr(getattr(config, "server", None), "access_mode", "local") or "local")
        app_store_channel = str(request.query.get("channel") or "").strip()
        if not app_store_channel:
            app_store_channel = str((device or {}).get("channel") or "stable").strip() or "stable"
        app_store_count = len(ReleaseRegistry(kernel).latest_by_module(channel=app_store_channel))
        return web.json_response(
            {
                "ok": True,
                "api_version": "v1",
                "generated_at": _now_iso(),
                "kernel": kernel.status(),
                "policy": {
                    "tailscale_only": bool(policy.get("tailscale_only", True)),
                    "tailscale_suffix": str(policy.get("tailscale_suffix") or ".ts.net"),
                    "require_signed_updates": bool(policy.get("require_signed_updates", True)),
                },
                "device": device,
                "mission": {
                    "primary_function": _companion_primary_function(),
                    "setup": _companion_setup_blueprint(access_mode=access_mode),
                },
                "app_store": {
                    "channel": app_store_channel,
                    "apps_published": int(app_store_count),
                    "catalog_endpoint": "/api/companion/v1/app-store",
                    "push_endpoint_template": "/api/companion/v1/devices/{device_id}/apps/{module_id}/push",
                },
                **data,
            }
        )

    async def api_companion_app_store(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        channel = str(request.query.get("channel") or "stable").strip() or "stable"
        device_id = str(request.query.get("device_id") or "").strip()
        include_ineligible = _boolish(request.query.get("include_ineligible"), default=True)

        device_row = DeviceRegistry(kernel).get(device_id) if device_id else None
        if device_id and device_row is None:
            return web.json_response(
                {"ok": False, "error": f"device not found: {device_id}"},
                status=404,
            )

        app_version = str(request.query.get("app_version") or "").strip()
        if (not app_version) and device_row is not None:
            app_version = str(device_row.app_version or "").strip()

        capabilities = _csv_list(request.query.get("capabilities"))
        if (not capabilities) and device_row is not None:
            capabilities = _device_capabilities(device_row)

        catalog = _app_store_catalog(
            kernel=kernel,
            channel=channel,
            device_id=device_id,
            app_version=app_version,
            capabilities=capabilities,
            include_ineligible=include_ineligible,
        )
        return web.json_response(
            {
                "ok": True,
                "api_version": "v1",
                "generated_at": _now_iso(),
                "channel": channel,
                "device": device_row.to_dict() if device_row is not None else None,
                "app_version": app_version,
                "capabilities": list(capabilities),
                **catalog,
            }
        )

    async def api_companion_modules(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        reg = ModuleRegistry(kernel)
        rows = [m.to_dict() for m in reg.list()]
        return web.json_response({"ok": True, "count": len(rows), "modules": rows})

    async def api_companion_slots(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        runtime = ModuleRuntime(kernel)
        slots = runtime.slot_index()
        return web.json_response(
            {
                "ok": True,
                "slots": slots,
                "enabled_modules": len(runtime.enabled_modules()),
            }
        )

    async def api_companion_slot_get(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        runtime = ModuleRuntime(kernel)
        slot = str(request.match_info.get("slot") or "").strip()
        if not slot:
            raise web.HTTPBadRequest(text="missing slot")
        out = runtime.render_slot(slot)
        out["ok"] = True
        return web.json_response(out)

    async def api_companion_module_enable(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer = _require_control_plane_identity(request, kernel)
        module_id = str(request.match_info.get("module_id") or "").strip()
        if not module_id:
            raise web.HTTPBadRequest(text="missing module_id")
        reg = ModuleRegistry(kernel)
        row = reg.set_enabled(module_id, True, timestamp=_now_iso())
        if row is None:
            return web.json_response({"ok": False, "error": f"module not found: {module_id}"}, status=404)
        _audit(kernel).append(
            "module.enable",
            peer_identity=peer,
            details={"module_id": module_id, "status": "enabled"},
        )
        return web.json_response({"ok": True, "module": row.to_dict()})

    async def api_companion_module_disable(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer = _require_control_plane_identity(request, kernel)
        module_id = str(request.match_info.get("module_id") or "").strip()
        if not module_id:
            raise web.HTTPBadRequest(text="missing module_id")
        reg = ModuleRegistry(kernel)
        row = reg.set_enabled(module_id, False, timestamp=_now_iso())
        if row is None:
            return web.json_response({"ok": False, "error": f"module not found: {module_id}"}, status=404)
        _audit(kernel).append(
            "module.disable",
            peer_identity=peer,
            details={"module_id": module_id, "status": "disabled"},
        )
        return web.json_response({"ok": True, "module": row.to_dict()})

    async def api_companion_device_app_push(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer_identity = _require_control_plane_identity(request, kernel)
        payload = await read_json(request)
        device_id = str(request.match_info.get("device_id") or "").strip()
        module_id = str(request.match_info.get("module_id") or "").strip()
        if not device_id:
            raise web.HTTPBadRequest(text="missing device_id")
        if not module_id:
            raise web.HTTPBadRequest(text="missing module_id")
        actor = _actor_from_payload(payload)
        response_payload, status = run_companion_device_app_push(
            kernel=kernel,
            device_id=device_id,
            module_id=module_id,
            payload=payload,
            peer_identity=peer_identity,
            actor=actor,
            now_iso=_now_iso(),
        )
        return web.json_response(response_payload, status=status)

    async def api_companion_studio_build_bundle(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer_identity = _require_control_plane_identity(request, kernel)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="json body must be an object")
        policy = kernel.load_policy()
        secret = str(os.environ.get("THOMAS_COMPANION_UPDATE_SECRET") or "").strip()
        studio = BundleStudio(
            kernel,
            secret=secret,
            require_signature=bool(policy.get("require_signed_updates", True)),
        )
        try:
            result = studio.build_bundle(payload)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        out = {"ok": True, **result.to_dict()}
        _audit(kernel).append(
            "studio.build_bundle",
            actor=_actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "bundle_dir": out.get("bundle_dir"),
                "file_count": out.get("file_count"),
                "module_id": (((out.get("manifest") or {}).get("module") or {}).get("id")),
                "module_version": (((out.get("manifest") or {}).get("module") or {}).get("version")),
            },
        )
        return web.json_response(out)

    async def api_companion_preview_bundle(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer_identity = _require_control_plane_identity(request, kernel)
        payload = await read_json(request)
        bundle_dir = _bundle_path_from_payload(payload)
        verifier = _new_verifier(kernel)
        report = verifier.verify_bundle(bundle_dir)
        if not report.ok or report.manifest is None:
            return web.json_response(
                {
                    "ok": False,
                    "bundle_dir": str(bundle_dir),
                    "errors": list(report.errors),
                    "warnings": list(report.warnings),
                    "preview": None,
                },
                status=400,
            )
        module = report.manifest.module
        entry_payload = _module_payload_from_bundle(
            bundle_dir,
            module_id=module.module_id,
            entrypoint=module.entrypoint,
        )
        preview = {
            "module": module.to_dict(),
            "slots": {
                slot: [
                    {
                        "module_id": module.module_id,
                        "version": module.version,
                        "display_name": module.display_name,
                        "entrypoint": module.entrypoint,
                        "permissions": list(module.permissions),
                        "payload": entry_payload,
                    }
                ]
                for slot in list(module.slots)
            },
        }
        _audit(kernel).append(
            "bundle.preview",
            actor=_actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "bundle_dir": str(bundle_dir),
                "module_id": module.module_id,
                "module_version": module.version,
                "slots": list(module.slots),
            },
        )
        return web.json_response(
            {
                "ok": True,
                "bundle_dir": str(bundle_dir),
                "warnings": list(report.warnings),
                "preview": preview,
            }
        )

    async def api_companion_verify_bundle(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer_identity = _require_control_plane_identity(request, kernel)
        payload = await read_json(request)
        bundle_dir = _bundle_path_from_payload(payload)
        verifier = _new_verifier(kernel)
        report = verifier.verify_bundle(bundle_dir)
        out = report.to_dict()
        out["peer_identity"] = peer_identity
        out["bundle_dir"] = str(bundle_dir)
        _audit(kernel).append(
            "bundle.verify",
            actor=_actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "bundle_dir": str(bundle_dir),
                "ok": bool(report.ok),
                "errors": list(report.errors),
                "warnings": list(report.warnings),
            },
        )
        status = 200 if report.ok else 400
        return web.json_response(out, status=status)

    async def api_companion_apply_bundle(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer_identity = _require_control_plane_identity(request, kernel)
        payload = await read_json(request)
        bundle_dir = _bundle_path_from_payload(payload)
        dry_run = _boolish(payload.get("dry_run"), default=True)
        if "execute" in payload:
            dry_run = not _boolish(payload.get("execute"), default=False)

        verifier = _new_verifier(kernel)
        verify_report = verifier.verify_bundle(bundle_dir)
        verify_payload = verify_report.to_dict()
        verify_payload["bundle_dir"] = str(bundle_dir)
        if not verify_report.ok:
            _audit(kernel).append(
                "bundle.apply",
                actor=_actor_from_payload(payload),
                peer_identity=peer_identity,
                details={
                    "bundle_dir": str(bundle_dir),
                    "ok": False,
                    "stage": "verify",
                    "errors": list(verify_report.errors),
                },
            )
            return web.json_response(
                {
                    "ok": False,
                    "errors": list(verify_report.errors),
                    "warnings": list(verify_report.warnings),
                    "bundle_dir": str(bundle_dir),
                    "verify": verify_payload,
                },
                status=400,
            )

        compliance_payload = _run_compliance_check(
            kernel=kernel,
            payload=payload,
            bundle_dir=bundle_dir,
            verify_report=verify_report,
            actor=_actor_from_payload(payload),
            peer_identity=peer_identity,
        )
        if not bool(compliance_payload.get("ok")):
            report = compliance_payload.get("report") or {}
            _audit(kernel).append(
                "bundle.apply",
                actor=_actor_from_payload(payload),
                peer_identity=peer_identity,
                details={
                    "bundle_dir": str(bundle_dir),
                    "ok": False,
                    "stage": "compliance",
                    "policy_profile_id": str(report.get("policy_profile_id") or ""),
                    "compliance_report_id": str(report.get("report_id") or ""),
                    "blocking_violations": int((report.get("counts") or {}).get("blocking_violations") or 0),
                },
            )
            return web.json_response(
                {
                    "ok": False,
                    "errors": ["compliance check failed"],
                    "warnings": list((compliance_payload.get("report") or {}).get("warnings") or []),
                    "bundle_dir": str(bundle_dir),
                    "verify": verify_payload,
                    "compliance": compliance_payload,
                },
                status=400,
            )

        applier = UpdateApplier(kernel, verifier=verifier)
        result = applier.apply_bundle(bundle_dir, dry_run=dry_run)
        result["peer_identity"] = peer_identity
        result["bundle_dir"] = str(bundle_dir)
        _audit(kernel).append(
            "bundle.apply",
            actor=_actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "bundle_dir": str(bundle_dir),
                "ok": bool(result.get("ok")),
                "dry_run": bool(result.get("dry_run")),
                "module_id": str(result.get("module_id") or ""),
                "errors": list(result.get("errors") or []),
                "warnings": list(result.get("warnings") or []),
            },
        )
        status = 200 if bool(result.get("ok")) else 400
        return web.json_response(result, status=status)

    async def api_companion_ship(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        peer_identity = _require_control_plane_identity(request, kernel)
        payload = await read_json(request)
        bundle_dir = _bundle_path_from_payload(payload)
        channel = str(payload.get("channel") or "stable").strip() or "stable"
        actor = _actor_from_payload(payload)
        execute = _boolish(payload.get("execute"), default=True)
        result_payload, status = run_companion_ship(
            kernel=kernel,
            payload=payload,
            bundle_dir=bundle_dir,
            channel=channel,
            actor=actor,
            execute=execute,
            peer_identity=peer_identity,
            verifier=_new_verifier(kernel),
            now_iso=_now_iso(),
        )
        return web.json_response(result_payload, status=status)

    app.router.add_get("/api/companion/v1/status", api_companion_status)
    app.router.add_get("/api/companion/v1/contract", api_companion_contract)
    app.router.add_get("/api/companion/v1/studio/capabilities", api_companion_studio_capabilities)
    app.router.add_get("/api/companion/v1/policy/profiles", api_companion_policy_profiles)
    app.router.add_get(
        "/api/companion/v1/policy/profile/{profile_id}",
        api_companion_policy_profile_get,
    )
    app.router.add_post("/api/companion/v1/compliance/check", api_companion_compliance_check)
    app.router.add_get("/api/companion/v1/bootstrap", api_companion_bootstrap)
    app.router.add_get("/api/companion/v1/app-store", api_companion_app_store)
    app.router.add_get("/api/companion/v1/modules", api_companion_modules)
    app.router.add_get("/api/companion/v1/slots", api_companion_slots)
    app.router.add_get("/api/companion/v1/slots/{slot}", api_companion_slot_get)
    app.router.add_post("/api/companion/v1/modules/{module_id}/enable", api_companion_module_enable)
    app.router.add_post("/api/companion/v1/modules/{module_id}/disable", api_companion_module_disable)
    app.router.add_post(
        "/api/companion/v1/devices/{device_id}/apps/{module_id}/push",
        api_companion_device_app_push,
    )
    app.router.add_post("/api/companion/v1/studio/build-bundle", api_companion_studio_build_bundle)
    app.router.add_post("/api/companion/v1/bundles/preview", api_companion_preview_bundle)
    app.router.add_post("/api/companion/v1/bundles/verify", api_companion_verify_bundle)
    app.router.add_post("/api/companion/v1/bundles/apply", api_companion_apply_bundle)
    app.router.add_post("/api/companion/v1/ship", api_companion_ship)
    register_companion_device_release_routes(
        app,
        deps=CompanionDeviceReleaseDeps(
            require_api_access=require_api_access,
            read_json=read_json,
            config=config,
            kernel_from_config=_kernel_from_config,
            require_control_plane_identity=_require_control_plane_identity,
            string_list=_string_list,
            installed_modules_from_payload=_installed_modules_from_payload,
            actor_from_payload=_actor_from_payload,
            now_iso=_now_iso,
            audit_for=_audit,
            int_or_none=_int_or_none,
            new_verifier=_new_verifier,
            run_compliance_check=_run_compliance_check,
            bundle_path_from_payload=_bundle_path_from_payload,
            release_manifest=_release_manifest,
            release_bundle_dir=_release_bundle_dir,
            zip_bundle=_zip_bundle,
        ),
    )
