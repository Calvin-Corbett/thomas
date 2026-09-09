"""aiohttp route registration for onboarding telemetry, outcomes, and isolated desktop setup."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.desktop_operator.host_service import get_global_desktop_host_service
from thomas.preferences.store import PreferencesPatch, PreferencesStore, get_db_path

RequireAccessFn = Callable[[web.Request], None]

log = logging.getLogger(__name__)


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


def register_onboarding_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
) -> None:
    async def api_onboarding_telemetry(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await request.json() if request.can_read_body else {}
        event_name = str(body.get("event") or "").strip() or "unknown"
        payload_raw = body.get("payload")
        payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}
        onboarding_session_id = str(
            payload.get("onboarding_session_id") or body.get("onboarding_session_id") or ""
        ).strip()
        if onboarding_session_id and "onboarding_session_id" not in payload:
            payload["onboarding_session_id"] = onboarding_session_id

        t_ms: int | None = None
        elapsed_raw = payload.get("elapsed_ms", body.get("elapsed_ms"))
        try:
            elapsed = int(elapsed_raw)
            if elapsed >= 0:
                t_ms = elapsed
                payload["elapsed_ms"] = elapsed
        except Exception:
            t_ms = None

        run_id = None
        if onboarding_session_id:
            run_id = f"onboarding-{onboarding_session_id}-{int(time.time() * 1000)}"
        try:
            from thomas.observability.event_recorder import record_event, start_run

            active_run_id = start_run(
                meta={"source": "onboarding.telemetry"},
                run_id=run_id,
            )
            record_event(
                f"onboarding.client.{event_name}",
                payload,
                t_ms=t_ms,
                run_id=active_run_id,
            )
        except Exception as exc:
            log.warning("onboarding telemetry persistence failed: %s", exc)

        log.info("onboarding telemetry: %s", event_name)
        return web.json_response({"ok": True})

    async def api_onboarding_outcomes(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report, get_outcomes_report

            days = max(1, int(request.query.get("days", "7") or 7))
            db_path = str(request.query.get("db") or "").strip()
            if db_path:
                report = build_onboarding_outcome_report(Path(db_path), since_days=days)
            else:
                report = get_outcomes_report(since_days=days)
        except Exception as exc:
            report = {"ok": False, "error": str(exc)}
        return web.json_response(report)

    async def api_onboarding_outcomes_gate(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report
            from thomas.observability.onboarding_outcomes_gate import evaluate_onboarding_outcomes_gate, get_gate_status

            days = max(1, int(request.query.get("days", "7") or 7))
            min_events = int(request.query.get("min_events_for_quality_thresholds", "20") or 20)
            min_completion = float(request.query.get("min_completion_rate", "0.9") or 0.9)
            min_recovery = float(request.query.get("min_recovery_success_rate", "0.8") or 0.8)
            max_median = float(request.query.get("max_median_time_to_ready_seconds", "480") or 480.0)
            db_path = str(request.query.get("db") or "").strip()
            if db_path:
                report = build_onboarding_outcome_report(Path(db_path), since_days=days)
                gate = evaluate_onboarding_outcomes_gate(
                    report,
                    min_events_for_quality_thresholds=max(0, int(min_events)),
                    min_completion_rate=max(0.0, min(1.0, float(min_completion))),
                    min_recovery_success_rate=max(0.0, min(1.0, float(min_recovery))),
                    max_median_time_to_ready_seconds=max(1.0, float(max_median)),
                )
                status = {
                    "ok": bool(gate.get("ok", False)),
                    "gate": gate,
                    "onboarding_summary": dict(report.get("summary") or {}),
                    "errors": list(gate.get("errors") or []),
                    "warnings": list(gate.get("warnings") or []),
                }
            else:
                status = get_gate_status(
                    since_days=days,
                    min_events_for_quality_thresholds=max(0, int(min_events)),
                    min_completion_rate=max(0.0, min(1.0, float(min_completion))),
                    min_recovery_success_rate=max(0.0, min(1.0, float(min_recovery))),
                    max_median_time_to_ready_seconds=max(1.0, float(max_median)),
                )
                gate_payload = dict(status.get("gate") or {})
                status["errors"] = list(gate_payload.get("errors") or [])
                status["warnings"] = list(gate_payload.get("warnings") or [])
        except Exception as exc:
            status = {"ok": False, "error": str(exc)}
        return web.json_response(status)

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

    app.router.add_post("/api/onboarding/telemetry", api_onboarding_telemetry)
    app.router.add_get("/api/onboarding/outcomes", api_onboarding_outcomes)
    app.router.add_get("/api/onboarding/outcomes/gate", api_onboarding_outcomes_gate)
    app.router.add_get("/api/onboarding/desktop/status", api_onboarding_desktop_status)
    app.router.add_post("/api/onboarding/desktop/opt-in", api_onboarding_desktop_opt_in)
    app.router.add_post("/api/onboarding/desktop/trust", api_onboarding_desktop_trust)
    app.router.add_post("/api/onboarding/desktop/vm-source", api_onboarding_desktop_vm_source)
    app.router.add_post("/api/onboarding/desktop/install", api_onboarding_desktop_install)
    app.router.add_post("/api/onboarding/desktop/open-viewer", api_onboarding_desktop_open_viewer)
