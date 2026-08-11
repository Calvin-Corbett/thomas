"""Directed Evolve-agent HTTP API for Thomas's live self-builder.

This module owns ONE job: starting a Code run and driving it while it lives --
the launch checks, the subprocess, the transcript stream, steering, stopping,
and the per-conversation run registry that lets several runs exist at once.

Everything a run is looked at THROUGH was moved to siblings, because it served
a different question and the file had grown past the 1500-line ceiling the
architecture gate enforces:

* ``evolve_agent_watch_routes``        -- the live SSE feed and the status snapshot
* ``evolve_agent_conversation_routes`` -- the sidebar and the file browser
* ``evolve_agent_workspace_routes``    -- changes, revert, keep, checkpoint, deliverables
* ``evolve_agent_artifact_routes``     -- serving one built file, under capability and CSP
* ``evolve_agent_playtest_routes``     -- Thomas playing a game it built
* ``evolve_agent_run_state``           -- the app-state keys and the run registry

They are built here and their handlers merged into one map, so registration is
unchanged: ``evolve_agent_registration`` still resolves every route by name out
of a single dict.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sqlite3
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_git, forge_code_projects, forge_code_store

# The SSE line decoder and payload translator moved with `stream` into
# evolve_agent_watch_routes; they stay importable from here because callers and
# tests have always reached them at this path.
from thomas.forge.anvil.forge_code_http_stream import (
    IncrementalLineDecoder as _IncrementalLineDecoder,
)
from thomas.forge.anvil.forge_code_http_stream import line_to_sse_payload as _line_to_sse_payload
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError
from thomas.server.app_keys import APP_DELIVERABLE_PREVIEW_SERVICE, APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE

from .evolve_agent_artifact_routes import build_evolve_agent_artifact_handlers
from .evolve_agent_conversation_routes import build_evolve_agent_conversation_handlers
from .evolve_agent_http_support import (
    attachment_goal_note,
    git_status_unavailable_response,
    prepare_code_oauth_credential,
    stage_code_attachments,
    validate_active_run_request,
)
from .evolve_agent_playtest_routes import build_evolve_agent_playtest_handlers
from .evolve_agent_registration import register_evolve_agent_handler_map

# The keys are re-exported: they moved below the route modules so a sibling can
# read the same run state without importing this module back, and callers
# (including tests) that have always found them here still do.
from .evolve_agent_run_state import (
    APP_EVOLVE_AGENT_APPROVALS,
    APP_EVOLVE_AGENT_CONVO,
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_LOCK,
    APP_EVOLVE_AGENT_MODEL,
    APP_EVOLVE_AGENT_PROJECT,
    APP_EVOLVE_AGENT_RUNS,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_SETTINGS,
    APP_EVOLVE_AGENT_SNAPSHOT,
    APP_EVOLVE_AGENT_TASK,
    prune_runs,
    runs,
    slot_active,
    slot_for_run_id,
    slot_running,
)
from .evolve_agent_runtime import (
    _action_receipt,
    _agent_dir,
    _agent_launch,
    _attach_code_activity_release,
    _await_recording,
    _code_action_hash,
    _default_repo_root,
    _delete_action_receipt,
    _drain,
    _drain_and_record,
    _kill_tree,
    _mark_steer_requested,
    _mark_stop_requested,
    _recording_active,
    _release_code_activity_lease,
    _release_code_start_gate,
    _request_id,
    _run_replay_available,
    _save_action_receipt,
    _terminate_process,
    _transcript_path,
)
from .evolve_agent_watch_routes import build_evolve_agent_watch_handlers
from .evolve_agent_workspace_routes import build_evolve_agent_workspace_handlers

log = logging.getLogger(__name__)


def _is_thomas_source(path: Any) -> bool:
    """True when a path is the running server's own source checkout."""
    try:
        source = forge_code_projects.thomas_source_repo_root()
        if source is None or not path:
            return False
        return Path(str(path)).expanduser().resolve() == Path(source).resolve()
    except (OSError, ValueError):
        return False


def _unspecified_project_root(root: Path) -> Path:
    """Where a Code conversation goes when the user chose no project.

    Never Thomas's own source. That used to be the fallback, so any turn
    arriving without a project -- including one whose JSON failed to parse and
    was treated as an empty body -- silently bound the product tree and returned
    200, which is how a worker's deliverable ends up written beside the code
    that wrote it.

    A configured root that is some other repository is a deliberate choice and
    is still honoured. But it must actually be bindable: in an installed copy
    the computed root is the package's parent directory, which is not a
    repository at all, and failing there would leave someone unable to start
    anything. Scratch is the answer in both cases.
    """
    if not _is_thomas_source(root):
        try:
            return forge_code_projects.validate_project_root(root, fallback=root)
        except forge_code_projects.ForgeCodeProjectError:
            pass
    return forge_code_projects.default_scratch_project(root)


def _new_task_project_root(root: Path, task: str) -> Path:
    """Where a NEW Code task goes when nobody picked a project: its own folder.

    This is ``_unspecified_project_root`` with the shared drawer taken out of it.
    That drawer was one ~/.thomas/code_scratch for everybody, and it is where a
    task landed whenever the catalog root was Thomas's own source (every dev
    install) or was not a repository at all (every packaged install) -- which is
    to say, always. Measured on this workspace: 106 tasks bound to that single
    directory, index.html written by five different tasks each silently replacing
    the last, four of the owner's builds gone and the only surviving trace an
    orphaned stylesheet whose page no longer exists. Making the overwrite visible
    was not enough; the tasks have to stop landing on top of each other.

    A catalog root that IS a separate repository is still honoured, unchanged:
    that is somebody deliberately pointing Thomas at a project, not the absence
    of a choice.

    Only NEW tasks reach here. A conversation that is already bound is loaded
    from the registry first, so nothing existing moves.

    Falling back to the shared scratch when a folder cannot be made is
    deliberate: a task that cannot start at all is worse than one that shares.
    """
    if not _is_thomas_source(root):
        try:
            return forge_code_projects.validate_project_root(root, fallback=root)
        except forge_code_projects.ForgeCodeProjectError:
            pass
    try:
        return forge_code_projects.project_for_new_task(task)
    except forge_code_projects.ForgeCodeProjectError:
        log.warning("a per-task Code project could not be created; using shared scratch", exc_info=True)
        return forge_code_projects.default_scratch_project(root)


def _chosen_project(requested: Any, *, picked: bool = False) -> Any:
    """Drop a "choice" that is only a leftover handed back to us.

    The Code UI saves whatever root it was given and sends it as ``project_root``
    on the next NEW task. Originally that root was always ~/.thomas/code_scratch,
    so the value is already sitting in browsers -- and arriving as an explicit
    project_root it is indistinguishable from a deliberate pick. It cannot be
    one: the picker offers real projects and the drawer is not among them, so
    there is no click that produces it.

    Task-born folders get the same treatment, for the same reason, measured
    2026-08-05: task A's own folder came back as task B's ``project_root``
    (nothing was picked -- the client had simply kept it), so B built inside A
    and A's finished run listed B's page under "THOMAS MADE 2 THINGS". Unlike
    the drawer, a task folder CAN be clicked -- it appears in the picker -- so
    it is dropped only when the request carries no ``project_choice: "picked"``,
    the flag every real pick now sends. Folders the user made or chose
    themselves carry no task-born stamp and pass through untouched, flag or no
    flag.

    Only new tasks pass through here. A conversation already bound to one of
    these folders is resolved from the registry and still opens it.
    """
    if not requested:
        return None
    if forge_code_projects.is_shared_scratch(requested):
        return None
    if not picked and forge_code_projects.is_task_born_project(requested):
        return None
    return requested


# What a page may pull in while it runs. Keeping the preview to web assets
# means previewing a page cannot serve source or secrets from the project.
_PREVIEWABLE_SUFFIXES = {
    ".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".ogg", ".wav", ".webm", ".mp4",
}

# Directories the preview walk must never even ENTER. The old rglob("*")
# filtered these from its RESULTS but still descended into them, and it ran on
# the event loop -- measured live (py-spy, 2026-08-05): a conversation whose
# project root was a full checkout froze the WHOLE server for the duration of a
# ~1.5M-entry walk; every request, including "/", timed out for four minutes.
# The walk fires automatically -- the results UI hydrates artifact thumbnails
# whenever a Code conversation renders -- so one click on the wrong task took
# Thomas down for everyone watching.
_PREVIEW_PRUNED_DIRS = {".git", "node_modules", ".thomas", ".claude", ".venv", "__pycache__"}


def _preview_allowlist(root: Path) -> set[str]:
    """Walk a project for previewable web assets, pruning as it goes.

    Runs in a worker thread (see conversation_preview) and prunes excluded
    directories IN PLACE so the walk never enters them, instead of enumerating
    a million entries and discarding most of them afterwards.
    """
    allowed: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PREVIEW_PRUNED_DIRS]
        for filename in filenames:
            if Path(filename).suffix.lower() not in _PREVIEWABLE_SUFFIXES:
                continue
            rel = Path(dirpath, filename).relative_to(root)
            allowed.add(rel.as_posix())
    return allowed

# How many Code runs may execute concurrently across conversations.
# Raised from the old hard cap of 3 and made live-configurable via
# THOMAS_MAX_CONCURRENT_CODE_RUNS so a user can run as many different Code
# projects at once as they want; the ceiling only guards against runaway
# subprocess/model fan-out exhausting the host (each run spawns a headless
# build subprocess + model stream). Per-conversation serialization is
# unchanged — two runs in the SAME project would corrupt its state.
DEFAULT_MAX_CONCURRENT_CODE_RUNS = 8
_CODE_RUN_CEILING = 64


def _max_concurrent_code_runs() -> int:
    raw = str(os.environ.get("THOMAS_MAX_CONCURRENT_CODE_RUNS", "")).strip()
    if raw:
        try:
            requested = int(raw)
        except ValueError:
            requested = 0
        if requested > 0:
            return min(requested, _CODE_RUN_CEILING)
    return DEFAULT_MAX_CONCURRENT_CODE_RUNS


# Back-compat alias for callers/tests importing the old constant name.
MAX_CONCURRENT_CODE_RUNS = DEFAULT_MAX_CONCURRENT_CODE_RUNS


def build_evolve_agent_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> dict[str, Any]:
    if APP_EVOLVE_AGENT_APPROVALS not in app:
        app[APP_EVOLVE_AGENT_APPROVALS] = {}
    if APP_EVOLVE_AGENT_LOCK not in app:
        app[APP_EVOLVE_AGENT_LOCK] = asyncio.Lock()

    def _root() -> Path:
        return Path(root_resolver())

    def _load_conversation(cid: str) -> tuple[Path, dict[str, Any] | None]:
        """Find a conversation and the project it actually lives in.

        The registry is not the only truth about where a conversation is. It is
        written by whoever created the conversation, and plenty never wrote a
        row: measured on this workspace, 65 of the 108 tasks the sidebar shows
        have no registry entry at all -- they were written straight into the
        shared drawer. Resolving by registry alone sent every one of those to
        the catalog root, where the file is not, so opening them returned 404,
        renaming and deleting them touched nothing, and continuing one started
        a fresh project that could not see its own history.

        The LIST endpoint never had that problem, because it does not ask the
        registry where anything is -- it walks the known roots and reads what is
        there. This looks where the list looked, so the two can no longer
        disagree about a conversation both can see.
        """
        catalog = _root()
        bound = forge_code_projects.conversation_project(catalog, cid)
        conv = forge_code_store.load_conversation(bound, cid)
        if conv is not None:
            return bound, conv
        for root in forge_code_projects.conversation_roots(catalog):
            if root == bound:
                continue
            found = forge_code_store.load_conversation(root, cid)
            if found is not None:
                return root, found
        return bound, None

    def _project_for_conversation(cid: str) -> Path:
        return _load_conversation(cid)[0]

    def _running() -> bool:
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        return proc is not None and proc.returncode is None

    # ── Per-conversation run registry (parallel Code runs, Codex-style) ──
    # The rules live in evolve_agent_run_state so the watch handlers read the
    # registry the same way this module writes it; these are the app-bound
    # spellings the launch path uses.
    def _runs() -> dict[str, dict[str, Any]]:
        return runs(app)

    def _slot_running(slot: dict[str, Any] | None) -> bool:
        return slot_running(slot)

    def _slot_active(slot: dict[str, Any] | None) -> bool:
        return slot_active(slot)

    def _prune_runs() -> dict[str, dict[str, Any]]:
        return prune_runs(app)

    def _slot_for_run_id(run_id: str) -> dict[str, Any] | None:
        return slot_for_run_id(app, run_id)

    def _track_process(
        proc: Any,
        transcript: Path,
        project_root: Path,
        cid: str,
        model: str,
        snap: dict[str, str],
        catalog_root: Path,
        request_id: str,
        run_id: str,
        message: str,
        settings: dict[str, Any],
        activity_token: str,
    ) -> None:
        generation = int((app.get(APP_EVOLVE_AGENT_SESSION) or {}).get("generation") or 0) + 1
        session = {
            "generation": generation,
            "run_id": run_id,
            "request_id": request_id,
            "started_at": time.time(),
            "message": message,
            "project_root": str(project_root),
            "conversation_id": cid,
            "settings": settings,
            "snapshot": snap,
            "transcript": str(transcript),
            "proc": proc,
        }
        # Legacy single-slot mirror: most recent run (existing consumers).
        app[APP_EVOLVE_AGENT_SESSION] = session
        app[APP_EVOLVE_AGENT_TASK], app[APP_EVOLVE_AGENT_CONVO] = proc, cid
        app[APP_EVOLVE_AGENT_PROJECT] = str(project_root)
        app[APP_EVOLVE_AGENT_SETTINGS] = settings
        task = asyncio.ensure_future(
            _drain_and_record(
                proc,
                transcript,
                project_root,
                cid,
                model,
                snap,
                app,
                catalog_root=catalog_root,
                request_id=request_id,
                run_id=run_id,
            )
        )
        _attach_code_activity_release(task, app, activity_token)
        drain = {"generation": generation, "run_id": run_id, "task": task}
        app[APP_EVOLVE_AGENT_DRAIN] = drain
        _prune_runs()[cid] = {"session": session, "drain": drain}

    async def send(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        message = str((body or {}).get("message") or "").strip()
        if not message:
            return web.json_response({"ok": False, "error": "empty message"}, status=400)
        async with app[APP_EVOLVE_AGENT_LOCK]:
            return await _start_run(body if isinstance(body, dict) else {}, message)

    async def _start_run(body: dict[str, Any], message: str) -> web.Response:
        catalog_root = _root()
        request_id = _request_id(body)
        action_hash = _code_action_hash(message, body)
        replay = _action_receipt(catalog_root, "run", request_id)
        if replay is not None:
            if replay.get("action_hash") != action_hash:
                conflict = {
                    "ok": False,
                    "error": "request_id belongs to a different Code action",
                    "code": "idempotency_conflict",
                }
                return web.json_response(conflict, status=409)
            if not _run_replay_available(
                replay, app.get(APP_EVOLVE_AGENT_SESSION), _running(), app.get(APP_EVOLVE_AGENT_DRAIN)
            ):
                return web.json_response(
                    {
                        "ok": False,
                        "error": "the prior Code run cannot be verified after restart",
                        "code": "run_recovery_required",
                        "run_state": replay.get("state"),
                    },
                    status=409,
                )
            persistence = replay.get("persistence") if isinstance(replay.get("persistence"), dict) else {}
            return web.json_response(
                {**(replay.get("response") or {}), **persistence, "replayed": True, "run_state": replay.get("state")}
            )
        # Parallel runs (Codex-style): serialize per CONVERSATION, allow up to
        # MAX_CONCURRENT_CODE_RUNS across different conversations/projects.
        active_slots = {cid_key: slot for cid_key, slot in _prune_runs().items() if _slot_active(slot)}
        requested_cid = str(body.get("conversation_id") or "").strip()
        target_slot = active_slots.get(requested_cid) if requested_cid else None
        if target_slot is not None:
            code = "agent_result_recording" if not _slot_running(target_slot) else "agent_already_running"
            return web.json_response(
                {"ok": False, "error": "another Code run is still active", "code": code}, status=409
            )
        run_ceiling = _max_concurrent_code_runs()
        if len(active_slots) >= run_ceiling:
            return web.json_response(
                {
                    "ok": False,
                    "error": (
                        f"all {run_ceiling} concurrent Code run slots are busy — raise "
                        "THOMAS_MAX_CONCURRENT_CODE_RUNS to run more at once"
                    ),
                    "code": "agent_already_running",
                },
                status=409,
            )
        # Legacy safety net: a live run not present in the registry (pre-registry
        # state or tests seeding only the legacy keys) still blocks, with the
        # original running-vs-recording distinction preserved.
        legacy_recording = _recording_active(app.get(APP_EVOLVE_AGENT_DRAIN))
        if not active_slots and (_running() or legacy_recording):
            return web.json_response(
                {
                    "ok": False,
                    "error": "another Code run is still active",
                    "code": "agent_result_recording"
                    if legacy_recording and not _running()
                    else "agent_already_running",
                },
                status=409,
            )
        try:
            settings = ForgeCodeSettings.from_payload(body)
        except ForgeCodeSettingsError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "invalid_settings"}, status=400)

        conversation_id = str(body.get("conversation_id") or "").strip()
        source_evolve_item = body.get("source_evolve_item")
        source_evolve_item = source_evolve_item if isinstance(source_evolve_item, dict) else None

        requested_project = body.get("project_root")
        # Sent by every control that actually picks a folder (the dialog, a
        # project card, a typed name). Its absence is what identifies a root the
        # client merely kept from the previous task.
        project_picked = str(body.get("project_choice") or "").strip().lower() == "picked"
        # "setup" | "without" | "" -- the answer to the history question, absent
        # until the person has actually been asked one.
        history_choice = str(body.get("history_choice") or "").strip().lower()
        if history_choice not in ("setup", "without"):
            history_choice = ""
        loop = asyncio.get_running_loop()
        try:
            if conversation_id:
                project_root, conv = _load_conversation(conversation_id)
                if conv is None:
                    # An id with nothing behind it is still a NEW task, so it
                    # gets its own folder rather than the shared drawer.
                    chosen = _chosen_project(requested_project, picked=project_picked)
                    project_root = (
                        forge_code_projects.validate_project_root(chosen, fallback=catalog_root)
                        if chosen
                        else await loop.run_in_executor(None, _new_task_project_root, catalog_root, message)
                    )
                    _repo = forge_code_projects.thomas_source_repo_root()
                    if _repo is not None and project_root == _repo:
                        project_root = await loop.run_in_executor(
                            None, _new_task_project_root, catalog_root, message
                        )
                else:
                    if requested_project:
                        try:
                            selected = forge_code_projects.validate_project_root(
                                requested_project, fallback=catalog_root
                            )
                        except forge_code_projects.ForgeCodeProjectError:
                            # A root that no longer exists is not a choice -- it
                            # is the client replaying a path this conversation's
                            # folder has since been renamed away from. The bound
                            # folder is the truth, and the folder cannot change
                            # inside a conversation anyway, so a dead replay must
                            # not kill the message that would use the real one.
                            log.info(
                                "ignoring unusable project_root %r for bound conversation %s",
                                requested_project,
                                conversation_id,
                            )
                            selected = project_root
                        if selected != project_root:
                            return web.json_response(
                                {
                                    "ok": False,
                                    "error": "project_root cannot change inside an existing Code conversation",
                                    "code": "project_change_requires_new_conversation",
                                },
                                status=409,
                            )
                    # THE SAME HARD SAFETY NET AS THE OTHER TWO BRANCHES. This one
                    # takes its root from the stored conversation, so it was the
                    # only way into Thomas's own source tree -- and it is the
                    # branch every "continue this task" goes through. Measured on
                    # this workspace: 20 conversations resolve to the checkout,
                    # three with real turns, and one of them put `notes.txt` in
                    # the repository root. Revert is `git checkout -- <file>`,
                    # which for an untracked file is a delete, so those tasks
                    # could also remove files from the product source.
                    #
                    # Refused rather than redirected, unlike the new-task
                    # branches. They are choosing a folder and may be handed a
                    # different one; this conversation already HAS a folder, and
                    # the check directly above exists to stop it moving. Silently
                    # moving it here would break that rule while enforcing this
                    # one. A new task is one click away and lands somewhere safe.
                    _repo = forge_code_projects.thomas_source_repo_root()
                    if _repo is not None and project_root == _repo:
                        return web.json_response(
                            {
                                "ok": False,
                                "error": (
                                    "This task is pointed at Thomas's own source folder, which Code "
                                    "will not edit. Start a new task and it will get its own folder."
                                ),
                                "code": "project_is_thomas_source",
                                "project_root": str(project_root),
                            },
                            status=409,
                        )
                    if not (conv.get("turns") or []):
                        # The FIRST message of a conversation opened by New
                        # chat: conversation_new bound a folder before any
                        # words existed, so the folder carries a timestamp
                        # name while the send-first path names folders after
                        # the task. Now that the words exist, give the folder
                        # its real name. The forge side only acts on folders
                        # its own stamp proves were named from nothing and
                        # that hold no user files; everything else -- picked
                        # projects, folders with work in them, task-named
                        # folders -- passes through untouched, and any
                        # failure keeps the generic name without blocking
                        # this run.
                        project_root = await loop.run_in_executor(
                            None,
                            forge_code_projects.rename_task_born_for_first_message,
                            catalog_root,
                            conversation_id,
                            project_root,
                            message,
                        )
            else:
                # New conversation, no explicit project -> a folder of ITS OWN,
                # named after the task. Never the one shared scratch drawer, and
                # never Thomas's own source tree (the catalog root).
                chosen = _chosen_project(requested_project, picked=project_picked)
                _fallback: Path = (
                    catalog_root
                    if chosen
                    else await loop.run_in_executor(None, _new_task_project_root, catalog_root, message)
                )
                project_root = forge_code_projects.validate_project_root(
                    chosen,
                    fallback=_fallback,
                    allow_without_history=(history_choice == "without"),
                )
                if history_choice == "setup":
                    project_root = forge_code_projects.initialize_history(project_root)
                # HARD SAFETY NET: a stale client localStorage (or catalog root)
                # can still resolve to Thomas's own source repo, which Code must
                # never edit. If it does, substitute this task's own project.
                _repo = forge_code_projects.thomas_source_repo_root()
                if _repo is not None and project_root == _repo:
                    project_root = await loop.run_in_executor(None, _new_task_project_root, catalog_root, message)
                conv = None
        except forge_code_projects.ForgeCodeHistoryRequired as exc:
            # Not a dead end -- a question. The old message promised Thomas
            # "asks first" for your own folders and then never asked, so 117 of
            # this user's 121 projects were simply unopenable.
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
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "invalid_project_root"}, status=400)

        created_conversation = conv is None
        if created_conversation:
            conv = forge_code_store.draft_conversation(source_evolve_item=source_evolve_item)
        cid = conv["id"]
        capability_report = settings.capability_report()
        # Stage user attachments (photos as files, docs as text) into the project
        # BEFORE the git snapshot: they are inputs the agent reads, and must not
        # surface later as run outputs/artifacts in the change delta.
        try:
            staged_attachments = stage_code_attachments(project_root, body)
        except OSError:
            log.warning("Code attachments could not be staged", exc_info=True)
            staged_attachments = []
        goal_message = message + attachment_goal_note(staged_attachments)
        try:
            snap = forge_code_git.snapshot(project_root)
        except forge_code_git.ForgeCodeGitError as exc:
            log.warning("Code launch could not confirm Git workspace state: %s", exc)
            return git_status_unavailable_response(exc)
        run_id = f"run-{secrets.token_urlsafe(12)}"
        transcript = _transcript_path(catalog_root, run_id)
        oauth_access_token, auth_error = await prepare_code_oauth_credential(app, settings.family)
        if auth_error is not None:
            return auth_error
        cmd, env = _agent_launch(
            settings,
            project_root,
            cid,
            package_root=Path(__file__).resolve().parents[3],
        )
        start_token = secrets.token_urlsafe(24)
        env["THOMAS_CODE_START_GATE"] = "pipe"
        env["THOMAS_CODE_START_TOKEN"] = start_token
        env["THOMAS_CODE_RUN_ID"] = run_id
        env["THOMAS_CODE_REQUEST_ID"] = request_id
        # Make this run visible to Thomas's own instruments.
        #
        # Until now the run store was wired to the Chat path ONLY -- start_chat_v2_run
        # is called from chat_v2.py and workspace_specialist_runtime.py, and nothing
        # anywhere on the Code path. So Code runs, the ones that actually build
        # things, were never recorded at all. On 2026-08-04 a real Code run built a
        # working clock.html and the run count in runs.sqlite3 went 408 -> 408.
        #
        # The damage is not to the user, it is to everyone reasoning ABOUT Thomas.
        # The newest row in that database was 2026-07-29, which reads as "Thomas has
        # been idle for six days" when it actually means "Chat has been idle and Code
        # has never been visible". A day was spent drawing conclusions from it, by me
        # and by fourteen agents, none of whom could see the mode being used.
        #
        # Deliberately fails silent-but-visible rather than silent: a run row with no
        # end time is obviously incomplete and reconcile_stale_runs() already exists
        # to close those. FINALISATION IS NOT WIRED YET -- the "done" frame below is
        # where it belongs, and until it is there these rows will show as unfinished.
        _record_code_run_start(app, run_id, cid, project_root, settings)

        response = {
            "ok": True,
            "started": True,
            "request_id": request_id,
            "run_id": run_id,
            "run_state": "running",
            "conversation_id": cid,
            "project_root": str(project_root),
            "settings": capability_report,
        }
        reservation = {"state": "launching", "action_hash": action_hash, "response": response}
        proc, persisted, activity_token, gate_release_state = None, None, "", {"payload_write_attempted": False}
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                *cmd,
                cwd=str(project_root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            _save_action_receipt(catalog_root, "run", request_id, reservation)
            if _action_receipt(catalog_root, "run", request_id) != reservation:
                raise RuntimeError("Code launch receipt could not be verified")
            transcript.write_bytes(b"")
            turn_identity = {"request_id": request_id, "request_fingerprint": action_hash}
            persisted = (
                forge_code_store.persist_draft_with_user_turn(project_root, conv, message, **turn_identity)
                if created_conversation
                else forge_code_store.append_user_turn(project_root, cid, message, **turn_identity)
            )
            if persisted is None:
                raise RuntimeError("Code user turn could not be persisted")
            if forge_code_projects.conversation_metadata(catalog_root, cid) is None:
                forge_code_projects.bind_conversation(catalog_root, cid, project_root, settings=capability_report)
            else:
                forge_code_projects.update_conversation_settings(catalog_root, cid, capability_report)
            _save_action_receipt(catalog_root, "run", request_id, {**reservation, "state": "running"})
            activity_token = await _release_code_start_gate(
                app, proc, start_token, oauth_access_token, run_id, goal_message, gate_release_state
            )
        except (asyncio.CancelledError, OSError, RuntimeError, TypeError, ValueError):
            termination = {}
            if proc is not None:
                termination = await asyncio.shield(_terminate_process(proc))
            delivered = bool(gate_release_state["payload_write_attempted"])
            activity_token = str(gate_release_state.get("activity_token") or activity_token)
            if delivered and proc is not None:
                _track_process(
                    proc,
                    transcript,
                    project_root,
                    cid,
                    settings.recorded_model(),
                    snap,
                    catalog_root,
                    request_id,
                    run_id,
                    message,
                    capability_report,
                    activity_token,
                )
                activity_token = ""
            if activity_token:
                _release_code_activity_lease(app, activity_token)
            if delivered:
                retry_safe = False
            elif created_conversation:
                retry_safe = forge_code_store.delete_conversation(project_root, cid)
            elif persisted is not None:
                retry_safe = forge_code_store.rollback_user_turn(
                    project_root, cid, request_id, before=conv, after=persisted
                )
            else:
                retry_safe = forge_code_store.load_conversation(project_root, cid) == conv
            if retry_safe:
                _delete_action_receipt(catalog_root, "run", request_id)
            raise
        _track_process(
            proc,
            transcript,
            project_root,
            cid,
            settings.recorded_model(),
            snap,
            catalog_root,
            request_id,
            run_id,
            message,
            capability_report,
            activity_token,
        )
        return web.json_response(response)

    async def approve(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            body = {}
        approval_id = str((body or {}).get("approval_id") or "").strip()
        approvals = app[APP_EVOLVE_AGENT_APPROVALS]
        approval = approvals.get(approval_id)
        if not isinstance(approval, dict) or float(approval.get("expires_at") or 0) < time.time():
            return web.json_response({"ok": False, "error": "approval is missing or expired"}, status=404)
        if approval.get("state") != "pending":
            return web.json_response({"ok": False, "error": "approval is no longer pending"}, status=409)
        approval["state"] = "approved"
        approval["approved_at"] = time.time()
        return web.json_response(
            {
                "ok": True,
                "approval": {
                    key: value for key, value in approval.items() if key not in {"message_hash", "action_hash"}
                },
            }
        )

    async def steer(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            body = {}
        message = str((body or {}).get("message") or "").strip()
        if not message:
            return web.json_response({"ok": False, "error": "empty steering message"}, status=400)
        # Steer exactly the requested run when several are live.
        slot = _slot_for_run_id(str((body or {}).get("run_id") or ""))
        if slot is not None:
            proc = (slot.get("session") or {}).get("proc")
            if proc is None or proc.returncode is not None:
                return web.json_response({"ok": False, "error": "that Code run is not running"}, status=409)
            _mark_steer_requested(proc)
            asyncio.get_running_loop().run_in_executor(None, _kill_tree, proc)
            return web.json_response(
                {"ok": True, "stop_requested": True, "restart_required": True, "message": message}, status=202
            )
        if not _running():
            return web.json_response({"ok": False, "error": "no Code task is running"}, status=409)
        stale = validate_active_run_request(body, app.get(APP_EVOLVE_AGENT_SESSION))
        if stale is not None:
            return stale
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        if proc is not None and proc.returncode is None:
            _mark_steer_requested(proc)
            asyncio.get_running_loop().run_in_executor(None, _kill_tree, proc)
        return web.json_response(
            {"ok": True, "stop_requested": True, "restart_required": True, "message": message}, status=202
        )

    async def stop(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            body = {}
        # Resolve the slot for the REQUESTED run so stopping targets exactly
        # that run even when several are live.
        slot = _slot_for_run_id(str((body or {}).get("run_id") or ""))
        if slot is not None:
            proc = (slot.get("session") or {}).get("proc")
            _mark_stop_requested(proc)
            receipt = await _terminate_process(proc)
            if receipt["termination_confirmed"]:
                receipt.update(await _await_recording(slot.get("drain")))
            status_code = (
                200 if receipt["termination_confirmed"] else 202 if receipt["state"] == "termination_pending" else 409
            )
            return web.json_response(receipt, status=status_code)
        if _running():
            stale = validate_active_run_request(body, app.get(APP_EVOLVE_AGENT_SESSION))
            if stale is not None:
                return stale
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        _mark_stop_requested(proc)
        receipt = await _terminate_process(proc)
        if receipt["termination_confirmed"]:
            receipt.update(await _await_recording(app.get(APP_EVOLVE_AGENT_DRAIN)))
        status_code = (
            200 if receipt["termination_confirmed"] else 202 if receipt["state"] == "termination_pending" else 409
        )
        return web.json_response(receipt, status=status_code)

    async def conversation_preview(request: web.Request) -> web.Response:
        """An isolated loopback origin that can actually SERVE the project.

        A generated page was previewed with srcdoc, which has no origin and no
        base URL, so anything the page fetches at runtime fails. Static script
        tags could be inlined, but Thomas moved a game's renderer to a dynamic
        loader and the preview 404'd 51 times and silently fell back to the old
        canvas -- a broken game that looked like the renderer not working.

        This is the same service Chat previews deliverables through: a real
        origin, so relative paths, dynamic imports and fetches behave exactly as
        they will for the user. The allowlist keeps it to web assets, so
        previewing a page cannot serve source or secrets sitting in the project.
        """
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        tail = str(request.query.get("path") or "").strip().replace("\\", "/").lstrip("/")
        if not tail or ".." in tail.split("/"):
            return web.json_response({"ok": False, "error": "invalid path"}, status=400)
        service = request.app.get(APP_DELIVERABLE_PREVIEW_SERVICE)
        if service is None:
            return web.json_response({"ok": False, "error": "preview service unavailable"}, status=503)
        try:
            project_root, conv = _load_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        if conv is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        root = Path(project_root)
        target = (root / tail).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            return web.json_response({"ok": False, "error": "file not found"}, status=404)
        # The same refusal the edit path makes (`project_is_thomas_source`),
        # for the same reason plus one more: walking the checkout is exactly
        # the multi-minute freeze described above _preview_allowlist, and Code
        # will not serve its own source tree as an app either way.
        if _is_thomas_source(root):
            return web.json_response(
                {
                    "ok": False,
                    "error": "This task is pointed at Thomas's own source folder, which Code will not preview.",
                    "code": "project_is_thomas_source",
                },
                status=409,
            )
        # RELATIVE paths from a PRUNED walk, off the event loop. See
        # _preview_allowlist for both measured failure modes this closes: the
        # absolute-parts filter that emptied every allowlist under ~/.thomas,
        # and the on-loop rglob that froze the whole server on big roots.
        allowed = await asyncio.to_thread(_preview_allowlist, root)
        if not allowed:
            return web.json_response({"ok": False, "error": "nothing to preview"}, status=404)
        try:
            url = await service.preview_directory_url(
                subject_id=f"code:{cid}",
                workspace=root,
                tail=tail,
                allowed_files=allowed,
            )
        except (FileNotFoundError, RuntimeError, OSError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)
        return web.json_response({"ok": True, "url": url, "path": tail})

    # The siblings are built with the SAME resolvers this module uses, passed in
    # rather than re-derived, so every Code route still agrees about where a
    # conversation lives and whether a run is in flight. Their handlers join one
    # map because registration looks routes up by name in a single dict.
    handlers: dict[str, Any] = {
        "send": send,
        "approve": approve,
        "steer": steer,
        "stop": stop,
        "conversation_preview": conversation_preview,
    }
    handlers.update(
        build_evolve_agent_watch_handlers(
            app,
            require_api_access=require_api_access,
            catalog_root=_root,
            running=_running,
        )
    )
    handlers.update(
        build_evolve_agent_conversation_handlers(
            require_api_access=require_api_access,
            catalog_root=_root,
            load_conversation=_load_conversation,
            project_for_conversation=_project_for_conversation,
            chosen_project=_chosen_project,
            new_task_project_root=_new_task_project_root,
        )
    )
    handlers.update(
        build_evolve_agent_workspace_handlers(
            app,
            require_api_access=require_api_access,
            catalog_root=_root,
            load_conversation=_load_conversation,
            project_for_conversation=_project_for_conversation,
            running=_running,
        )
    )
    handlers.update(
        build_evolve_agent_artifact_handlers(
            app,
            require_api_access=require_api_access,
            project_for_conversation=_project_for_conversation,
        )
    )
    handlers.update(
        build_evolve_agent_playtest_handlers(
            app,
            require_api_access=require_api_access,
            project_for_conversation=_project_for_conversation,
        )
    )
    return handlers



# The failures a run-store write can realistically produce. Named rather than a bare
# `except Exception`, so a recorder bug still surfaces while a storage hiccup never
# breaks a launch. Mirrors chat_v2_run_store's set.
_RUN_STORE_ERRORS = (AttributeError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError)


def _record_code_run_start(app, run_id: str, cid: str, project_root, settings) -> None:
    """Write one row so a Code run exists in Thomas's own run store.

    Never raises and never blocks the run. A recorder that can take the product down
    would be worse than no recorder, and this one is being added precisely because
    nobody noticed it was missing for months -- so it must not become the thing that
    makes launches fail.
    """

    module = app.get(APP_RUN_STORE_MODULE)
    if not bool(app.get(APP_RUN_STORE_ENABLED, False)) or module is None:
        return
    try:
        module.create_run(
            {
                "run_id": run_id,
                "session_id": str(cid or ""),
                "surface": "code",
                "profile": str(getattr(settings, "family", "") or ""),
                "model_id": str(getattr(settings, "recorded_model", lambda: "")() or ""),
                "mode": "code",
                "project_root": str(project_root or ""),
            }
        )
    except _RUN_STORE_ERRORS as exc:
        # Named rather than bare: a recorder must not break a launch, but it must
        # also not swallow a bug in itself. Same set Chat's recorder uses.
        log.warning("Code run not recorded (run store write failed): %s", exc)


def register_evolve_agent_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> None:
    handlers = build_evolve_agent_handlers(app, require_api_access=require_api_access, root_resolver=root_resolver)
    register_evolve_agent_handler_map(app, handlers)
