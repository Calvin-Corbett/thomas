"""Route handlers for local project registry and launcher."""

from __future__ import annotations

import os
import shutil
import subprocess
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

    app.router.add_get("/api/local/projects", api_local_projects_list)
    app.router.add_post("/api/local/projects/import", api_local_projects_import)
    app.router.add_post("/api/local/projects/link", api_local_projects_import)
    app.router.add_post("/api/local/projects/pick-folder", api_local_projects_pick_folder)
    app.router.add_get("/api/local/projects/{project_id}", api_local_project_detail)
    app.router.add_patch("/api/local/projects/{project_id}/layout", api_local_project_layout)
    app.router.add_post("/api/local/projects/{project_id}/action", api_local_project_action)
    app.router.add_post("/api/local/projects/{project_id}/launch", api_local_project_action)
    app.router.add_delete("/api/local/projects/{project_id}", api_local_projects_delete)
