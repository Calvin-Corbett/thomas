"""Route handlers for local project registry and launcher."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core import task_bot_runtime
from thomas.server.routes import local_projects_helpers_aiohttp as _helpers
from thomas.server.routes.deliverable_aiohttp import (
    _workspace_dir,
    deliverable_entry,
    deliverable_kind,
    deliverable_url,
)
from thomas.server.routes.local_project_workspace import (
    _find_session_owner,
    _library_entry_status,
    _library_file_receipt,
    _save_project_workspace,
    _session_preview,
    _workspace_state,
    build_project_chat_context,
)
from thomas.server.routes.local_projects_helpers_aiohttp import (
    _MAX_PROJECTS,
    _build_project_dossier,
    _find_project,
    _perform_project_action,
    _pick_folder_via_dialog,
    _project_root_key,
    _read_registry,
    _refresh_projects,
    _resolve_project_root,
    _safe_int,
    _safe_text,
    _sort_projects,
    _utc_now_iso,
    _write_registry,
)

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]


def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    if not command:
        return {"kind": "error", "error": "missing command", "command": []}

    launched_command = list(command)
    creation_kwargs: dict[str, Any] = {"cwd": str(cwd)}
    if os.name == "nt":
        executable = shutil.which(command[0]) or ""
        if executable.lower().endswith((".cmd", ".bat")):
            launched_command = ["cmd.exe", "/c", *command]
        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        if creation_flags:
            creation_kwargs["creationflags"] = creation_flags

    proc = subprocess.Popen(launched_command, **creation_kwargs)
    return {
        "kind": "command_started",
        "pid": int(getattr(proc, "pid", 0) or 0),
        "command": list(command),
        "launched_command": launched_command,
    }


_helpers.os = os
_helpers.shutil = shutil
_helpers.subprocess = subprocess
_helpers._run_command = _run_command


_GENERATED_PROJECT_PREFIX = "generated-"


def _generated_project_id(execution_id: str) -> str:
    clean_id = "".join(ch for ch in str(execution_id or "").strip() if ch.isalnum() or ch in "-_")
    return f"{_GENERATED_PROJECT_PREFIX}{clean_id}" if clean_id else ""


def _generated_execution_id(project_id: str) -> str:
    raw = _safe_text(project_id)
    if not raw.startswith(_GENERATED_PROJECT_PREFIX):
        return ""
    execution_id = raw[len(_GENERATED_PROJECT_PREFIX) :]
    return "".join(ch for ch in execution_id if ch.isalnum() or ch in "-_")


def _generated_deliverable_summary(raw_summary: str, entry_name: str) -> str:
    entry = _safe_text(entry_name) or "generated app"
    summary = _safe_text(raw_summary)
    if not summary:
        return f"Generated app ready: {entry}."
    return f"Generated app ready: {entry} — {summary}"


def _generated_deliverable_project(record: dict[str, Any], *, index: int = 0) -> dict[str, Any] | None:
    execution_id = _safe_text(record.get("execution_id"))
    if not execution_id:
        return None
    state = _safe_text(record.get("state")).lower()
    if state not in {"completed", "verified", "done"}:
        return None

    artifact_kind = deliverable_kind(execution_id)
    artifact_url = deliverable_url(execution_id)
    if artifact_kind != "web" or not artifact_url:
        return None

    workspace = _workspace_dir(execution_id)
    if workspace is None:
        return None
    entry = deliverable_entry(execution_id) or ""
    entry_name = Path(entry).name or "generated-app.html"
    display_name = Path(entry_name).stem or execution_id
    project_id = _generated_project_id(execution_id)
    summary = _generated_deliverable_summary(
        _safe_text(record.get("progress_summary") or record.get("summary")), entry_name
    )
    updated_at = _safe_text(record.get("completed_at") or record.get("updated_at") or record.get("created_at"))
    root_path = str(workspace)
    launch_candidate = {
        "action": "open_entry",
        "label": "Open App",
        "available": True,
        "target": artifact_url,
        "command_display": f"Open {entry_name}",
    }
    folder_candidate = {
        "action": "open_folder",
        "label": "Open Folder",
        "available": True,
        "target": root_path,
        "command_display": "Open generated workspace",
    }
    return {
        "id": project_id,
        "name": display_name,
        "root_path": root_path,
        "kind": "generated_deliverable",
        "project_type": "web_app",
        "framework": "Generated HTML",
        "package_manager": "",
        "created_at": _safe_text(record.get("created_at")),
        "updated_at": updated_at,
        "launch_count": _safe_int(record.get("launch_count"), 0),
        "last_launched_at": _safe_text(record.get("last_launched_at")),
        "last_prepared_at": "",
        "board_position": _helpers._normalize_board_position({}, index=index),
        "board_icon": {"emoji": "APP", "accent": _helpers._accent_for_id(project_id)},
        "entry_path": entry,
        "summary": summary or "Generated app built by Thomas.",
        "scope_summary": "Generated by Thomas and ready to open from My Stuff.",
        "readiness": {"state": "open_ready", "label": "Generated"},
        "prepare": {"needed": False, "available": False, "command": [], "command_display": ""},
        "analysis": {
            "import_method": "generated_task",
            "top_level": [entry] if entry else [],
            "file_count": 0,
            "execution_id": execution_id,
        },
        "profile": {
            "launch": {"available": True, "target": artifact_url, "command": [], "command_display": artifact_url},
            "prepare": {"available": False, "needed": False, "command": [], "command_display": ""},
            "test_candidates": [],
            "readiness": {"state": "open_ready", "label": "Generated"},
        },
        "findings_preview": [
            {
                "title": "Generated deliverable",
                "detail": summary or f"Thomas produced {entry_name}.",
                "level": "good",
            }
        ],
        "launch_candidates": [launch_candidate, folder_candidate],
        "actions": {"primary": "open_entry", "secondary": ["open_folder"]},
        "generated": True,
        "source": "task_execution",
        "source_execution_id": execution_id,
        "artifact_url": artifact_url,
        "artifact_name": entry_name,
        "artifact_kind": artifact_kind,
    }


def _generated_deliverable_projects(*, start_index: int = 0, limit: int = _MAX_PROJECTS) -> list[dict[str, Any]]:
    rows = task_bot_runtime.list_executions(refresh=True)
    projects: list[dict[str, Any]] = []
    for row in rows:
        execution_id = _safe_text(row.get("execution_id"))
        full = task_bot_runtime.get_execution(execution_id) if execution_id else None
        project = _generated_deliverable_project(full or row, index=start_index + len(projects))
        if project is not None:
            projects.append(project)
        if len(projects) >= limit:
            break
    return projects


def _find_generated_deliverable_project(project_id: str, *, index: int = 0) -> dict[str, Any] | None:
    execution_id = _generated_execution_id(project_id)
    if not execution_id:
        return None
    record = task_bot_runtime.get_execution(execution_id)
    if record is None:
        return None
    return _generated_deliverable_project(record, index=index)


def _perform_generated_project_action(project: dict[str, Any], action: str) -> tuple[str, dict[str, Any]]:
    normalized = _safe_text(action).lower() or "open_entry"
    if normalized in {"launch", "open_entry"}:
        url = _safe_text(project.get("artifact_url"))
        if not url:
            raise web.HTTPConflict(text="generated deliverable is no longer available")
        return "open_entry", {"kind": "open_url", "url": url, "target": url}
    if normalized == "open_folder":
        root = Path(_safe_text(project.get("root_path")))
        if not root.exists():
            raise web.HTTPConflict(text="generated workspace is no longer available")
        return "open_folder", _helpers._open_path(root)
    raise web.HTTPBadRequest(text=f"unsupported generated project action: {normalized}")


def register_local_project_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    require_loopback: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    """Register all local project API routes."""

    async def api_local_projects_list(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        projects = _refresh_projects(request.app)
        generated = _generated_deliverable_projects(
            start_index=len(projects), limit=max(0, _MAX_PROJECTS - len(projects))
        )
        projects = projects + generated
        return web.json_response({"ok": True, "count": len(projects), "projects": projects})

    async def api_local_projects_import(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        root = _resolve_project_root(payload.get("path") or payload.get("root_path"))
        name = _safe_text(payload.get("name") or payload.get("display_name"))
        import_method = _safe_text(payload.get("import_method") or "path") or "path"

        projects = _read_registry(request.app)
        root_key = _project_root_key(root)
        existing_index = -1
        existing_row: dict[str, Any] | None = None
        for index, row in enumerate(projects):
            row_root = _safe_text(row.get("root_path"))
            if row_root and _project_root_key(Path(row_root)) == root_key:
                existing_index = index
                existing_row = row
                break

        project = _build_project_dossier(
            root,
            existing=existing_row,
            name=name or None,
            touch=True,
            index=existing_index if existing_index >= 0 else len(projects),
            import_method=import_method,
        )
        if existing_index >= 0:
            projects[existing_index] = project
        else:
            projects.append(project)
        projects = _sort_projects(projects)[:_MAX_PROJECTS]
        _write_registry(request.app, projects)
        return web.json_response(
            {
                "ok": True,
                "updated": existing_index >= 0,
                "count": len(projects),
                "project": project,
            }
        )

    async def api_local_projects_pick_folder(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        path_value = _pick_folder_via_dialog()
        if not path_value:
            return web.json_response({"ok": True, "cancelled": True, "path": ""})
        return web.json_response({"ok": True, "cancelled": False, "path": str(_resolve_project_root(path_value))})

    async def api_local_project_detail(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _refresh_projects(request.app)
        try:
            _, project = _find_project(projects, project_id)
        except web.HTTPNotFound:
            project = _find_generated_deliverable_project(project_id, index=len(projects))
            if project is None:
                raise
        return web.json_response({"ok": True, "project": project})

    async def api_local_project_layout(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        x = _safe_int(payload.get("x"), -1)
        y = _safe_int(payload.get("y"), -1)
        if x < 0 or y < 0:
            raise web.HTTPBadRequest(text="x and y are required integer coordinates")
        projects = _refresh_projects(request.app)
        try:
            index, project = _find_project(projects, project_id)
        except web.HTTPNotFound:
            project = _find_generated_deliverable_project(project_id, index=len(projects))
            if project is None:
                raise
            project["board_position"] = {"x": x, "y": y}
            return web.json_response({"ok": True, "project": project})
        project["board_position"] = {"x": x, "y": y}
        project["updated_at"] = _utc_now_iso()
        projects[index] = project
        _write_registry(request.app, projects)
        return web.json_response({"ok": True, "project": project})

    async def api_local_project_action(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload: Any = {}
        if request.can_read_body:
            payload = await read_json(request)
            if payload is None:
                payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        action = _safe_text(payload.get("action")).lower() or "launch"

        projects = _refresh_projects(request.app)
        try:
            index, project = _find_project(projects, project_id)
        except web.HTTPNotFound:
            project = _find_generated_deliverable_project(project_id, index=len(projects))
            if project is None:
                raise
            final_action, result = _perform_generated_project_action(project, action)
            return web.json_response({"ok": True, "action": final_action, "project": project, "result": result})
        final_action, result = _perform_project_action(project, action)
        now = _utc_now_iso()
        project["updated_at"] = now
        if final_action in {"launch", "open_entry", "open_folder", "test"}:
            project["launch_count"] = max(0, _safe_int(project.get("launch_count"))) + 1
            project["last_launched_at"] = now
        if final_action == "prepare":
            project["last_prepared_at"] = now
        projects[index] = project
        _write_registry(request.app, projects)
        return web.json_response({"ok": True, "action": final_action, "project": project, "result": result})

    async def api_local_projects_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _read_registry(request.app)
        index, project = _find_project(projects, project_id)
        projects.pop(index)
        _write_registry(request.app, projects)
        return web.json_response(
            {
                "ok": True,
                "removed_id": project_id,
                "removed_name": _safe_text(project.get("name")),
                "count": len(projects),
            }
        )

    async def api_local_project_context(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        workspace = _workspace_state(project)
        if "objective" in payload:
            workspace["objective"] = _safe_text(payload.get("objective"))[:2000]
        if "instructions" in payload:
            workspace["instructions"] = _safe_text(payload.get("instructions"))[:4000]
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response({"ok": True, "project_id": project_id, "workspace": workspace})

    async def api_local_project_chat_attach(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        session_id = _safe_text(payload.get("session_id") or payload.get("sessionId"))
        if not session_id:
            raise web.HTTPBadRequest(text="session_id is required")
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        owner = _find_session_owner(projects, session_id)
        if owner and owner != project_id:
            raise web.HTTPConflict(text="session is already attached to a different project")
        preview = await _session_preview(request.app, session_id, message_limit=2)
        if not preview["available"]:
            raise web.HTTPNotFound(text="persisted chat session not found")
        workspace = _workspace_state(project)
        chats = workspace["chats"]
        existing = next((row for row in chats if _safe_text(row.get("session_id")) == session_id), None)
        record = existing or {"session_id": session_id, "attached_at": _utc_now_iso()}
        record["title"] = _safe_text(payload.get("title"))[:200] or _safe_text(record.get("title")) or "Project chat"
        record["pinned"] = bool(payload.get("pinned", record.get("pinned", False)))
        if existing is None:
            chats.append(record)
        workspace["chats"] = chats[-100:]
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response({"ok": True, "project_id": project_id, "chat": record, "preview": preview})

    async def api_local_project_chat_update(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        session_id = _safe_text(request.match_info.get("session_id"))
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        workspace = _workspace_state(project)
        record = next(
            (row for row in workspace["chats"] if _safe_text(row.get("session_id")) == session_id),
            None,
        )
        if record is None:
            raise web.HTTPNotFound(text="chat is not attached to this project")
        if "title" in payload:
            record["title"] = _safe_text(payload.get("title"))[:200] or "Project chat"
        if "pinned" in payload:
            record["pinned"] = bool(payload.get("pinned"))
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response({"ok": True, "project_id": project_id, "chat": record})

    async def api_local_project_chat_remove(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        session_id = _safe_text(request.match_info.get("session_id"))
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        workspace = _workspace_state(project)
        before = len(workspace["chats"])
        workspace["chats"] = [row for row in workspace["chats"] if _safe_text(row.get("session_id")) != session_id]
        if len(workspace["chats"]) == before:
            raise web.HTTPNotFound(text="chat is not attached to this project")
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response({"ok": True, "project_id": project_id, "removed_session_id": session_id})

    async def api_local_project_library_add(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        receipt = _library_file_receipt(
            project,
            _safe_text(payload.get("path")),
            title=_safe_text(payload.get("title")),
        )
        workspace = _workspace_state(project)
        workspace["library"] = [row for row in workspace["library"] if _safe_text(row.get("id")) != receipt["id"]] + [
            receipt
        ]
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response({"ok": True, "project_id": project_id, "entry": receipt})

    async def api_local_project_library_remove(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        entry_id = _safe_text(request.match_info.get("entry_id"))
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        workspace = _workspace_state(project)
        before = len(workspace["library"])
        workspace["library"] = [row for row in workspace["library"] if _safe_text(row.get("id")) != entry_id]
        if len(workspace["library"]) == before:
            raise web.HTTPNotFound(text="library entry not found")
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response({"ok": True, "project_id": project_id, "removed_entry_id": entry_id})

    async def api_local_project_resume(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _refresh_projects(request.app)
        _, project = _find_project(projects, project_id)
        workspace = _workspace_state(project)
        chat_previews = [
            {
                **dict(chat),
                **await _session_preview(request.app, _safe_text(chat.get("session_id"))),
            }
            for chat in workspace["chats"]
        ]
        library = [_library_entry_status(project, row) for row in workspace["library"]]
        return web.json_response(
            {
                "ok": True,
                "project_id": project_id,
                "project_name": _safe_text(project.get("name")),
                "objective": workspace["objective"],
                "instructions": workspace["instructions"],
                "chats": chat_previews,
                "pinned_chats": [row for row in chat_previews if bool(row.get("pinned"))],
                "library": library,
                "stale_library_count": sum(1 for row in library if row.get("stale")),
                "updated_at": workspace["updated_at"],
            }
        )

    async def api_local_project_share_create(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        project_id = _safe_text(request.match_info.get("project_id"))
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        workspace = _workspace_state(project)
        include_all_chats = bool(payload.get("include_all_chats", False))
        chat_rows = (
            workspace["chats"] if include_all_chats else [row for row in workspace["chats"] if row.get("pinned")]
        )
        chats = []
        for row in chat_rows:
            preview = await _session_preview(request.app, _safe_text(row.get("session_id")))
            if preview["available"]:
                chats.append({"title": _safe_text(row.get("title")), "messages": preview["messages"]})
        library = []
        for row in workspace["library"]:
            status = _library_entry_status(project, row)
            if not status["stale"]:
                library.append(
                    {
                        "title": status["title"],
                        "path": status["path"],
                        "sha256": status["sha256"],
                    }
                )
        ttl = max(60, min(_safe_int(payload.get("expires_in_seconds"), 3600), 7 * 24 * 3600))
        share_id = secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(24)
        snapshot = {
            "schema_version": "thomas.project.share.v1",
            "share_id": share_id,
            "project_id": project_id,
            "project_name": _safe_text(project.get("name")),
            "objective": workspace["objective"],
            "chats": chats,
            "library": library,
            "created_at": _utc_now_iso(),
            "expires_at_epoch": int(time.time()) + ttl,
            "permissions": ["read"],
        }
        share_record = {
            "share_id": share_id,
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "expires_at_epoch": snapshot["expires_at_epoch"],
            "created_at": snapshot["created_at"],
            "snapshot": json.loads(json.dumps(snapshot, ensure_ascii=False)),
        }
        workspace["shares"].append(share_record)
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response(
            {
                "ok": True,
                "project_id": project_id,
                "share_id": share_id,
                "token": token,
                "expires_at_epoch": snapshot["expires_at_epoch"],
                "permissions": ["read"],
            }
        )

    async def api_local_project_share_get(request: web.Request) -> web.Response:
        require_loopback(request)
        share_id = _safe_text(request.match_info.get("share_id"))
        token = _safe_text(request.query.get("token"))
        record = None
        for project in _refresh_projects(request.app):
            workspace = _workspace_state(project)
            record = next((row for row in workspace["shares"] if _safe_text(row.get("share_id")) == share_id), None)
            if record is not None:
                break
        if record is None:
            raise web.HTTPNotFound(text="share not found")
        supplied = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not token or not secrets.compare_digest(supplied, _safe_text(record.get("token_sha256"))):
            raise web.HTTPForbidden(text="invalid share token")
        if _safe_int(record.get("expires_at_epoch"), 0) < int(time.time()):
            raise web.HTTPGone(text="share expired")
        return web.json_response({"ok": True, "share": dict(record.get("snapshot") or {})})

    async def api_local_project_share_revoke(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        project_id = _safe_text(request.match_info.get("project_id"))
        share_id = _safe_text(request.match_info.get("share_id"))
        projects = _refresh_projects(request.app)
        index, project = _find_project(projects, project_id)
        workspace = _workspace_state(project)
        before = len(workspace["shares"])
        workspace["shares"] = [row for row in workspace["shares"] if _safe_text(row.get("share_id")) != share_id]
        if len(workspace["shares"]) == before:
            raise web.HTTPNotFound(text="share not found")
        _save_project_workspace(request.app, projects, index, project, workspace)
        return web.json_response({"ok": True, "project_id": project_id, "revoked_share_id": share_id})

    app.router.add_get("/api/local/projects", api_local_projects_list)
    app.router.add_post("/api/local/projects/import", api_local_projects_import)
    app.router.add_post("/api/local/projects/link", api_local_projects_import)
    app.router.add_post("/api/local/projects/pick-folder", api_local_projects_pick_folder)
    app.router.add_get("/api/local/projects/{project_id}", api_local_project_detail)
    app.router.add_patch("/api/local/projects/{project_id}/layout", api_local_project_layout)
    app.router.add_post("/api/local/projects/{project_id}/action", api_local_project_action)
    app.router.add_post("/api/local/projects/{project_id}/launch", api_local_project_action)
    app.router.add_patch("/api/local/projects/{project_id}/context", api_local_project_context)
    app.router.add_post("/api/local/projects/{project_id}/chats", api_local_project_chat_attach)
    app.router.add_patch("/api/local/projects/{project_id}/chats/{session_id}", api_local_project_chat_update)
    app.router.add_delete("/api/local/projects/{project_id}/chats/{session_id}", api_local_project_chat_remove)
    app.router.add_post("/api/local/projects/{project_id}/library", api_local_project_library_add)
    app.router.add_delete("/api/local/projects/{project_id}/library/{entry_id}", api_local_project_library_remove)
    app.router.add_get("/api/local/projects/{project_id}/resume", api_local_project_resume)
    app.router.add_post("/api/local/projects/{project_id}/shares", api_local_project_share_create)
    app.router.add_delete("/api/local/projects/{project_id}/shares/{share_id}", api_local_project_share_revoke)
    app.router.add_get("/api/local/project-shares/{share_id}", api_local_project_share_get)
    app.router.add_delete("/api/local/projects/{project_id}", api_local_projects_delete)
