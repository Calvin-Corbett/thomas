"""aiohttp route registration for onboarding telemetry and outcome gates."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from aiohttp import web

RequireAccessFn = Callable[[web.Request], None]

log = logging.getLogger(__name__)


def register_onboarding_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
) -> None:
    async def api_onboarding_telemetry(request: web.Request) -> web.Response:
        """Receive onboarding telemetry events."""
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

        t_ms: Optional[int] = None
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
        """Return onboarding outcome metrics."""
        require_api_access(request)
        try:
            from thomas.observability.onboarding_outcomes import get_outcomes_report
            from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report
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
        """Return onboarding outcomes gate status."""
        require_api_access(request)
        try:
            from thomas.observability.onboarding_outcomes_gate import get_gate_status
            from thomas.observability.onboarding_outcomes_gate import evaluate_onboarding_outcomes_gate
            from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report

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

    app.router.add_post("/api/onboarding/telemetry", api_onboarding_telemetry)
    app.router.add_get("/api/onboarding/outcomes", api_onboarding_outcomes)
    app.router.add_get("/api/onboarding/outcomes/gate", api_onboarding_outcomes_gate)
