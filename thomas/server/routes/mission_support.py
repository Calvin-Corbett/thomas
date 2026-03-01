"""Mission route shared constants and helper utilities."""

from __future__ import annotations

import contextlib
import ipaddress
import json
import math
import os
import re
import secrets
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

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
_ARTIFACT_CONTENT_TYPES: dict[str, str] = {
    "report.md": "text/markdown",
    "execution_plan.md": "text/markdown",
    "scorecard.json": "application/json",
    "before_after.delta.json": "application/json",
    "benchmark_results.raw.json": "application/json",
    "agentic_benchmark.config.json": "application/json",
}
_MAX_ALERT_NOTIFICATION_BODY_CHARS = 8000
_ALERT_HTTP_TIMEOUT_SECONDS = 8.0
_MISSION_ALLOWED_JOB_KINDS = {
    "workflow_task",
    "autonomy_task",
    "daily_briefing",
    "reminder",
    "video_generation",
    "speech_transcription",
    "speech_synthesis",
}
_MISSION_ALLOWED_RISK_CLASSES = {"low", "medium", "high", "critical"}
_MISSION_TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "dead"}
_AUTOPILOT_OBJECTIVE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{4,80}$")


def _task_pack_key_for_path(path: Path) -> str:
    name = str(path.name or "").strip()
    m = re.fullmatch(r"task_pack\.agentic\.([A-Za-z0-9._-]+)\.json", name, re.IGNORECASE)
    if m:
        return str(m.group(1) or "").strip().lower()
    return str(path.stem or "").strip().lower()


def _read_task_pack_meta(path: Path, *, key: str) -> dict[str, Any]:
    payload = _json_or_empty(path)
    tasks_raw = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    tasks: list[dict[str, Any]] = []
    duration_budget_seconds = 0
    for row in tasks_raw:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not tid and not title:
            continue
        budget_value = row.get("time_budget_seconds")
        budget_seconds: int | None = None
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


def _discover_task_packs(repo_root: Path) -> dict[str, dict[str, Any]]:
    demo_dir = (repo_root / "demo").resolve()
    if not demo_dir.exists() or not demo_dir.is_dir():
        return {}
    files = sorted(
        [p for p in demo_dir.glob("task_pack.agentic*.json") if p.is_file()],
        key=lambda p: p.name.lower(),
    )
    out: dict[str, dict[str, Any]] = {}
    for path in files:
        key = _task_pack_key_for_path(path)
        if not key or key in out:
            continue
        out[key] = _read_task_pack_meta(path, key=key)
    return out


def _default_task_pack_key(packs: dict[str, dict[str, Any]]) -> str:
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


def _short_id(value: Any, width: int = 6) -> str:
    txt = str(value or "").strip()
    if not txt:
        return ""
    return txt[: max(1, int(width))]


def _compact_model_label(value: Any, max_len: int = 24) -> str:
    txt = str(value or "").strip()
    if not txt:
        return ""
    if "/" in txt:
        txt = txt.split("/")[-1]
    txt = txt.replace("models:", "").replace("model:", "").strip()
    return _trim_summary(txt, max_len)


def _mission_display_hhmm_utc(value: Any) -> str:
    epoch = _iso_to_epoch(value)
    if epoch <= 0:
        return ""
    try:
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        return dt.strftime("%H:%MZ")
    except Exception:
        return ""


def _mission_run_display_name(run_meta: dict[str, Any]) -> str:
    mode = str(run_meta.get("mode") or "").strip().lower()
    if mode:
        base = f"{mode.title()} Session"
    else:
        base = "Chat Session"

    profile = str(run_meta.get("profile") or "").strip()
    model_id = _compact_model_label(run_meta.get("model_id"))
    session_id = _short_id(run_meta.get("session_id"), width=6)
    started = _mission_display_hhmm_utc(run_meta.get("started_at"))

    suffix = profile or model_id or (f"session {session_id}" if session_id else "")
    parts = [base]
    if suffix:
        parts.append(suffix)
    if started:
        parts.append(started)
    return " | ".join(parts)


def _mission_job_display_name(job: Any) -> str:
    kind = str(getattr(job, "kind", "") or "").strip().lower()
    payload = getattr(job, "payload", None)
    payload_dict = payload if isinstance(payload, dict) else {}

    raw_name = str(getattr(job, "name", "") or "").strip()
    generic_names = {"job", "task", "mission task", "workflow task", "autonomy task"}
    if raw_name and raw_name.lower() not in generic_names:
        return _trim_summary(raw_name, 84)

    goal = str(payload_dict.get("goal") or payload_dict.get("task") or payload_dict.get("prompt") or "").strip()
    if goal:
        return _trim_summary(goal, 84)

    if kind == "workflow_task":
        workflow = str(payload_dict.get("workflow") or "chain").strip().lower() or "chain"
        return f"Workflow Task ({workflow})"
    if kind == "autonomy_task":
        return "Autonomy Task"
    if kind == "daily_briefing":
        return "Daily Briefing"
    if kind == "reminder":
        return "Reminder"
    if kind == "video_generation":
        return "Video Generation"
    if kind == "speech_transcription":
        return "Speech Transcription"
    if kind == "speech_synthesis":
        return "Speech Synthesis"
    if kind:
        return _trim_summary(kind.replace("_", " ").title(), 84)
    return "Mission Job"


def _json_or_empty(path: Path) -> dict[str, Any]:
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


def _parse_iso_datetime(value: Any) -> datetime | None:
    txt = str(value or "").strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _mission_validate_hhmm(value: Any) -> str:
    txt = str(value or "").strip()
    if not re.fullmatch(r"^\d{2}:\d{2}$", txt):
        raise web.HTTPBadRequest(text="schedule.at must be HH:MM")
    hh = int(txt[:2])
    mm = int(txt[3:5])
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        raise web.HTTPBadRequest(text="schedule.at must be HH:MM")
    return txt


def _mission_normalize_schedule(raw: Any, *, run_at: datetime | None) -> dict[str, Any] | None:
    if raw is None:
        if run_at is None:
            return None
        return {"type": "once", "run_at": run_at.isoformat()}
    if not isinstance(raw, dict):
        raise web.HTTPBadRequest(text="schedule must be an object")

    stype = str(raw.get("type") or "").strip().lower()
    if not stype:
        if run_at is None:
            return None
        stype = "once"

    if stype == "once":
        when = _parse_iso_datetime(raw.get("run_at")) or run_at
        if when is None:
            raise web.HTTPBadRequest(text="schedule.run_at required for once")
        return {"type": "once", "run_at": when.isoformat()}

    if stype == "interval":
        with contextlib.suppress(Exception):
            every = float(raw.get("every_seconds"))
            if math.isfinite(every) and every > 0:
                out: dict[str, Any] = {"type": "interval", "every_seconds": float(every)}
                start_at = _parse_iso_datetime(raw.get("start_at"))
                if start_at is not None:
                    out["start_at"] = start_at.isoformat()
                return out
        raise web.HTTPBadRequest(text="schedule.every_seconds must be > 0")

    if stype == "daily":
        at = _mission_validate_hhmm(raw.get("at"))
        tz = str(raw.get("tz") or "UTC").strip() or "UTC"
        return {"type": "daily", "at": at, "tz": tz}

    if stype == "weekly":
        at = _mission_validate_hhmm(raw.get("at"))
        tz = str(raw.get("tz") or "UTC").strip() or "UTC"
        dow_raw = raw.get("dow")
        dows: list[int] = []
        if isinstance(dow_raw, list):
            for row in dow_raw:
                with contextlib.suppress(Exception):
                    day = int(row)
                    if 0 <= day <= 6:
                        dows.append(day)
        dows = sorted(set(dows))
        if not dows:
            raise web.HTTPBadRequest(text="schedule.dow must include weekday numbers 0..6")
        return {"type": "weekly", "at": at, "tz": tz, "dow": dows}

    raise web.HTTPBadRequest(text=f"unsupported schedule type '{stype}'")


def _autopilot_objective_id(raw_objective_id: Any, *, goal: str) -> str:
    candidate = str(raw_objective_id or "").strip()
    if candidate and _AUTOPILOT_OBJECTIVE_ID_RE.fullmatch(candidate):
        return candidate
    seed = re.sub(r"[^a-z0-9]+", "-", str(goal or "").strip().lower()).strip("-")
    if not seed:
        seed = "objective"
    suffix = secrets.token_urlsafe(4).replace("-", "").replace("_", "").lower()
    return f"{seed[:48]}-{suffix[:8]}"


def _autopilot_schedule_from_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    run_at = _parse_iso_datetime(payload.get("run_at"))
    raw_schedule = payload.get("schedule")
    if raw_schedule is not None:
        schedule = _mission_normalize_schedule(raw_schedule, run_at=run_at)
        if schedule is None:
            raise web.HTTPBadRequest(text="schedule is required")
        return schedule, "custom"

    cadence = str(payload.get("cadence") or payload.get("mode") or "continuous").strip().lower()
    if cadence in {"", "continuous", "always", "24/7", "24x7", "247"}:
        every_seconds = _coerce_int(payload.get("every_seconds"), 900)
        if payload.get("every_minutes") is not None:
            every_seconds = max(every_seconds, _coerce_int(payload.get("every_minutes"), 15) * 60)
        every_seconds = max(60, min(every_seconds, 86400))
        return {"type": "interval", "every_seconds": float(every_seconds)}, "continuous"
    if cadence in {"interval", "repeat"}:
        every_seconds = _coerce_int(payload.get("every_seconds"), 900)
        every_seconds = max(60, min(every_seconds, 86400))
        return {"type": "interval", "every_seconds": float(every_seconds)}, "interval"
    if cadence in {"hour", "hourly"}:
        return {"type": "interval", "every_seconds": float(3600)}, "hourly"
    if cadence in {"daily", "day"}:
        at = _mission_validate_hhmm(payload.get("at") or "09:00")
        tz = str(payload.get("tz") or "UTC").strip() or "UTC"
        return {"type": "daily", "at": at, "tz": tz}, "daily"
    if cadence in {"weekly", "week"}:
        at = _mission_validate_hhmm(payload.get("at") or "09:00")
        tz = str(payload.get("tz") or "UTC").strip() or "UTC"
        dow_raw = payload.get("dow")
        dows: list[int] = []
        if isinstance(dow_raw, list):
            for row in dow_raw:
                with contextlib.suppress(Exception):
                    day = int(row)
                    if 0 <= day <= 6:
                        dows.append(day)
        dows = sorted(set(dows)) or [0]
        return {"type": "weekly", "at": at, "tz": tz, "dow": dows}, "weekly"
    raise web.HTTPBadRequest(text=f"unsupported cadence '{cadence}'")


def _mission_job_payload(job: Any) -> dict[str, Any]:
    retry_policy = getattr(job, "retry_policy", None)
    retry_payload: dict[str, Any] = {}
    if retry_policy is not None:
        retry_payload = {
            "max_attempts": int(getattr(retry_policy, "max_attempts", 0) or 0),
            "base_delay_s": float(getattr(retry_policy, "base_delay_s", 0.0) or 0.0),
            "max_delay_s": float(getattr(retry_policy, "max_delay_s", 0.0) or 0.0),
            "jitter": float(getattr(retry_policy, "jitter", 0.0) or 0.0),
            "backoff": float(getattr(retry_policy, "backoff", 0.0) or 0.0),
        }

    payload = getattr(job, "payload", None)
    result = getattr(job, "result", None)
    error = getattr(job, "error", None)
    schedule = getattr(job, "schedule", None)
    return {
        "id": str(getattr(job, "id", "") or ""),
        "name": str(getattr(job, "name", "") or ""),
        "kind": str(getattr(job, "kind", "") or ""),
        "status": str(getattr(job, "status", "") or ""),
        "created_at": _coerce_iso(getattr(job, "created_at", None)),
        "updated_at": _coerce_iso(getattr(job, "updated_at", None)),
        "next_run_at": (_coerce_iso(getattr(job, "next_run_at", None)) if getattr(job, "next_run_at", None) else ""),
        "parent_id": str(getattr(job, "parent_id", "") or ""),
        "session_id": str(getattr(job, "session_id", "") or ""),
        "payload": payload if isinstance(payload, dict) else {},
        "result": result if isinstance(result, dict) else {},
        "error": error if isinstance(error, dict) else {},
        "schedule": schedule if isinstance(schedule, dict) else None,
        "attempts": int(getattr(job, "attempts", 0) or 0),
        "retry_policy": retry_payload,
        "risk_class": str(getattr(job, "risk_class", "") or "low"),
        "requires_approval": bool(getattr(job, "requires_approval", False)),
        "approved": bool(getattr(job, "approved", False)) if getattr(job, "approved", None) is not None else None,
        "cancelled": bool(getattr(job, "cancelled", False)),
    }


def _safe_approval_dict(ap: Any) -> dict[str, Any]:
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


def _http_post_json(
    url: str, payload: dict[str, Any], *, timeout_s: float = _ALERT_HTTP_TIMEOUT_SECONDS
) -> dict[str, Any]:
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


def _contains_header_newline(value: str) -> bool:
    return "\n" in value or "\r" in value


def _sanitize_alert_header(value: Any, *, field: str, default: str = "") -> str:
    text = str(value or default).strip()
    if _contains_header_newline(text):
        raise web.HTTPBadRequest(text=f"invalid {field}")
    return text


def _is_private_or_local_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    if not normalized:
        return True
    if normalized in {"localhost"} or normalized.endswith(".localhost") or normalized.endswith(".local"):
        return True
    with contextlib.suppress(Exception):
        ip = ipaddress.ip_address(normalized)
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    return False


def _alert_webhook_host_allowlist() -> list[str]:
    raw = str(os.environ.get("THOMAS_ALERT_WEBHOOK_HOST_ALLOWLIST") or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        host = str(part or "").strip().lower().rstrip(".")
        if host:
            out.append(host)
    return out


def _host_allowlisted(host: str, allowlist: list[str]) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    for item in allowlist:
        if normalized == item or normalized.endswith("." + item):
            return True
    return False


def _normalize_alert_webhook_url(raw_url: str) -> str:
    text = str(raw_url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise web.HTTPBadRequest(text="invalid webhook_url")
    if parsed.username or parsed.password:
        raise web.HTTPBadRequest(text="invalid webhook_url")
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        raise web.HTTPBadRequest(text="invalid webhook_url")

    allow_private_targets = _coerce_bool(
        os.environ.get("THOMAS_ALERT_ALLOW_PRIVATE_WEBHOOK_URLS"),
        False,
    )
    if _is_private_or_local_host(host) and not allow_private_targets:
        raise web.HTTPBadRequest(text="webhook_url must target a public host")

    allowlist = _alert_webhook_host_allowlist()
    if allowlist and not _host_allowlisted(host, allowlist):
        raise web.HTTPBadRequest(text="webhook_url host is not allowlisted")

    return parsed.geturl()


def _send_alert_email(to_addr: str, subject: str, body_text: str) -> dict[str, Any]:
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
    if _contains_header_newline(str(to_addr)) or _contains_header_newline(str(subject)):
        return {"ok": False, "error": "email unavailable: invalid header value"}

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
    if any(k in low for k in ("fs.", "file", "path", "git.", "diff.", "code_search", "read", "write", "edit")):
        return "files"
    return "tools"


def _latest_run_event(run_store_mod: Any, run_id: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    try:
        for evt in run_store_mod.stream_replay(run_id):
            if isinstance(evt, dict):
                latest = evt
    except Exception:
        return None
    return latest
