"""Aiohttp companion routes for device, release, and audit surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from thomas.companion.audit import CompanionAuditLog
from thomas.companion.devices import DeviceRegistry
from thomas.companion.kernel import CompanionKernel
from thomas.companion.policy import resolve_policy_profile
from thomas.companion.releases import ReleaseRegistry
from thomas.companion.update import BundleVerifier

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]
KernelFromConfigFn = Callable[[Any], CompanionKernel]
RequireControlPlaneIdentityFn = Callable[[web.Request, CompanionKernel], str]
StringListFn = Callable[[Any], list[str]]
InstalledModulesFn = Callable[[Any], dict[str, str]]
ActorFromPayloadFn = Callable[[Any], str]
NowIsoFn = Callable[[], str]
AuditForKernelFn = Callable[[CompanionKernel], CompanionAuditLog]
IntOrNoneFn = Callable[[Any], int | None]
NewVerifierFn = Callable[[CompanionKernel], BundleVerifier]
RunComplianceCheckFn = Callable[..., dict[str, Any]]
BundlePathFromPayloadFn = Callable[[Any], Path]
ReleaseManifestFn = Callable[[dict[str, Any]], dict[str, Any]]
ReleaseBundleDirFn = Callable[[dict[str, Any]], Path]
ZipBundleFn = Callable[[Path], bytes]


@dataclass
class CompanionDeviceReleaseDeps:
    """Dependency bundle for companion device/release route registration."""

    require_api_access: RequireAccessFn
    read_json: ReadJsonFn
    config: Any
    kernel_from_config: KernelFromConfigFn
    require_control_plane_identity: RequireControlPlaneIdentityFn
    string_list: StringListFn
    installed_modules_from_payload: InstalledModulesFn
    actor_from_payload: ActorFromPayloadFn
    now_iso: NowIsoFn
    audit_for: AuditForKernelFn
    int_or_none: IntOrNoneFn
    new_verifier: NewVerifierFn
    run_compliance_check: RunComplianceCheckFn
    bundle_path_from_payload: BundlePathFromPayloadFn
    release_manifest: ReleaseManifestFn
    release_bundle_dir: ReleaseBundleDirFn
    zip_bundle: ZipBundleFn


def register_companion_device_release_routes(
    app: web.Application,
    *,
    deps: CompanionDeviceReleaseDeps,
) -> None:
    """Attach companion device/release/audit API endpoints."""

    async def api_companion_devices(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        deps.require_control_plane_identity(request, kernel)
        channel = str(request.query.get("channel") or "").strip()
        rows = [item.to_dict() for item in DeviceRegistry(kernel).list(channel=channel)]
        return web.json_response({"ok": True, "count": len(rows), "devices": rows})

    async def api_companion_device_register(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="json body must be an object")
        device_id = str(payload.get("device_id") or "").strip()
        if not device_id:
            raise web.HTTPBadRequest(text="missing device_id")
        platform = str(payload.get("platform") or "").strip()
        distribution_channel = str(payload.get("distribution_channel") or "").strip()
        storefront_region = str(payload.get("storefront_region") or "").strip()
        policy_profile_id = resolve_policy_profile(
            platform=platform,
            distribution_channel=distribution_channel,
            storefront_region=storefront_region,
            requested_profile_id=str(payload.get("policy_profile_id") or "").strip(),
        )
        capabilities = [str(x) for x in list(payload.get("capabilities") or []) if str(x).strip()]
        runtime_capability_set = deps.string_list(payload.get("runtime_capability_set")) or capabilities
        row = DeviceRegistry(kernel).upsert(
            device_id=device_id,
            platform=platform,
            app_version=str(payload.get("app_version") or "").strip(),
            channel=str(payload.get("channel") or "stable").strip() or "stable",
            distribution_channel=distribution_channel,
            storefront_region=storefront_region,
            app_build_id=str(payload.get("app_build_id") or "").strip(),
            tailscale_identity=peer_identity,
            capabilities=capabilities,
            runtime_capability_set=runtime_capability_set,
            installed_modules=deps.installed_modules_from_payload(payload),
            metadata=dict(payload.get("metadata") or {}),
            policy_profile=policy_profile_id,
            timestamp=deps.now_iso(),
        )
        deps.audit_for(kernel).append(
            "device.register",
            actor=deps.actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "device_id": device_id,
                "channel": row.channel,
                "platform": row.platform,
                "distribution_channel": row.distribution_channel,
                "policy_profile": row.policy_profile,
            },
        )
        return web.json_response({"ok": True, "device": row.to_dict()})

    async def api_companion_device_heartbeat(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            payload = {}
        device_id = str(request.match_info.get("device_id") or "").strip()
        if not device_id:
            raise web.HTTPBadRequest(text="missing device_id")
        reg = DeviceRegistry(kernel)
        current = reg.get(device_id)
        if current is None:
            return web.json_response({"ok": False, "error": f"device not found: {device_id}"}, status=404)
        platform = str(payload.get("platform") or current.platform).strip()
        distribution_channel = str(payload.get("distribution_channel") or current.distribution_channel).strip()
        storefront_region = str(payload.get("storefront_region") or current.storefront_region).strip()
        runtime_capability_set = deps.string_list(payload.get("runtime_capability_set")) or list(
            current.runtime_capability_set
        )
        capabilities = [str(x) for x in list(payload.get("capabilities") or current.capabilities) if str(x).strip()]
        policy_profile_id = resolve_policy_profile(
            platform=platform,
            distribution_channel=distribution_channel,
            storefront_region=storefront_region,
            requested_profile_id=str(payload.get("policy_profile_id") or current.policy_profile).strip(),
        )
        row = reg.upsert(
            device_id=device_id,
            platform=platform,
            app_version=str(payload.get("app_version") or current.app_version).strip(),
            channel=str(payload.get("channel") or current.channel).strip() or "stable",
            distribution_channel=distribution_channel,
            storefront_region=storefront_region,
            app_build_id=str(payload.get("app_build_id") or current.app_build_id).strip(),
            tailscale_identity=peer_identity or current.tailscale_identity,
            capabilities=capabilities,
            runtime_capability_set=runtime_capability_set,
            installed_modules=(
                deps.installed_modules_from_payload(payload) or dict(current.installed_modules)
            ),
            metadata=dict(payload.get("metadata") or current.metadata),
            policy_profile=policy_profile_id,
            timestamp=deps.now_iso(),
        )
        deps.audit_for(kernel).append(
            "device.heartbeat",
            actor=deps.actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "device_id": device_id,
                "channel": row.channel,
                "platform": row.platform,
                "distribution_channel": row.distribution_channel,
                "policy_profile": row.policy_profile,
            },
        )
        return web.json_response({"ok": True, "device": row.to_dict()})

    async def api_companion_device_pin_release(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            payload = {}
        device_id = str(request.match_info.get("device_id") or "").strip()
        if not device_id:
            raise web.HTTPBadRequest(text="missing device_id")
        release_id = str(payload.get("release_id") or "").strip()
        if not release_id:
            raise web.HTTPBadRequest(text="missing release_id")
        release = ReleaseRegistry(kernel).get(release_id)
        if release is None:
            return web.json_response({"ok": False, "error": f"release not found: {release_id}"}, status=404)
        row = DeviceRegistry(kernel).set_pinned_release(device_id, release_id, timestamp=deps.now_iso())
        if row is None:
            return web.json_response({"ok": False, "error": f"device not found: {device_id}"}, status=404)
        deps.audit_for(kernel).append(
            "device.pin_release",
            actor=deps.actor_from_payload(payload),
            peer_identity=peer_identity,
            details={"device_id": device_id, "release_id": release_id},
        )
        return web.json_response({"ok": True, "device": row.to_dict(), "release": release.to_dict()})

    async def api_companion_device_unpin_release(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            payload = {}
        device_id = str(request.match_info.get("device_id") or "").strip()
        if not device_id:
            raise web.HTTPBadRequest(text="missing device_id")
        row = DeviceRegistry(kernel).set_pinned_release(device_id, "", timestamp=deps.now_iso())
        if row is None:
            return web.json_response({"ok": False, "error": f"device not found: {device_id}"}, status=404)
        deps.audit_for(kernel).append(
            "device.unpin_release",
            actor=deps.actor_from_payload(payload),
            peer_identity=peer_identity,
            details={"device_id": device_id},
        )
        return web.json_response({"ok": True, "device": row.to_dict()})

    async def api_companion_device_updates_check(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            payload = {}
        device_id = str(request.match_info.get("device_id") or "").strip()
        if not device_id:
            raise web.HTTPBadRequest(text="missing device_id")
        devices = DeviceRegistry(kernel)
        device = devices.get(device_id)
        if device is None:
            return web.json_response({"ok": False, "error": f"device not found: {device_id}"}, status=404)
        channel = str(payload.get("channel") or device.channel or "stable").strip() or "stable"
        installed_modules = deps.installed_modules_from_payload(payload) or dict(device.installed_modules)
        release_registry = ReleaseRegistry(kernel)

        pinned_release_id = str(payload.get("pinned_release_id") or "").strip() or str(
            device.pinned_release_id or ""
        ).strip()
        source = "channel"
        updates: list[dict[str, Any]] = []
        if pinned_release_id:
            rel = release_registry.get(pinned_release_id)
            if rel is not None:
                current = installed_modules.get(rel.module_id, "0.0.0")
                allowed = release_registry.release_allowed_for_device(
                    rel,
                    device_id=device_id,
                    app_version=str(payload.get("app_version") or device.app_version or ""),
                    capabilities=list(payload.get("capabilities") or device.capabilities or []),
                    pinned=True,
                )
                if allowed and rel.module_version and rel.module_version != current:
                    try:
                        # Only treat as update when newer than installed semver.
                        if rel.module_version != current:
                            from thomas.companion.contracts import parse_semver_tuple

                            if parse_semver_tuple(rel.module_version) > parse_semver_tuple(current or "0.0.0"):
                                updates = [rel.to_dict()]
                    except Exception:
                        # If installed version is malformed, still surface pinned release.
                        updates = [rel.to_dict()]
            source = "pinned"
        else:
            updates = [
                rel.to_dict()
                for rel in release_registry.resolve_updates(
                    channel=channel,
                    installed_modules=installed_modules,
                    device_id=device_id,
                    app_version=str(payload.get("app_version") or device.app_version or ""),
                    capabilities=list(payload.get("capabilities") or device.capabilities or []),
                )
            ]
        deps.audit_for(kernel).append(
            "device.updates.check",
            actor=deps.actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "device_id": device_id,
                "channel": channel,
                "source": source,
                "pinned_release_id": pinned_release_id,
                "updates_count": len(updates),
            },
        )
        return web.json_response(
            {
                "ok": True,
                "device_id": device_id,
                "channel": channel,
                "source": source,
                "pinned_release_id": pinned_release_id,
                "count": len(updates),
                "updates": updates,
            }
        )

    async def api_companion_releases(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        channel = str(request.query.get("channel") or "").strip()
        module_id = str(request.query.get("module_id") or "").strip()
        try:
            limit = int(request.query.get("limit", "200"))
        except Exception:
            limit = 200
        rows = [
            rel.to_dict()
            for rel in ReleaseRegistry(kernel).list(channel=channel, module_id=module_id, limit=limit)
        ]
        return web.json_response({"ok": True, "count": len(rows), "releases": rows})

    async def api_companion_release_get(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        release_id = str(request.match_info.get("release_id") or "").strip()
        if not release_id:
            raise web.HTTPBadRequest(text="missing release_id")
        row = ReleaseRegistry(kernel).get(release_id)
        if row is None:
            return web.json_response({"ok": False, "error": f"release not found: {release_id}"}, status=404)
        return web.json_response({"ok": True, "release": row.to_dict()})

    async def api_companion_release_manifest(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        release_id = str(request.match_info.get("release_id") or "").strip()
        if not release_id:
            raise web.HTTPBadRequest(text="missing release_id")
        row = ReleaseRegistry(kernel).get(release_id)
        if row is None:
            return web.json_response({"ok": False, "error": f"release not found: {release_id}"}, status=404)
        payload = row.to_dict()
        manifest = deps.release_manifest(payload)
        return web.json_response({"ok": True, "release": payload, "manifest": manifest})

    async def api_companion_release_download(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        release_id = str(request.match_info.get("release_id") or "").strip()
        if not release_id:
            raise web.HTTPBadRequest(text="missing release_id")
        row = ReleaseRegistry(kernel).get(release_id)
        if row is None:
            return web.json_response({"ok": False, "error": f"release not found: {release_id}"}, status=404)
        release_payload = row.to_dict()
        bundle_dir = deps.release_bundle_dir(release_payload)
        body = deps.zip_bundle(bundle_dir)
        filename = f"{release_id}.zip"
        return web.Response(
            body=body,
            content_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    async def api_companion_release_publish(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        bundle_dir = deps.bundle_path_from_payload(payload)
        channel = str(payload.get("channel") or "stable").strip() or "stable"
        actor = deps.actor_from_payload(payload)
        verifier = deps.new_verifier(kernel)
        verify_report = verifier.verify_bundle(bundle_dir)
        verify_payload = verify_report.to_dict()
        verify_payload["bundle_dir"] = str(bundle_dir)
        compliance_payload = deps.run_compliance_check(
            kernel=kernel,
            payload=payload,
            bundle_dir=bundle_dir,
            verify_report=verify_report,
            actor=actor,
            peer_identity=peer_identity,
        )
        if not bool(compliance_payload.get("ok")):
            report = compliance_payload.get("report") or {}
            deps.audit_for(kernel).append(
                "release.publish",
                actor=actor,
                peer_identity=peer_identity,
                details={
                    "channel": channel,
                    "bundle_dir": str(bundle_dir),
                    "ok": False,
                    "stage": "compliance",
                    "policy_profile_id": str(report.get("policy_profile_id") or ""),
                    "compliance_report_id": str(report.get("report_id") or ""),
                    "blocking_violations": int(((report.get("counts") or {}).get("blocking_violations") or 0)),
                },
            )
            return web.json_response(
                {
                    "ok": False,
                    "errors": ["compliance check failed"],
                    "warnings": list(((report or {}).get("warnings") or [])),
                    "release": None,
                    "verify": verify_payload,
                    "compliance": compliance_payload,
                },
                status=400,
            )
        reg = ReleaseRegistry(kernel)
        result = reg.publish_from_bundle(
            bundle_dir,
            channel=channel,
            published_by=actor,
            verifier=verifier,
            rollout_pct=(deps.int_or_none(payload.get("rollout_pct")) or 100),
            target_devices=deps.string_list(payload.get("target_devices")),
            exclude_devices=deps.string_list(payload.get("exclude_devices")),
            min_app_version=str(payload.get("min_app_version") or "").strip(),
            required_capabilities=deps.string_list(payload.get("required_capabilities")),
            status=str(payload.get("status") or "active").strip() or "active",
            policy_profile_id=str(
                (compliance_payload.get("report") or {}).get("policy_profile_id") or "strict_global"
            ),
            compliance_report_id=str((compliance_payload.get("report") or {}).get("report_id") or ""),
            compliance_status=("pass" if bool(compliance_payload.get("ok")) else "block"),
            compliance_violations=(
                deps.int_or_none(
                    (compliance_payload.get("report") or {}).get("counts", {}).get("blocking_violations")
                )
                or 0
            ),
            compliance_warnings=(
                deps.int_or_none(
                    (compliance_payload.get("report") or {}).get("counts", {}).get("warnings")
                )
                or 0
            ),
            compliance_checked_at=str((compliance_payload.get("report") or {}).get("checked_at") or ""),
            timestamp=deps.now_iso(),
        )
        result["verify"] = verify_payload
        result["compliance"] = compliance_payload
        deps.audit_for(kernel).append(
            "release.publish",
            actor=actor,
            peer_identity=peer_identity,
            details={
                "channel": channel,
                "bundle_dir": str(bundle_dir),
                "ok": bool(result.get("ok")),
                "errors": list(result.get("errors") or []),
                "policy_profile_id": str(
                    (compliance_payload.get("report") or {}).get("policy_profile_id") or ""
                ),
                "compliance_report_id": str((compliance_payload.get("report") or {}).get("report_id") or ""),
            },
        )
        status = 200 if bool(result.get("ok")) else 400
        return web.json_response(result, status=status)

    async def api_companion_release_rollout(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            payload = {}
        release_id = str(request.match_info.get("release_id") or "").strip()
        if not release_id:
            raise web.HTTPBadRequest(text="missing release_id")
        row = ReleaseRegistry(kernel).set_rollout(
            release_id,
            rollout_pct=(deps.int_or_none(payload.get("rollout_pct")) if "rollout_pct" in payload else None),
            target_devices=(deps.string_list(payload.get("target_devices")) if "target_devices" in payload else None),
            exclude_devices=(
                deps.string_list(payload.get("exclude_devices")) if "exclude_devices" in payload else None
            ),
            min_app_version=(
                str(payload.get("min_app_version") or "").strip() if "min_app_version" in payload else None
            ),
            required_capabilities=(
                deps.string_list(payload.get("required_capabilities"))
                if "required_capabilities" in payload
                else None
            ),
            status=(str(payload.get("status") or "").strip() if "status" in payload else None),
        )
        if row is None:
            return web.json_response({"ok": False, "error": f"release not found: {release_id}"}, status=404)
        deps.audit_for(kernel).append(
            "release.rollout",
            actor=deps.actor_from_payload(payload),
            peer_identity=peer_identity,
            details={
                "release_id": release_id,
                "rollout_pct": row.rollout_pct,
                "status": row.status,
            },
        )
        return web.json_response({"ok": True, "release": row.to_dict()})

    async def api_companion_release_promote(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            payload = {}
        release_id = str(request.match_info.get("release_id") or "").strip()
        if not release_id:
            raise web.HTTPBadRequest(text="missing release_id")
        channel = str(payload.get("channel") or "stable").strip() or "stable"
        actor = deps.actor_from_payload(payload)
        result = ReleaseRegistry(kernel).promote_release(
            release_id,
            channel=channel,
            actor=actor,
            timestamp=deps.now_iso(),
        )
        status = 200 if bool(result.get("ok")) else 404
        deps.audit_for(kernel).append(
            "release.promote",
            actor=actor,
            peer_identity=peer_identity,
            details={
                "source_release_id": release_id,
                "channel": channel,
                "ok": bool(result.get("ok")),
            },
        )
        return web.json_response(result, status=status)

    async def api_companion_release_rollback(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        peer_identity = deps.require_control_plane_identity(request, kernel)
        payload = await deps.read_json(request)
        if not isinstance(payload, dict):
            payload = {}
        release_id = str(request.match_info.get("release_id") or "").strip()
        if not release_id:
            raise web.HTTPBadRequest(text="missing release_id")
        channel = str(payload.get("channel") or "stable").strip() or "stable"
        actor = deps.actor_from_payload(payload)
        result = ReleaseRegistry(kernel).promote_release(
            release_id,
            channel=channel,
            actor=actor,
            timestamp=deps.now_iso(),
        )
        status = 200 if bool(result.get("ok")) else 404
        deps.audit_for(kernel).append(
            "release.rollback",
            actor=actor,
            peer_identity=peer_identity,
            details={
                "release_id": release_id,
                "channel": channel,
                "ok": bool(result.get("ok")),
            },
        )
        return web.json_response(result, status=status)

    async def api_companion_audit_events(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        kernel = deps.kernel_from_config(deps.config)
        try:
            limit = int(request.query.get("limit", "100"))
        except Exception:
            limit = 100
        event_type = str(request.query.get("event_type") or "").strip()
        rows = deps.audit_for(kernel).list(limit=limit, event_type=event_type)
        return web.json_response({"ok": True, "count": len(rows), "events": rows})

    app.router.add_get("/api/companion/v1/devices", api_companion_devices)
    app.router.add_post("/api/companion/v1/devices/register", api_companion_device_register)
    app.router.add_post("/api/companion/v1/devices/{device_id}/heartbeat", api_companion_device_heartbeat)
    app.router.add_post("/api/companion/v1/devices/{device_id}/pin-release", api_companion_device_pin_release)
    app.router.add_post("/api/companion/v1/devices/{device_id}/unpin-release", api_companion_device_unpin_release)
    app.router.add_post("/api/companion/v1/devices/{device_id}/updates/check", api_companion_device_updates_check)
    app.router.add_get("/api/companion/v1/releases", api_companion_releases)
    app.router.add_get("/api/companion/v1/releases/{release_id}", api_companion_release_get)
    app.router.add_get("/api/companion/v1/releases/{release_id}/manifest", api_companion_release_manifest)
    app.router.add_get("/api/companion/v1/releases/{release_id}/download", api_companion_release_download)
    app.router.add_post("/api/companion/v1/releases/publish", api_companion_release_publish)
    app.router.add_post("/api/companion/v1/releases/{release_id}/rollout", api_companion_release_rollout)
    app.router.add_post("/api/companion/v1/releases/{release_id}/promote", api_companion_release_promote)
    app.router.add_post("/api/companion/v1/releases/{release_id}/rollback", api_companion_release_rollback)
    app.router.add_get("/api/companion/v1/audit/events", api_companion_audit_events)
