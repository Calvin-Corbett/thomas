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
    context = {
        "work_app_id": app_id,
        "work_job_id": job_id,
        "job_scope": str(job.get("memory", {}).get("scope") or ""),
        "job_memory": dict(job.get("memory") or {}),
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
