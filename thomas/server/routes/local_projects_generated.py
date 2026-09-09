"""Projects derived from things Thomas built for the user.

Every app Thomas generates lands in its own workspace under ``~/.thomas`` and is
surfaced in the library as a project you can open. Turning an execution record
into that project entry -- naming it, describing it, locating its artifact -- is
a separate concern from serving the project registry's HTTP routes, and it is
the larger half of the two.
"""

from __future__ import annotations

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
    _safe_int,
    _safe_text,
)

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
    entry = _safe_text(entry_name) or "deliverable"
    summary = _safe_text(raw_summary)
    if not summary:
        return f"Deliverable ready: {entry}."
    return f"Deliverable ready: {entry} — {summary}"


# Presentation per deliverable kind (`deliverable_kind` values). Everything a
# finished run produced is listable; only what the card SAYS differs by kind.
_KIND_PRESENTATION: dict[str, dict[str, str]] = {
    "web": {"framework": "Generated HTML", "project_type": "web_app", "icon": "APP", "open_label": "Open App"},
    "pdf": {"framework": "Generated PDF", "project_type": "generated_document", "icon": "PDF", "open_label": "Open PDF"},
    "image": {"framework": "Generated image", "project_type": "generated_image", "icon": "IMG", "open_label": "Open Image"},
    "text": {"framework": "Generated document", "project_type": "generated_document", "icon": "DOC", "open_label": "Open File"},
    "file": {"framework": "Generated file", "project_type": "generated_file", "icon": "FILE", "open_label": "Open File"},
}


def _generated_deliverable_project(record: dict[str, Any], *, index: int = 0) -> dict[str, Any] | None:
    execution_id = _safe_text(record.get("execution_id"))
    if not execution_id:
        return None
    state = _safe_text(record.get("state")).lower()
    if state not in {"completed", "verified", "done"}:
        return None

    artifact_kind = deliverable_kind(execution_id)
    artifact_url = deliverable_url(execution_id)
    # Only an EMPTY workspace is skipped: that run produced no file at all, so
    # there is nothing to open. Any produced kind is listed. The old
    # `artifact_kind != "web"` gate silently dropped every non-HTML deliverable
    # -- measured 2026-08-06 on the live ledger: 163 finished deliverables
    # (89 text, 55 pdf, 8 image, 11 other) invisible while 122 web ones listed,
    # so a chat that wrote packing.txt was the only path back to packing.txt.
    if not artifact_url:
        return None

    workspace = _workspace_dir(execution_id)
    if workspace is None:
        return None
    presentation = _KIND_PRESENTATION.get(artifact_kind, _KIND_PRESENTATION["file"])
    entry = deliverable_entry(execution_id) or ""
    entry_name = Path(entry).name or "deliverable"
    project_id = _generated_project_id(execution_id)
    # What the user asked for, not what the file happens to be called. 88 of 113
    # generated apps are named "index" because the name was the filename stem --
    # a list of them is unusable, and it is the reason none of this was findable.
    request_title = _request_title(record)
    display_name = request_title or Path(entry_name).stem or execution_id
    summary = _generated_deliverable_summary(
        _safe_text(record.get("progress_summary") or record.get("summary")), entry_name
    )
    updated_at = _safe_text(record.get("completed_at") or record.get("updated_at") or record.get("created_at"))
    root_path = str(workspace)
    launch_candidate = {
        "action": "open_entry",
        "label": presentation["open_label"],
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
        "request_title": request_title,
        "root_path": root_path,
        "kind": "generated_deliverable",
        "project_type": presentation["project_type"],
        "framework": presentation["framework"],
        "package_manager": "",
        "created_at": _safe_text(record.get("created_at")),
        "updated_at": updated_at,
        "launch_count": _safe_int(record.get("launch_count"), 0),
        "last_launched_at": _safe_text(record.get("last_launched_at")),
        "last_prepared_at": "",
        "board_position": _helpers._normalize_board_position({}, index=index),
        "board_icon": {"emoji": presentation["icon"], "accent": _helpers._accent_for_id(project_id)},
        "entry_path": entry,
        "summary": summary or "Built by Thomas.",
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


_TITLE_MAX_CHARS = 72
# Leading politeness and framing the user typed but did not mean as a title.
_TITLE_LEAD_NOISE = (
    "please ",
    "can you ",
    "could you ",
    "i want you to ",
    "i want ",
    "i need you to ",
    "i need ",
    "hey thomas ",
    "thomas ",
)


def _request_title(record: dict[str, Any]) -> str:
    """A card title in the user's own words: what they asked Thomas to make.

    ``summary`` on an execution record is the original ask ("Make a small snake
    game i can play"). ``progress_summary`` is the worker talking to itself
    ("Created index.html. why_blocked: The required monolith guard script is
    absent...") and must never reach a card.
    """
    text = " ".join(_safe_text(record.get("summary")).split())
    if not text:
        return ""
    lowered = text.lower()
    for lead in _TITLE_LEAD_NOISE:
        if lowered.startswith(lead):
            text = text[len(lead) :].lstrip()
            break
    if not text:
        return ""
    # One sentence is a title; a paragraph is not.
    for stop in (". ", "! ", "? ", "\n"):
        head = text.split(stop, 1)[0]
        if len(head) >= 12:
            text = head
    text = text.rstrip(" .")
    if len(text) > _TITLE_MAX_CHARS:
        clipped = text[:_TITLE_MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:-")
        text = f"{clipped or text[:_TITLE_MAX_CHARS]}…"
    return text[:1].upper() + text[1:] if text else ""


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
