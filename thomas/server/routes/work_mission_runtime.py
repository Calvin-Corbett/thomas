"""Mission lifecycle helpers for the canonical Work routes."""

from __future__ import annotations

import inspect
from typing import Any

from aiohttp import web

from thomas.work import (
    WorkConflictError,
    WorkDependencyUnavailableError,
    WorkNotFoundError,
    WorkStore,
    WorkValidationError,
)


def event_delivery_id(request: web.Request, payload: dict[str, Any]) -> str:
    """Read the stable caller identity required for event idempotency."""

    values = (
        request.headers.get("Idempotency-Key"),
        request.headers.get("X-Event-ID"),
        payload.get("event_id"),
        payload.get("message_id"),
    )
    event_id = next((str(value).strip() for value in values if str(value or "").strip()), "")
    if not event_id or len(event_id) > 240:
        raise WorkValidationError("Work events require an Idempotency-Key header or event_id")
    return event_id


def find_automation(
    store: WorkStore,
    app_id: str,
    job_id: str,
    automation_id: str,
) -> dict[str, Any]:
    automation = next(
        (row for row in store.list_automations(app_id, job_id) if str(row.get("id") or "") == automation_id),
        None,
    )
    if not isinstance(automation, dict):
        raise WorkNotFoundError("automation not found")
    return automation


def workflow_scoped_automation(
    automation: dict[str, Any],
    workflow: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach one workflow identity and goal to its delegated Mission payload."""

    if workflow is None:
        return automation
    template = dict(automation.get("mission_template") or {})
    payload = dict(template.get("payload") or {})
    payload["work_workflow_id"] = str(workflow["id"])
    template.update({"goal": str(workflow["purpose"]), "payload": payload})
    return {**automation, "mission_template": template}


def job_with_mission_bindings(
    store: WorkStore,
    job: dict[str, Any],
) -> dict[str, Any]:
    """Resolve public connector identities without exposing credential refs."""

    enriched = dict(job)
    accounts = {str(row.get("id") or ""): row for row in store.list_accounts(include_archived=True)}
    bindings: list[dict[str, Any]] = []
    for row in job.get("connector_bindings") or []:
        if not isinstance(row, dict) or not row.get("enabled", True):
            continue
        account = accounts.get(str(row.get("account_id") or ""))
        if not isinstance(account, dict) or account.get("status") != "active":
            raise WorkConflictError("Work automation connector account is not active")
        bindings.append({**row, "label": account.get("label", ""), "identity": account.get("identity", "")})
    enriched["connector_bindings"] = bindings
    return enriched


def active_mission_ids(automation: dict[str, Any]) -> list[str]:
    """Return every distinct Mission run currently owned by an automation."""

    delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
    active = delegation.get("active_mission_job_ids", [])
    values = list(active) if isinstance(active, list) else []
    if str(delegation.get("state") or "").lower() != "armed":
        values.extend((delegation.get("last_mission_job_id"), delegation.get("mission_job_id")))
    return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))


async def cancel_automation_missions(
    app: web.Application,
    store: WorkStore,
    app_id: str,
    job_id: str,
    automation: dict[str, Any],
    *,
    canceller_key: web.AppKey[object],
) -> list[dict[str, Any]]:
    delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
    state = str(delegation.get("state") or "").lower()
    last_run = delegation.get("last_run") if isinstance(delegation.get("last_run"), dict) else {}
    mission_ids = active_mission_ids(automation)
    if not mission_ids or state in {"cancelled", "failed", "succeeded", "not_deployed"}:
        return []
    canceller = app.get(canceller_key)
    if not callable(canceller):
        raise WorkDependencyUnavailableError("Mission cancellation is unavailable; the automation was not changed")
    receipts: list[dict[str, Any]] = []
    for mission_job_id in mission_ids:
        last_run_is_terminal = str(last_run.get("mission_job_id") or "") == mission_job_id and str(
            last_run.get("status") or ""
        ).lower() in {"cancelled", "failed", "dead", "succeeded"}
        if last_run_is_terminal:
            continue
        try:
            pending = canceller(mission_job_id)
            result = await pending if inspect.isawaitable(pending) else pending
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            raise WorkDependencyUnavailableError("Mission could not cancel the active automation") from exc
        if not isinstance(result, dict) or str(result.get("status") or "").lower() != "cancelled":
            raise WorkDependencyUnavailableError("Mission did not confirm automation cancellation")
        receipt = {**result, "id": str(result.get("id") or mission_job_id)}
        receipts.append(reconcile_cancelled_automation(store, app_id, job_id, automation, receipt))
    return receipts


def reconcile_cancelled_automation(
    store: WorkStore,
    app_id: str,
    job_id: str,
    automation: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Persist one matching Mission cancellation receipt before further mutation."""

    expected_ids = active_mission_ids(automation)
    mission_id = str(receipt.get("id") or "").strip()
    if not expected_ids or mission_id not in expected_ids:
        raise WorkDependencyUnavailableError("Mission cancellation receipt did not match the active automation")
    confirmed = {**receipt, "id": mission_id, "status": "cancelled"}
    store.reconcile_automation_mission(
        app_id,
        job_id,
        str(automation.get("id") or ""),
        confirmed,
    )
    return confirmed


async def cancel_job_automation_missions(
    app: web.Application,
    store: WorkStore,
    app_id: str,
    job_id: str,
    *,
    canceller_key: web.AppKey[object],
) -> list[dict[str, Any]]:
    """Cancel every active Mission before a job can pause or archive."""

    receipts: list[dict[str, Any]] = []
    for _pass in range(3):
        cancelled_this_pass = False
        for automation in store.list_automations(app_id, job_id):
            pending_receipts = await cancel_automation_missions(
                app,
                store,
                app_id,
                job_id,
                automation,
                canceller_key=canceller_key,
            )
            if not pending_receipts:
                continue
            receipts.extend(pending_receipts)
            cancelled_this_pass = True
        if not cancelled_this_pass:
            return receipts
    raise WorkDependencyUnavailableError("Mission cancellation could not prove that every job automation stopped")


__all__ = [
    "active_mission_ids",
    "cancel_automation_missions",
    "cancel_job_automation_missions",
    "event_delivery_id",
    "find_automation",
    "job_with_mission_bindings",
    "reconcile_cancelled_automation",
    "workflow_scoped_automation",
]
