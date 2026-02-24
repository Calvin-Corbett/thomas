"""aiohttp routes for Asset Studio connector orchestration."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from thomas.asset_studio.runtime import AssetStudioJobStore, AssetStudioRuntime, TERMINAL_STATES
from thomas.preferences.store import get_db_path

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

APP_ASSET_STUDIO_RUNTIME = web.AppKey("asset_studio_runtime", AssetStudioRuntime)
APP_ASSET_STUDIO_CLEANUP = web.AppKey("asset_studio_cleanup", bool)


def _resolve_asset_studio_db_path() -> Path:
    base = Path(get_db_path()).expanduser().resolve()
    suffix = base.suffix or ".sqlite3"
    return base.with_name(f"{base.stem}.asset_studio{suffix}")


def _runtime_for_app(app: web.Application) -> AssetStudioRuntime:
    existing = app.get(APP_ASSET_STUDIO_RUNTIME)
    if existing is not None:
        return existing
    runtime = AssetStudioRuntime(store=AssetStudioJobStore(_resolve_asset_studio_db_path()))
    app[APP_ASSET_STUDIO_RUNTIME] = runtime
    return runtime


def _parse_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise ValueError("tags must be a list or comma-separated string")
    output: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        tag = str(item or "").strip()
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        output.append(tag)
    return output


def register_asset_studio_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    runtime = _runtime_for_app(app)

    if not bool(app.get(APP_ASSET_STUDIO_CLEANUP)):
        async def _asset_studio_cleanup(app_: web.Application) -> None:
            runner = app_.get(APP_ASSET_STUDIO_RUNTIME)
            if runner is None:
                return
            try:
                await runner.shutdown()
            except Exception:
                return

        app.on_cleanup.append(_asset_studio_cleanup)
        app[APP_ASSET_STUDIO_CLEANUP] = True

    async def api_asset_studio_connectors(request: web.Request) -> web.Response:
        require_api_access(request)
        include_detection = _parse_bool(request.query.get("detect"), default=True)
        rows = await runtime.list_connectors(include_detection=include_detection)
        return web.json_response({"ok": True, "count": len(rows), "connectors": rows})

    async def api_asset_studio_connector_detect(request: web.Request) -> web.Response:
        require_api_access(request)
        connector_id = str(request.match_info.get("connector_id") or "").strip()
        if not connector_id:
            raise web.HTTPBadRequest(text="missing connector_id")
        try:
            detection = await runtime.detect_connector(connector_id)
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown connector '{connector_id}'")
        return web.json_response({"ok": True, "connector_id": connector_id, "detection": detection})

    async def api_asset_studio_connector_actions(request: web.Request) -> web.Response:
        require_api_access(request)
        connector_id = str(request.match_info.get("connector_id") or "").strip()
        if not connector_id:
            raise web.HTTPBadRequest(text="missing connector_id")
        connector = runtime.catalog.get(connector_id)
        if connector is None:
            raise web.HTTPNotFound(text=f"unknown connector '{connector_id}'")
        actions = [action.to_dict() for action in connector.actions]
        return web.json_response(
            {
                "ok": True,
                "connector_id": connector_id,
                "count": len(actions),
                "actions": actions,
            }
        )

    async def api_asset_studio_health(request: web.Request) -> web.Response:
        require_api_access(request)
        include_detection = _parse_bool(request.query.get("detect"), default=True)
        jobs_limit = _parse_int(request.query.get("limit"), default=200, minimum=1, maximum=1000)
        snapshot = await runtime.health_snapshot(include_detection=include_detection, jobs_limit=jobs_limit)
        return web.json_response({"ok": True, "health": snapshot})

    async def api_asset_studio_completion_webhook_get(request: web.Request) -> web.Response:
        require_api_access(request)
        webhook = await runtime.get_completion_webhook()
        return web.json_response(
            {
                "ok": True,
                "configured": bool(webhook),
                "webhook": webhook,
            }
        )

    async def api_asset_studio_completion_webhook_set(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        endpoint = str(payload.get("url") or "").strip()
        if not endpoint:
            raise web.HTTPBadRequest(text="missing url")
        secret = str(payload.get("secret") or "")
        enabled = _parse_bool(payload.get("enabled"), default=True)
        timeout_s = _parse_int(payload.get("timeout_s"), default=5, minimum=1, maximum=30)
        try:
            webhook = await runtime.configure_completion_webhook(
                url=endpoint,
                secret=secret,
                enabled=enabled,
                timeout_s=timeout_s,
            )
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"ok": True, "configured": True, "webhook": webhook})

    async def api_asset_studio_completion_webhook_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        deleted = await runtime.clear_completion_webhook()
        return web.json_response({"ok": True, "deleted": bool(deleted)})

    async def api_asset_studio_jobs_preview(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        connector_id = str(payload.get("connector_id") or "").strip()
        action_id = str(payload.get("action_id") or "").strip()
        action_payload = payload.get("payload")
        if not connector_id:
            raise web.HTTPBadRequest(text="missing connector_id")
        if not action_id:
            raise web.HTTPBadRequest(text="missing action_id")
        if action_payload is None:
            action_payload = {}
        if not isinstance(action_payload, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        try:
            preview = await runtime.preview_job(
                connector_id=connector_id,
                action_id=action_id,
                payload=action_payload,
            )
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown connector '{connector_id}'")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"ok": True, "preview": preview})

    async def api_asset_studio_jobs_validate(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        connector_id = str(payload.get("connector_id") or "").strip()
        action_id = str(payload.get("action_id") or "").strip()
        action_payload = payload.get("payload")
        if not connector_id:
            raise web.HTTPBadRequest(text="missing connector_id")
        if not action_id:
            raise web.HTTPBadRequest(text="missing action_id")
        if action_payload is None:
            action_payload = {}
        if not isinstance(action_payload, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        try:
            validation = await runtime.validate_job_payload(
                connector_id=connector_id,
                action_id=action_id,
                payload=action_payload,
            )
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown connector '{connector_id}'")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"ok": True, "validation": validation})

    async def api_asset_studio_jobs_batch(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        rows = payload.get("jobs")
        if not isinstance(rows, list):
            raise web.HTTPBadRequest(text="payload.jobs must be an array")
        max_jobs = _parse_int(payload.get("max_jobs"), default=50, minimum=1, maximum=200)
        if len(rows) > max_jobs:
            raise web.HTTPBadRequest(text=f"payload.jobs exceeds max_jobs ({max_jobs})")
        result = await runtime.create_jobs_batch([row for row in rows if isinstance(row, dict)])
        skipped = len(rows) - len([row for row in rows if isinstance(row, dict)])
        if skipped:
            result["failed"] = int(result.get("failed") or 0) + int(skipped)
            errors = list(result.get("errors") or [])
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    continue
                errors.append({"index": idx, "error": "row must be a JSON object"})
            result["errors"] = errors
        response = {
            "ok": int(result.get("failed") or 0) == 0,
            "submitted": int(result.get("submitted") or 0),
            "failed": int(result.get("failed") or 0),
            "jobs": list(result.get("jobs") or []),
            "errors": list(result.get("errors") or []),
        }
        return web.json_response(response)

    async def api_asset_studio_jobs_recommend(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        goal = str(payload.get("goal") or "").strip()
        body = payload.get("payload")
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        if not goal:
            raise web.HTTPBadRequest(text="missing goal")
        try:
            recommendation = await runtime.recommend_job(goal=goal, payload=body)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"ok": True, "recommendation": recommendation})

    async def api_asset_studio_jobs_recommendations(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        goal = str(payload.get("goal") or "").strip()
        body = payload.get("payload")
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        if not goal:
            raise web.HTTPBadRequest(text="missing goal")
        limit = _parse_int(payload.get("limit"), default=3, minimum=1, maximum=10)
        try:
            recommendations = await runtime.recommend_jobs(goal=goal, payload=body, limit=limit)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"ok": True, "count": len(recommendations), "recommendations": recommendations})

    async def api_asset_studio_jobs_auto(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        goal = str(payload.get("goal") or "").strip()
        body = payload.get("payload")
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        if not goal:
            raise web.HTTPBadRequest(text="missing goal")
        dry_run = _parse_bool(payload.get("dry_run"), default=False)
        wait = _parse_bool(payload.get("wait"), default=False)
        wait_timeout_s = _parse_int(payload.get("wait_timeout_s"), default=30, minimum=1, maximum=600)
        try:
            result = await runtime.auto_create_job(goal=goal, payload=body, dry_run=dry_run)
        except ValueError as exc:
            recommendation = await runtime.recommend_job(goal=goal, payload=body)
            return web.json_response(
                {
                    "ok": False,
                    "error": str(exc),
                    "recommendation": recommendation,
                },
                status=400,
            )
        job = result.get("job")
        waited = False
        wait_timed_out = False
        if wait and not dry_run and isinstance(job, dict):
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                waited = True
                latest = await runtime.wait_for_job(job_id, timeout_s=wait_timeout_s)
                if isinstance(latest, dict):
                    job = latest
                status = str((job or {}).get("status") or "").strip().lower()
                wait_timed_out = status not in TERMINAL_STATES
        return web.json_response(
            {
                "ok": True,
                "recommendation": result.get("recommendation"),
                "job": job,
                "dry_run": bool(result.get("dry_run")),
                "waited": bool(waited),
                "wait_timed_out": bool(wait_timed_out),
            }
        )

    async def api_asset_studio_templates_create(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        name = str(payload.get("name") or "").strip()
        connector_id = str(payload.get("connector_id") or "").strip()
        action_id = str(payload.get("action_id") or "").strip()
        action_payload = payload.get("payload")
        if not name:
            raise web.HTTPBadRequest(text="missing name")
        if not connector_id:
            raise web.HTTPBadRequest(text="missing connector_id")
        if not action_id:
            raise web.HTTPBadRequest(text="missing action_id")
        if action_payload is None:
            action_payload = {}
        if not isinstance(action_payload, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        try:
            tags = _parse_tags(payload.get("tags"))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        pin_index_present = "pin_index" in payload
        pin_index = _parse_int(payload.get("pin_index"), default=0, minimum=0, maximum=9999) if pin_index_present else None
        pinned = _parse_bool(payload.get("pinned"), default=bool(pin_index_present))
        favorite = _parse_bool(payload.get("favorite"), default=False)
        try:
            template = await runtime.create_template(
                name=name,
                connector_id=connector_id,
                action_id=action_id,
                payload=action_payload,
                tags=tags,
                favorite=favorite,
                pinned=pinned,
                pin_index=pin_index,
            )
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown connector '{connector_id}'")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"ok": True, "template": template})

    async def api_asset_studio_templates_list(request: web.Request) -> web.Response:
        require_api_access(request)
        limit = _parse_int(request.query.get("limit"), default=100, minimum=1, maximum=500)
        favorites_only = _parse_bool(request.query.get("favorite"), default=False)
        tag = str(request.query.get("tag") or "").strip()
        rows = await runtime.list_templates(limit=limit, favorites_only=favorites_only, tag=tag)
        return web.json_response({"ok": True, "count": len(rows), "templates": rows})

    async def api_asset_studio_template_update(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        has_name = "name" in payload
        has_tags = "tags" in payload
        has_favorite = "favorite" in payload
        has_pinned = "pinned" in payload
        has_pin_index = "pin_index" in payload
        if not (has_name or has_tags or has_favorite or has_pinned or has_pin_index):
            raise web.HTTPBadRequest(text="at least one of name, tags, favorite, pinned, pin_index is required")
        name = str(payload.get("name") or "").strip() if has_name else None
        tags = None
        if has_tags:
            try:
                tags = _parse_tags(payload.get("tags"))
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc))
        favorite = _parse_bool(payload.get("favorite"), default=False) if has_favorite else None
        pinned = _parse_bool(payload.get("pinned"), default=False) if has_pinned else None
        pin_index = _parse_int(payload.get("pin_index"), default=0, minimum=0, maximum=9999) if has_pin_index else None
        try:
            template = await runtime.update_template_metadata(
                template_id,
                name=name if has_name else None,
                tags=tags,
                favorite=favorite,
                pinned=pinned,
                pin_index=pin_index,
            )
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        if template is None:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        return web.json_response({"ok": True, "template": template})

    async def api_asset_studio_template_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        deleted = await runtime.delete_template(template_id)
        if not deleted:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        return web.json_response({"ok": True, "deleted": True, "template_id": template_id})

    async def api_asset_studio_template_clone(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        clone_name = str(payload.get("name") or "").strip()
        try:
            cloned = await runtime.clone_template(template_id, name=clone_name)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        if cloned is None:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        return web.json_response({"ok": True, "template": cloned, "cloned_from": template_id})

    async def api_asset_studio_template_export(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        include_secret = _parse_bool(request.query.get("include_secret"), default=False)
        bundle = await runtime.export_template_bundle(template_id, include_secret=include_secret)
        if bundle is None:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        return web.json_response({"ok": True, "bundle": bundle})

    async def api_asset_studio_templates_import(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        bundle = payload.get("bundle")
        if bundle is None:
            bundle = payload
        if not isinstance(bundle, dict):
            raise web.HTTPBadRequest(text="payload.bundle must be a JSON object")
        name_override = str(payload.get("name_override") or "").strip()
        try:
            result = await runtime.import_template_bundle(bundle, name_override=name_override)
        except KeyError as exc:
            raise web.HTTPNotFound(text=str(exc))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response(
            {
                "ok": True,
                "template": result.get("template"),
                "webhook": result.get("webhook"),
            }
        )

    async def api_asset_studio_template_webhook_get(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        try:
            webhook = await runtime.get_template_webhook(template_id)
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        return web.json_response(
            {
                "ok": True,
                "configured": bool(webhook),
                "webhook": webhook,
                "template_id": template_id,
            }
        )

    async def api_asset_studio_template_webhook_set(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        endpoint = str(payload.get("url") or "").strip()
        if not endpoint:
            raise web.HTTPBadRequest(text="missing url")
        secret = str(payload.get("secret") or "")
        enabled = _parse_bool(payload.get("enabled"), default=True)
        timeout_s = _parse_int(payload.get("timeout_s"), default=5, minimum=1, maximum=30)
        try:
            webhook = await runtime.configure_template_webhook(
                template_id=template_id,
                url=endpoint,
                secret=secret,
                enabled=enabled,
                timeout_s=timeout_s,
            )
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response(
            {
                "ok": True,
                "configured": True,
                "webhook": webhook,
                "template_id": template_id,
            }
        )

    async def api_asset_studio_template_webhook_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        try:
            deleted = await runtime.clear_template_webhook(template_id)
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        return web.json_response({"ok": True, "deleted": bool(deleted), "template_id": template_id})

    async def api_asset_studio_template_run(request: web.Request) -> web.Response:
        require_api_access(request)
        template_id = str(request.match_info.get("template_id") or "").strip()
        if not template_id:
            raise web.HTTPBadRequest(text="missing template_id")
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        payload_override = payload.get("payload")
        if payload_override is None:
            payload_override = {}
        if not isinstance(payload_override, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        dry_run = _parse_bool(payload.get("dry_run"), default=False)
        wait = _parse_bool(payload.get("wait"), default=False)
        wait_timeout_s = _parse_int(payload.get("wait_timeout_s"), default=30, minimum=1, maximum=600)
        try:
            result = await runtime.run_template(
                template_id=template_id,
                payload_override=payload_override,
                dry_run=dry_run,
            )
        except KeyError:
            raise web.HTTPNotFound(text="template connector is no longer available")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        if result is None:
            raise web.HTTPNotFound(text=f"unknown template '{template_id}'")
        validation = result.get("validation")
        if not bool(dry_run) and isinstance(validation, dict) and not bool(validation.get("can_submit")):
            return web.json_response(
                {
                    "ok": False,
                    "error": "template payload is missing required fields",
                    "template": result.get("template"),
                    "payload": result.get("payload"),
                    "validation": validation,
                    "dry_run": False,
                    "job": None,
                },
                status=400,
            )
        job = result.get("job")
        submitted = bool(result.get("submitted"))
        waited = False
        wait_timed_out = False
        if wait and submitted and not dry_run and isinstance(job, dict):
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                waited = True
                latest = await runtime.wait_for_job(job_id, timeout_s=wait_timeout_s)
                if isinstance(latest, dict):
                    job = latest
                status = str((job or {}).get("status") or "").strip().lower()
                wait_timed_out = status not in TERMINAL_STATES
        return web.json_response(
            {
                "ok": True,
                "template": result.get("template"),
                "payload": result.get("payload"),
                "validation": validation,
                "dry_run": bool(result.get("dry_run")),
                "submitted": submitted,
                "job": job,
                "waited": bool(waited),
                "wait_timed_out": bool(wait_timed_out),
            }
        )

    async def api_asset_studio_template_run_by_name(request: web.Request) -> web.Response:
        require_api_access(request)
        template_name = str(request.match_info.get("template_name") or "").strip()
        if not template_name:
            raise web.HTTPBadRequest(text="missing template_name")
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        payload_override = payload.get("payload")
        if payload_override is None:
            payload_override = {}
        if not isinstance(payload_override, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        dry_run = _parse_bool(payload.get("dry_run"), default=False)
        wait = _parse_bool(payload.get("wait"), default=False)
        wait_timeout_s = _parse_int(payload.get("wait_timeout_s"), default=30, minimum=1, maximum=600)
        try:
            result = await runtime.run_template_by_name(
                name=template_name,
                payload_override=payload_override,
                dry_run=dry_run,
            )
        except KeyError:
            raise web.HTTPNotFound(text="template connector is no longer available")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        if result is None:
            raise web.HTTPNotFound(text=f"unknown template '{template_name}'")
        validation = result.get("validation")
        if not bool(dry_run) and isinstance(validation, dict) and not bool(validation.get("can_submit")):
            return web.json_response(
                {
                    "ok": False,
                    "error": "template payload is missing required fields",
                    "template": result.get("template"),
                    "payload": result.get("payload"),
                    "validation": validation,
                    "dry_run": False,
                    "job": None,
                },
                status=400,
            )
        job = result.get("job")
        submitted = bool(result.get("submitted"))
        waited = False
        wait_timed_out = False
        if wait and submitted and not dry_run and isinstance(job, dict):
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                waited = True
                latest = await runtime.wait_for_job(job_id, timeout_s=wait_timeout_s)
                if isinstance(latest, dict):
                    job = latest
                status = str((job or {}).get("status") or "").strip().lower()
                wait_timed_out = status not in TERMINAL_STATES
        return web.json_response(
            {
                "ok": True,
                "template": result.get("template"),
                "payload": result.get("payload"),
                "validation": validation,
                "dry_run": bool(result.get("dry_run")),
                "submitted": submitted,
                "job": job,
                "waited": bool(waited),
                "wait_timed_out": bool(wait_timed_out),
            }
        )

    async def api_asset_studio_template_run_favorite(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        template_name = str(payload.get("name") or "").strip()
        tag = str(payload.get("tag") or "").strip()
        payload_override = payload.get("payload")
        if payload_override is None:
            payload_override = {}
        if not isinstance(payload_override, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        dry_run = _parse_bool(payload.get("dry_run"), default=False)
        wait = _parse_bool(payload.get("wait"), default=False)
        wait_timeout_s = _parse_int(payload.get("wait_timeout_s"), default=30, minimum=1, maximum=600)
        try:
            result = await runtime.run_favorite_template(
                name=template_name,
                tag=tag,
                payload_override=payload_override,
                dry_run=dry_run,
            )
        except KeyError:
            raise web.HTTPNotFound(text="template connector is no longer available")
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        if result is None:
            raise web.HTTPNotFound(text="no matching favorite template")
        validation = result.get("validation")
        if not bool(dry_run) and isinstance(validation, dict) and not bool(validation.get("can_submit")):
            return web.json_response(
                {
                    "ok": False,
                    "error": "template payload is missing required fields",
                    "template": result.get("template"),
                    "payload": result.get("payload"),
                    "validation": validation,
                    "dry_run": False,
                    "job": None,
                },
                status=400,
            )
        job = result.get("job")
        submitted = bool(result.get("submitted"))
        waited = False
        wait_timed_out = False
        if wait and submitted and not dry_run and isinstance(job, dict):
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                waited = True
                latest = await runtime.wait_for_job(job_id, timeout_s=wait_timeout_s)
                if isinstance(latest, dict):
                    job = latest
                status = str((job or {}).get("status") or "").strip().lower()
                wait_timed_out = status not in TERMINAL_STATES
        return web.json_response(
            {
                "ok": True,
                "template": result.get("template"),
                "payload": result.get("payload"),
                "validation": validation,
                "dry_run": bool(result.get("dry_run")),
                "submitted": submitted,
                "job": job,
                "waited": bool(waited),
                "wait_timed_out": bool(wait_timed_out),
            }
        )

    async def api_asset_studio_jobs_create(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        connector_id = str(payload.get("connector_id") or "").strip()
        action_id = str(payload.get("action_id") or "").strip()
        action_payload = payload.get("payload")
        if not connector_id:
            raise web.HTTPBadRequest(text="missing connector_id")
        if not action_id:
            raise web.HTTPBadRequest(text="missing action_id")
        if action_payload is None:
            action_payload = {}
        if not isinstance(action_payload, dict):
            raise web.HTTPBadRequest(text="payload.payload must be a JSON object")
        wait = _parse_bool(payload.get("wait"), default=False)
        wait_timeout_s = _parse_int(payload.get("wait_timeout_s"), default=30, minimum=1, maximum=600)
        try:
            job = await runtime.create_job(
                connector_id=connector_id,
                action_id=action_id,
                payload=action_payload,
            )
        except KeyError as exc:
            raise web.HTTPNotFound(text=str(exc))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        waited = False
        wait_timed_out = False
        if wait and isinstance(job, dict):
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                waited = True
                latest = await runtime.wait_for_job(job_id, timeout_s=wait_timeout_s)
                if isinstance(latest, dict):
                    job = latest
                status = str(job.get("status") or "").strip().lower()
                wait_timed_out = status not in TERMINAL_STATES
        return web.json_response(
            {
                "ok": True,
                "job": job,
                "waited": bool(waited),
                "wait_timed_out": bool(wait_timed_out),
            }
        )

    async def api_asset_studio_jobs_list(request: web.Request) -> web.Response:
        require_api_access(request)
        limit = _parse_int(request.query.get("limit"), default=100, minimum=1, maximum=500)
        status = str(request.query.get("status") or "").strip()
        rows = await runtime.list_jobs(limit=limit, status=status)
        return web.json_response({"ok": True, "count": len(rows), "jobs": rows})

    async def api_asset_studio_job_get(request: web.Request) -> web.Response:
        require_api_access(request)
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        job = await runtime.get_job(job_id)
        if not job:
            raise web.HTTPNotFound(text=f"unknown job '{job_id}'")
        return web.json_response({"ok": True, "job": job})

    async def api_asset_studio_job_events(request: web.Request) -> web.Response:
        require_api_access(request)
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        job = await runtime.get_job(job_id)
        if not job:
            raise web.HTTPNotFound(text=f"unknown job '{job_id}'")
        after = _parse_int(request.query.get("after"), default=0, minimum=0, maximum=10_000_000)
        limit = _parse_int(request.query.get("limit"), default=200, minimum=1, maximum=1000)
        events = await runtime.list_events(job_id, after_seq=after, limit=limit)
        return web.json_response({"ok": True, "count": len(events), "events": events, "job_status": job.get("status")})

    async def api_asset_studio_job_events_stream(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        job = await runtime.get_job(job_id)
        if not job:
            raise web.HTTPNotFound(text=f"unknown job '{job_id}'")

        after = _parse_int(request.query.get("after"), default=0, minimum=0, maximum=10_000_000)
        ticks = _parse_int(request.query.get("ticks"), default=40, minimum=1, maximum=400)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        cursor = after
        sent_any = False
        for _ in range(ticks):
            current = await runtime.get_job(job_id)
            events = await runtime.list_events(job_id, after_seq=cursor, limit=300)
            for event in events:
                cursor = max(cursor, int(event.get("seq") or 0))
                blob = json.dumps(event, ensure_ascii=True)
                await response.write(f"data: {blob}\n\n".encode("utf-8"))
                sent_any = True
            if current is None:
                break
            if str(current.get("status") or "").strip().lower() in TERMINAL_STATES and not events:
                break
            await asyncio.sleep(0.25)

        if not sent_any:
            await response.write(b"data: {}\n\n")
        with contextlib.suppress(Exception):
            await response.write_eof()
        return response

    async def api_asset_studio_job_cancel(request: web.Request) -> web.Response:
        require_api_access(request)
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        job = await runtime.cancel_job(job_id)
        if not job:
            raise web.HTTPNotFound(text=f"unknown job '{job_id}'")
        refreshed = await runtime.get_job(job_id)
        return web.json_response({"ok": True, "job": refreshed or job})

    async def api_asset_studio_job_retry(request: web.Request) -> web.Response:
        require_api_access(request)
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")
        job = await runtime.retry_job(job_id)
        if not job:
            raise web.HTTPNotFound(text=f"unknown job '{job_id}'")
        return web.json_response({"ok": True, "retried_from": job_id, "job": job})

    app.router.add_get("/api/asset-studio/v1/connectors", api_asset_studio_connectors)
    app.router.add_get("/api/asset-studio/v1/health", api_asset_studio_health)
    app.router.add_get("/api/asset-studio/v1/webhooks/completion", api_asset_studio_completion_webhook_get)
    app.router.add_post("/api/asset-studio/v1/webhooks/completion", api_asset_studio_completion_webhook_set)
    app.router.add_delete("/api/asset-studio/v1/webhooks/completion", api_asset_studio_completion_webhook_delete)
    app.router.add_post("/api/asset-studio/v1/connectors/{connector_id}/detect", api_asset_studio_connector_detect)
    app.router.add_get("/api/asset-studio/v1/connectors/{connector_id}/actions", api_asset_studio_connector_actions)
    app.router.add_post("/api/asset-studio/v1/jobs/preview", api_asset_studio_jobs_preview)
    app.router.add_post("/api/asset-studio/v1/jobs/validate", api_asset_studio_jobs_validate)
    app.router.add_post("/api/asset-studio/v1/jobs/batch", api_asset_studio_jobs_batch)
    app.router.add_post("/api/asset-studio/v1/jobs/recommend", api_asset_studio_jobs_recommend)
    app.router.add_post("/api/asset-studio/v1/jobs/recommendations", api_asset_studio_jobs_recommendations)
    app.router.add_post("/api/asset-studio/v1/jobs/auto", api_asset_studio_jobs_auto)
    app.router.add_post("/api/asset-studio/v1/templates", api_asset_studio_templates_create)
    app.router.add_post("/api/asset-studio/v1/templates/import", api_asset_studio_templates_import)
    app.router.add_get("/api/asset-studio/v1/templates", api_asset_studio_templates_list)
    app.router.add_patch("/api/asset-studio/v1/templates/{template_id}", api_asset_studio_template_update)
    app.router.add_delete("/api/asset-studio/v1/templates/{template_id}", api_asset_studio_template_delete)
    app.router.add_post("/api/asset-studio/v1/templates/{template_id}/clone", api_asset_studio_template_clone)
    app.router.add_get("/api/asset-studio/v1/templates/{template_id}/export", api_asset_studio_template_export)
    app.router.add_get("/api/asset-studio/v1/templates/{template_id}/webhook", api_asset_studio_template_webhook_get)
    app.router.add_post("/api/asset-studio/v1/templates/{template_id}/webhook", api_asset_studio_template_webhook_set)
    app.router.add_delete("/api/asset-studio/v1/templates/{template_id}/webhook", api_asset_studio_template_webhook_delete)
    app.router.add_post("/api/asset-studio/v1/templates/{template_id}/run", api_asset_studio_template_run)
    app.router.add_post("/api/asset-studio/v1/templates/by-name/{template_name}/run", api_asset_studio_template_run_by_name)
    app.router.add_post("/api/asset-studio/v1/templates/run-favorite", api_asset_studio_template_run_favorite)
    app.router.add_post("/api/asset-studio/v1/jobs", api_asset_studio_jobs_create)
    app.router.add_get("/api/asset-studio/v1/jobs", api_asset_studio_jobs_list)
    app.router.add_get("/api/asset-studio/v1/jobs/{job_id}", api_asset_studio_job_get)
    app.router.add_get("/api/asset-studio/v1/jobs/{job_id}/events", api_asset_studio_job_events)
    app.router.add_get("/api/asset-studio/v1/jobs/{job_id}/events/stream", api_asset_studio_job_events_stream)
    app.router.add_post("/api/asset-studio/v1/jobs/{job_id}/cancel", api_asset_studio_job_cancel)
    app.router.add_post("/api/asset-studio/v1/jobs/{job_id}/retry", api_asset_studio_job_retry)
