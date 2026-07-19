"""Read-compatible migration of earlier Workforce prototypes into Work state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .validation import legacy_safe_id, utc_now_iso

SCHEMA_VERSION = 1


def empty_work_state() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now,
        "updated_at": now,
        "apps": {},
        "connector_accounts": {},
        "global_skills": {},
        "migrations": {"sources": []},
    }


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _history(session_id: str, messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = messages if isinstance(messages, list) else []
    last = rows[-1] if rows and isinstance(rows[-1], dict) else {}
    return {
        "session_id": session_id,
        "message_count": len(rows),
        "last_message_at": str(last.get("created_at") or ""),
        "title": "",
        "metadata": {"legacy_message_count": len(rows)} if rows else {},
    }


def _base_app(app_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    now = str(raw.get("updated_at") or raw.get("created_at") or utc_now_iso())
    name = str(raw.get("name") or raw.get("title") or app_id).strip() or app_id
    goal = str(raw.get("goal") or raw.get("description") or "").strip()
    status = str(raw.get("status") or "active").strip().lower()
    if status not in {"onboarding", "active", "paused", "archived"}:
        status = "active"
    return {
        "id": app_id,
        "name": name[:160],
        "goal": goal[:4_000],
        "status": status,
        "created_at": str(raw.get("created_at") or now),
        "updated_at": now,
        "onboarding": {
            "state": "ready" if goal else "collecting",
            "phase": "ready" if goal else "goal_discovery",
            "messages": [],
            "fields": {},
            "next_prompt": "",
            "updated_at": now,
        },
        "dashboard": {
            "metrics": list(raw.get("dashboard_metrics") or []),
            "sections": list(raw.get("dashboard_sections") or []),
            "artifacts": [],
        },
        "memory": {
            "scope": str(raw.get("memory_scope") or f"work/{app_id}"),
            "summary": "",
            "metadata": {},
        },
        "jobs": {},
        "metadata": {"legacy_source": "workforce"},
    }


def _base_job(app_id: str, job_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    now = str(raw.get("updated_at") or raw.get("created_at") or utc_now_iso())
    status = str(raw.get("status") or "active").strip().lower()
    if bool(raw.get("paused")):
        status = "paused"
    if status not in {"active", "paused", "archived"}:
        status = "active"
    legacy_payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    goal = str(raw.get("goal") or raw.get("summary") or legacy_payload.get("prompt") or "").strip()
    return {
        "id": job_id,
        "app_id": app_id,
        "name": str(raw.get("name") or raw.get("title") or job_id).strip()[:160],
        "goal": goal[:4_000],
        "description": str(raw.get("summary") or raw.get("detail") or "").strip()[:4_000],
        "status": status,
        "created_at": str(raw.get("created_at") or now),
        "updated_at": now,
        "settings": {},
        "history": _history(f"work:{app_id}:{job_id}"),
        "memory": {"scope": f"work/{app_id}/{job_id}", "summary": "", "workflows": [], "metadata": {}},
        "dashboard": {"metrics": [], "sections": [], "artifacts": []},
        "connector_bindings": [],
        "private_skills": [],
        "automations": [],
        "activity": [],
        "metadata": {
            "legacy_status": str(raw.get("status") or ""),
            "legacy_run_count": int(raw.get("run_count") or 0),
        },
    }


def _account_from_grant(state: dict[str, Any], grant: dict[str, Any]) -> str:
    provider = legacy_safe_id(grant.get("connector_id") or "connector", prefix="connector")
    account_id = legacy_safe_id(grant.get("account_id") or f"{provider}-default", prefix="account")
    accounts = state["connector_accounts"]
    if account_id not in accounts:
        now = utc_now_iso()
        accounts[account_id] = {
            "id": account_id,
            "provider": provider,
            "label": str(grant.get("label") or account_id)[:160],
            "identity": str(grant.get("account_id") or account_id)[:240],
            "credential_ref": "",
            "status": "active"
            if str(grant.get("status") or "").lower() in {"ready", "connected", "active"}
            else "planned",
            "metadata": {"legacy_scopes": list(grant.get("scopes") or [])},
            "created_at": now,
            "updated_at": now,
        }
    return account_id


def _legacy_workflow_trigger(value: Any) -> dict[str, Any]:
    """Translate the recognized Workforce clock trigger into Work semantics."""

    text = str(value or "").strip()
    if len(text) == 5 and text[2] == ":" and text.replace(":", "").isdigit():
        hour, minute = (int(part) for part in text.split(":"))
        if hour <= 23 and minute <= 59:
            return {"type": "daily", "at": text, "tz": "UTC"}
    return {"type": "manual"}


def _migrate_runtime_apps(state: dict[str, Any], apps_root: Path) -> int:
    if not apps_root.is_dir():
        return 0
    migrated = 0
    resolved_root = apps_root.resolve()
    for child in sorted(apps_root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.resolve().parent != resolved_root:
            continue
        spec = _read_json(child / "spec.json")
        if not isinstance(spec, dict):
            continue
        app_id = legacy_safe_id(spec.get("app_id") or spec.get("id") or child.name, prefix="app")
        app = state["apps"].setdefault(app_id, _base_app(app_id, spec))
        grants = [row for row in spec.get("connector_grants") or [] if isinstance(row, dict)]
        account_by_provider = {
            legacy_safe_id(row.get("connector_id") or "connector", prefix="connector"): _account_from_grant(state, row)
            for row in grants
        }
        jobs = _read_json(child / "jobs.json")
        if isinstance(jobs, list):
            for row in jobs:
                if not isinstance(row, dict):
                    continue
                job_id = legacy_safe_id(row.get("id") or row.get("workflow_id") or "job", prefix="job")
                job = _base_job(app_id, job_id, row)
                for connector in row.get("connector_ids") or []:
                    provider = legacy_safe_id(connector, prefix="connector")
                    account_id = account_by_provider.get(provider)
                    if account_id:
                        job["connector_bindings"].append(
                            {
                                "id": f"binding-{provider}",
                                "account_id": account_id,
                                "provider": provider,
                                "scopes": [],
                                "enabled": True,
                                "created_at": utc_now_iso(),
                            }
                        )
                app["jobs"][job_id] = job
        workflows = [row for row in spec.get("workflows") or [] if isinstance(row, dict)]
        if workflows and not app["jobs"]:
            default_job = _base_job(app_id, "primary", {"name": "Primary workflow", "goal": app["goal"]})
            app["jobs"]["primary"] = default_job
        for workflow in workflows:
            job_id = legacy_safe_id(workflow.get("workflow_id") or "primary", prefix="job")
            job = app["jobs"].setdefault(job_id, _base_job(app_id, job_id, workflow))
            automation_id = legacy_safe_id(workflow.get("workflow_id") or "automation", prefix="automation")
            job["automations"].append(
                {
                    "id": automation_id,
                    "name": str(workflow.get("title") or automation_id)[:160],
                    "enabled": True,
                    "trigger": _legacy_workflow_trigger(workflow.get("trigger")),
                    "mission_template": {
                        "workflow": "orchestrator_worker",
                        "goal": str(workflow.get("detail") or app["goal"]),
                    },
                    "delegation": {
                        "state": "not_deployed",
                        "mission_job_id": "",
                        "active_mission_job_ids": [],
                        "updated_at": "",
                    },
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
            )
        migrated += 1
    return migrated


def _migrate_user_work_apps(state: dict[str, Any], path: Path) -> int:
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("apps"), list):
        return 0
    messages_by_app = payload.get("messages") if isinstance(payload.get("messages"), dict) else {}
    sessions_by_app = payload.get("sessions") if isinstance(payload.get("sessions"), dict) else {}
    settings_by_app = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    migrated = 0
    for raw in payload["apps"]:
        if not isinstance(raw, dict):
            continue
        app_id = legacy_safe_id(raw.get("id") or raw.get("name") or "app", prefix="app")
        app = state["apps"].setdefault(app_id, _base_app(app_id, raw))
        job_id = "primary"
        job = app["jobs"].setdefault(job_id, _base_job(app_id, job_id, {"name": "Primary job", "goal": app["goal"]}))
        messages = messages_by_app.get(str(raw.get("id") or ""))
        session_id = str(sessions_by_app.get(str(raw.get("id") or "")) or f"work:{app_id}:{job_id}")[:240]
        job["history"] = _history(session_id, messages if isinstance(messages, list) else [])
        legacy_settings = settings_by_app.get(str(raw.get("id") or ""))
        if isinstance(legacy_settings, dict):
            allowed = {"autonomy", "guardrails", "reasoning", "thinking", "tokenEconomy"}
            job["settings"] = {key: value for key, value in legacy_settings.items() if key in allowed}
        migrated += 1
    return migrated


def migrate_legacy_work_state(
    *,
    runtime_apps_root: Path | None = None,
    user_work_apps_path: Path | None = None,
) -> dict[str, Any]:
    state = empty_work_state()
    sources = state["migrations"]["sources"]
    if runtime_apps_root is not None:
        count = _migrate_runtime_apps(state, runtime_apps_root)
        if count:
            sources.append({"kind": "runtime_workforce", "count": count, "at": utc_now_iso()})
    if user_work_apps_path is not None:
        count = _migrate_user_work_apps(state, user_work_apps_path)
        if count:
            sources.append({"kind": "user_work_apps", "count": count, "at": utc_now_iso()})
    state["updated_at"] = utc_now_iso()
    return state
