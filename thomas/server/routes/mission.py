"""Mission Control routes and benchmark UI APIs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import secrets
import smtplib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aiohttp import web

from thomas import __version__ as THOMAS_VERSION

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_MAX_BENCH_LOG_LINES = 220
_MAX_BENCH_JOBS = 24
_BENCHMARK_ARTIFACTS = (
    "report.md",
    "scorecard.json",
    "before_after.delta.json",
    "benchmark_results.raw.json",
    "agentic_benchmark.config.json",
    "execution_plan.md",
)
_ARTIFACT_CONTENT_TYPES: Dict[str, str] = {
    "report.md": "text/markdown",
    "execution_plan.md": "text/markdown",
    "scorecard.json": "application/json",
    "before_after.delta.json": "application/json",
    "benchmark_results.raw.json": "application/json",
    "agentic_benchmark.config.json": "application/json",
}
_MAX_ALERT_NOTIFICATION_BODY_CHARS = 8000
_ALERT_HTTP_TIMEOUT_SECONDS = 8.0


def _task_pack_key_for_path(path: Path) -> str:
    name = str(path.name or "").strip()
    m = re.fullmatch(r"task_pack\.agentic\.([A-Za-z0-9._-]+)\.json", name, re.IGNORECASE)
    if m:
        return str(m.group(1) or "").strip().lower()
    return str(path.stem or "").strip().lower()


def _read_task_pack_meta(path: Path, *, key: str) -> Dict[str, Any]:
    payload = _json_or_empty(path)
    tasks_raw = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    tasks: List[Dict[str, Any]] = []
    duration_budget_seconds = 0
    for row in tasks_raw:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not tid and not title:
            continue
        budget_value = row.get("time_budget_seconds")
        budget_seconds: Optional[int] = None
        if budget_value is not None:
            with contextlib.suppress(Exception):
                parsed = int(budget_value)
                if parsed > 0:
                    budget_seconds = parsed
                    duration_budget_seconds += parsed
        tasks.append(
            {
                "id": tid,
                "title": title or tid,
                "time_budget_seconds": budget_seconds,
                "success_criteria": str(row.get("success_criteria") or "").strip(),
            }
        )
    protocol_raw = payload.get("protocol") if isinstance(payload.get("protocol"), list) else []
    protocol = [str(x or "").strip() for x in protocol_raw if str(x or "").strip()]
    return {
        "key": str(key or "").strip().lower(),
        "id": str(payload.get("id") or key),
        "name": str(payload.get("name") or key),
        "version": int(payload.get("version") or 1),
        "description": str(payload.get("description") or "").strip(),
        "protocol": protocol,
        "task_count": len(tasks),
        "duration_budget_seconds": duration_budget_seconds,
        "tasks": tasks,
        "path": str(path.resolve()),
        "file_name": path.name,
    }


def _discover_task_packs(repo_root: Path) -> Dict[str, Dict[str, Any]]:
    demo_dir = (repo_root / "demo").resolve()
    if not demo_dir.exists() or not demo_dir.is_dir():
        return {}
    files = sorted(
        [p for p in demo_dir.glob("task_pack.agentic*.json") if p.is_file()],
        key=lambda p: p.name.lower(),
    )
    out: Dict[str, Dict[str, Any]] = {}
    for path in files:
        key = _task_pack_key_for_path(path)
        if not key or key in out:
            continue
        out[key] = _read_task_pack_meta(path, key=key)
    return out


def _default_task_pack_key(packs: Dict[str, Dict[str, Any]]) -> str:
    if "smoke" in packs:
        return "smoke"
    keys = sorted(packs.keys())
    return keys[0] if keys else ""


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_iso(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")
    txt = str(value or "").strip()
    if txt:
        return txt
    return _utc_iso_now()


def _iso_to_epoch(value: Any) -> float:
    txt = str(value or "").strip()
    if not txt:
        return 0.0
    try:
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        return float(datetime.fromisoformat(txt).timestamp())
    except Exception:
        return 0.0


def _trim_summary(value: Any, max_len: int = 180) -> str:
    txt = " ".join(str(value or "").strip().split())
    if len(txt) <= max_len:
        return txt
    return txt[: max(0, max_len - 3)].rstrip() + "..."


def _json_or_empty(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    txt = str(value or "").strip().lower()
    if not txt:
        return default
    if txt in {"1", "true", "yes", "y", "on"}:
        return True
    if txt in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_int(value: Any, default: int) -> int:
    with contextlib.suppress(Exception):
        return int(value)
    return int(default)


def _safe_approval_dict(ap: Any) -> Dict[str, Any]:
    if ap is None:
        return {}
    if isinstance(ap, dict):
        row = ap
    elif hasattr(ap, "__dict__"):
        row = dict(vars(ap))
    else:
        row = {}
    requested_at = row.get("requested_at")
    decided_at = row.get("decided_at")
    return {
        "id": str(row.get("id") or "").strip(),
        "job_id": str(row.get("job_id") or "").strip(),
        "risk_class": str(row.get("risk_class") or "").strip().lower(),
        "status": str(row.get("status") or "").strip().lower(),
        "action": row.get("action") if isinstance(row.get("action"), dict) else {},
        "requested_at": _coerce_iso(requested_at),
        "decided_at": _coerce_iso(decided_at) if decided_at else "",
        "decided_by": str(row.get("decided_by") or "").strip(),
        "decision_reason": str(row.get("decision_reason") or "").strip(),
    }


def _http_post_json(url: str, payload: Dict[str, Any], *, timeout_s: float = _ALERT_HTTP_TIMEOUT_SECONDS) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=str(url),
        method="POST",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "thomas-mission-control/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            text = resp.read(2048).decode("utf-8", errors="replace")
            return {"ok": 200 <= status < 300, "status": status, "body": text[:600]}
    except urllib.error.HTTPError as exc:
        with contextlib.suppress(Exception):
            text = exc.read(2048).decode("utf-8", errors="replace")
            return {"ok": False, "status": int(getattr(exc, "code", 500) or 500), "error": text[:600]}
        return {"ok": False, "status": int(getattr(exc, "code", 500) or 500), "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": f"{type(exc).__name__}: {exc}"}


def _send_alert_email(to_addr: str, subject: str, body_text: str) -> Dict[str, Any]:
    host = str(os.environ.get("THOMAS_ALERT_SMTP_HOST") or "").strip()
    port = _coerce_int(os.environ.get("THOMAS_ALERT_SMTP_PORT") or "587", 587)
    user = str(os.environ.get("THOMAS_ALERT_SMTP_USER") or "").strip()
    password = str(os.environ.get("THOMAS_ALERT_SMTP_PASS") or "").strip()
    sender = str(os.environ.get("THOMAS_ALERT_EMAIL_FROM") or user or "").strip()
    use_tls = _coerce_bool(os.environ.get("THOMAS_ALERT_SMTP_TLS"), True)
    if not host or not sender:
        return {
            "ok": False,
            "error": "email unavailable: set THOMAS_ALERT_SMTP_HOST and THOMAS_ALERT_EMAIL_FROM",
        }
    if not to_addr:
        return {"ok": False, "error": "email unavailable: missing recipient"}

    msg = EmailMessage()
    msg["Subject"] = str(subject or "Thomas Mission Alert")
    msg["From"] = sender
    msg["To"] = str(to_addr)
    msg.set_content(str(body_text or "")[:_MAX_ALERT_NOTIFICATION_BODY_CHARS], subtype="plain", charset="utf-8")

    try:
        with smtplib.SMTP(host=host, port=port, timeout=_ALERT_HTTP_TIMEOUT_SECONDS) as smtp:
            if use_tls:
                with contextlib.suppress(Exception):
                    smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _serve_versioned_page(path: Path) -> web.StreamResponse:
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
        html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
        return web.Response(
            text=html,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        return web.FileResponse(path)


def _discover_repo_root(web_dir: Path) -> Path:
    wd = web_dir.resolve()
    for base in [wd, *wd.parents]:
        candidate = base / "demo" / "agentic-runs"
        if candidate.exists():
            return base
    with contextlib.suppress(Exception):
        return wd.parents[2]
    return wd


def _room_for_tool_name(tool_name: str) -> str:
    low = str(tool_name or "").strip().lower()
    if any(
        k in low
        for k in ("fs.", "file", "path", "git.", "diff.", "code_search", "read", "write", "edit")
    ):
        return "files"
    return "tools"


def _latest_run_event(run_store_mod: Any, run_id: str) -> Optional[Dict[str, Any]]:
    latest: Optional[Dict[str, Any]] = None
    try:
        for evt in run_store_mod.stream_replay(run_id):
            if isinstance(evt, dict):
                latest = evt
    except Exception:
        return None
    return latest


def _run_state_room_and_summary(
    run_meta: Dict[str, Any],
    last_evt: Optional[Dict[str, Any]],
) -> tuple[str, str, str]:
    event_type = str((last_evt or {}).get("type") or "").strip().lower()
    if run_meta.get("ended_at"):
        status = (
            "succeeded"
            if run_meta.get("ok") is True
            else ("failed" if run_meta.get("ok") is False else "completed")
        )
    else:
        status = "running"
    room = "planning" if status == "running" else "done"
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
    elif event_type in {"route", "iteration", "swarm_start", "task_update", "model_runtime"}:
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
        elif event_type == "swarm_start":
            summary = "Swarm plan ready; dispatching agents."
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
    elif event_type == "swarm_done":
        ok = bool((last_evt or {}).get("ok"))
        status = "succeeded" if ok else "failed"
        room = "done" if ok else "review"
        summary = _trim_summary(
            str((last_evt or {}).get("final") or ("Swarm complete." if ok else "Swarm failed.")),
            140,
        )
    elif event_type == "done":
        status = "succeeded"
        room = "done"
        summary = "Run complete."

    return status, room, summary


def _job_room_and_summary(job: Any) -> tuple[str, str]:
    status = str(getattr(job, "status", "") or "").strip().lower()
    kind = str(getattr(job, "kind", "") or "").strip().lower()
    payload = getattr(job, "payload", {}) if isinstance(getattr(job, "payload", {}), dict) else {}

    if status == "queued":
        room = "inbox"
    elif status == "running":
        if kind in {"video_generation", "speech_transcription", "speech_synthesis"}:
            room = "tools"
        elif kind in {"workflow_task"}:
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


def _collect_benchmark_runs(runs_dir: Path, limit: int) -> List[Dict[str, Any]]:
    if not runs_dir.exists() or not runs_dir.is_dir():
        return []
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    for run_dir in run_dirs[:limit]:
        run_id = run_dir.name
        scorecard = _json_or_empty(run_dir / "scorecard.json")
        summary = scorecard.get("summary") if isinstance(scorecard.get("summary"), dict) else {}
        config = _json_or_empty(run_dir / "agentic_benchmark.config.json")
        delta = _json_or_empty(run_dir / "before_after.delta.json")
        pack_snapshot = _json_or_empty(run_dir / "task_pack.agentic.snapshot.json")
        if not pack_snapshot:
            pack_snapshot = _json_or_empty(run_dir / "task_pack.snapshot.json")
        competitors_raw = scorecard.get("competitors")
        if isinstance(competitors_raw, list):
            competitors = [str(x) for x in competitors_raw if str(x or "").strip()]
        else:
            competitors = list((summary.get("competitors") or {}).keys())

        ranking = summary.get("ranking") if isinstance(summary.get("ranking"), list) else []
        top = ranking[0] if ranking and isinstance(ranking[0], dict) else {}
        top_competitor = str(top.get("competitor") or "").strip()
        per_competitor = summary.get("competitors") if isinstance(summary.get("competitors"), dict) else {}
        top_metrics_raw = (
            per_competitor.get(top_competitor)
            if isinstance(per_competitor.get(top_competitor), dict)
            else {}
        )
        pack_tasks = pack_snapshot.get("tasks") if isinstance(pack_snapshot.get("tasks"), list) else []
        pack_tasks_total = len(pack_tasks)
        top_tasks_total_raw = top_metrics_raw.get("tasks_total") if isinstance(top_metrics_raw, dict) else None
        top_tasks_total = int(top_tasks_total_raw or 0) if str(top_tasks_total_raw or "").strip() else 0
        if top_tasks_total <= 0:
            top_tasks_total = pack_tasks_total
        top_success_count_raw = top_metrics_raw.get("success_count") if isinstance(top_metrics_raw, dict) else None
        top_success_count = (
            int(top_success_count_raw or 0) if str(top_success_count_raw or "").strip() else 0
        )
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
        artifacts: Dict[str, str] = {}
        for name in _BENCHMARK_ARTIFACTS:
            if (run_dir / name).exists():
                artifacts[name] = f"/api/mission/benchmarks/runs/{run_id}/artifact/{name}"
        out.append(
            {
                "run_id": run_id,
                "created_at": created_at,
                "competitors": competitors,
                "top_competitor": top_competitor,
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
                        float(top_metrics_raw.get("success_rate") or 0.0)
                        if isinstance(top_metrics_raw, dict)
                        else 0.0
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


def _mission_topology_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    agents = payload.get("agents") if isinstance(payload.get("agents"), list) else []
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    nodes: List[Dict[str, Any]] = []
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
    edges: List[Dict[str, Any]] = []
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

    timeline: List[Dict[str, Any]] = []
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


def register_mission_routes(
    app: web.Application,
    *,
    web_dir: Path,
    require_api_access: Callable[[web.Request], None],
    run_store_enabled_key: Any,
    run_store_module_key: Any,
) -> None:
    repo_root = _discover_repo_root(web_dir)
    runs_dir = (repo_root / "demo" / "agentic-runs").resolve()

    benchmark_jobs: Dict[str, Dict[str, Any]] = {}
    benchmark_tasks: Dict[str, asyncio.Task[Any]] = {}
    benchmark_procs: Dict[str, asyncio.subprocess.Process] = {}
    benchmark_lock = asyncio.Lock()

    async def mission_page(_request: web.Request) -> web.StreamResponse:
        return _serve_versioned_page(web_dir / "mission.html")

    async def _mission_approvals_payload() -> Dict[str, Any]:
        out: Dict[str, Any] = {
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

        broker = app.get("approvals")
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

    def _build_mission_control_payload() -> Dict[str, Any]:
        rooms = [
            {"id": "inbox", "label": "Inbox", "description": "Queued and waiting"},
            {"id": "planning", "label": "Planning", "description": "Reasoning and decomposition"},
            {"id": "tools", "label": "Tools", "description": "Calling external tools/APIs"},
            {"id": "files", "label": "Files", "description": "Touching workspace/filesystem"},
            {"id": "review", "label": "Review", "description": "Drafting, approvals, or blocked"},
            {"id": "done", "label": "Done", "description": "Completed and recently finished"},
        ]

        agents: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []

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
                updated_at = str(run.get("ended_at") or run.get("started_at") or _utc_iso_now())
                mode = str(run.get("mode") or "").strip()
                profile_name = str(run.get("profile") or "").strip()
                model_id = str(run.get("model_id") or "").strip()
                agents.append(
                    {
                        "id": f"run:{run_id}",
                        "source": "chat_run",
                        "kind": "run",
                        "name": f"{'Swarm' if mode == 'swarm' else 'Chat'} {run_id[:8]}",
                        "room": room,
                        "status": status,
                        "summary": summary,
                        "updated_at": updated_at,
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
            active_jobs = [
                j
                for j in jobs
                if str(getattr(j, "status", "") or "").strip().lower() in active_statuses
            ]
            ended_jobs = [
                j
                for j in jobs
                if str(getattr(j, "status", "") or "").strip().lower() not in active_statuses
            ]
            selected_jobs = active_jobs[:36] + ended_jobs[:18]

            for job in selected_jobs:
                job_id = str(getattr(job, "id", "") or "").strip()
                if not job_id:
                    continue
                room, summary = _job_room_and_summary(job)
                status = str(getattr(job, "status", "") or "").strip().lower() or "unknown"
                updated_at = _coerce_iso(
                    getattr(job, "updated_at", None) or getattr(job, "created_at", None)
                )
                kind = str(getattr(job, "kind", "") or "").strip()
                name = str(getattr(job, "name", "") or kind or "job")
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
                o
                for o in objectives
                if str(getattr(o, "status", "") or "").strip().lower() in active_obj_statuses
            ]
            ended_objs = [
                o
                for o in objectives
                if str(getattr(o, "status", "") or "").strip().lower() not in active_obj_statuses
            ]
            selected_objs = active_objs[:22] + ended_objs[:10]
            for obj in selected_objs:
                obj_id = str(getattr(obj, "id", "") or "").strip()
                if not obj_id:
                    continue
                room, summary = _objective_room_and_summary(obj)
                status = str(getattr(obj, "status", "") or "").strip().lower() or "unknown"
                updated_at = _coerce_iso(
                    getattr(obj, "updated_at", None) or getattr(obj, "created_at", None)
                )
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
                        "current_step_index": int(
                            getattr(obj, "current_step_index", 0) or 0
                        ),
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
                            f"job:{str(getattr(evt, 'job_id', '') or '')}"
                            if getattr(evt, "job_id", None)
                            else ""
                        ),
                        "run_id": "",
                        "ts": ts_iso,
                        "type": str(getattr(evt, "event_type", "") or "audit"),
                        "text": _trim_summary(
                            (
                                str(getattr(evt, "event_type", "") or "event")
                                + (" " + detail_txt if detail_txt else "")
                            ),
                            160,
                        ),
                    }
                )

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
            1
            for a in agents
            if str(a.get("status") or "")
            in {"running", "queued", "awaiting_approval", "blocked"}
        )
        return {
            "ok": True,
            "generated_at": _utc_iso_now(),
            "rooms": rooms,
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
            except Exception:
                raise web.HTTPBadRequest(text="invalid interval")
            if (not math.isfinite(interval_s)) or interval_s <= 0:
                raise web.HTTPBadRequest(text="invalid interval")
        interval_s = min(30.0, max(0.35, interval_s))

        max_updates = 0
        raw_max_updates = str(request.query.get("max_updates") or "").strip()
        if raw_max_updates:
            try:
                max_updates = int(raw_max_updates)
            except Exception:
                raise web.HTTPBadRequest(text="invalid max_updates")
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

        async def send(obj: Dict[str, Any]) -> None:
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

    async def _mission_require_store() -> Any:
        store = app.get("autonomy_store")
        if store is None:
            raise web.HTTPNotFound(text="autonomy store is not available")
        return store

    def _mission_wakeup_engine() -> None:
        engine = app.get("autonomy_engine")
        if engine is None:
            return
        wake = getattr(engine, "wake_up", None)
        if callable(wake):
            wake()

    async def api_mission_job_cancel(request: web.Request) -> web.Response:
        require_api_access(request)
        store = await _mission_require_store()
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        try:
            store.cancel_job(job_id, actor="mission_control")
        except KeyError:
            raise web.HTTPNotFound(text="job not found")
        _mission_wakeup_engine()
        return web.json_response({"ok": True, "job_id": job_id, "action": "cancel"})

    async def api_mission_job_run_now(request: web.Request) -> web.Response:
        require_api_access(request)
        store = await _mission_require_store()
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        try:
            store.set_job_status(
                job_id,
                "queued",
                next_run_at=datetime.now(timezone.utc),
                lock_clear=True,
            )
        except KeyError:
            raise web.HTTPNotFound(text="job not found")
        _mission_wakeup_engine()
        return web.json_response({"ok": True, "job_id": job_id, "action": "run_now"})

    async def api_mission_job_requeue(request: web.Request) -> web.Response:
        require_api_access(request)
        store = await _mission_require_store()
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        try:
            store.set_job_status(
                job_id,
                "queued",
                error=None,
                result=None,
                attempts=0,
                next_run_at=datetime.now(timezone.utc),
                lock_clear=True,
            )
        except KeyError:
            raise web.HTTPNotFound(text="job not found")
        _mission_wakeup_engine()
        return web.json_response({"ok": True, "job_id": job_id, "action": "requeue"})

    async def api_mission_autonomy_approval_decide(request: web.Request) -> web.Response:
        require_api_access(request)
        store = await _mission_require_store()
        approval_id = str(request.match_info.get("approval_id") or "").strip()
        if not approval_id:
            raise web.HTTPBadRequest(text="missing approval_id")
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        approve = bool(payload.get("approve"))
        actor = str(payload.get("actor") or "mission_control").strip() or "mission_control"
        reason = str(payload.get("reason") or "").strip() or None
        try:
            ap = store.decide_approval(
                approval_id=approval_id,
                approve=approve,
                actor=actor,
                reason=reason,
            )
        except KeyError:
            raise web.HTTPNotFound(text="approval not found")

        if approve:
            with contextlib.suppress(Exception):
                store.set_job_status(
                    ap.job_id,
                    "queued",
                    approved=True,
                    requires_approval=False,
                    next_run_at=datetime.now(timezone.utc),
                    lock_clear=True,
                )
        else:
            with contextlib.suppress(Exception):
                store.cancel_job(ap.job_id, actor=actor)
        _mission_wakeup_engine()
        return web.json_response(
            {
                "ok": True,
                "approval_id": str(getattr(ap, "id", approval_id)),
                "job_id": str(getattr(ap, "job_id", "")),
                "status": str(getattr(ap, "status", "approved" if approve else "denied")),
            }
        )

    async def api_mission_guardrails_approval_resolve(request: web.Request) -> web.Response:
        require_api_access(request)
        broker = app.get("approvals")
        if broker is None:
            raise web.HTTPNotFound(text="guardrails approvals are not available")
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        run_id = str(payload.get("run_id") or "").strip()
        tool_call_id = str(payload.get("tool_call_id") or "").strip()
        if not run_id or not tool_call_id:
            raise web.HTTPBadRequest(text="missing run_id or tool_call_id")
        approve = bool(payload.get("approve"))
        allow_session_tool = bool(payload.get("allow_session_tool"))
        tool_name = str(payload.get("tool_name") or "").strip() or None
        session_id = str(payload.get("session_id") or "").strip() or None
        resolve_fn = getattr(broker, "resolve", None)
        if not callable(resolve_fn):
            raise web.HTTPNotFound(text="guardrails approvals are not available")
        ok = await resolve_fn(
            run_id=run_id,
            tool_call_id=tool_call_id,
            approved=approve,
            allow_session_tool=allow_session_tool,
            tool_name=tool_name,
            session_id=session_id,
        )
        if not ok:
            raise web.HTTPNotFound(text="pending approval not found")
        return web.json_response(
            {
                "ok": True,
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "decision": "approve" if approve else "deny",
                "allow_session_tool": allow_session_tool,
            }
        )

    async def api_mission_alert_notify(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        alerts_raw = payload.get("alerts")
        alerts: List[Dict[str, Any]] = []
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
        webhook_url = str(channels.get("webhook_url") or "").strip()
        email_to = str(channels.get("email_to") or "").strip()
        subject = str(channels.get("subject") or "").strip() or "Thomas Mission Alert"

        lines: List[str] = []
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

        out: Dict[str, Any] = {"ok": True, "channels": {}}
        if webhook_url:
            if not re.match(r"^https?://", webhook_url, re.IGNORECASE):
                raise web.HTTPBadRequest(text="invalid webhook_url")
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

    async def api_benchmark_runs(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            limit = int(str(request.query.get("limit") or "40").strip())
        except Exception:
            limit = 40
        limit = max(1, min(limit, 200))
        runs = _collect_benchmark_runs(runs_dir, limit=limit)
        return web.json_response(
            {
                "ok": True,
                "runs_dir": str(runs_dir),
                "runs": runs,
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_packs(request: web.Request) -> web.Response:
        require_api_access(request)
        packs_map = _discover_task_packs(repo_root)
        default_key = _default_task_pack_key(packs_map)
        safe_keys = (
            "key",
            "id",
            "name",
            "version",
            "description",
            "protocol",
            "task_count",
            "duration_budget_seconds",
            "tasks",
            "file_name",
        )
        packs = sorted(
            [{k: v.get(k) for k in safe_keys} for v in packs_map.values()],
            key=lambda row: (0 if str(row.get("key") or "") == default_key else 1, str(row.get("name") or "")),
        )
        return web.json_response(
            {
                "ok": True,
                "default_pack": default_key,
                "packs": packs,
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_artifact(request: web.Request) -> web.Response:
        require_api_access(request)
        run_id = str(request.match_info.get("run_id") or "").strip()
        artifact = str(request.match_info.get("artifact") or "").strip()
        if artifact not in _BENCHMARK_ARTIFACTS:
            raise web.HTTPNotFound(text="artifact not found")
        run_dir = _run_dir_for_id(runs_dir, run_id)
        target = run_dir / artifact
        if not target.exists() or not target.is_file():
            raise web.HTTPNotFound(text="artifact not found")
        content_type = _ARTIFACT_CONTENT_TYPES.get(artifact, "application/octet-stream")
        return web.Response(
            body=target.read_bytes(),
            content_type=content_type,
            headers={"Cache-Control": "no-store"},
        )

    async def _run_benchmark_job(job_id: str, cmd: List[str], cwd: Path) -> None:
        log_tail: List[str] = []
        run_dir_text = ""
        proc: Optional[asyncio.subprocess.Process] = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "running"
                    job["started_at"] = _utc_iso_now()
                    job["pid"] = int(proc.pid or 0)
                    benchmark_procs[job_id] = proc

            if proc.stdout is not None:
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
                        log_tail.append(line)
                        if len(log_tail) > _MAX_BENCH_LOG_LINES:
                            log_tail = log_tail[-_MAX_BENCH_LOG_LINES:]
                        marker = "Agentic benchmark completed: "
                        if line.startswith(marker):
                            run_dir_text = line[len(marker) :].strip()

            exit_code = int(await proc.wait())
            resolved_run_dir = ""
            resolved_run_id = ""
            if run_dir_text:
                with contextlib.suppress(Exception):
                    resolved_path = Path(run_dir_text).resolve()
                    resolved_run_dir = str(resolved_path)
                    resolved_run_id = resolved_path.name

            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "succeeded" if exit_code == 0 else "failed"
                    job["ended_at"] = _utc_iso_now()
                    job["exit_code"] = exit_code
                    job["run_dir"] = resolved_run_dir
                    job["run_id"] = resolved_run_id
                    job["log_tail"] = list(log_tail)
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(Exception):
                    proc.terminate()
            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "cancelled"
                    job["ended_at"] = _utc_iso_now()
                    job["log_tail"] = list(log_tail)
            raise
        except Exception as exc:
            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "failed"
                    job["ended_at"] = _utc_iso_now()
                    job["error"] = f"{type(exc).__name__}: {exc}"
                    job["log_tail"] = list(log_tail)
        finally:
            async with benchmark_lock:
                benchmark_procs.pop(job_id, None)

    async def api_benchmark_run(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        profile = str(payload.get("profile") or "local").strip() or "local"
        include_baseline = bool(payload.get("include_baseline", False))
        thomas_mode = str(payload.get("thomas_mode") or "fast").strip().lower()
        if thomas_mode not in {"fast", "auto", "thinking", "swarm"}:
            thomas_mode = "fast"
        token_economy = str(payload.get("token_economy") or "optimal").strip().lower()
        if token_economy not in {"cheap", "optimal", "max"}:
            token_economy = "optimal"
        runner = str(payload.get("runner") or "embedded").strip().lower()
        if runner not in {"embedded", "api"}:
            runner = "embedded"

        packs_map = _discover_task_packs(repo_root)
        if not packs_map:
            raise web.HTTPNotFound(text="no benchmark task packs found")
        default_pack_key = _default_task_pack_key(packs_map)
        task_pack_key = str(payload.get("task_pack") or default_pack_key).strip().lower()
        aliases = {
            "quick": "smoke",
            "short": "smoke",
            "full": "local",
            "default": default_pack_key,
        }
        task_pack_key = aliases.get(task_pack_key, task_pack_key)
        pack_meta = packs_map.get(task_pack_key)
        if pack_meta is None:
            available = ", ".join(sorted(packs_map.keys()))
            raise web.HTTPBadRequest(
                text=f"unknown task_pack '{task_pack_key}'. available: {available}"
            )
        task_pack_path = Path(str(pack_meta.get("path") or "")).resolve()
        if not task_pack_path.exists():
            raise web.HTTPNotFound(text=f"task pack not found: {task_pack_path}")

        max_iterations: Optional[int] = None
        if payload.get("max_iterations") is not None:
            try:
                max_iterations = int(payload.get("max_iterations"))
            except Exception:
                raise web.HTTPBadRequest(text="invalid max_iterations")
            if max_iterations <= 0:
                raise web.HTTPBadRequest(text="invalid max_iterations")

        cmd = [
            sys.executable,
            "scripts/run_agentic_benchmark.py",
            "--profile",
            profile,
            "--task-pack",
            str(task_pack_path),
            "--thomas-runner",
            runner,
            "--thomas-mode",
            thomas_mode,
            "--thomas-token-economy",
            token_economy,
        ]
        if not include_baseline:
            cmd.append("--skip-baseline")
        if max_iterations is not None:
            cmd.extend(["--max-iterations", str(max_iterations)])

        job_id = secrets.token_urlsafe(8)
        created_at = _utc_iso_now()
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": created_at,
            "started_at": "",
            "ended_at": "",
            "pid": 0,
            "exit_code": None,
            "run_id": "",
            "run_dir": "",
            "error": "",
            "options": {
                "profile": profile,
                "task_pack": str(task_pack_path),
                "task_pack_key": task_pack_key,
                "task_pack_id": str(pack_meta.get("id") or ""),
                "task_pack_name": str(pack_meta.get("name") or ""),
                "task_count": int(pack_meta.get("task_count") or 0),
                "include_baseline": include_baseline,
                "thomas_mode": thomas_mode,
                "token_economy": token_economy,
                "runner": runner,
                "max_iterations": max_iterations,
            },
            "cmd": cmd,
            "log_tail": [],
        }

        task = asyncio.create_task(_run_benchmark_job(job_id, cmd, repo_root))
        async with benchmark_lock:
            benchmark_jobs[job_id] = job
            benchmark_tasks[job_id] = task
            if len(benchmark_jobs) > _MAX_BENCH_JOBS:
                stale = sorted(
                    benchmark_jobs.values(),
                    key=lambda j: _iso_to_epoch(j.get("created_at")),
                )[:-_MAX_BENCH_JOBS]
                for old in stale:
                    old_id = str(old.get("id") or "")
                    if not old_id or old_id == job_id:
                        continue
                    old_task = benchmark_tasks.get(old_id)
                    if old_task and not old_task.done():
                        continue
                    benchmark_jobs.pop(old_id, None)
                    benchmark_tasks.pop(old_id, None)
                    benchmark_procs.pop(old_id, None)

        return web.json_response(
            {"ok": True, "job": job},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_jobs(request: web.Request) -> web.Response:
        require_api_access(request)
        async with benchmark_lock:
            jobs = [dict(v) for v in benchmark_jobs.values()]
        jobs.sort(key=lambda j: _iso_to_epoch(j.get("created_at")), reverse=True)
        return web.json_response(
            {"ok": True, "jobs": jobs},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_job_cancel(request: web.Request) -> web.Response:
        require_api_access(request)
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")

        async with benchmark_lock:
            job = benchmark_jobs.get(job_id)
            if job is None:
                raise web.HTTPNotFound(text="job not found")
            task = benchmark_tasks.get(job_id)
            proc = benchmark_procs.get(job_id)
            job["status"] = "cancel_requested"

        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.terminate()
        if task is not None and not task.done():
            task.cancel()

        return web.json_response({"ok": True, "job_id": job_id, "action": "cancel"})

    async def _cleanup_benchmark_jobs(_app: web.Application) -> None:
        async with benchmark_lock:
            tasks = list(benchmark_tasks.values())
            procs = list(benchmark_procs.values())
        for proc in procs:
            if proc.returncode is None:
                with contextlib.suppress(Exception):
                    proc.terminate()
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    app.on_cleanup.append(_cleanup_benchmark_jobs)

    app.router.add_get("/mission", mission_page)
    app.router.add_get("/api/mission/control", api_mission_control)
    app.router.add_get("/api/mission/stream", api_mission_stream)
    app.router.add_post("/api/mission/jobs/{job_id}/cancel", api_mission_job_cancel)
    app.router.add_post("/api/mission/jobs/{job_id}/run_now", api_mission_job_run_now)
    app.router.add_post("/api/mission/jobs/{job_id}/requeue", api_mission_job_requeue)
    app.router.add_post(
        "/api/mission/approvals/autonomy/{approval_id}/decision",
        api_mission_autonomy_approval_decide,
    )
    app.router.add_post(
        "/api/mission/approvals/guardrails/resolve",
        api_mission_guardrails_approval_resolve,
    )
    app.router.add_post("/api/mission/alerts/notify", api_mission_alert_notify)
    app.router.add_get("/api/mission/benchmarks/packs", api_benchmark_packs)
    app.router.add_get("/api/mission/benchmarks/runs", api_benchmark_runs)
    app.router.add_get(
        "/api/mission/benchmarks/runs/{run_id}/artifact/{artifact}",
        api_benchmark_artifact,
    )
    app.router.add_post("/api/mission/benchmarks/run", api_benchmark_run)
    app.router.add_get("/api/mission/benchmarks/jobs", api_benchmark_jobs)
    app.router.add_post("/api/mission/benchmarks/jobs/{job_id}/cancel", api_benchmark_job_cancel)
