"""aiohttp routes for companion kernel/module control plane."""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from thomas.companion.audit import CompanionAuditLog
from thomas.companion.contracts import allowed_permissions
from thomas.companion.devices import DeviceRegistry
from thomas.companion.kernel import CompanionKernel, KERNEL_VERSION
from thomas.companion.network import TailscalePolicy, assert_peer_allowed
from thomas.companion.policy import (
    PolicyComplianceService,
    get_policy_profile,
    list_policy_profiles,
    resolve_policy_profile,
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


def _string_list(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            out.append(text)
    return sorted(set(out))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _coerce_policy_context(payload: Any, *, kernel: CompanionKernel) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    target_device_id = str(
        body.get("target_device_id")
        or body.get("device_id")
        or ""
    ).strip()
    target_device = DeviceRegistry(kernel).get(target_device_id) if target_device_id else None

    runtime_caps = _string_list(body.get("runtime_capability_set"))
    if not runtime_caps and target_device is not None:
        runtime_caps = [str(x) for x in list(target_device.runtime_capability_set) if str(x).strip()]
    if not runtime_caps and target_device is not None:
        runtime_caps = [str(x) for x in list(target_device.capabilities) if str(x).strip()]

    platform = str(body.get("platform") or "").strip() or (target_device.platform if target_device else "")
    distribution_channel = str(body.get("distribution_channel") or "").strip() or (
        target_device.distribution_channel if target_device else ""
    )
    storefront_region = str(body.get("storefront_region") or "").strip() or (
        target_device.storefront_region if target_device else ""
    )
    requested_policy_profile_id = str(
        body.get("policy_profile_id")
        or body.get("target_policy_profile")
        or ""
    ).strip()
    resolved_policy_profile_id = resolve_policy_profile(
        platform=platform,
        distribution_channel=distribution_channel,
        storefront_region=storefront_region,
        requested_profile_id=requested_policy_profile_id,
    )

    return {
        "target_device_id": target_device_id,
        "platform": platform,
        "distribution_channel": distribution_channel,
        "storefront_region": storefront_region,
        "requested_policy_profile_id": requested_policy_profile_id,
        "policy_profile_id": resolved_policy_profile_id,
        "runtime_capability_set": runtime_caps,
        "required_capabilities": _string_list(body.get("required_capabilities")),
        "commerce_model": str(body.get("commerce_model") or "").strip(),
        "store_billing_enabled": _boolish(body.get("store_billing_enabled"), default=False),
        "ugc_enabled": _boolish(body.get("ugc_enabled"), default=False),
        "moderation_controls": _string_list(body.get("moderation_controls")),
        "age_gate_enabled": _boolish(body.get("age_gate_enabled"), default=False),
        "collects_personal_data": _boolish(body.get("collects_personal_data"), default=False),
        "privacy_policy_url": str(body.get("privacy_policy_url") or "").strip(),
        "url_allowlist": _string_list(body.get("url_allowlist") or body.get("external_navigation_allowlist")),
    }


def _studio_capability_catalog() -> dict[str, Any]:
    profiles = [item.to_dict() for item in list_policy_profiles()]
    return {
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
        "default_slots": [
            "home.main",
            "home.secondary",
            "search.main",
            "settings.main",
            "profile.main",
        ],
        "ui_component_primitives": [
            "container",
            "text",
            "image",
            "icon",
            "button",
            "input",
            "toggle",
            "list",
            "tabs",
            "chart",
            "form",
            "webview",
            "map",
            "video",
        ],
        "action_primitives": [
            "navigate",
            "open_url",
            "api_call",
            "persist_state",
            "emit_event",
            "show_toast",
            "request_permission",
        ],
        "data_primitives": [
            "local_state",
            "secure_storage",
            "remote_http_json",
            "websocket_stream",
            "device_sensor",
            "push_channel",
        ],
        "release_controls": {
            "supports_rollout_pct": True,
            "supports_target_devices": True,
            "supports_exclude_devices": True,
            "supports_min_app_version": True,
            "supports_required_capabilities": True,
            "supports_status": True,
            "supports_device_pinning": True,
            "supports_release_promote": True,
            "supports_release_rollback": True,
            "supports_policy_profile_selection": True,
            "supports_compliance_check": True,
            "supports_store_targeting": True,
        },
        "policy_profiles": profiles,
        "templates": {
            "module": {
                "id": "companion.custom",
                "version": "0.1.0",
                "entrypoint": "modules/companion.custom/ui/screen.json",
                "slots": ["home.main"],
                "permissions": ["ui.render", "storage.read"],
                "ui_schema_version": "0.1.0",
                "display_name": "Custom Module",
                "description": "Generated from Thomas Studio",
            },
            "screen_payload": {
                "screen_id": "home",
                "title": "Custom Screen",
                "components": [
                    {"type": "text", "value": "hello from Thomas companion studio"},
                ],
            },
        },
    }


def _module_payload_from_bundle(bundle_dir: Path, *, module_id: str, entrypoint: str) -> Any:
    rel = str(entrypoint or "").replace("\\", "/").strip()
    module_prefix = f"modules/{module_id}/"
    if not rel.startswith(module_prefix):
        raise web.HTTPBadRequest(text="bundle module.entrypoint is outside module namespace")
    payload_path = (bundle_dir / "payload" / rel).resolve()
    if not payload_path.exists() or not payload_path.is_file():
        raise web.HTTPBadRequest(text=f"bundle entrypoint payload missing: payload/{rel}")
    try:
        return json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise web.HTTPBadRequest(text=f"invalid bundle entrypoint payload json: {exc}")


def _release_bundle_dir(release_row: dict[str, Any]) -> Path:
    raw = str(release_row.get("bundle_dir") or "").strip()
    if not raw:
        raise web.HTTPNotFound(text="release bundle_dir missing")
    bundle_dir = Path(raw).expanduser().resolve()
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        raise web.HTTPNotFound(text="release bundle_dir not found")
    return bundle_dir


def _release_manifest(release_row: dict[str, Any]) -> dict[str, Any]:
    manifest_path_raw = str(release_row.get("manifest_path") or "").strip()
    if manifest_path_raw:
        manifest_path = Path(manifest_path_raw).expanduser().resolve()
    else:
        manifest_path = _release_bundle_dir(release_row) / "manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        raise web.HTTPNotFound(text="release manifest not found")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise web.HTTPInternalServerError(text=f"invalid release manifest json: {exc}")
    if not isinstance(payload, dict):
        raise web.HTTPInternalServerError(text="invalid release manifest payload")
    return payload


def _zip_bundle(bundle_dir: Path) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in sorted(bundle_dir.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(bundle_dir).as_posix()
            zf.write(file_path, arcname=rel)
    return out.getvalue()


def _run_compliance_check(
    *,
    kernel: CompanionKernel,
    payload: Any,
    bundle_dir: Path,
    verify_report: Any,
    actor: str,
    peer_identity: str,
) -> dict[str, Any]:
    ctx = _coerce_policy_context(payload, kernel=kernel)
    report = PolicyComplianceService(kernel).check_bundle(
        bundle_dir=bundle_dir,
        verify_report=verify_report,
        platform=str(ctx.get("platform") or ""),
        distribution_channel=str(ctx.get("distribution_channel") or ""),
        storefront_region=str(ctx.get("storefront_region") or ""),
        policy_profile_id=str(ctx.get("policy_profile_id") or ""),
        runtime_capability_set=list(ctx.get("runtime_capability_set") or []),
        required_capabilities=list(ctx.get("required_capabilities") or []),
        commerce_model=str(ctx.get("commerce_model") or ""),
        store_billing_enabled=bool(ctx.get("store_billing_enabled")),
        ugc_enabled=bool(ctx.get("ugc_enabled")),
        moderation_controls=list(ctx.get("moderation_controls") or []),
        age_gate_enabled=bool(ctx.get("age_gate_enabled")),
        collects_personal_data=bool(ctx.get("collects_personal_data")),
        privacy_policy_url=str(ctx.get("privacy_policy_url") or ""),
        url_allowlist=list(ctx.get("url_allowlist") or []),
        actor=actor,
        peer_identity=peer_identity,
    )
    return {
        "ok": bool(report.ok),
        "report": report.to_dict(),
        "context": ctx,
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
                "policy_profiles": profiles,
                "endpoints": list(_ENDPOINTS),
            }
        )

    async def api_companion_contract(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        policy = kernel.load_policy()
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
                "policy_profile_id": str(
                    ((compliance.get("report") or {}).get("policy_profile_id") or "")
                ),
                "report_id": str(((compliance.get("report") or {}).get("report_id") or "")),
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
                **data,
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
        applier = UpdateApplier(kernel, verifier=_new_verifier(kernel))
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

        verifier = _new_verifier(kernel)
        verify_report = verifier.verify_bundle(bundle_dir)
        verify_payload = verify_report.to_dict()
        verify_payload["bundle_dir"] = str(bundle_dir)

        compliance_payload: dict[str, Any] | None = None
        if not verify_report.ok:
            _audit(kernel).append(
                "ship",
                actor=actor,
                peer_identity=peer_identity,
                details={
                    "bundle_dir": str(bundle_dir),
                    "channel": channel,
                    "ok": False,
                    "stage": "verify",
                    "errors": list(verify_report.errors),
                },
            )
            return web.json_response(
                {
                    "ok": False,
                    "channel": channel,
                    "verify": verify_payload,
                    "apply": None,
                    "release": None,
                    "compliance": None,
                },
                status=400,
            )

        compliance_payload = _run_compliance_check(
            kernel=kernel,
            payload=payload,
            bundle_dir=bundle_dir,
            verify_report=verify_report,
            actor=actor,
            peer_identity=peer_identity,
        )
        if execute and not bool(compliance_payload.get("ok")):
            report = compliance_payload.get("report") or {}
            _audit(kernel).append(
                "ship",
                actor=actor,
                peer_identity=peer_identity,
                details={
                    "bundle_dir": str(bundle_dir),
                    "channel": channel,
                    "ok": False,
                    "stage": "compliance",
                    "policy_profile_id": str(report.get("policy_profile_id") or ""),
                    "compliance_report_id": str(report.get("report_id") or ""),
                    "blocking_violations": int(
                        ((report.get("counts") or {}).get("blocking_violations") or 0)
                    ),
                },
            )
            return web.json_response(
                {
                    "ok": False,
                    "channel": channel,
                    "verify": verify_payload,
                    "apply": None,
                    "release": None,
                    "compliance": compliance_payload,
                },
                status=400,
            )

        applier = UpdateApplier(kernel, verifier=verifier)
        apply_result = applier.apply_bundle(bundle_dir, dry_run=not execute)
        if not bool(apply_result.get("ok")):
            _audit(kernel).append(
                "ship",
                actor=actor,
                peer_identity=peer_identity,
                details={
                    "bundle_dir": str(bundle_dir),
                    "channel": channel,
                    "ok": False,
                    "stage": "apply",
                    "errors": list(apply_result.get("errors") or []),
                },
            )
            return web.json_response(
                {
                    "ok": False,
                    "channel": channel,
                    "verify": verify_payload,
                    "apply": apply_result,
                    "release": None,
                    "compliance": compliance_payload,
                },
                status=400,
            )

        release_payload: dict[str, Any] | None = None
        publish_result: dict[str, Any] | None = None
        if execute:
            publish_result = ReleaseRegistry(kernel).publish_from_bundle(
                bundle_dir,
                channel=channel,
                published_by=actor,
                verifier=verifier,
                rollout_pct=(_int_or_none(payload.get("rollout_pct")) or 100),
                target_devices=_string_list(payload.get("target_devices")),
                exclude_devices=_string_list(payload.get("exclude_devices")),
                min_app_version=str(payload.get("min_app_version") or "").strip(),
                required_capabilities=_string_list(payload.get("required_capabilities")),
                status=str(payload.get("status") or "active").strip() or "active",
                policy_profile_id=str(
                    ((compliance_payload or {}).get("report") or {}).get("policy_profile_id")
                    or "strict_global"
                ),
                compliance_report_id=str(
                    ((compliance_payload or {}).get("report") or {}).get("report_id") or ""
                ),
                compliance_status=(
                    "pass"
                    if bool((compliance_payload or {}).get("ok"))
                    else "block"
                ),
                compliance_violations=(
                    _int_or_none(
                        (((compliance_payload or {}).get("report") or {}).get("counts") or {}).get(
                            "blocking_violations"
                        )
                    )
                    or 0
                ),
                compliance_warnings=(
                    _int_or_none(
                        (((compliance_payload or {}).get("report") or {}).get("counts") or {}).get(
                            "warnings"
                        )
                    )
                    or 0
                ),
                compliance_checked_at=str(
                    ((compliance_payload or {}).get("report") or {}).get("checked_at") or ""
                ),
                timestamp=_now_iso(),
            )
            if not bool(publish_result.get("ok")):
                _audit(kernel).append(
                    "ship",
                    actor=actor,
                    peer_identity=peer_identity,
                    details={
                        "bundle_dir": str(bundle_dir),
                        "channel": channel,
                        "ok": False,
                        "stage": "publish",
                        "errors": list(publish_result.get("errors") or []),
                    },
                )
                return web.json_response(
                    {
                        "ok": False,
                        "channel": channel,
                        "verify": verify_payload,
                        "apply": apply_result,
                        "release": publish_result,
                        "compliance": compliance_payload,
                    },
                    status=400,
                )
            release_payload = publish_result

        result_payload = {
            "ok": True,
            "channel": channel,
            "verify": verify_payload,
            "apply": apply_result,
            "release": release_payload,
            "compliance": compliance_payload,
        }
        _audit(kernel).append(
            "ship",
            actor=actor,
            peer_identity=peer_identity,
            details={
                "bundle_dir": str(bundle_dir),
                "channel": channel,
                "ok": True,
                "dry_run": not execute,
                "module_id": str(apply_result.get("module_id") or ""),
                "release_id": (
                    str(((publish_result or {}).get("release") or {}).get("release_id") or "")
                    if publish_result is not None
                    else ""
                ),
                "policy_profile_id": str(
                    (((compliance_payload or {}).get("report") or {}).get("policy_profile_id") or "")
                ),
                "compliance_report_id": str(
                    (((compliance_payload or {}).get("report") or {}).get("report_id") or "")
                ),
            },
        )
        return web.json_response(result_payload)

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
    app.router.add_get("/api/companion/v1/modules", api_companion_modules)
    app.router.add_get("/api/companion/v1/slots", api_companion_slots)
    app.router.add_get("/api/companion/v1/slots/{slot}", api_companion_slot_get)
    app.router.add_post("/api/companion/v1/modules/{module_id}/enable", api_companion_module_enable)
    app.router.add_post("/api/companion/v1/modules/{module_id}/disable", api_companion_module_disable)
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
