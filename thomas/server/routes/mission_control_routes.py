"""Mission control payload and stream route builders."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.desktop_operator import manager as desktop_operator_manager
from thomas.server.app_keys import APP_APPROVALS_BROKER

from .mission_runtime_views import (
    _job_room_and_summary,
    _mission_topology_payload,
    _objective_room_and_summary,
    _run_state_room_and_summary,
    _run_updated_at,
    _timestamp_iso,
)
from .mission_support import (
    _coerce_iso,
    _iso_to_epoch,
    _latest_run_event,
    _mission_job_display_name,
    _mission_run_display_name,
    _safe_approval_dict,
    _trim_summary,
    _utc_iso_now,
)


def build_mission_control_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    run_store_enabled_key: Any,
    run_store_module_key: Any,
):
    def _resolve_approvals_broker():
        broker = app.get(APP_APPROVALS_BROKER)
        if broker is None:
            broker = app.get("approvals")
            if broker is not None:
                app[APP_APPROVALS_BROKER] = broker
        return broker

    async def _mission_approvals_payload() -> dict[str, Any]:
        out: dict[str, Any] = {
            "autonomy": [],
            "guardrails": [],
            "pending_total": 0,
        }
        autonomy_store = app.get("autonomy_store")
        if autonomy_store is not None:
            try:
                aps = list(autonomy_store.list_approvals(status="pending", limit=240) or [])
            except Exception:
                aps = []
            for ap in aps:
                row = _safe_approval_dict(ap)
                if not row.get("id"):
                    continue
                row["source"] = "autonomy"
                out["autonomy"].append(row)
            out["autonomy"].sort(key=lambda r: _iso_to_epoch(r.get("requested_at")), reverse=True)

        broker = _resolve_approvals_broker()
        pending_fn = getattr(broker, "pending", None) if broker is not None else None
        if callable(pending_fn):
            try:
                pending_rows = await pending_fn()
            except Exception:
                pending_rows = []
            for row in pending_rows if isinstance(pending_rows, list) else []:
                if not isinstance(row, dict):
                    continue
                created_raw = row.get("created_at")
                created_iso = _timestamp_iso(float(created_raw)) if created_raw is not None else _utc_iso_now()
                out["guardrails"].append(
                    {
                        "source": "guardrails",
                        "run_id": str(row.get("run_id") or "").strip(),
                        "tool_call_id": str(row.get("tool_call_id") or "").strip(),
                        "session_id": str(row.get("session_id") or "").strip(),
                        "tool_name": str(row.get("tool_name") or "").strip(),
                        "reason": str(row.get("reason") or "").strip(),
                        "args_preview": row.get("args_preview"),
                        "requested_at": created_iso,
                    }
                )
            out["guardrails"].sort(key=lambda r: _iso_to_epoch(r.get("requested_at")), reverse=True)

        out["pending_total"] = int(len(out["autonomy"]) + len(out["guardrails"]))
        return out

    def _desktop_operator_snapshot_payload() -> tuple[
        dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]
    ]:
        try:
            snapshot = desktop_operator_manager.get_global_desktop_operator_manager().status_snapshot()
        except Exception:
            return None, None, []
        if not isinstance(snapshot, dict) or not snapshot:
            return None, None, []

        host_posture = snapshot.get("host_posture") if isinstance(snapshot.get("host_posture"), dict) else {}
        active_session = snapshot.get("active_session") if isinstance(snapshot.get("active_session"), dict) else {}
        session = active_session.get("session") if isinstance(active_session.get("session"), dict) else {}
        window = active_session.get("window") if isinstance(active_session.get("window"), dict) else {}
        viewer = snapshot.get("viewer") if isinstance(snapshot.get("viewer"), dict) else {}
        if not viewer and isinstance(host_posture.get("viewer"), dict):
            viewer = dict(host_posture.get("viewer") or {})
        workflow_profiles = (
            snapshot.get("workflow_profiles") if isinstance(snapshot.get("workflow_profiles"), list) else []
        )
        first_profile = workflow_profiles[0] if workflow_profiles and isinstance(workflow_profiles[0], dict) else {}
        vm = snapshot.get("vm") if isinstance(snapshot.get("vm"), dict) else {}

        workflow_profile = str(session.get("workflow_profile") or first_profile.get("workflow_profile") or "").strip()
        adapter_name = str(session.get("adapter_name") or first_profile.get("adapter_name") or "").strip()
        session_state = str(session.get("session_state") or ("running" if snapshot.get("running") else "idle")).strip()
        risk_level = str(session.get("risk_level") or "low").strip() or "low"
        magic_ready = bool(session.get("magic_ready", host_posture.get("magic_ready", False)))
        installation_state = (
            str(host_posture.get("installation_state") or snapshot.get("installation_state") or "not_enabled").strip()
            or "not_enabled"
        )
        trust_mode = (
            str(host_posture.get("trust_mode") or snapshot.get("trust_mode") or "ask_every_time").strip()
            or "ask_every_time"
        )
        session_target = (
            str(host_posture.get("session_target") or snapshot.get("session_target") or "local_vm").strip()
            or "local_vm"
        )
        vm_id = str(vm.get("vm_id") or "").strip()
        running = bool(snapshot.get("running"))

        review_states = {"paused_for_approval", "blocked_by_policy", "verification_failed", "needs_rebind", "blocked"}
        has_live_desktop_work = bool(running or session or session_state in review_states)
        if not has_live_desktop_work:
            return snapshot, None, []
        if session_state in review_states:
            room = "review"
            status = "blocked"
        elif running:
            room = "tools"
            status = "running"
        else:
            room = "inbox"
            status = "queued"

        summary_bits = [
            str(session.get("pending_approval_reason") or "").strip(),
            str(host_posture.get("note") or "").strip(),
            str(host_posture.get("next_action") or "").strip(),
            str(snapshot.get("last_error") or "").strip(),
        ]
        summary = next((bit for bit in summary_bits if bit), "Desktop operator ready.")

        agent = {
            "id": "desktop:operator",
            "source": "desktop_operator",
            "kind": "service",
            "module_id": "desktop.operator",
            "name": "Desktop Operator",
            "room": room,
            "status": status,
            "summary": summary,
            "updated_at": _utc_iso_now(),
            "service_id": str(snapshot.get("service_id") or "desktop.operator"),
            "workflow_profile": workflow_profile,
            "adapter_name": adapter_name,
            "vm_id": vm_id,
            "session_state": session_state,
            "risk_level": risk_level,
            "magic_ready": magic_ready,
            "viewer_available": bool(viewer.get("available")),
            "viewer_mode": str(viewer.get("mode") or "").strip(),
            "viewer_command": str(viewer.get("command") or "").strip(),
            "viewer_url": str(viewer.get("url") or "").strip(),
            "viewer_takeover_supported": bool(viewer.get("takeover_supported")),
            "installation_state": installation_state,
            "trust_mode": trust_mode,
            "session_target": session_target,
            "running": running,
        }
        if window:
            agent["window_title"] = str(window.get("title") or "").strip()
            agent["window_monitor_id"] = str(window.get("monitor_id") or "").strip()

        events: list[dict[str, Any]] = []
        if summary:
            events.append(
                {
                    "id": f"evt:desktop:operator:{installation_state}:{session_state or 'idle'}",
                    "source": "desktop_operator",
                    "agent_id": "desktop:operator",
                    "run_id": "",
                    "ts": _utc_iso_now(),
                    "type": "status",
                    "text": _trim_summary(summary, 160),
                }
            )
        return snapshot, agent, events

    def _build_mission_control_payload() -> dict[str, Any]:
        rooms = [
            {"id": "inbox", "label": "Inbox", "description": "Queued and waiting"},
            {"id": "planning", "label": "Planning", "description": "Reasoning and decomposition"},
            {"id": "tools", "label": "Tools", "description": "Calling external tools/APIs"},
            {"id": "files", "label": "Files", "description": "Touching workspace/filesystem"},
            {"id": "review", "label": "Review", "description": "Drafting, approvals, or blocked"},
            {"id": "done", "label": "Done", "description": "Completed and recently finished"},
        ]

        agents: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        run_store_mod = app.get(run_store_module_key)
        run_store_enabled = bool(app.get(run_store_enabled_key)) and run_store_mod is not None
        if run_store_enabled:
            try:
                runs = list(run_store_mod.list_runs(limit=160, offset=0, filters={}) or [])
            except Exception:
                runs = []
            active_runs = [r for r in runs if not str(r.get("ended_at") or "").strip()]
            finished_runs = [r for r in runs if str(r.get("ended_at") or "").strip()]
            selected_runs = active_runs[:24] + finished_runs[:16]
            seen_run_ids: set[str] = set()
            for run in selected_runs:
                run_id = str(run.get("run_id") or "").strip()
                if not run_id or run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)
                last_evt = _latest_run_event(run_store_mod, run_id)
                status, room, summary = _run_state_room_and_summary(run, last_evt)
                updated_at = _run_updated_at(run, last_evt)
                created_at = _coerce_iso(run.get("created_at") or run.get("started_at"))
                started_at = _coerce_iso(run.get("started_at")) if run.get("started_at") else created_at
                ended_at = _coerce_iso(run.get("ended_at")) if run.get("ended_at") else ""
                session_id = str(run.get("session_id") or "").strip()
                mode = str(run.get("mode") or "").strip()
                profile_name = str(run.get("profile") or "").strip()
                model_id = str(run.get("model_id") or "").strip()
                agents.append(
                    {
                        "id": f"run:{run_id}",
                        "source": "chat_run",
                        "kind": "run",
                        "name": _mission_run_display_name(run),
                        "room": room,
                        "status": status,
                        "summary": summary,
                        "updated_at": updated_at,
                        "created_at": created_at,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "session_id": session_id,
                        "run_id": run_id,
                        "mode": mode,
                        "profile": profile_name,
                        "model_id": model_id,
                        "parent_id": "",
                        "last_event_type": str((last_evt or {}).get("type") or ""),
                    }
                )
                if isinstance(last_evt, dict):
                    events.append(
                        {
                            "id": f"evt:run:{run_id}:{int(last_evt.get('seq') or 0)}",
                            "source": "chat_run",
                            "agent_id": f"run:{run_id}",
                            "run_id": run_id,
                            "ts": _coerce_iso(updated_at),
                            "type": str(last_evt.get("type") or "event"),
                            "text": summary,
                        }
                    )

        autonomy_engine = app.get("autonomy_engine")
        autonomy_store = app.get("autonomy_store")
        autonomy_enabled = autonomy_store is not None and autonomy_engine is not None
        if autonomy_store is not None:
            try:
                jobs = list(autonomy_store.list_jobs(limit=320, offset=0) or [])
            except Exception:
                jobs = []

            active_statuses = {"queued", "running", "awaiting_approval"}
            active_jobs = [j for j in jobs if str(getattr(j, "status", "") or "").strip().lower() in active_statuses]
            ended_jobs = [j for j in jobs if str(getattr(j, "status", "") or "").strip().lower() not in active_statuses]
            selected_jobs = active_jobs[:36] + ended_jobs[:18]

            for job in selected_jobs:
                job_id = str(getattr(job, "id", "") or "").strip()
                if not job_id:
                    continue
                room, summary = _job_room_and_summary(job)
                status = str(getattr(job, "status", "") or "").strip().lower() or "unknown"
                updated_at = _coerce_iso(getattr(job, "updated_at", None) or getattr(job, "created_at", None))
                created_at = _coerce_iso(getattr(job, "created_at", None))
                session_id = str(getattr(job, "session_id", "") or "")
                kind = str(getattr(job, "kind", "") or "").strip()
                name = _mission_job_display_name(job)
                payload_obj = getattr(job, "payload", None)
                payload_dict = payload_obj if isinstance(payload_obj, dict) else {}
                model_profile = str(
                    payload_dict.get("profile")
                    or payload_dict.get("active_profile")
                    or payload_dict.get("model_profile")
                    or ""
                ).strip()
                model_id = str(
                    payload_dict.get("model_id")
                    or payload_dict.get("model")
                    or payload_dict.get("active_model_id")
                    or payload_dict.get("activeModelId")
                    or ""
                ).strip()
                agents.append(
                    {
                        "id": f"job:{job_id}",
                        "source": "autonomy_job",
                        "kind": "job",
                        "name": name,
                        "room": room,
                        "status": status,
                        "summary": summary,
                        "updated_at": updated_at,
                        "created_at": created_at,
                        "session_id": session_id,
                        "job_id": job_id,
                        "job_kind": kind,
                        "parent_id": str(getattr(job, "parent_id", "") or ""),
                        "next_run_at": _coerce_iso(getattr(job, "next_run_at", None))
                        if getattr(job, "next_run_at", None)
                        else "",
                        "profile": model_profile,
                        "model_id": model_id,
                        "requires_approval": bool(getattr(job, "requires_approval", False)),
                    }
                )

            try:
                objectives = list(autonomy_store.list_objectives(limit=180, offset=0) or [])
            except Exception:
                objectives = []
            active_obj_statuses = {"active", "blocked"}
            active_objs = [
                o for o in objectives if str(getattr(o, "status", "") or "").strip().lower() in active_obj_statuses
            ]
            ended_objs = [
                o for o in objectives if str(getattr(o, "status", "") or "").strip().lower() not in active_obj_statuses
            ]
            selected_objs = active_objs[:22] + ended_objs[:10]
            for obj in selected_objs:
                obj_id = str(getattr(obj, "id", "") or "").strip()
                if not obj_id:
                    continue
                room, summary = _objective_room_and_summary(obj)
                status = str(getattr(obj, "status", "") or "").strip().lower() or "unknown"
                updated_at = _coerce_iso(getattr(obj, "updated_at", None) or getattr(obj, "created_at", None))
                title = str(getattr(obj, "title", "") or "").strip() or f"objective {obj_id[:8]}"
                agents.append(
                    {
                        "id": f"objective:{obj_id}",
                        "source": "autonomy_objective",
                        "kind": "objective",
                        "name": title,
                        "room": room,
                        "status": status,
                        "summary": summary,
                        "updated_at": updated_at,
                        "objective_id": obj_id,
                        "root_job_id": str(getattr(obj, "root_job_id", "") or ""),
                        "parent_id": "",
                        "current_step_index": int(getattr(obj, "current_step_index", 0) or 0),
                    }
                )

            try:
                audit_events = list(autonomy_store.list_audit(limit=60) or [])
            except Exception:
                audit_events = []
            for evt in audit_events[:40]:
                ts_iso = _coerce_iso(getattr(evt, "ts", None))
                detail = getattr(evt, "detail", None)
                detail_txt = ""
                if isinstance(detail, dict):
                    detail_txt = _trim_summary(json.dumps(detail, ensure_ascii=False), 140)
                events.append(
                    {
                        "id": f"audit:{str(getattr(evt, 'id', '') or '')}",
                        "source": "autonomy_audit",
                        "agent_id": (
                            f"job:{str(getattr(evt, 'job_id', '') or '')}" if getattr(evt, "job_id", None) else ""
                        ),
                        "run_id": "",
                        "ts": ts_iso,
                        "type": str(getattr(evt, "event_type", "") or "audit"),
                        "text": _trim_summary(
                            (str(getattr(evt, "event_type", "") or "event") + (" " + detail_txt if detail_txt else "")),
                            160,
                        ),
                    }
                )

        desktop_snapshot, desktop_agent, desktop_events = _desktop_operator_snapshot_payload()
        if desktop_agent is not None:
            agents.append(desktop_agent)
        if desktop_events:
            events.extend(desktop_events)

        room_rank = {
            "planning": 0,
            "tools": 1,
            "files": 2,
            "review": 3,
            "inbox": 4,
            "done": 5,
        }
        status_rank = {
            "running": 0,
            "queued": 1,
            "awaiting_approval": 2,
            "blocked": 3,
            "succeeded": 4,
            "completed": 4,
            "failed": 5,
            "dead": 5,
            "cancelled": 6,
        }
        agents.sort(
            key=lambda a: (
                room_rank.get(str(a.get("room") or ""), 99),
                status_rank.get(str(a.get("status") or ""), 50),
                -_iso_to_epoch(a.get("updated_at")),
                str(a.get("name") or ""),
            )
        )
        events.sort(key=lambda e: _iso_to_epoch(e.get("ts")), reverse=True)
        events = events[:160]

        active_agents = sum(
            1 for a in agents if str(a.get("status") or "") in {"running", "queued", "awaiting_approval", "blocked"}
        )
        return {
            "ok": True,
            "generated_at": _utc_iso_now(),
            "rooms": rooms,
            "desktop_operator": desktop_snapshot or {},
            "engine": {
                "run_store_enabled": bool(run_store_enabled),
                "autonomy_enabled": bool(autonomy_enabled),
                "autonomy_running": bool(getattr(autonomy_engine, "is_running", False))
                if autonomy_engine is not None
                else False,
            },
            "totals": {
                "agents": len(agents),
                "active_agents": int(active_agents),
                "events": len(events),
            },
            "agents": agents,
            "events": events,
        }

    async def api_mission_control(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = _build_mission_control_payload()
        payload["approvals"] = await _mission_approvals_payload()
        payload["topology"] = _mission_topology_payload(payload)
        totals = payload.get("totals")
        if isinstance(totals, dict):
            totals["approvals_pending"] = int(payload["approvals"].get("pending_total") or 0)
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_mission_stream(request: web.Request) -> web.StreamResponse:
        require_api_access(request)

        interval_s = 2.2
        raw_interval = str(request.query.get("interval") or "").strip()
        if raw_interval:
            try:
                interval_s = float(raw_interval)
            except Exception as err:
                raise web.HTTPBadRequest(text="invalid interval") from err
            if (not math.isfinite(interval_s)) or interval_s <= 0:
                raise web.HTTPBadRequest(text="invalid interval")
        interval_s = min(30.0, max(0.35, interval_s))

        max_updates = 0
        raw_max_updates = str(request.query.get("max_updates") or "").strip()
        if raw_max_updates:
            try:
                max_updates = int(raw_max_updates)
            except Exception as err:
                raise web.HTTPBadRequest(text="invalid max_updates") from err
            if max_updates <= 0:
                raise web.HTTPBadRequest(text="invalid max_updates")
            max_updates = min(max_updates, 500)

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(request)

        async def send(obj: dict[str, Any]) -> None:
            line = json.dumps(obj, ensure_ascii=False)
            await resp.write(line.encode("utf-8") + b"\n")

        updates_sent = 0
        try:
            while True:
                payload = _build_mission_control_payload()
                payload["approvals"] = await _mission_approvals_payload()
                payload["topology"] = _mission_topology_payload(payload)
                totals = payload.get("totals")
                if isinstance(totals, dict):
                    totals["approvals_pending"] = int(payload["approvals"].get("pending_total") or 0)
                updates_sent += 1
                await send({"type": "snapshot", "seq": updates_sent, "payload": payload})
                if max_updates and updates_sent >= max_updates:
                    break
                await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            raise
        except (ConnectionResetError, BrokenPipeError):
            pass
        except RuntimeError:
            pass
        finally:
            with contextlib.suppress(Exception):
                await resp.write_eof()
        return resp

    return api_mission_control, api_mission_stream, _mission_approvals_payload
