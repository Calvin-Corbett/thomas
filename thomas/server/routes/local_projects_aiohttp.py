"""Route handlers for local project registry and launcher."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.routes import local_projects_helpers_aiohttp as _helpers
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
        _, project = _find_project(projects, project_id)
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
        index, project = _find_project(projects, project_id)
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
        index, project = _find_project(projects, project_id)
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
