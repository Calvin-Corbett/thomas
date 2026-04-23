"""Content Hub aggregation helpers for Mission Control."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from thomas.preferences.store import PreferencesStore, get_db_path
from .mission_content_hub_constants import (
    _CONTENT_ACTIVE_STATUSES,
    _CONTENT_FALLBACK_PLATFORM,
    _CONTENT_HINT_FIELDS,
    _CONTENT_HUB_CHECKLIST_TEMPLATE,
    _CONTENT_HUB_NAV_ITEMS,
    _CONTENT_HUB_ORGANIZATION_AXES,
    _CONTENT_KEYWORD_RE,
    _CONTENT_PLATFORM_ALIASES,
    _CONTENT_PLATFORM_ORDER,
    _CONTENT_RELEVANT_JOB_KINDS,
    _CONTENT_TERMINAL_STATUSES,
    _CONTENT_TEXT_PLATFORM_HINTS,
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_to_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0

def _content_count_installed_skills() -> int:
    roots: List[Path] = []
    codex_home = str(os.environ.get("CODEX_HOME") or "").strip()
    if codex_home:
        roots.append(Path(codex_home) / "skills")
    roots.append(Path.home() / ".codex" / "skills")

    seen_roots: set[str] = set()
    count = 0
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            name = str(child.name or "").strip()
            if not name or name.startswith("."):
                continue
            if name.lower() == ".system":
                continue
            if (child / "SKILL.md").exists():
                count += 1
    return count


def _content_count_configured_api_keys(user_id: str = "default") -> int:
    try:
        store = PreferencesStore(get_db_path())
        prefs = store.get(user_id=user_id)
        masked = prefs.api_keys.model_dump() if hasattr(prefs.api_keys, "model_dump") else {}
    except Exception:
        return 0
    total = 0
    for value in masked.values() if isinstance(masked, dict) else []:
        if str(value or "").strip():
            total += 1
    return total


def _content_count_recent_audit_events(autonomy_store: Any, *, hours: int = 24) -> int:
    if autonomy_store is None:
        return 0
    try:
        events = list(autonomy_store.list_audit(limit=320) or [])
    except Exception:
        return 0
    cutoff_epoch = datetime.now(timezone.utc).timestamp() - max(1, int(hours)) * 3600
    total = 0
    for ev in events:
        ts_epoch = _iso_to_epoch(getattr(ev, "ts", None))
        if ts_epoch >= cutoff_epoch:
            total += 1
    return total


def _content_compact_token(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[^a-z0-9]+", "", raw)


def _content_platform_from_token(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw in _CONTENT_PLATFORM_ALIASES:
        return _CONTENT_PLATFORM_ALIASES[raw]

    compact = _content_compact_token(raw)
    if not compact:
        return ""
    for alias, label in _CONTENT_PLATFORM_ALIASES.items():
        if compact == _content_compact_token(alias):
            return label
    return ""


def _content_platform_sort_key(label: Any) -> tuple[int, str]:
    name = str(label or "").strip()
    if name in _CONTENT_PLATFORM_ORDER:
        return (_CONTENT_PLATFORM_ORDER.index(name), name.lower())
    if name == _CONTENT_FALLBACK_PLATFORM:
        return (999, name.lower())
    return (500, name.lower())


def _content_collect_platform_labels(value: Any, out: set[str], *, depth: int = 0) -> None:
    if depth > 4:
        return
    if isinstance(value, str):
        raw = str(value or "").strip()
        if not raw:
            return
        direct = _content_platform_from_token(raw)
        if direct:
            out.add(direct)
        for token in re.split(r"[,;|/\n]+", raw):
            mapped = _content_platform_from_token(token)
            if mapped:
                out.add(mapped)
        return
    if isinstance(value, dict):
        for idx, (key, val) in enumerate(value.items()):
            if idx >= 60:
                break
            _content_collect_platform_labels(key, out, depth=depth + 1)
            _content_collect_platform_labels(val, out, depth=depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for idx, item in enumerate(value):
            if idx >= 80:
                break
            _content_collect_platform_labels(item, out, depth=depth + 1)


def _content_collect_text_fragments(value: Any, out: List[str], *, depth: int = 0) -> None:
    if depth > 4 or len(out) >= 160:
        return
    if isinstance(value, str):
        txt = " ".join(value.strip().split())
        if txt:
            out.append(txt[:260])
        return
    if isinstance(value, dict):
        for idx, (key, val) in enumerate(value.items()):
            if idx >= 60 or len(out) >= 160:
                break
            key_txt = str(key or "").strip()
            if key_txt:
                out.append(key_txt[:80])
            _content_collect_text_fragments(val, out, depth=depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for idx, item in enumerate(value):
            if idx >= 80 or len(out) >= 160:
                break
            _content_collect_text_fragments(item, out, depth=depth + 1)


def _content_job_text_blob(job_row: Dict[str, Any]) -> str:
    parts: List[str] = []
    for value in (
        job_row.get("name"),
        job_row.get("kind"),
        job_row.get("payload"),
        job_row.get("result"),
    ):
        _content_collect_text_fragments(value, parts)
    return " ".join(parts)


def _content_job_platforms(job_row: Dict[str, Any]) -> List[str]:
    labels: set[str] = set()
    payload = job_row.get("payload") if isinstance(job_row.get("payload"), dict) else {}
    result = job_row.get("result") if isinstance(job_row.get("result"), dict) else {}
    for source in (payload, result):
        for key in _CONTENT_HINT_FIELDS:
            if key in source:
                _content_collect_platform_labels(source.get(key), labels)
        for key, val in source.items():
            low_key = str(key or "").strip().lower()
            if (
                low_key in _CONTENT_HINT_FIELDS
                or low_key.endswith("_platform")
                or low_key.endswith("_platforms")
            ):
                _content_collect_platform_labels(val, labels)

    text_blob = _content_job_text_blob(job_row)
    for pattern, label in _CONTENT_TEXT_PLATFORM_HINTS:
        if pattern.search(text_blob):
            labels.add(label)
    return sorted(labels, key=_content_platform_sort_key)


def _content_job_is_related(kind: str, text_blob: str, platforms: List[str]) -> bool:
    low_kind = str(kind or "").strip().lower()
    if platforms:
        return True
    if any(token in low_kind for token in ("content", "social", "publish", "video")):
        return True
    if _CONTENT_KEYWORD_RE.search(text_blob):
        return True
    return low_kind in _CONTENT_RELEVANT_JOB_KINDS and bool(text_blob.strip())


def _trim_summary(value: Any, max_len: int = 180) -> str:
    """Truncate *value* to at most *max_len* characters."""
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _content_job_summary(job_row: Dict[str, Any]) -> str:
    payload = job_row.get("payload") if isinstance(job_row.get("payload"), dict) else {}
    for key in ("goal", "prompt", "task", "message", "text", "summary", "topic", "title"):
        txt = str(payload.get(key) or "").strip()
        if txt:
            return _trim_summary(txt, 76)
    fallback = str(job_row.get("name") or "").strip() or str(job_row.get("kind") or "content task")
    return _trim_summary(fallback.replace("_", " "), 76)


def _content_workflow_name(job_row: Dict[str, Any]) -> str:
    payload = job_row.get("payload") if isinstance(job_row.get("payload"), dict) else {}
    for key in ("workflow", "pipeline", "template"):
        value = str(payload.get(key) or "").strip()
        if value:
            cleaned = value.replace("_", " ").replace("-", " ")
            return " ".join(part.capitalize() for part in cleaned.split())
    kind = str(job_row.get("kind") or "").strip().replace("_", " ")
    return " ".join(part.capitalize() for part in kind.split()) or "Content Flow"


def _content_status_label(status: Any) -> str:
    raw = str(status or "").strip().lower().replace("_", " ")
    if not raw:
        return "Queued"
    return " ".join(part.capitalize() for part in raw.split())


def _content_workflow_trigger(schedule_types: set[str]) -> str:
    cleaned = sorted({str(s or "").strip().lower() for s in schedule_types if str(s or "").strip()})
    if not cleaned:
        return "Manual / event-driven"
    if len(cleaned) > 1:
        labels = []
        for kind in cleaned:
            if kind == "daily":
                labels.append("daily")
            elif kind == "weekly":
                labels.append("weekly")
            elif kind == "interval":
                labels.append("interval")
            elif kind == "once":
                labels.append("one-time")
            else:
                labels.append(kind)
        return "Mixed cadence: " + ", ".join(labels)
    stype = cleaned[0]
    if stype == "daily":
        return "Daily schedule"
    if stype == "weekly":
        return "Weekly schedule"
    if stype == "interval":
        return "Interval schedule"
    if stype == "once":
        return "One-time run"
    return stype


def _build_content_hub_payload(
    jobs: List[Dict[str, Any]],
    *,
    approvals_pending: int = 0,
    sessions_active: int = 0,
    sessions_recent_total: int = 0,
    skills_installed: int = 0,
    api_keys_configured: int = 0,
    audit_events_last_24h: int = 0,
) -> Dict[str, Any]:
    platform_map: Dict[str, Dict[str, Any]] = {}
    workflow_groups: Dict[str, Dict[str, Any]] = {}
    scheduler_rows: List[Dict[str, Any]] = []

    def ensure_platform(label: str) -> Dict[str, Any]:
        name = str(label or "").strip() or _CONTENT_FALLBACK_PLATFORM
        row = platform_map.get(name)
        if row is None:
            row = {
                "name": name,
                "connected": False,
                "total_jobs": 0,
                "queued": 0,
                "running": 0,
                "awaiting_approval": 0,
                "scheduled": 0,
                "published": 0,
                "failed": 0,
                "posts_last_7d": 0,
                "last_activity_at": "",
            }
            platform_map[name] = row
        return row

    for label in _CONTENT_PLATFORM_ORDER:
        ensure_platform(label)

    content_jobs = 0
    active_jobs = 0
    queued_jobs = 0
    awaiting_jobs = 0
    scheduled_jobs = 0
    recurring_cron_jobs = 0
    now_epoch = datetime.now(timezone.utc).timestamp()
    recent_cutoff_epoch = now_epoch - (7 * 24 * 60 * 60)

    for job in jobs:
        if not isinstance(job, dict):
            continue
        kind = str(job.get("kind") or "").strip().lower()
        text_blob = _content_job_text_blob(job)
        platforms = _content_job_platforms(job)
        if not _content_job_is_related(kind, text_blob, platforms):
            continue

        status = str(job.get("status") or "").strip().lower() or "queued"
        content_jobs += 1
        if status in _CONTENT_ACTIVE_STATUSES:
            active_jobs += 1
        if status in {"queued", "pending"}:
            queued_jobs += 1
        if status == "awaiting_approval":
            awaiting_jobs += 1

        run_at = str(job.get("next_run_at") or "").strip()
        if not run_at and status in _CONTENT_ACTIVE_STATUSES:
            run_at = str(job.get("updated_at") or job.get("created_at") or "").strip()
        schedule_obj = job.get("schedule") if isinstance(job.get("schedule"), dict) else {}
        schedule_type = str(schedule_obj.get("type") or "").strip().lower()
        if schedule_type in {"interval", "daily", "weekly"}:
            recurring_cron_jobs += 1
        if schedule_obj or run_at:
            scheduled_jobs += 1

        created_epoch = _iso_to_epoch(job.get("created_at"))
        updated_at = str(job.get("updated_at") or job.get("created_at") or "").strip()
        updated_epoch = _iso_to_epoch(updated_at)
        platform_labels = platforms[:] if platforms else [_CONTENT_FALLBACK_PLATFORM]

        for label in platform_labels:
            row = ensure_platform(label)
            row["connected"] = True
            row["total_jobs"] = int(row.get("total_jobs") or 0) + 1
            if status in {"queued", "pending"}:
                row["queued"] = int(row.get("queued") or 0) + 1
            elif status == "running":
                row["running"] = int(row.get("running") or 0) + 1
            elif status == "awaiting_approval":
                row["awaiting_approval"] = int(row.get("awaiting_approval") or 0) + 1
            if status in {"succeeded", "completed"}:
                row["published"] = int(row.get("published") or 0) + 1
            elif status in _CONTENT_TERMINAL_STATUSES:
                row["failed"] = int(row.get("failed") or 0) + 1
            if job.get("schedule") or run_at:
                row["scheduled"] = int(row.get("scheduled") or 0) + 1
            if created_epoch >= recent_cutoff_epoch:
                row["posts_last_7d"] = int(row.get("posts_last_7d") or 0) + 1
            if updated_epoch > _iso_to_epoch(row.get("last_activity_at")):
                row["last_activity_at"] = updated_at

        workflow_name = _content_workflow_name(job)
        workflow_key = workflow_name.lower()
        workflow = workflow_groups.get(workflow_key)
        if workflow is None:
            workflow = {
                "name": workflow_name,
                "total_jobs": 0,
                "active_jobs": 0,
                "requires_approval_count": 0,
                "awaiting_approval_count": 0,
                "platforms": set(),
                "schedule_types": set(),
                "last_activity_at": "",
            }
            workflow_groups[workflow_key] = workflow
        workflow["total_jobs"] = int(workflow.get("total_jobs") or 0) + 1
        if status in _CONTENT_ACTIVE_STATUSES:
            workflow["active_jobs"] = int(workflow.get("active_jobs") or 0) + 1
        if bool(job.get("requires_approval")):
            workflow["requires_approval_count"] = int(workflow.get("requires_approval_count") or 0) + 1
        if status == "awaiting_approval":
            workflow["awaiting_approval_count"] = int(workflow.get("awaiting_approval_count") or 0) + 1
        for label in platform_labels:
            workflow["platforms"].add(label)
        schedule = schedule_obj
        stype = str(schedule.get("type") or "").strip().lower()
        if stype:
            workflow["schedule_types"].add(stype)
        if updated_epoch > _iso_to_epoch(workflow.get("last_activity_at")):
            workflow["last_activity_at"] = updated_at

        if run_at or status in _CONTENT_ACTIVE_STATUSES:
            run_epoch = _iso_to_epoch(run_at)
            scheduler_rows.append(
                {
                    "job_id": str(job.get("id") or "").strip(),
                    "run_at": run_at,
                    "platform": platform_labels[0] if platform_labels else _CONTENT_FALLBACK_PLATFORM,
                    "type": _content_job_summary(job),
                    "workflow": workflow_name,
                    "status": _content_status_label(status),
                    "_has_run_at": bool(run_epoch > 0),
                    "_sort_epoch": run_epoch if run_epoch > 0 else updated_epoch,
                }
            )

    platform_rows = list(platform_map.values())
    platform_rows.sort(
        key=lambda row: (
            0 if bool(row.get("connected")) else 1,
            _content_platform_sort_key(row.get("name")),
        )
    )

    workflow_rows: List[Dict[str, Any]] = []
    for wf in workflow_groups.values():
        platforms = sorted(wf.get("platforms") or set(), key=_content_platform_sort_key)
        platform_count = len([p for p in platforms if p != _CONTENT_FALLBACK_PLATFORM]) or len(platforms)
        waiting = int(wf.get("awaiting_approval_count") or 0)
        gated = int(wf.get("requires_approval_count") or 0)
        if waiting > 0:
            approval = f"{waiting} item(s) awaiting approval."
        elif gated > 0:
            approval = f"{gated} item(s) configured with approval gates."
        else:
            approval = "No manual approval required."
        automation = (
            f"{int(wf.get('total_jobs') or 0)} job(s) mapped across {platform_count} platform(s). "
            f"{int(wf.get('active_jobs') or 0)} active now."
        )
        workflow_rows.append(
            {
                "name": str(wf.get("name") or "Content Flow"),
                "trigger": _content_workflow_trigger(wf.get("schedule_types") or set()),
                "automation": automation,
                "approval": approval,
                "total_jobs": int(wf.get("total_jobs") or 0),
                "active_jobs": int(wf.get("active_jobs") or 0),
                "platform_count": platform_count,
                "last_activity_at": str(wf.get("last_activity_at") or ""),
            }
        )
    workflow_rows.sort(
        key=lambda row: (
            -int(row.get("active_jobs") or 0),
            -int(row.get("total_jobs") or 0),
            -_iso_to_epoch(row.get("last_activity_at")),
            str(row.get("name") or "").lower(),
        )
    )
    workflow_rows = workflow_rows[:16]

    scheduler_rows.sort(
        key=lambda row: (
            0 if bool(row.get("_has_run_at")) else 1,
            float(row.get("_sort_epoch") or 0.0) if bool(row.get("_has_run_at")) else -float(row.get("_sort_epoch") or 0.0),
        )
    )
    scheduler_rows = scheduler_rows[:24]
    for row in scheduler_rows:
        row.pop("_has_run_at", None)
        row.pop("_sort_epoch", None)

    platform_rows_no_fallback = [p for p in platform_rows if str(p.get("name") or "") != _CONTENT_FALLBACK_PLATFORM]
    connected_platforms = sum(1 for p in platform_rows_no_fallback if bool(p.get("connected")))
    approvals_pending_total = max(int(approvals_pending or 0), awaiting_jobs)
    summary = {
        "connected_platforms": int(connected_platforms),
        "known_platforms": int(len(platform_rows_no_fallback)),
        "total_jobs": int(content_jobs),
        "active_jobs": int(active_jobs),
        "queued_posts": int(queued_jobs + awaiting_jobs),
        "workflows": int(len(workflow_rows)),
        "scheduled_posts": int(scheduled_jobs),
        "approvals_pending": int(approvals_pending_total),
        "sessions_active": int(max(0, sessions_active)),
        "sessions_recent_total": int(max(0, sessions_recent_total)),
        "cron_jobs": int(max(0, recurring_cron_jobs)),
        "skills_installed": int(max(0, skills_installed)),
        "api_keys_configured": int(max(0, api_keys_configured)),
        "logs_last_24h": int(max(0, audit_events_last_24h)),
    }

    tools = [
        {
            "title": "Unified Queue",
            "status": "Live" if content_jobs > 0 else "Idle",
            "detail": f"{content_jobs} live content job(s) tracked from mission data.",
        },
        {
            "title": "Workflow Builder",
            "status": "Live" if workflow_rows else "Idle",
            "detail": f"{len(workflow_rows)} workflow group(s) derived from active job payloads.",
        },
        {
            "title": "Scheduler",
            "status": "Live" if scheduler_rows else "Idle",
            "detail": f"{scheduled_jobs} scheduled/active publish jobs currently mapped.",
        },
        {
            "title": "Approvals + Guardrails",
            "status": "Attention" if approvals_pending_total > 0 else "Healthy",
            "detail": (
                f"{approvals_pending_total} approval item(s) pending review."
                if approvals_pending_total > 0
                else "No pending approvals right now."
            ),
        },
    ]

    health_checks = [
        {
            "name": "channel connections",
            "status": "ok" if connected_platforms > 0 else "warn",
            "detail": (
                f"{connected_platforms} of {len(platform_rows_no_fallback)} channels connected."
                if connected_platforms > 0
                else "No connected channels detected yet."
            ),
        },
        {
            "name": "session activity",
            "status": "ok" if sessions_active > 0 else "warn",
            "detail": (
                f"{sessions_active} active chat session(s) with {sessions_recent_total} recent runs."
                if sessions_active > 0
                else "No active run-store sessions right now."
            ),
        },
        {
            "name": "automation cron",
            "status": "ok" if recurring_cron_jobs > 0 else "warn",
            "detail": (
                f"{recurring_cron_jobs} recurring automation job(s) active."
                if recurring_cron_jobs > 0
                else "No recurring content cron jobs are configured."
            ),
        },
        {
            "name": "exec approvals",
            "status": "warn" if approvals_pending_total > 0 else "ok",
            "detail": (
                f"{approvals_pending_total} approval decision(s) pending."
                if approvals_pending_total > 0
                else "No pending approval decisions."
            ),
        },
        {
            "name": "credential coverage",
            "status": "ok" if api_keys_configured > 0 else "warn",
            "detail": (
                f"{api_keys_configured} API key provider(s) configured."
                if api_keys_configured > 0
                else "No provider API keys configured yet."
            ),
        },
        {
            "name": "run logs",
            "status": "ok" if audit_events_last_24h > 0 else "warn",
            "detail": (
                f"{audit_events_last_24h} autonomy audit log event(s) in last 24h."
                if audit_events_last_24h > 0
                else "No recent audit logs observed in last 24h."
            ),
        },
    ]
    health_status = "healthy" if all(str(c.get("status")) == "ok" for c in health_checks) else "attention"

    control_cards = [
        {
            "id": "connections",
            "label": "Connections / Channels",
            "value": f"{connected_platforms}/{len(platform_rows_no_fallback)}",
            "status": "live" if connected_platforms > 0 else "idle",
            "detail": "Connected channels with capability awareness.",
        },
        {
            "id": "sessions",
            "label": "Sessions",
            "value": str(max(0, sessions_active)),
            "status": "live" if sessions_active > 0 else "idle",
            "detail": f"{max(0, sessions_recent_total)} recent run session(s) tracked.",
        },
        {
            "id": "cron_jobs",
            "label": "Cron Jobs",
            "value": str(max(0, recurring_cron_jobs)),
            "status": "live" if recurring_cron_jobs > 0 else "idle",
            "detail": "Recurring automation schedules currently active.",
        },
        {
            "id": "skills",
            "label": "Skills",
            "value": str(max(0, skills_installed)),
            "status": "live" if skills_installed > 0 else "idle",
            "detail": "Installed local skills available to workflows.",
        },
        {
            "id": "api_keys",
            "label": "API Keys",
            "value": str(max(0, api_keys_configured)),
            "status": "live" if api_keys_configured > 0 else "warn",
            "detail": "Configured provider credentials in encrypted preferences.",
        },
        {
            "id": "approvals",
            "label": "Exec Approvals",
            "value": str(approvals_pending_total),
            "status": "warn" if approvals_pending_total > 0 else "healthy",
            "detail": "Human-gated publish or tool approval decisions pending.",
        },
        {
            "id": "logs",
            "label": "Logs (24h)",
            "value": str(max(0, audit_events_last_24h)),
            "status": "live" if audit_events_last_24h > 0 else "warn",
            "detail": "Autonomy audit events in the last 24 hours.",
        },
        {
            "id": "health",
            "label": "Health Checks",
            "value": "Healthy" if health_status == "healthy" else "Attention",
            "status": "healthy" if health_status == "healthy" else "warn",
            "detail": "Control surface combines connections, approvals, logs, and schedules.",
        },
    ]

    checklist_rows: List[Dict[str, Any]] = []
    for template in _CONTENT_HUB_CHECKLIST_TEMPLATE:
        cid = str(template.get("id") or "").strip()
        status = "planned"
        if cid in {"accounts_identity", "security"} and (connected_platforms > 0 or api_keys_configured > 0):
            status = "partial"
        if cid in {"content_model", "planning", "composer"} and (workflow_rows or content_jobs > 0):
            status = "partial"
        if cid in {"scheduling", "publishing_reliability", "automation"} and (scheduled_jobs > 0 or recurring_cron_jobs > 0):
            status = "partial"
        if cid in {"collaboration", "engagement_hub"} and approvals_pending_total >= 0:
            status = "partial"
        if cid in {"analytics"} and content_jobs > 0:
            status = "partial"
        if cid in {"extensibility"} and skills_installed > 0:
            status = "partial"
        if cid in {"ai_layer", "listening", "business_ops"} and content_jobs > 0:
            status = "planned"
        checklist_rows.append(
            {
                "id": cid,
                "title": str(template.get("title") or cid),
                "summary": str(template.get("summary") or ""),
                "status": status,
                "items": [str(x) for x in (template.get("items") or []) if str(x).strip()],
            }
        )

    return {
        "ok": True,
        "generated_at": _utc_iso_now(),
        "summary": summary,
        "platforms": platform_rows,
        "workflows": workflow_rows,
        "scheduler": scheduler_rows,
        "tools": tools,
        "control_surface": {
            "chat_first": {
                "enabled": True,
                "detail": "Chat can drive creation/scheduling while dashboard tracks runs, approvals, and health.",
            },
            "cards": control_cards,
            "health_status": health_status,
            "health_checks": health_checks,
        },
        "navigation": list(_CONTENT_HUB_NAV_ITEMS),
        "organization_axes": list(_CONTENT_HUB_ORGANIZATION_AXES),
        "checklist": checklist_rows,
    }
