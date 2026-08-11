"""The Code surface's conversation list, its records, and its file browser.

Split out of ``evolve_agent_routes`` because these handlers serve a different
thing than the module they came from. That module launches and drives a run --
subprocess, transcript, run registry, steering, stopping. Nothing here touches
a running process at all: this is the sidebar (which tasks exist, what they are
called, which project each one lives in) and the tree/file reader the results
pane browses with. They share only the conversation resolver, which is passed
in, so the two can be read and changed apart.

They are grouped together rather than one-per-file because they are the same
job seen from different angles: every one of them answers "where does this
conversation live, and what is in it". That question has one hard-won answer --
see ``_load_conversation`` in the routes module -- and keeping the callers
beside each other is what stops a new one from inventing a second.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_projects, forge_code_store, forge_code_tree
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError

# What "no usable body" actually looks like coming out of ``request.json()``:
# an empty or malformed payload, or bytes that are not text. Named rather than
# a blanket catch so a connection dropping mid-read still surfaces instead of
# being read as "the caller sent nothing". Same set the run-control handlers in
# ``evolve_agent_routes`` use for the same call.
_EMPTY_BODY_ERRORS = (json.JSONDecodeError, TypeError, UnicodeDecodeError)


def _friendly_project_error(exc: Exception, requested_root: Any = None) -> str:
    """Turn an internal validator message into something a person can act on.

    These strings go straight to the screen. The raw ones are written for whoever
    is reading the traceback -- "project_root must be inside a git repository"
    names an internal argument and a tool the reader may not use, states a rule
    without a reason, and offers no way forward. Someone who just wanted to open
    their own folder is simply stopped.
    """
    raw = str(exc)
    name = ""
    if requested_root:
        try:
            name = Path(str(requested_root)).name
        except (OSError, ValueError):
            name = ""
    where = f'"{name}"' if name else "That folder"

    if "must be inside a git repository" in raw:
        return (
            f"{where} doesn't have version history yet, so Thomas can't undo its own edits there. "
            "Thomas sets this up automatically for folders it created. For your own folders it "
            "asks first, so nothing is added to your files without you knowing."
        )
    if "does not exist" in raw:
        return f"{where} isn't there any more. It may have been moved, renamed, or deleted."
    if "must be a directory" in raw:
        return f"{where} is a file, not a folder. Pick the folder that contains your project."
    if "could not be inspected" in raw:
        return f"Thomas couldn't read {where}. It may be on a drive that's disconnected, or permission is denied."
    if "could not be prepared for editing" in raw:
        return f"Thomas couldn't get {where} ready to edit. The folder may be read-only."
    if "unavailable repository root" in raw or "not a directory" in raw:
        return f"{where} looks like a broken project folder. Try picking it again, or choose a different one."
    return f"Thomas can't open {where} right now."


def build_evolve_agent_conversation_handlers(
    *,
    require_api_access: Callable[[web.Request], None],
    catalog_root: Callable[[], Path],
    load_conversation: Callable[[str], tuple[Path, dict[str, Any] | None]],
    project_for_conversation: Callable[[str], Path],
    chosen_project: Callable[..., Any],
    new_task_project_root: Callable[[Path, str], Path],
) -> dict[str, Any]:
    """Build the conversation handlers against the routes module's resolvers.

    The resolvers arrive as arguments rather than being re-implemented here:
    ``load_conversation`` is the one that walks every known project root instead
    of trusting the registry, and a second copy of that rule would be a second
    place for it to go stale.
    """

    async def conversations_list(request: web.Request) -> web.Response:
        require_api_access(request)
        root = catalog_root()
        by_id: dict[str, dict[str, Any]] = {}
        for project_root in forge_code_projects.conversation_roots(root):
            for summary in forge_code_store.list_conversations(project_root):
                cid = str(summary.get("id") or "")
                if not cid or cid in by_id:
                    continue
                metadata = forge_code_projects.conversation_metadata(root, cid) or {}
                enriched = dict(summary)
                enriched["project_root"] = str(metadata.get("project_root") or project_root)
                enriched["settings"] = metadata.get("settings") or {}
                by_id[cid] = enriched
        summaries = sorted(by_id.values(), key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return web.json_response(
            {
                "ok": True,
                "conversations": summaries,
                "days": forge_code_store.group_by_day(summaries),
            }
        )

    async def conversation_get(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        try:
            project_root, conv = load_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        if conv is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        metadata = forge_code_projects.conversation_metadata(catalog_root(), cid) or {}
        enriched = dict(conv)
        enriched["project_root"] = str(project_root)
        enriched["settings"] = metadata.get("settings") or {}
        return web.json_response({"ok": True, "conversation": enriched})

    async def conversation_new(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except _EMPTY_BODY_ERRORS:
            body = {}
        title = str((body or {}).get("title") or "").strip()
        source = (body or {}).get("source_evolve_item")
        if not isinstance(source, dict):
            source = None
        requested_root = chosen_project(
            (body or {}).get("project_root"),
            picked=str((body or {}).get("project_choice") or "").strip().lower() == "picked",
        )
        # "setup" | "without" | "" -- the answer to the history question, absent
        # until the person has actually been asked.
        history_choice = str((body or {}).get("history_choice") or "").strip().lower()
        if history_choice not in ("setup", "without"):
            history_choice = ""
        try:
            # Everything Thomas builds lands in ~/.thomas/workspaces/<exec-id>,
            # which is never a git repo -- so every app Thomas made for the user
            # was unopenable until now. Prepare Thomas's own folders on demand.
            # Folders outside ~/.thomas belong to the user and are left alone.
            loop = asyncio.get_running_loop()
            new_project_name = str((body or {}).get("new_project_name") or "").strip()
            if new_project_name and not requested_root:
                # A NEW project gets its own folder. Sending nothing used to mean
                # "share the one scratch repo", which is how the user's pacman,
                # star-catcher and museum all ended up in Thomas's working
                # directory together, overwriting one another's index.html.
                requested_root = str(
                    await loop.run_in_executor(None, forge_code_projects.create_named_project, new_project_name)
                )
            if requested_root:
                await loop.run_in_executor(None, forge_code_projects.ensure_git_repo, requested_root)
                if history_choice == "setup":
                    await loop.run_in_executor(None, forge_code_projects.initialize_history, requested_root)
                project_root = forge_code_projects.validate_project_root(
                    requested_root,
                    fallback=catalog_root(),
                    allow_without_history=(history_choice == "without"),
                )
            else:
                # Nothing was chosen, so this task gets its OWN folder instead of
                # the shared drawer. Resolved only in this branch, so a request
                # that names its project never pays for creating one it will not
                # use. It shells out to git, so it runs off the loop.
                project_root = await loop.run_in_executor(None, new_task_project_root, catalog_root(), title)
            settings = ForgeCodeSettings.from_payload(body if isinstance(body, dict) else {})
        except forge_code_projects.ForgeCodeHistoryRequired as exc:
            # A question, not a dead end. The previous message promised Thomas
            # "asks first" for your own folders and then never asked, which left
            # 117 of this user's 121 projects unopenable.
            name = Path(str(exc.project_path)).name or "That folder"
            return web.json_response(
                {
                    "ok": False,
                    "code": "history_choice_required",
                    "needs_history_choice": True,
                    "project_root": str(exc.project_path),
                    "project_name": name,
                    "error": (
                        f'"{name}" has no version history, so Thomas cannot undo its own edits there. '
                        "Set up history so changes can be reverted, or work without undo."
                    ),
                    "choices": [
                        {"id": "setup", "label": "Set up history", "recommended": True},
                        {"id": "without", "label": "Work without undo"},
                    ],
                },
                status=409,
            )
        except (forge_code_projects.ForgeCodeProjectError, ForgeCodeSettingsError) as exc:
            return web.json_response(
                {
                    "ok": False,
                    "error": _friendly_project_error(exc, requested_root),
                    "detail": str(exc),
                    "code": "invalid_code_configuration",
                },
                status=400,
            )
        conv = forge_code_store.new_conversation(
            project_root,
            title=title or None,
            source_evolve_item=source or None,
        )
        report = settings.capability_report()
        forge_code_projects.bind_conversation(
            catalog_root(),
            conv["id"],
            project_root,
            settings=report,
            allow_without_history=(history_choice == "without"),
        )
        enriched = dict(conv)
        enriched["project_root"] = str(project_root)
        enriched["settings"] = report
        return web.json_response({"ok": True, "conversation": enriched})

    async def conversation_rename(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        title = str((body or {}).get("title") or "").strip()
        if not title:
            return web.json_response({"ok": False, "error": "empty title"}, status=400)
        try:
            project_root = project_for_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        conv = forge_code_store.rename_conversation(project_root, cid, title)
        if conv is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        return web.json_response({"ok": True, "conversation": conv})

    async def conversation_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        try:
            project_root = project_for_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        removed = forge_code_store.delete_conversation(project_root, cid)
        if not removed:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        forge_code_projects.forget_conversation(catalog_root(), cid)
        return web.json_response({"ok": True, "deleted": True, "id": cid})

    async def conversation_tree(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        try:
            project_root, conv = load_conversation(cid)
            if conv is None:
                return web.json_response({"ok": False, "error": "not found"}, status=404)
            tree = forge_code_tree.list_project_tree(
                project_root,
                request.query.get("path", ""),
                limit=int(request.query.get("limit", "250")),
            )
        except (forge_code_projects.ForgeCodeProjectError, forge_code_tree.ForgeCodeTreeError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "invalid_tree_path"}, status=400)
        return web.json_response({"ok": True, **tree})

    async def conversation_file(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        try:
            project_root, conv = load_conversation(cid)
            if conv is None:
                return web.json_response({"ok": False, "error": "not found"}, status=404)
            result = forge_code_tree.read_project_file(project_root, request.query.get("path", ""))
        except (forge_code_projects.ForgeCodeProjectError, forge_code_tree.ForgeCodeTreeError) as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "invalid_file_path"}, status=400)
        return web.json_response({"ok": True, **result})

    return {
        "conversations_list": conversations_list,
        "conversation_get": conversation_get,
        "conversation_new": conversation_new,
        "conversation_rename": conversation_rename,
        "conversation_delete": conversation_delete,
        "conversation_tree": conversation_tree,
        "conversation_file": conversation_file,
    }
