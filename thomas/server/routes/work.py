"""Canonical Work metadata APIs.

Work owns durable definitions and scoped metadata. Automation execution is
always delegated through the injected Mission submitter; this module is not a
second scheduler or executor.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_CONFIG
from thomas.work import (
    WorkConflictError,
    WorkCorruptStateError,
    WorkDependencyUnavailableError,
    WorkNotFoundError,
    WorkStore,
    WorkValidationError,
)
from thomas.work.connectors import list_work_connectors
from thomas.work.mission import build_mission_job_payload

from .work_connector_runtime import connect_account_secret, public_account
from .work_mission_runtime import (
    active_mission_ids,
    cancel_automation_missions,
    cancel_job_automation_missions,
    event_delivery_id,
    find_automation,
    job_with_mission_bindings,
    workflow_scoped_automation,
)
from .work_onboarding_runtime import WorkOnboardingRuntime

RequireAccessFn = Callable[[web.Request], None]
MissionSubmitter = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]
MissionStatusProvider = Callable[[str], dict[str, Any] | None | Awaitable[dict[str, Any] | None]]
MissionCanceller = Callable[[str], dict[str, Any] | Awaitable[dict[str, Any]]]

APP_WORK_STORE = web.AppKey("work_store", WorkStore)
APP_WORK_MISSION_SUBMITTER = web.AppKey("work_mission_submitter", object)
APP_WORK_MISSION_STATUS_PROVIDER = web.AppKey("work_mission_status_provider", object)
APP_WORK_MISSION_CANCELLER = web.AppKey("work_mission_canceller", object)


def _include_archived(request: web.Request) -> bool:
    raw = str(request.rel_url.query.get("include_archived") or "").strip().lower()
    if raw in {"", "0", "false", "no"}:
        return False
    if raw in {"1", "true", "yes"}:
        return True
    raise WorkValidationError("include_archived must be true or false")


async def _read_body(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise WorkValidationError("request body must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise WorkValidationError("request body must be a JSON object")
    return payload


def _ok(*, status: int = 200, **payload: Any) -> web.Response:
    return web.json_response({"ok": True, **payload}, status=status)


def _expected_errors(handler: Callable[[web.Request], Awaitable[web.StreamResponse]]):
    @wraps(handler)
    async def wrapped(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request)
        except WorkValidationError as exc:
            return web.json_response(
                {"ok": False, "code": "work_validation_error", "error": str(exc)},
                status=400,
            )
        except WorkNotFoundError as exc:
            return web.json_response(
                {"ok": False, "code": "work_not_found", "error": str(exc)},
                status=404,
            )
        except WorkConflictError as exc:
            return web.json_response(
                {"ok": False, "code": "work_conflict", "error": str(exc)},
                status=409,
            )
        except WorkDependencyUnavailableError as exc:
            return web.json_response(
                {"ok": False, "code": "work_dependency_unavailable", "error": str(exc)},
                status=503,
            )
        except WorkCorruptStateError as exc:
            return web.json_response(
                {"ok": False, "code": "work_state_unavailable", "error": str(exc)},
                status=500,
            )

    return wrapped


def register_work_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    store: WorkStore | None = None,
    mission_submitter: MissionSubmitter | None = None,
    mission_status_provider: MissionStatusProvider | None = None,
    mission_canceller: MissionCanceller | None = None,
) -> WorkStore:
    """Register Work routes and return the initialized durable store."""

    work_store = store or WorkStore.from_config(app[APP_CONFIG])
    onboarding_runtime = WorkOnboardingRuntime(work_store)
    event_delivery_locks = tuple(asyncio.Lock() for _ in range(64))
    app[APP_WORK_STORE] = work_store
    if mission_submitter is not None:
        app[APP_WORK_MISSION_SUBMITTER] = mission_submitter
    if mission_status_provider is not None:
        app[APP_WORK_MISSION_STATUS_PROVIDER] = mission_status_provider
    if mission_canceller is not None:
        app[APP_WORK_MISSION_CANCELLER] = mission_canceller

    def guard(request: web.Request) -> None:
        require_api_access(request)

    def ids(request: web.Request) -> tuple[str, str]:
        return request.match_info["app_id"], request.match_info["job_id"]

    async def apps_list(request: web.Request) -> web.Response:
        guard(request)
        return _ok(apps=work_store.list_apps(include_archived=_include_archived(request)))

    async def apps_create(request: web.Request) -> web.Response:
        guard(request)
        return _ok(status=201, app=work_store.create_app(await _read_body(request)))

    async def app_get(request: web.Request) -> web.Response:
        guard(request)
        return _ok(app=work_store.get_app(request.match_info["app_id"]))

    async def app_update(request: web.Request) -> web.Response:
        guard(request)
        return _ok(app=work_store.update_app(request.match_info["app_id"], await _read_body(request)))

    async def app_archive(request: web.Request) -> web.Response:
        guard(request)
        return _ok(app=work_store.archive_app(request.match_info["app_id"]))

    async def onboarding_get(request: web.Request) -> web.Response:
        guard(request)
        return _ok(onboarding=work_store.get_app(request.match_info["app_id"])["onboarding"])

    async def onboarding_message(request: web.Request) -> web.Response:
        guard(request)
        return _ok(
            status=201,
            message=work_store.append_onboarding_message(request.match_info["app_id"], await _read_body(request)),
        )

    async def onboarding_update(request: web.Request) -> web.Response:
        guard(request)
        return _ok(onboarding=work_store.update_onboarding(request.match_info["app_id"], await _read_body(request)))

    async def app_dashboard_get(request: web.Request) -> web.Response:
        guard(request)
        return _ok(dashboard=work_store.get_app(request.match_info["app_id"])["dashboard"])

    async def app_dashboard_update(request: web.Request) -> web.Response:
        guard(request)
        return _ok(dashboard=work_store.update_app_dashboard(request.match_info["app_id"], await _read_body(request)))

    async def app_artifact_add(request: web.Request) -> web.Response:
        guard(request)
        return _ok(
            status=201,
            artifact=work_store.add_app_artifact(request.match_info["app_id"], await _read_body(request)),
        )

    async def accounts_list(request: web.Request) -> web.Response:
        guard(request)
        provider = str(request.rel_url.query.get("provider") or "")
        accounts = work_store.list_accounts(
            provider=provider,
            include_archived=_include_archived(request),
        )
        return _ok(accounts=[public_account(account) for account in accounts])

    async def connectors_list(request: web.Request) -> web.Response:
        guard(request)
        return _ok(connectors=list_work_connectors())

    async def account_create(request: web.Request) -> web.Response:
        guard(request)
        payload = await _read_body(request)
        if "credential_ref" in payload:
            raise WorkValidationError("credential_ref is server managed; use the connector connect endpoint")
        account = work_store.create_account(payload)
        return _ok(status=201, account=public_account(account))

    async def account_update(request: web.Request) -> web.Response:
        guard(request)
        payload = await _read_body(request)
        if "credential_ref" in payload:
            raise WorkValidationError("credential_ref is server managed; use the connector connect endpoint")
        return _ok(account=public_account(work_store.update_account(request.match_info["account_id"], payload)))

    async def account_connect(request: web.Request) -> web.Response:
        guard(request)
        account = connect_account_secret(
            app,
            work_store,
            request.match_info["account_id"],
            await _read_body(request),
        )
        return _ok(account=account)

    async def jobs_list(request: web.Request) -> web.Response:
        guard(request)
        return _ok(
            jobs=work_store.list_jobs(
                request.match_info["app_id"],
                include_archived=_include_archived(request),
            )
        )

    async def job_create(request: web.Request) -> web.Response:
        guard(request)
        app_id = request.match_info["app_id"]
        payload = await _read_body(request)
        job, created = await onboarding_runtime.create_job(app, app_id, payload)
        return _ok(
            status=201 if created else 200,
            job=job,
        )

    async def job_get(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(job=work_store.get_job(app_id, job_id))

    async def job_update(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(job=work_store.update_job(app_id, job_id, await _read_body(request)))

    async def job_archive(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        await cancel_job_automation_missions(
            app,
            work_store,
            app_id,
            job_id,
            canceller_key=APP_WORK_MISSION_CANCELLER,
        )
        return _ok(job=work_store.set_job_status(app_id, job_id, "archived"))

    async def job_status(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        action = request.match_info["action"]
        status = {"pause": "paused", "resume": "active", "archive": "archived"}[action]
        if status != "active":
            await cancel_job_automation_missions(
                app,
                work_store,
                app_id,
                job_id,
                canceller_key=APP_WORK_MISSION_CANCELLER,
            )
        return _ok(job=work_store.set_job_status(app_id, job_id, status))

    async def history_get(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(history=work_store.get_job(app_id, job_id)["history"])

    async def history_update(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(history=work_store.update_history(app_id, job_id, await _read_body(request)))

    async def memory_get(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(memory=work_store.get_job(app_id, job_id)["memory"])

    async def memory_update(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(memory=work_store.update_job_memory(app_id, job_id, await _read_body(request)))

    async def workflows_list(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        workflows = work_store.list_workflows(app_id, job_id)
        return _ok(workflows=workflows, active_workflow_id=work_store.active_workflow_id(app_id, job_id))

    async def workflow_create(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        workflow = work_store.create_workflow(app_id, job_id, await _read_body(request))
        return _ok(status=201, workflow=workflow, active_workflow_id=work_store.active_workflow_id(app_id, job_id))

    async def workflow_select(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        workflow = work_store.select_workflow(app_id, job_id, request.match_info["workflow_id"])
        return _ok(workflow=workflow, active_workflow_id=str(workflow["id"]))

    async def workflow_update(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        workflow_id = request.match_info["workflow_id"]
        workflow = work_store.update_workflow(app_id, job_id, workflow_id, await _read_body(request))
        return _ok(workflow=workflow, active_workflow_id=work_store.active_workflow_id(app_id, job_id))

    async def job_dashboard_get(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(dashboard=work_store.get_job(app_id, job_id)["dashboard"])

    async def job_dashboard_update(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(dashboard=work_store.update_job_dashboard(app_id, job_id, await _read_body(request)))

    async def job_artifact_add(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(status=201, artifact=work_store.add_job_artifact(app_id, job_id, await _read_body(request)))

    async def binding_add(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(status=201, binding=work_store.bind_account(app_id, job_id, await _read_body(request)))

    async def bindings_list(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(bindings=work_store.list_bindings(app_id, job_id))

    async def binding_delete(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(binding=work_store.unbind_account(app_id, job_id, request.match_info["binding_id"]))

    async def skills_list(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(skills=work_store.list_skills(app_id, job_id))

    async def skill_create(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(status=201, skill=work_store.create_skill(app_id, job_id, await _read_body(request)))

    async def skill_update(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(
            skill=work_store.update_skill(
                app_id,
                job_id,
                request.match_info["skill_id"],
                await _read_body(request),
            )
        )

    async def global_skills_list(request: web.Request) -> web.Response:
        guard(request)
        return _ok(skills=work_store.list_global_skills())

    async def skill_promotion_request(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(
            skill=work_store.request_skill_promotion(
                app_id,
                job_id,
                request.match_info["skill_id"],
            )
        )

    async def skill_promotion_approve(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        body = await _read_body(request)
        skill, global_skill = work_store.approve_skill_promotion(
            app_id,
            job_id,
            request.match_info["skill_id"],
            approved_by=str(body.get("approved_by") or ""),
        )
        return _ok(skill=skill, global_skill=global_skill)

    async def activity_list(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(activity=work_store.list_activity(app_id, job_id))

    async def _mission_status(mission_job_id: str) -> dict[str, Any] | None:
        provider = app.get(APP_WORK_MISSION_STATUS_PROVIDER)
        if callable(provider):
            try:
                pending = provider(mission_job_id)
                result = await pending if inspect.isawaitable(pending) else pending
            except (OSError, RuntimeError, ValueError) as exc:
                raise WorkDependencyUnavailableError("Mission status could not be read") from exc
            if result is not None and not isinstance(result, dict):
                raise WorkDependencyUnavailableError("Mission returned an invalid status receipt")
            if isinstance(result, dict) and str(result.get("id") or "").strip() != mission_job_id:
                raise WorkDependencyUnavailableError("Mission status receipt did not match the requested job")
            return result
        mission_store = app.get("autonomy_store")
        if mission_store is None or not callable(getattr(mission_store, "get_job", None)):
            return None
        try:
            mission_job = mission_store.get_job(mission_job_id)
        except KeyError:
            return None
        return {
            "id": str(getattr(mission_job, "id", "") or ""),
            "status": str(getattr(mission_job, "status", "") or ""),
            "result": getattr(mission_job, "result", None) or {},
            "error": getattr(mission_job, "error", None) or {},
            "updated_at": str(getattr(mission_job, "updated_at", "") or ""),
        }

    async def _reconcile_automations(app_id: str, job_id: str) -> tuple[list[dict[str, Any]], bool]:
        rows = work_store.list_automations(app_id, job_id)
        provider_available = (
            callable(app.get(APP_WORK_MISSION_STATUS_PROVIDER)) or app.get("autonomy_store") is not None
        )
        if not provider_available:
            return rows, False
        for automation in rows:
            for mission_job_id in active_mission_ids(automation):
                mission = await _mission_status(mission_job_id)
                if mission is not None:
                    work_store.reconcile_automation_mission(app_id, job_id, str(automation["id"]), mission)
        return work_store.list_automations(app_id, job_id), True

    async def automations_list(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        automations, mission_available = await _reconcile_automations(app_id, job_id)
        return _ok(automations=automations, mission_available=mission_available)

    async def automation_create(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        return _ok(
            status=201,
            automation=work_store.create_automation(app_id, job_id, await _read_body(request)),
        )

    async def automation_update(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        automation_id = request.match_info["automation_id"]
        payload = await _read_body(request)
        current = find_automation(work_store, app_id, job_id, automation_id)
        # Any definition change invalidates the deployed Mission schedule. A
        # disable or edit therefore cancels first and fails closed if Mission
        # cannot prove the cancellation.
        if payload:
            await cancel_automation_missions(
                app,
                work_store,
                app_id,
                job_id,
                current,
                canceller_key=APP_WORK_MISSION_CANCELLER,
            )
        return _ok(
            automation=work_store.update_automation(
                app_id,
                job_id,
                automation_id,
                payload,
            )
        )

    async def automation_delete(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        automation_id = request.match_info["automation_id"]
        current = find_automation(work_store, app_id, job_id, automation_id)
        if any(row.get("automation_id") == automation_id for row in work_store.list_workflows(app_id, job_id)):
            raise WorkConflictError("linked workflow automation cannot be deleted")
        await cancel_automation_missions(
            app,
            work_store,
            app_id,
            job_id,
            current,
            canceller_key=APP_WORK_MISSION_CANCELLER,
        )
        return _ok(
            automation=work_store.delete_automation(
                app_id,
                job_id,
                automation_id,
            )
        )

    async def _submit_mission(mission_payload: dict[str, Any]) -> str:
        submitter = app.get(APP_WORK_MISSION_SUBMITTER)
        if not callable(submitter):
            raise WorkDependencyUnavailableError("Mission submitter is not configured")
        try:
            submitted = submitter(mission_payload)
            result = await submitted if inspect.isawaitable(submitted) else submitted
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkDependencyUnavailableError("Mission rejected the Work automation") from exc
        if not isinstance(result, dict):
            raise WorkDependencyUnavailableError("Mission returned an invalid delegation receipt")
        mission_job = result.get("job") if isinstance(result.get("job"), dict) else {}
        mission_job_id = str(result.get("job_id") or mission_job.get("id") or "").strip()
        if not mission_job_id:
            raise WorkDependencyUnavailableError("Mission did not return a job id")
        return mission_job_id

    async def _deploy_automation(
        app_id: str,
        job_id: str,
        automation_id: str,
        *,
        manual_only: bool = False,
        workflow: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        app_row = work_store.get_app(app_id)
        job = work_store.get_job(app_id, job_id)
        automation = next(
            (row for row in job["automations"] if row.get("id") == automation_id),
            None,
        )
        if not isinstance(automation, dict):
            raise WorkNotFoundError("automation not found")
        trigger = automation.get("trigger") if isinstance(automation.get("trigger"), dict) else {}
        if manual_only and str(trigger.get("type") or "") != "manual":
            raise WorkConflictError("run once requires a linked manual automation")
        mission_automation = workflow_scoped_automation(automation, workflow)
        mission_payload = build_mission_job_payload(
            app_row, job_with_mission_bindings(work_store, job), mission_automation
        )
        if str(trigger.get("type") or "") == "event":
            armed = work_store.arm_event_automation(app_id, job_id, automation_id)
            return armed, {"armed": True, "event_name": trigger["event_name"]}
        work_store.claim_automation_submission(app_id, job_id, automation_id)
        try:
            mission_job_id = await _submit_mission(mission_payload)
        except WorkDependencyUnavailableError as exc:
            work_store.fail_automation_submission(app_id, job_id, automation_id, error=str(exc))
            work_store.record_activity(
                app_id,
                job_id,
                kind="automation_failed",
                state_value="failed",
                summary=f"Automation could not start: {automation['name']}",
                details={"automation_id": automation_id, "error": str(exc)},
            )
            raise
        automation = work_store.mark_automation_delegated(
            app_id,
            job_id,
            automation_id,
            mission_job_id=mission_job_id,
        )
        return automation, {"job_id": mission_job_id, "delegated": True}

    async def automation_deploy(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        automation_id = request.match_info["automation_id"]
        workflow = next(
            (row for row in work_store.list_workflows(app_id, job_id) if row.get("automation_id") == automation_id),
            None,
        )
        automation, mission = await _deploy_automation(
            app_id,
            job_id,
            automation_id,
            workflow=workflow,
        )
        return _ok(status=202, automation=automation, mission=mission)

    async def workflow_run_once(request: web.Request) -> web.Response:
        guard(request)
        app_id, job_id = ids(request)
        workflow_id = request.match_info["workflow_id"]
        workflow = work_store.get_workflow(app_id, job_id, workflow_id)
        if work_store.active_workflow_id(app_id, job_id) != workflow_id or workflow.get("status") != "active":
            raise WorkConflictError("select and activate the workflow before running it")
        automation_id = str(workflow.get("automation_id") or "")
        if not automation_id:
            raise WorkConflictError("workflow needs a linked manual automation before it can run")
        automation, mission = await _deploy_automation(
            app_id,
            job_id,
            automation_id,
            manual_only=True,
            workflow=workflow,
        )
        return _ok(status=202, workflow=workflow, automation=automation, mission=mission)

    async def event_receive(request: web.Request) -> web.Response:
        guard(request)
        event_name = str(request.match_info["event_name"] or "").strip()
        if not event_name.replace("_", "").replace("-", "").isalnum():
            raise WorkValidationError("invalid Work event name")
        event_payload = await _read_body(request)
        event_id = event_delivery_id(request, event_payload)
        lock_digest = hashlib.sha256(f"{event_name}:{event_id}".encode()).digest()
        lock = event_delivery_locks[int.from_bytes(lock_digest[:2], "big") % len(event_delivery_locks)]
        async with lock:
            return await _dispatch_event(event_name, event_payload, event_id)

    async def _dispatch_event(
        event_name: str,
        event_payload: dict[str, Any],
        event_id: str,
    ) -> web.Response:
        receipts: list[dict[str, Any]] = []
        for app_row in work_store.list_apps():
            if app_row.get("status") != "active":
                continue
            for job in work_store.list_jobs(str(app_row["id"])):
                if job.get("status") != "active":
                    continue
                for automation in job.get("automations") or []:
                    trigger = automation.get("trigger") if isinstance(automation.get("trigger"), dict) else {}
                    delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
                    if not (
                        automation.get("enabled")
                        and trigger.get("type") == "event"
                        and trigger.get("event_name") == event_name
                        and delegation.get("state") == "armed"
                    ):
                        continue
                    workflow = next(
                        (
                            row
                            for row in job.get("memory", {}).get("workflows", [])
                            if row.get("automation_id") == automation.get("id")
                        ),
                        None,
                    )
                    mission_payload = build_mission_job_payload(
                        app_row,
                        job_with_mission_bindings(
                            work_store,
                            job,
                        ),
                        workflow_scoped_automation(automation, workflow),
                    )
                    mission_payload["payload"]["event"] = event_payload
                    mission_payload["payload"]["work_event_id"] = event_id
                    delivery_id = hashlib.sha256(
                        f"{app_row['id']}:{job['id']}:{automation['id']}:{event_id}".encode()
                    ).hexdigest()
                    mission_payload["payload"]["work_event_delivery_id"] = delivery_id
                    claim = work_store.claim_event_delegation(
                        str(app_row["id"]),
                        str(job["id"]),
                        str(automation["id"]),
                        event_id=event_id,
                    )
                    if not claim["claimed"]:
                        prior = claim["receipt"]
                        receipts.append(
                            {
                                "app_id": app_row["id"],
                                "job_id": job["id"],
                                "automation_id": automation["id"],
                                "mission_job_id": prior["mission_job_id"],
                                "state": "armed",
                                "replayed": True,
                            }
                        )
                        continue
                    try:
                        mission_job_id = await _submit_mission(mission_payload)
                    except WorkDependencyUnavailableError as exc:
                        work_store.fail_event_delegation(
                            str(app_row["id"]),
                            str(job["id"]),
                            str(automation["id"]),
                            event_id=event_id,
                            error=str(exc),
                        )
                        raise
                    try:
                        updated = work_store.record_event_delegation(
                            str(app_row["id"]),
                            str(job["id"]),
                            str(automation["id"]),
                            mission_job_id=mission_job_id,
                            event_id=event_id,
                        )
                    except OSError as exc:
                        raise WorkDependencyUnavailableError(
                            "Mission started, but Work is awaiting durable receipt reconciliation"
                        ) from exc
                    receipts.append(
                        {
                            "app_id": app_row["id"],
                            "job_id": job["id"],
                            "automation_id": automation["id"],
                            "mission_job_id": mission_job_id,
                            "state": updated["delegation"]["state"],
                        }
                    )
        return _ok(status=202, event_name=event_name, event_id=event_id, delegated=receipts)

    routes: list[tuple[str, str, Callable[[web.Request], Awaitable[web.StreamResponse]]]] = [
        ("GET", "/api/work/apps", apps_list),
        ("POST", "/api/work/apps", apps_create),
        ("GET", "/api/work/apps/{app_id}", app_get),
        ("PATCH", "/api/work/apps/{app_id}", app_update),
        ("DELETE", "/api/work/apps/{app_id}", app_archive),
        ("GET", "/api/work/apps/{app_id}/onboarding", onboarding_get),
        ("POST", "/api/work/apps/{app_id}/onboarding/messages", onboarding_message),
        ("PATCH", "/api/work/apps/{app_id}/onboarding", onboarding_update),
        ("GET", "/api/work/apps/{app_id}/dashboard", app_dashboard_get),
        ("PATCH", "/api/work/apps/{app_id}/dashboard", app_dashboard_update),
        ("POST", "/api/work/apps/{app_id}/artifacts", app_artifact_add),
        ("GET", "/api/work/accounts", accounts_list),
        ("GET", "/api/work/connectors", connectors_list),
        ("GET", "/api/work/skills", global_skills_list),
        ("POST", "/api/work/accounts", account_create),
        ("PATCH", "/api/work/accounts/{account_id}", account_update),
        ("POST", "/api/work/accounts/{account_id}/connect", account_connect),
        ("GET", "/api/work/apps/{app_id}/jobs", jobs_list),
        ("POST", "/api/work/apps/{app_id}/jobs", job_create),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}", job_get),
        ("PATCH", "/api/work/apps/{app_id}/jobs/{job_id}", job_update),
        ("DELETE", "/api/work/apps/{app_id}/jobs/{job_id}", job_archive),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/{action:pause|resume|archive}", job_status),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/history", history_get),
        ("PATCH", "/api/work/apps/{app_id}/jobs/{job_id}/history", history_update),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/memory", memory_get),
        ("PATCH", "/api/work/apps/{app_id}/jobs/{job_id}/memory", memory_update),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/workflows", workflows_list),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/workflows", workflow_create),
        ("PATCH", "/api/work/apps/{app_id}/jobs/{job_id}/workflows/{workflow_id}", workflow_update),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/workflows/{workflow_id}/select", workflow_select),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/workflows/{workflow_id}/run-once", workflow_run_once),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/dashboard", job_dashboard_get),
        ("PATCH", "/api/work/apps/{app_id}/jobs/{job_id}/dashboard", job_dashboard_update),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/artifacts", job_artifact_add),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/bindings", bindings_list),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/bindings", binding_add),
        ("DELETE", "/api/work/apps/{app_id}/jobs/{job_id}/bindings/{binding_id}", binding_delete),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/skills", skills_list),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/skills", skill_create),
        ("PATCH", "/api/work/apps/{app_id}/jobs/{job_id}/skills/{skill_id}", skill_update),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/skills/{skill_id}/promotion/request", skill_promotion_request),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/skills/{skill_id}/promotion/approve", skill_promotion_approve),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/activity", activity_list),
        ("GET", "/api/work/apps/{app_id}/jobs/{job_id}/automations", automations_list),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/automations", automation_create),
        ("PATCH", "/api/work/apps/{app_id}/jobs/{job_id}/automations/{automation_id}", automation_update),
        ("DELETE", "/api/work/apps/{app_id}/jobs/{job_id}/automations/{automation_id}", automation_delete),
        ("POST", "/api/work/apps/{app_id}/jobs/{job_id}/automations/{automation_id}/deploy", automation_deploy),
        ("POST", "/api/work/events/{event_name}", event_receive),
    ]
    for method, path, handler in routes:
        app.router.add_route(method, path, _expected_errors(handler))
    from thomas.server.routes.work_dashboard_runtime import register_work_dashboard_routes

    register_work_dashboard_routes(
        app,
        guard=guard,
        work_store=work_store,
        expected_errors=_expected_errors,
        ok=_ok,
        deploy_automation=_deploy_automation,
    )
    return work_store


__all__ = [
    "APP_WORK_MISSION_STATUS_PROVIDER",
    "APP_WORK_MISSION_SUBMITTER",
    "APP_WORK_STORE",
    "register_work_routes",
]
