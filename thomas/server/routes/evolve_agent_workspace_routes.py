"""What a Code run did to the project: review it, undo it, keep it, commit it.

Split out of ``evolve_agent_routes`` because these five handlers answer to the
project's working tree, not to a process. ``changes`` reads git status narrowed
to the run's own files, ``revert`` puts one of them back, ``keep`` acknowledges
one, ``checkpoint`` commits the lot on a branch, and ``deliverables`` lists what
came out. None of them start, steer or stop anything; the only run state they
touch is "is a run in flight" (checkpoint refuses during one) and "which
conversation is current" (the legacy fallback when the caller names none).

Kept together because they share the delicate part: every one of them has to
resolve the project a conversation actually lives in before it can say anything
true, and ``revert`` is the one route in the Code surface that can DELETE a
user's file -- it is idempotent by receipt and gated by an approval, and those
two mechanics belong beside the handlers that share their conversation scope
rather than buried in the middle of a launch path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_deliverables, forge_code_git, forge_code_projects, forge_code_store

from .evolve_agent_http_support import git_status_unavailable_response
from .evolve_agent_run_state import APP_EVOLVE_AGENT_APPROVALS, APP_EVOLVE_AGENT_CONVO, APP_EVOLVE_AGENT_PROJECT
from .evolve_agent_runtime import (
    _action_receipt,
    _authorize_conversation_revert,
    _conversation_changed_files,
    _finish_approval_execution,
    _request_id,
    _save_action_receipt,
)

# The same named set the run-control handlers use: an absent or malformed body
# is "the caller sent nothing", while a read that fails for any other reason
# must surface rather than be silently treated as an empty request.
_EMPTY_BODY_ERRORS = (json.JSONDecodeError, TypeError, UnicodeDecodeError)


def build_evolve_agent_workspace_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    catalog_root: Callable[[], Path],
    load_conversation: Callable[[str], tuple[Path, dict[str, Any] | None]],
    project_for_conversation: Callable[[str], Path],
    running: Callable[[], bool],
) -> dict[str, Any]:
    """Build the working-tree handlers against the routes module's resolvers.

    ``running`` is passed in rather than re-derived: a checkpoint taken while
    the agent is still writing would commit a half-finished tree, and the one
    definition of "a run is in flight" lives with the launcher.
    """

    async def deliverables_list(request: web.Request) -> web.Response:
        """List real, openable Forge Code build outputs for the My Stuff surface.

        Walks the same roots ``conversations_list`` walks, for the same reason:
        a run records its deliverable in the PROJECT it worked in, and every
        task now gets its own folder. Reading the catalog root alone returned an
        empty list -- measured live, 0 returned while 16 sat across 4 project
        roots -- and an empty list reads as "nothing has been built".
        """
        require_api_access(request)
        root = catalog_root()
        return web.json_response(
            {
                "ok": True,
                "deliverables": forge_code_deliverables.list_deliverables_across(
                    root,
                    forge_code_projects.conversation_roots(root),
                ),
            }
        )

    async def changes(request: web.Request) -> web.Response:
        require_api_access(request)
        # SCOPE to the active conversation's OWN build output, not the whole dirty
        # tree. The set of files this run wrote is recorded per agent turn
        # (changed_files); we intersect it with what git STILL reports as dirty so
        # a file that was reverted/committed drops out -- the diffs stay REAL, just
        # narrowed to this run's set. With no conversation context we fall back to
        # the full dirty tree (prior behavior) rather than show nothing.
        cid = request.query.get("cid") or app.get(APP_EVOLVE_AGENT_CONVO) or ""
        try:
            root = (
                project_for_conversation(str(cid)) if cid else Path(app.get(APP_EVOLVE_AGENT_PROJECT) or catalog_root())
            )
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        conv = forge_code_store.load_conversation(root, str(cid)) if cid else None
        scoped = _conversation_changed_files(conv)
        try:
            dirty = forge_code_git.changed_files(root)
        except forge_code_git.ForgeCodeGitError as exc:
            return git_status_unavailable_response(exc)
        if scoped is not None:
            files = [f for f in dirty if f in scoped]
        else:
            files = dirty
        try:
            out = forge_code_git.change_evidence(root, files)
        except forge_code_git.ForgeCodeGitError as exc:
            return git_status_unavailable_response(exc)
        return web.json_response({"ok": True, "changed": out})

    async def revert(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except _EMPTY_BODY_ERRORS:
            body = {}
        file = str((body or {}).get("file") or "").strip()
        if not file:
            return web.json_response({"ok": False, "error": "no file"}, status=400)
        cid = str((body or {}).get("conversation_id") or app.get(APP_EVOLVE_AGENT_CONVO) or "")
        if not cid:
            return web.json_response(
                {"ok": False, "error": "conversation_id is required", "code": "conversation_required"}, status=400
            )
        approval_id = str((body or {}).get("approval_id") or "").strip()
        request_id = _request_id(body if isinstance(body, dict) else {}, fallback=approval_id)
        scope = {"conversation_id": cid, "file": file.replace("\\", "/"), "approval_id": approval_id}
        replay = _action_receipt(catalog_root(), "revert", request_id)
        if replay is not None:
            if replay.get("scope") != scope:
                return web.json_response(
                    {"ok": False, "error": "request_id belongs to another revert", "code": "idempotency_conflict"},
                    status=409,
                )
            return web.json_response({**(replay.get("result") or {}), "replayed": True})
        try:
            root, conversation = load_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        if conversation is None:
            return web.json_response({"ok": False, "error": "not found", "code": "conversation_not_found"}, status=404)
        metadata = forge_code_projects.conversation_metadata(catalog_root(), cid)
        approvals = app[APP_EVOLVE_AGENT_APPROVALS]
        approval = approvals.get(approval_id)
        if isinstance(approval, dict) and approval.get("state") == "consumed" and approval.get("operation") == scope:
            return web.json_response({**(approval.get("result") or {}), "replayed": True})
        file, error, status_code = _authorize_conversation_revert(
            root=root,
            conversation_id=cid,
            file=file,
            conversation=conversation,
            metadata=metadata,
            approvals=approvals,
            approval_id=approval_id,
        )
        if error is not None:
            return web.json_response(error, status=status_code)
        result = None
        try:
            result = forge_code_git.revert_file(root, file)
            scope["file"] = file
            approval = approvals.get(approval_id)
            if isinstance(approval, dict):
                approval.update({"operation": scope, "result": result})
            _save_action_receipt(catalog_root(), "revert", request_id, {"scope": scope, "result": result})
            return web.json_response(result)
        finally:
            approval = approvals.get(approval_id)
            _finish_approval_execution(approval, succeeded=isinstance(result, dict) and result.get("ok") is True)

    async def keep(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except _EMPTY_BODY_ERRORS:
            body = {}
        file = str((body or {}).get("file") or "").strip()
        if not file:
            return web.json_response({"ok": False, "error": "no file"}, status=400)
        # Keep is a deliberate no-op on disk: the change already lives in the
        # working tree, so "keep" just acknowledges it and leaves it untouched.
        cid = str((body or {}).get("conversation_id") or app.get(APP_EVOLVE_AGENT_CONVO) or "")
        try:
            root = project_for_conversation(cid) if cid else Path(app.get(APP_EVOLVE_AGENT_PROJECT) or catalog_root())
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        return web.json_response({"ok": True, "kept": True, "file": file, "project_root": str(root)})

    async def checkpoint(request: web.Request) -> web.Response:
        """Codex-parity checkpoint: commit the conversation's kept changes on a
        new thomas-code/ branch; include a PR-ready remote URL when one exists."""
        require_api_access(request)
        if running():
            return web.json_response({"ok": False, "error": "wait for the run to finish first"}, status=409)
        try:
            body = await request.json()
        except _EMPTY_BODY_ERRORS:
            body = {}
        cid = str((body or {}).get("conversation_id") or "").strip()
        message = str((body or {}).get("message") or "").strip() or "Thomas Code checkpoint"
        if not cid:
            return web.json_response({"ok": False, "error": "conversation_id required"}, status=400)
        try:
            project_root = project_for_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        # The user's work only — never Thomas's internal conversation metadata.
        files = [f for f in forge_code_git.changed_files(project_root) if not f.startswith(".thomas/")]
        try:
            result = forge_code_git.checkpoint(project_root, files, message)
        except forge_code_git.ForgeCodeGitError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        return web.json_response({"ok": True, **result, "files": files})

    return {
        "deliverables_list": deliverables_list,
        "changes": changes,
        "revert": revert,
        "keep": keep,
        "checkpoint": checkpoint,
    }
