"""Mission workflow orchestration - content hub, alerts, and workflow coordination."""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from .mission_content_hub import (
    _build_content_hub_payload,
    _content_count_configured_api_keys,
    _content_count_installed_skills,
    _content_count_recent_audit_events,
)
from .mission_support import (
    _MAX_ALERT_NOTIFICATION_BODY_CHARS,
    _http_post_json,
    _mission_job_payload,
    _normalize_alert_webhook_url,
    _sanitize_alert_header,
    _send_alert_email,
    _utc_iso_now,
)


def build_mission_workflow_handlers(
    app: web.Application,
    run_store_enabled_key: Any,
    run_store_module_key: Any,
    _mission_approvals_payload: Any,
) -> tuple:
    """Build workflow orchestration route handlers.

    Args:
        app: aiohttp Application instance
        run_store_enabled_key: App key for run store enabled flag
        run_store_module_key: App key for run store module
        _mission_approvals_payload: Async callable to get approvals payload

    Returns:
        Tuple of route handler coroutines
    """

    async def api_mission_content_hub(request: web.Request) -> web.Response:
        """Get content hub dashboard payload with system metrics and stats."""
        store = app.get("autonomy_store")
        job_rows: list[dict[str, Any]] = []
        if store is not None:
            try:
                jobs = list(store.list_jobs(limit=420, offset=0) or [])
            except KeyError as exc:
                raise web.HTTPInternalServerError(text=f"unable to list content jobs: {exc}") from exc
            job_rows = [_mission_job_payload(job) for job in jobs]

        run_store_mod = app.get(run_store_module_key)
        run_store_enabled = bool(app.get(run_store_enabled_key)) and run_store_mod is not None
        sessions_active = 0
        sessions_recent_total = 0
        if run_store_enabled and run_store_mod is not None:
            try:
                runs = list(run_store_mod.list_runs(limit=220, offset=0, filters={}) or [])
            except KeyError:
                runs = []
            sessions_recent_total = len(runs)
            sessions_active = sum(1 for run in runs if not str(run.get("ended_at") or "").strip())

        skills_installed = _content_count_installed_skills()
        api_keys_configured = _content_count_configured_api_keys(user_id="default")
        audit_events_last_24h = _content_count_recent_audit_events(store, hours=24)

        approvals_payload = await _mission_approvals_payload()
        approvals_pending = int(approvals_payload.get("pending_total") or 0)
        payload = _build_content_hub_payload(
            job_rows,
            approvals_pending=approvals_pending,
            sessions_active=sessions_active,
            sessions_recent_total=sessions_recent_total,
            skills_installed=skills_installed,
            api_keys_configured=api_keys_configured,
            audit_events_last_24h=audit_events_last_24h,
        )
        payload["engine"] = {
            "autonomy_store_available": bool(store is not None),
            "run_store_enabled": bool(run_store_enabled),
        }
        payload["approvals"] = {"pending_total": approvals_pending}
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_mission_alert_notify(request: web.Request) -> web.Response:
        """Send mission alerts via webhook and/or email channels."""
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except ValueError:
            payload = {}

        alerts_raw = payload.get("alerts")
        alerts: list[dict[str, Any]] = []
        if isinstance(alerts_raw, list):
            for row in alerts_raw[:16]:
                if not isinstance(row, dict):
                    continue
                alerts.append(
                    {
                        "severity": str(row.get("severity") or "").strip().lower(),
                        "title": str(row.get("title") or "").strip(),
                        "detail": str(row.get("detail") or "").strip(),
                    }
                )
        channels = payload.get("channels") if isinstance(payload.get("channels"), dict) else {}
        webhook_url = _normalize_alert_webhook_url(channels.get("webhook_url"))
        email_to = _sanitize_alert_header(channels.get("email_to"), field="email_to")
        subject = (
            _sanitize_alert_header(
                channels.get("subject"),
                field="subject",
                default="Thomas Mission Alert",
            )
            or "Thomas Mission Alert"
        )

        lines: list[str] = []
        for row in alerts:
            sev = str(row.get("severity") or "info").upper()
            title = str(row.get("title") or "alert")
            detail = str(row.get("detail") or "")
            lines.append(f"[{sev}] {title}")
            if detail:
                lines.append(f"  {detail}")
        if not lines:
            lines.append("[INFO] Mission notification")
            lines.append("  No alert details supplied.")
        body_text = "\n".join(lines)[:_MAX_ALERT_NOTIFICATION_BODY_CHARS]

        out: dict[str, Any] = {"ok": True, "channels": {}}
        if webhook_url:
            webhook_res = _http_post_json(
                webhook_url,
                {
                    "source": "thomas.mission_control",
                    "sent_at": _utc_iso_now(),
                    "alerts": alerts,
                    "subject": subject,
                    "text": body_text,
                },
            )
            out["channels"]["webhook"] = webhook_res
            out["ok"] = bool(out["ok"] and webhook_res.get("ok"))
        if email_to:
            email_res = _send_alert_email(email_to, subject, body_text)
            out["channels"]["email"] = email_res
            out["ok"] = bool(out["ok"] and email_res.get("ok"))
        out["channels"]["desktop"] = {"ok": True, "note": "desktop notifications are browser-local"}
        if not webhook_url and not email_to:
            out["ok"] = True
            out["channels"]["noop"] = {"ok": True, "note": "no webhook/email channel configured"}
        return web.json_response(out, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    return (
        api_mission_content_hub,
        api_mission_alert_notify,
    )
