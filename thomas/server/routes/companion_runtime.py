"""Shared runtime helpers for companion aiohttp routes."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.companion.audit import CompanionAuditLog
from thomas.companion.contracts import allowed_permissions
from thomas.companion.devices import DeviceRegistry
from thomas.companion.kernel import CompanionKernel
from thomas.companion.policy import (
    PolicyComplianceService,
    list_policy_profiles,
    resolve_policy_profile,
)
from thomas.companion.releases import ReleaseRegistry
from thomas.companion.update import BundleVerifier, UpdateApplier

log = logging.getLogger(__name__)


def _boolish(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


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


def _csv_list(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            out.extend(_csv_list(item))
        return sorted(set(out))
    text = str(value or "").strip()
    if not text:
        return []
    for part in text.split(","):
        token = str(part or "").strip()
        if token:
            out.append(token)
    return sorted(set(out))


def _device_capabilities(device: Any) -> list[str]:
    runtime_caps = _string_list(list(getattr(device, "runtime_capability_set", []) or []))
    if runtime_caps:
        return runtime_caps
    return _string_list(list(getattr(device, "capabilities", []) or []))


def _release_module_metadata(release_row: dict[str, Any]) -> tuple[str, str]:
    display_name = str(release_row.get("module_id") or "").strip() or "module"
    description = str(release_row.get("release_notes") or "").strip()
    try:
        manifest = _release_manifest(release_row)
        module_payload = manifest.get("module") if isinstance(manifest, dict) else {}
        if isinstance(module_payload, dict):
            display_name = str(module_payload.get("display_name") or "").strip() or display_name
            description = str(module_payload.get("description") or "").strip() or description
    except Exception:
        pass
    return display_name, description


def _app_store_catalog(
    *,
    kernel: CompanionKernel,
    channel: str,
    device_id: str,
    app_version: str,
    capabilities: list[str],
    include_ineligible: bool,
) -> dict[str, Any]:
    reg = ReleaseRegistry(kernel)
    latest = reg.latest_by_module(channel=channel)
    apps: list[dict[str, Any]] = []
    eligible_count = 0
    for module_id in sorted(latest.keys()):
        rel = latest[module_id]
        eligible = reg.release_allowed_for_device(
            rel,
            device_id=device_id,
            app_version=app_version,
            capabilities=capabilities,
            pinned=False,
        )
        if eligible:
            eligible_count += 1
        if (not include_ineligible) and (not eligible):
            continue
        rel_payload = rel.to_dict()
        display_name, description = _release_module_metadata(rel_payload)
        apps.append(
            {
                "module_id": rel.module_id,
                "display_name": display_name,
                "description": description,
                "latest_release": rel_payload,
                "compatibility": {
                    "eligible": bool(eligible),
                    "status": str(rel.status or "active"),
                    "rollout_pct": int(rel.rollout_pct),
                    "min_app_version": str(rel.min_app_version or ""),
                    "required_capabilities": list(rel.required_capabilities),
                },
                "install": {
                    "push_endpoint": (
                        f"/api/companion/v1/devices/{device_id}/apps/{rel.module_id}/push" if device_id else ""
                    ),
                    "release_manifest_endpoint": (f"/api/companion/v1/releases/{rel.release_id}/manifest"),
                    "release_download_endpoint": (f"/api/companion/v1/releases/{rel.release_id}/download"),
                    "updates_check_endpoint": (
                        f"/api/companion/v1/devices/{device_id}/updates/check" if device_id else ""
                    ),
                },
            }
        )
    return {
        "count": len(apps),
        "eligible_count": int(eligible_count),
        "apps": apps,
    }


def _coerce_policy_context(payload: Any, *, kernel: CompanionKernel) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    target_device_id = str(body.get("target_device_id") or body.get("device_id") or "").strip()
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
    requested_policy_profile_id = str(body.get("policy_profile_id") or body.get("target_policy_profile") or "").strip()
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
            "pair_device",
            "publish_release",
            "push_release_to_device",
        ],
        "data_primitives": [
            "local_state",
            "secure_storage",
            "remote_http_json",
            "websocket_stream",
            "headless_web_runtime",
            "device_sensor",
            "push_channel",
            "companion_app_store",
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
            "headless_web_module": {
                "module": {
                    "id": "companion.headless.web",
                    "version": "0.1.0",
                    "entrypoint": "modules/companion.headless.web/ui/screen.json",
                    "slots": ["home.main"],
                    "permissions": ["network.egress", "storage.read", "ui.render"],
                    "ui_schema_version": "0.1.0",
                    "display_name": "Headless Web Runtime",
                    "description": "Websocket-backed headless website surface for companion.",
                },
                "screen_payload": {
                    "screen_id": "headless-web-runtime",
                    "title": "Headless Web Runtime",
                    "components": [
                        {
                            "type": "webview",
                            "url": "https://example.com/headless",
                            "mode": "headless",
                            "stream": {"type": "websocket", "url": "wss://example.com/realtime"},
                        }
                    ],
                },
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
    except (OSError, ValueError) as exc:
        log.warning("Invalid bundle entrypoint payload json (payload/%s): %s", rel, exc)
        raise web.HTTPBadRequest(text="invalid bundle entrypoint payload json") from exc


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
    except (OSError, ValueError) as exc:
        log.error("Invalid release manifest json (%s): %s", manifest_path, exc)
        raise web.HTTPInternalServerError(text="invalid release manifest json") from exc
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


def run_companion_device_app_push(
    *,
    kernel: CompanionKernel,
    device_id: str,
    module_id: str,
    payload: Any,
    peer_identity: str,
    actor: str,
    now_iso: str,
) -> tuple[dict[str, Any], int]:
    body = payload if isinstance(payload, dict) else {}
    devices = DeviceRegistry(kernel)
    device = devices.get(device_id)
    if device is None:
        return {"ok": False, "error": f"device not found: {device_id}"}, 404

    channel = str(body.get("channel") or device.channel or "stable").strip() or "stable"
    release_id = str(body.get("release_id") or "").strip()
    execute = _boolish(body.get("execute"), default=True)
    capabilities = _string_list(body.get("capabilities")) or _device_capabilities(device)
    app_version = str(body.get("app_version") or device.app_version or "").strip()

    releases = ReleaseRegistry(kernel)
    selected = releases.get(release_id) if release_id else None
    if release_id and selected is None:
        return {"ok": False, "error": f"release not found: {release_id}"}, 404

    if selected is None:
        for rel in releases.list(channel=channel, module_id=module_id, limit=300):
            if releases.release_allowed_for_device(
                rel,
                device_id=device_id,
                app_version=app_version,
                capabilities=capabilities,
                pinned=False,
            ):
                selected = rel
                break
        if selected is None:
            return {
                "ok": False,
                "error": "no eligible release found for device/module",
                "module_id": module_id,
                "channel": channel,
                "device_id": device_id,
            }, 404

    if selected.module_id != module_id:
        return {
            "ok": False,
            "error": "selected release module mismatch",
            "expected_module_id": module_id,
            "actual_module_id": selected.module_id,
        }, 400

    eligible = releases.release_allowed_for_device(
        selected,
        device_id=device_id,
        app_version=app_version,
        capabilities=capabilities,
        pinned=False,
    )
    if not eligible:
        return {
            "ok": False,
            "error": "selected release is not eligible for this device",
            "device_id": device_id,
            "release": selected.to_dict(),
        }, 400

    device_after = device
    if execute:
        updated = devices.set_pinned_release(device_id, selected.release_id, timestamp=now_iso)
        if updated is None:
            return {"ok": False, "error": f"device not found: {device_id}"}, 404
        device_after = updated

    response_payload = {
        "ok": True,
        "planned": not execute,
        "device_id": device_id,
        "module_id": module_id,
        "channel": channel,
        "release": selected.to_dict(),
        "device": device_after.to_dict(),
        "install": {
            "updates_check_endpoint": f"/api/companion/v1/devices/{device_id}/updates/check",
            "release_manifest_endpoint": (f"/api/companion/v1/releases/{selected.release_id}/manifest"),
            "release_download_endpoint": (f"/api/companion/v1/releases/{selected.release_id}/download"),
        },
    }
    CompanionAuditLog(kernel).append(
        "app.push",
        actor=actor or "api",
        peer_identity=peer_identity,
        details={
            "device_id": device_id,
            "module_id": module_id,
            "release_id": selected.release_id,
            "channel": channel,
            "planned": bool(not execute),
        },
    )
    return response_payload, 200


def run_companion_ship(
    *,
    kernel: CompanionKernel,
    payload: Any,
    bundle_dir: Path,
    channel: str,
    actor: str,
    execute: bool,
    peer_identity: str,
    verifier: BundleVerifier,
    now_iso: str,
) -> tuple[dict[str, Any], int]:
    verify_report = verifier.verify_bundle(bundle_dir)
    verify_payload = verify_report.to_dict()
    verify_payload["bundle_dir"] = str(bundle_dir)

    compliance_payload: dict[str, Any] | None = None
    if not verify_report.ok:
        CompanionAuditLog(kernel).append(
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
        return {
            "ok": False,
            "channel": channel,
            "verify": verify_payload,
            "apply": None,
            "release": None,
            "compliance": None,
        }, 400

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
        CompanionAuditLog(kernel).append(
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
                "blocking_violations": int((report.get("counts") or {}).get("blocking_violations") or 0),
            },
        )
        return {
            "ok": False,
            "channel": channel,
            "verify": verify_payload,
            "apply": None,
            "release": None,
            "compliance": compliance_payload,
        }, 400

    applier = UpdateApplier(kernel, verifier=verifier)
    apply_result = applier.apply_bundle(bundle_dir, dry_run=not execute)
    if not bool(apply_result.get("ok")):
        CompanionAuditLog(kernel).append(
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
        return {
            "ok": False,
            "channel": channel,
            "verify": verify_payload,
            "apply": apply_result,
            "release": None,
            "compliance": compliance_payload,
        }, 400

    release_payload: dict[str, Any] | None = None
    publish_result: dict[str, Any] | None = None
    if execute:
        publish_result = ReleaseRegistry(kernel).publish_from_bundle(
            bundle_dir,
            channel=channel,
            published_by=actor,
            verifier=verifier,
            rollout_pct=(_int_or_none((payload or {}).get("rollout_pct")) or 100),
            target_devices=_string_list((payload or {}).get("target_devices")),
            exclude_devices=_string_list((payload or {}).get("exclude_devices")),
            min_app_version=str((payload or {}).get("min_app_version") or "").strip(),
            required_capabilities=_string_list((payload or {}).get("required_capabilities")),
            status=str((payload or {}).get("status") or "active").strip() or "active",
            policy_profile_id=str(
                ((compliance_payload or {}).get("report") or {}).get("policy_profile_id") or "strict_global"
            ),
            compliance_report_id=str(((compliance_payload or {}).get("report") or {}).get("report_id") or ""),
            compliance_status=("pass" if bool((compliance_payload or {}).get("ok")) else "block"),
            compliance_violations=(
                _int_or_none(
                    (((compliance_payload or {}).get("report") or {}).get("counts") or {}).get("blocking_violations")
                )
                or 0
            ),
            compliance_warnings=(
                _int_or_none((((compliance_payload or {}).get("report") or {}).get("counts") or {}).get("warnings"))
                or 0
            ),
            compliance_checked_at=str(((compliance_payload or {}).get("report") or {}).get("checked_at") or ""),
            timestamp=now_iso,
        )
        if not bool(publish_result.get("ok")):
            CompanionAuditLog(kernel).append(
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
            return {
                "ok": False,
                "channel": channel,
                "verify": verify_payload,
                "apply": apply_result,
                "release": publish_result,
                "compliance": compliance_payload,
            }, 400
        release_payload = publish_result

    result_payload = {
        "ok": True,
        "channel": channel,
        "verify": verify_payload,
        "apply": apply_result,
        "release": release_payload,
        "compliance": compliance_payload,
    }
    CompanionAuditLog(kernel).append(
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
            "policy_profile_id": str(((compliance_payload or {}).get("report") or {}).get("policy_profile_id") or ""),
            "compliance_report_id": str(((compliance_payload or {}).get("report") or {}).get("report_id") or ""),
        },
    )
    return result_payload, 200
