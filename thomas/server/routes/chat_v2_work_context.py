"""Server-derived, job-scoped context for Work chat turns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from thomas.server.routes.work import APP_WORK_STORE
from thomas.work import WorkNotFoundError, WorkStore


@dataclass(slots=True)
class WorkContextError(ValueError):
    message: str
    status: int

    def __str__(self) -> str:
        return self.message


def resolve_work_private_context(
    app: web.Application,
    *,
    surface_mode: str,
    context_id: str,
    client_private_context: Any,
) -> str:
    supplied = str(client_private_context or "").strip()
    if supplied:
        raise WorkContextError(
            "Work private context is derived by Thomas and cannot be supplied by the client",
            400,
        )
    if surface_mode != "work":
        return ""
    parts = str(context_id or "").split(":")
    # App onboarding uses an app id, and create-another-job onboarding uses a
    # three-part transient namespace. Neither is an existing job context.
    if len(parts) != 2 or not all(parts):
        return ""
    store = app.get(APP_WORK_STORE)
    if not isinstance(store, WorkStore):
        raise WorkContextError("Work job context is unavailable", 503)
    app_id, job_id = parts
    try:
        job = store.get_job(app_id, job_id)
    except WorkNotFoundError as exc:
        raise WorkContextError("Work job context was not found", 404) from exc
    accounts = {str(row.get("id") or ""): row for row in store.list_accounts(include_archived=True)}
    bindings: list[dict[str, Any]] = []
    for binding in job.get("connector_bindings") or []:
        if not isinstance(binding, dict) or not binding.get("enabled", True):
            continue
        account = accounts.get(str(binding.get("account_id") or ""), {})
        bindings.append(
            {
                "binding_id": str(binding.get("id") or ""),
                "account_id": str(binding.get("account_id") or ""),
                "provider": str(binding.get("provider") or account.get("provider") or ""),
                "label": str(account.get("label") or ""),
                "identity": str(account.get("identity") or ""),
                "scopes": [str(scope) for scope in binding.get("scopes") or []],
            }
        )
    # The job's built-in spreadsheets ARE its live data. Thomas must be able to
    # answer "which location made the most money?" from what the user typed
    # into the dashboard sheets — bounded so a huge sheet can't flood context.
    sheets: list[dict[str, Any]] = []
    dashboard = job.get("dashboard") if isinstance(job.get("dashboard"), dict) else {}
    for sheet in (dashboard.get("sheets") or [])[:6]:
        if not isinstance(sheet, dict):
            continue
        sheets.append(
            {
                "id": str(sheet.get("id") or ""),
                "title": str(sheet.get("title") or ""),
                "columns": [str(col) for col in (sheet.get("columns") or [])[:16]],
                "rows": [
                    [str(cell)[:120] for cell in row[:16]]
                    for row in (sheet.get("rows") or [])[:60]
                    if isinstance(row, list)
                ],
            }
        )
    metrics = [
        {"label": str(row.get("label") or ""), "value": str(row.get("value") or "")}
        for row in (dashboard.get("metrics") or [])[:12]
        if isinstance(row, dict)
    ]
    context = {
        "work_app_id": app_id,
        "work_job_id": job_id,
        "job_scope": str(job.get("memory", {}).get("scope") or ""),
        "job_memory": dict(job.get("memory") or {}),
        "dashboard_sheets": sheets,
        "dashboard_metrics": metrics,
        "private_skills": [
            {
                "id": str(skill.get("id") or ""),
                "name": str(skill.get("name") or ""),
                "description": str(skill.get("description") or ""),
                "skill_ref": str(skill.get("skill_ref") or ""),
            }
            for skill in job.get("private_skills") or []
            if isinstance(skill, dict) and skill.get("status") != "disabled"
        ],
        "connector_bindings": bindings,
    }
    return json.dumps(context, ensure_ascii=False, sort_keys=True)


__all__ = ["WorkContextError", "resolve_work_private_context"]
