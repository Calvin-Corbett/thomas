"""Mission run-state and topology projection helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from .mission_support import (
    _RUN_ID_RE,
    _coerce_iso,
    _iso_to_epoch,
    _json_or_empty,
    _room_for_tool_name,
    _trim_summary,
    _utc_iso_now,
)

_STALE_RUN_IDLE_SECONDS = 10 * 60
_DEAD_RUN_ERROR_PREFIX = "dead_run:"


def _event_activity_iso(run_meta: dict[str, Any], last_evt: dict[str, Any] | None) -> str:
    event = last_evt or {}
    ts_ms_raw = event.get("ts_ms")
    try:
        ts_ms = float(ts_ms_raw)
    except Exception:
        ts_ms = 0.0
    if ts_ms > 0:
        return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")

    started_epoch = _iso_to_epoch(run_meta.get("started_at"))
    t_ms_raw = event.get("t_ms")
    try:
        t_ms = float(t_ms_raw)
    except Exception:
        t_ms = -1.0
    if started_epoch > 0 and t_ms >= 0:
        dt = datetime.fromtimestamp(started_epoch, tz=timezone.utc) + timedelta(milliseconds=t_ms)
        return dt.isoformat(timespec="seconds")

    return _coerce_iso(run_meta.get("started_at"))


def _run_updated_at(run_meta: dict[str, Any], last_evt: dict[str, Any] | None) -> str:
    ended_at = str(run_meta.get("ended_at") or "").strip()
    if ended_at:
        return _coerce_iso(ended_at)
    return _event_activity_iso(run_meta, last_evt)


def _run_is_stale(
    run_meta: dict[str, Any],
    last_evt: dict[str, Any] | None,
    *,
    now_iso: str | None = None,
    idle_seconds: int = _STALE_RUN_IDLE_SECONDS,
) -> bool:
    if str(run_meta.get("ended_at") or "").strip():
        return False
    now_epoch = _iso_to_epoch(now_iso or _utc_iso_now())
    updated_epoch = _iso_to_epoch(_run_updated_at(run_meta, last_evt))
    if now_epoch <= 0 or updated_epoch <= 0:
        return False
    return (now_epoch - updated_epoch) >= max(1, int(idle_seconds))


def _run_state_room_and_summary(
    run_meta: dict[str, Any],
    last_evt: dict[str, Any] | None,
    *,
    now_iso: str | None = None,
    idle_seconds: int = _STALE_RUN_IDLE_SECONDS,
) -> tuple[str, str, str]:
    event_type = str((last_evt or {}).get("type") or "").strip().lower()
    stale_run = _run_is_stale(run_meta, last_evt, now_iso=now_iso, idle_seconds=idle_seconds)
    error_txt = str(run_meta.get("error") or "").strip().lower()
    if run_meta.get("ended_at"):
        if error_txt.startswith(_DEAD_RUN_ERROR_PREFIX):
            status = "dead"
        else:
            status = (
                "succeeded"
                if run_meta.get("ok") is True
                else ("failed" if run_meta.get("ok") is False else "completed")
            )
    elif stale_run:
        status = "dead"
    else:
        status = "running"
    room = "planning" if status == "running" else ("review" if status == "dead" else "done")
    summary = _trim_summary(
        str(run_meta.get("mode") or "run")
        + " / "
        + str(run_meta.get("profile") or "profile")
        + " / "
        + str(run_meta.get("model_id") or "default model"),
        140,
    )

    if not event_type:
        return status, room, summary

    if event_type in {"tool_start", "tool_args", "tool_result"}:
        tool_name = str((last_evt or {}).get("name") or "")
        room = _room_for_tool_name(tool_name)
        if event_type == "tool_start":
            summary = _trim_summary(f"Running tool {tool_name or 'tool'}", 140)
        elif event_type == "tool_result":
            ok = bool((last_evt or {}).get("ok"))
            summary = _trim_summary(f"{'Finished' if ok else 'Failed'} tool {tool_name or 'tool'}", 140)
        else:
            summary = _trim_summary(f"Preparing args for {tool_name or 'tool'}", 140)
    elif event_type in {"agent_tool_start", "agent_tool_result"}:
        tool_name = str((last_evt or {}).get("tool") or "")
        agent_id = str((last_evt or {}).get("agent_id") or "agent")
        room = _room_for_tool_name(tool_name)
        if event_type == "agent_tool_start":
            summary = _trim_summary(f"{agent_id} running {tool_name or 'tool'}", 140)
        else:
            ok = bool((last_evt or {}).get("ok"))
            summary = _trim_summary(f"{agent_id} {'finished' if ok else 'failed'} {tool_name or 'tool'}", 140)
    elif event_type in {"route", "iteration", "task_update", "model_runtime"}:
        room = "planning"
        if event_type == "route":
            summary = _trim_summary(
                f"Routing in {str((last_evt or {}).get('mode') or run_meta.get('mode') or 'auto')} mode",
                140,
            )
        elif event_type == "iteration":
            summary = _trim_summary(f"Iteration {int((last_evt or {}).get('iteration') or 1)}", 140)
        elif event_type == "task_update":
            task_status = str((last_evt or {}).get("status") or "").strip().lower()
            task_title = str((last_evt or {}).get("title") or (last_evt or {}).get("task_id") or "task")
            if task_status in {"failed", "cancelled"}:
                status = "failed" if task_status == "failed" else "cancelled"
                room = "review"
            elif task_status == "blocked":
                status = "blocked"
                room = "review"
            summary = _trim_summary(f"Task {task_title}: {task_status or 'update'}", 140)
        else:
            summary = "Updating runtime model state."
    elif event_type in {"text", "agent_text"}:
        room = "review"
        txt = str((last_evt or {}).get("text") or "").strip()
        summary = _trim_summary(txt or "Drafting response text.", 140)
    elif event_type in {"error"}:
        status = "failed"
        room = "review"
        summary = _trim_summary(str((last_evt or {}).get("error") or "Run failed"), 140)
    elif event_type == "done":
        status = "succeeded"
        room = "done"
        summary = "Run complete."

    if status == "dead":
        room = "review"

    if stale_run and not run_meta.get("ended_at") and status in {"running", "dead"}:
        status = "dead"
        room = "review"
        summary = _trim_summary(f"Run went idle after {summary}", 140)

    return status, room, summary


def _job_room_and_summary(job: Any) -> tuple[str, str]:
    status = str(getattr(job, "status", "") or "").strip().lower()
    kind = str(getattr(job, "kind", "") or "").strip().lower()
    payload = getattr(job, "payload", {}) if isinstance(getattr(job, "payload", {}), dict) else {}

    if status == "queued":
        room = "inbox"
    elif status == "running":
        if kind in {"video_generation", "speech_transcription", "speech_synthesis"} or kind in {"workflow_task"}:
            room = "tools"
        else:
            room = "planning"
    elif status == "awaiting_approval":
        room = "review"
    elif status in {"succeeded"}:
        room = "done"
    elif status in {"cancelled", "failed", "dead"}:
        room = "review"
    else:
        room = "planning"

    if status == "queued":
        summary = f"Queued {kind or 'job'}."
    elif status == "running":
        summary = f"Running {kind or 'job'}."
    elif status == "awaiting_approval":
        summary = f"Waiting approval for {kind or 'job'}."
    elif status == "succeeded":
        summary = f"Completed {kind or 'job'}."
    elif status in {"cancelled", "failed", "dead"}:
        summary = f"{status} {kind or 'job'}."
    else:
        summary = f"{status or 'active'} {kind or 'job'}."

    if isinstance(payload, dict):
        goal = str(payload.get("goal") or "").strip()
        if goal:
            summary = _trim_summary(goal, 140)

    return room, _trim_summary(summary, 140)


def _objective_room_and_summary(obj: Any) -> tuple[str, str]:
    status = str(getattr(obj, "status", "") or "").strip().lower()
    if status in {"queued", "pending"}:
        room = "inbox"
    elif status in {"active"}:
        room = "planning"
    elif status in {"blocked"}:
        room = "review"
    elif status in {"completed"}:
        room = "done"
    elif status in {"failed", "cancelled"}:
        room = "review"
    else:
        room = "planning"

    next_action = str(getattr(obj, "next_action_text", "") or "").strip()
    blocker = str(getattr(obj, "blocker_text", "") or "").strip()
    goal = str(getattr(obj, "goal", "") or "").strip()
    summary = next_action or blocker or goal or f"{status or 'active'} objective"
    return room, _trim_summary(summary, 140)


def _run_dir_for_id(runs_dir: Path, run_id: str) -> Path:
    rid = str(run_id or "").strip()
    if not _RUN_ID_RE.fullmatch(rid):
        raise web.HTTPBadRequest(text="invalid run id")
    root = runs_dir.resolve()
    target = (runs_dir / rid).resolve()
    if root != target and root not in target.parents:
        raise web.HTTPForbidden(text="invalid run path")
    if not target.exists() or not target.is_dir():
        raise web.HTTPNotFound(text="benchmark run not found")
    return target


def _timestamp_iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return _utc_iso_now()


def _collect_benchmark_runs(runs_dir: Path, limit: int) -> list[dict[str, Any]]:
    if not runs_dir.exists() or not runs_dir.is_dir():
        return []
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for run_dir in run_dirs[:limit]:
        run_id = run_dir.name
        scorecard = _json_or_empty(run_dir / "scorecard.json")
        summary = scorecard.get("summary") if isinstance(scorecard.get("summary"), dict) else {}
        config = _json_or_empty(run_dir / "agentic_benchmark.config.json")
        delta = _json_or_empty(run_dir / "before_after.delta.json")
        pack_snapshot = _json_or_empty(run_dir / "task_pack.agentic.snapshot.json")
        if not pack_snapshot:
            pack_snapshot = _json_or_empty(run_dir / "task_pack.snapshot.json")
        references_raw = scorecard.get("references")
        if isinstance(references_raw, list):
            references = [str(x) for x in references_raw if str(x or "").strip()]
        else:
            references = list((summary.get("references") or {}).keys())

        ranking = summary.get("ranking") if isinstance(summary.get("ranking"), list) else []
        top = ranking[0] if ranking and isinstance(ranking[0], dict) else {}
        top_reference = str(top.get("reference") or "").strip()
        per_reference = summary.get("references") if isinstance(summary.get("references"), dict) else {}
        top_metrics_raw = (
            per_reference.get(top_reference) if isinstance(per_reference.get(top_reference), dict) else {}
        )
        pack_tasks = pack_snapshot.get("tasks") if isinstance(pack_snapshot.get("tasks"), list) else []
        pack_tasks_total = len(pack_tasks)
        top_tasks_total_raw = top_metrics_raw.get("tasks_total") if isinstance(top_metrics_raw, dict) else None
        top_tasks_total = int(top_tasks_total_raw or 0) if str(top_tasks_total_raw or "").strip() else 0
        if top_tasks_total <= 0:
            top_tasks_total = pack_tasks_total
        top_success_count_raw = top_metrics_raw.get("success_count") if isinstance(top_metrics_raw, dict) else None
        top_success_count = int(top_success_count_raw or 0) if str(top_success_count_raw or "").strip() else 0
        run_status = "unknown"
        if top_tasks_total > 0:
            if top_success_count >= top_tasks_total:
                run_status = "pass"
            elif top_success_count <= 0:
                run_status = "fail"
            else:
                run_status = "partial"
        created_at = (
            str(scorecard.get("created_at") or "").strip()
            or str(config.get("created_at") or "").strip()
            or _timestamp_iso(run_dir.stat().st_mtime)
        )
        artifacts: dict[str, str] = {}
        out.append(
            {
                "run_id": run_id,
                "created_at": created_at,
                "references": references,
                "top_reference": top_reference,
                "top_weighted_score": top.get("weighted_score"),
                "status": run_status,
                "run_options": {
                    "profile": str(config.get("profile") or "").strip(),
                    "thomas_mode": str(config.get("thomas_mode") or "").strip().lower(),
                    "token_economy": str(config.get("thomas_token_economy") or "").strip().lower(),
                    "runner": str(config.get("thomas_runner") or "").strip().lower(),
                    "baseline_enabled": bool(config.get("baseline_enabled")),
                },
                "task_pack": {
                    "id": str(pack_snapshot.get("id") or scorecard.get("task_pack_id") or ""),
                    "name": str(pack_snapshot.get("name") or ""),
                    "version": int(pack_snapshot.get("version") or scorecard.get("task_pack_version") or 1),
                    "task_count": pack_tasks_total,
                },
                "top_metrics": {
                    "tasks_total": top_tasks_total,
                    "success_count": top_success_count,
                    "success_rate": (
                        float(top_metrics_raw.get("success_rate") or 0.0) if isinstance(top_metrics_raw, dict) else 0.0
                    ),
                    "avg_elapsed_seconds": (
                        float(top_metrics_raw.get("avg_elapsed_seconds") or 0.0)
                        if isinstance(top_metrics_raw, dict)
                        else 0.0
                    ),
                    "avg_quality_score": (
                        float(top_metrics_raw.get("avg_quality_score") or 0.0)
                        if isinstance(top_metrics_raw, dict)
                        else 0.0
                    ),
                },
                "before_after": delta,
                "artifacts": artifacts,
            }
        )
    return out


def _mission_topology_payload(payload: dict[str, Any]) -> dict[str, Any]:
    agents = payload.get("agents") if isinstance(payload.get("agents"), list) else []
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for a in agents:
        if not isinstance(a, dict):
            continue
        node_id = str(a.get("id") or "").strip()
        if not node_id or node_id in node_ids:
            continue
        node_ids.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "label": str(a.get("name") or node_id),
                "source": str(a.get("source") or ""),
                "status": str(a.get("status") or ""),
                "room": str(a.get("room") or ""),
                "updated_at": str(a.get("updated_at") or ""),
            }
        )

    edge_keys: set[str] = set()
    edges: list[dict[str, Any]] = []
    for a in agents:
        if not isinstance(a, dict):
            continue
        target_id = str(a.get("id") or "").strip()
        if not target_id:
            continue
        parent_id_raw = str(a.get("parent_id") or "").strip()
        if parent_id_raw:
            src = f"job:{parent_id_raw}" if not parent_id_raw.startswith("job:") else parent_id_raw
            key = f"{src}->{target_id}:parent_job"
            if key not in edge_keys:
                edge_keys.add(key)
                edges.append({"from": src, "to": target_id, "type": "parent_job"})

        root_job_id = str(a.get("root_job_id") or "").strip()
        if root_job_id:
            src = f"job:{root_job_id}" if not root_job_id.startswith("job:") else root_job_id
            key = f"{src}->{target_id}:objective_root"
            if key not in edge_keys:
                edge_keys.add(key)
                edges.append({"from": src, "to": target_id, "type": "objective_root"})

        run_id = str(a.get("run_id") or "").strip()
        if run_id and target_id != f"run:{run_id}":
            src = f"run:{run_id}"
            key = f"{src}->{target_id}:run_scope"
            if key not in edge_keys:
                edge_keys.add(key)
                edges.append({"from": src, "to": target_id, "type": "run_scope"})

    timeline: list[dict[str, Any]] = []
    for ev in events[:140]:
        if not isinstance(ev, dict):
            continue
        timeline.append(
            {
                "ts": str(ev.get("ts") or ""),
                "type": str(ev.get("type") or ""),
                "source": str(ev.get("source") or ""),
                "agent_id": str(ev.get("agent_id") or ""),
                "run_id": str(ev.get("run_id") or ""),
                "text": str(ev.get("text") or ""),
            }
        )
    return {
        "nodes": nodes,
        "edges": edges,
        "timeline": timeline,
    }
