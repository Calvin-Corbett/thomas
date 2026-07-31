"""Directed Evolve-agent HTTP API for Thomas's live self-builder."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import (
    forge_code_deliverables,
    forge_code_git,
    forge_code_projects,
    forge_code_store,
    forge_code_tree,
)
from thomas.forge.anvil.forge_code_http_stream import (
    IncrementalLineDecoder as _IncrementalLineDecoder,
)
from thomas.forge.anvil.forge_code_http_stream import line_to_sse_payload as _line_to_sse_payload
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError
from thomas.server.app_keys import APP_DELIVERABLE_PREVIEW_SERVICE

from .evolve_agent_http_support import (
    attachment_goal_note,
    conversation_artifact_allowlist,
    git_status_unavailable_response,
    prepare_code_oauth_credential,
    stage_code_attachments,
    validate_active_run_request,
)
from .evolve_agent_registration import register_evolve_agent_handler_map
from .evolve_agent_runtime import (
    _action_receipt,
    _agent_dir,
    _agent_launch,
    _attach_code_activity_release,
    _authorize_conversation_revert,
    _await_recording,
    _code_action_hash,
    _conversation_changed_files,
    _default_repo_root,
    _delete_action_receipt,
    _drain,
    _drain_and_record,
    _finish_approval_execution,
    _kill_tree,
    _recording_active,
    _recording_status,
    _release_code_activity_lease,
    _release_code_start_gate,
    _request_id,
    _run_replay_available,
    _save_action_receipt,
    _sse_frame,
    _terminate_process,
    _transcript_path,
)

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


def _chosen_project(requested: Any) -> Any:
    """Drop a "choice" that is only the shared drawer handed back to us.

    The Code UI saves whatever root it was given and sends it as ``project_root``
    on the next NEW task. Until now that root was always ~/.thomas/code_scratch,
    so the value is already sitting in browsers -- and arriving as an explicit
    project_root it is indistinguishable from a deliberate pick. It cannot be
    one: the picker offers real projects and the drawer is not among them, so
    there is no click that produces it.

    Only new tasks pass through here. A conversation already bound to the drawer
    is resolved from the registry and still opens it.
    """
    return None if requested and forge_code_projects.is_shared_scratch(requested) else requested


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

# What a page may pull in while it runs. Keeping the preview to web assets
# means previewing a page cannot serve source or secrets from the project.
_PREVIEWABLE_SUFFIXES = {
    ".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".ogg", ".wav", ".webm", ".mp4",
}

APP_EVOLVE_AGENT_TASK = "evolve_agent_task"
APP_EVOLVE_AGENT_DRAIN = "evolve_agent_drain"
APP_EVOLVE_AGENT_SESSION = "evolve_agent_session"
APP_EVOLVE_AGENT_CONVO = "evolve_agent_convo"
APP_EVOLVE_AGENT_SNAPSHOT = "evolve_agent_snapshot"
APP_EVOLVE_AGENT_MODEL = "evolve_agent_model"
APP_EVOLVE_AGENT_PROJECT = "evolve_agent_project"
APP_EVOLVE_AGENT_SETTINGS = "evolve_agent_settings"
APP_EVOLVE_AGENT_APPROVALS = "evolve_agent_approvals"
APP_EVOLVE_AGENT_LOCK = "evolve_agent_lock"
# Per-conversation run registry: dict[conversation_id -> {"session": ..., "drain": ...}].
APP_EVOLVE_AGENT_RUNS = "evolve_agent_runs"
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
    artifact_capability_secret = secrets.token_bytes(32)
    artifact_capability_ttl_seconds = 3600

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
    # Each conversation gets its own slot {session, drain}; the legacy single
    # keys keep mirroring the MOST RECENT run so existing consumers still work.
    def _runs() -> dict[str, dict[str, Any]]:
        runs = app.get(APP_EVOLVE_AGENT_RUNS)
        if not isinstance(runs, dict):
            runs = {}
            app[APP_EVOLVE_AGENT_RUNS] = runs
        return runs

    def _slot_running(slot: dict[str, Any] | None) -> bool:
        proc = ((slot or {}).get("session") or {}).get("proc")
        return proc is not None and proc.returncode is None

    def _slot_active(slot: dict[str, Any] | None) -> bool:
        return _slot_running(slot) or _recording_active((slot or {}).get("drain"))

    def _prune_runs() -> dict[str, dict[str, Any]]:
        runs = _runs()
        for key in [key for key, slot in runs.items() if not _slot_active(slot)]:
            runs.pop(key, None)
        return runs

    def _slot_for_run_id(run_id: str) -> dict[str, Any] | None:
        wanted = str(run_id or "").strip()
        if not wanted:
            return None
        for slot in _runs().values():
            if str((slot.get("session") or {}).get("run_id") or "") == wanted:
                return slot
        return None

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
                    chosen = _chosen_project(requested_project)
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
                        selected = forge_code_projects.validate_project_root(
                            requested_project, fallback=catalog_root
                        )
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
            else:
                # New conversation, no explicit project -> a folder of ITS OWN,
                # named after the task. Never the one shared scratch drawer, and
                # never Thomas's own source tree (the catalog root).
                chosen = _chosen_project(requested_project)
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
            asyncio.get_running_loop().run_in_executor(None, _kill_tree, proc)
        return web.json_response(
            {"ok": True, "stop_requested": True, "restart_required": True, "message": message}, status=202
        )

    async def stream(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        session = dict(app.get(APP_EVOLVE_AGENT_SESSION) or {})
        run_id = str(session.get("run_id") or "legacy")
        recording = app.get(APP_EVOLVE_AGENT_DRAIN)
        wanted = str(request.query.get("run_id") or "").strip()
        if wanted and wanted != run_id:
            # Any REGISTERED run can be streamed, not just the most recent one.
            slot = _slot_for_run_id(wanted)
            if slot is None:
                return web.json_response(
                    {"ok": False, "error": "that Code run is not active", "code": "run_not_active"}, status=409
                )
            session = dict(slot.get("session") or {})
            run_id = wanted
            recording = slot.get("drain")
        try:
            cursor = max(0, int(request.query.get("cursor") or 0))
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid stream cursor"}, status=400)
        transcript = Path(session.get("transcript") or _transcript_path(_root()))
        proc = session.get("proc") or app.get(APP_EVOLVE_AGENT_TASK)
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(request)
        pos = 0
        sequence = 0
        linedec = _IncrementalLineDecoder()

        async def _emit_line(line: str) -> None:
            nonlocal sequence
            payload = _line_to_sse_payload(line)
            if payload:
                sequence += 1
                if sequence > cursor:
                    await resp.write(_sse_frame(payload, run_id, sequence))

        try:
            while not (request.transport is None or request.transport.is_closing()):
                chunk = b""
                if transcript.exists():
                    with open(transcript, "rb") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        pos = fh.tell()
                if chunk:
                    for line in linedec.feed(chunk):
                        await _emit_line(line)
                    # Data was flowing — loop again IMMEDIATELY (no poll delay) to
                    await asyncio.sleep(0)
                    continue
                if proc is None or proc.returncode is not None:
                    persistence = await _await_recording(recording)
                    # Final drain: the child may have flushed its last lines after
                    # our read above but before we noticed it exited — pick them up.
                    if transcript.exists():
                        with open(transcript, "rb") as fh:
                            fh.seek(pos)
                            tail = fh.read()
                            pos = fh.tell()
                        if tail:
                            for line in linedec.feed(tail):
                                await _emit_line(line)
                    for line in linedec.flush():
                        await _emit_line(line)
                    sequence += 1
                    if sequence > cursor:
                        await resp.write(
                            _sse_frame(
                                {
                                    "type": "done",
                                    **persistence,
                                    "conversation_id": session.get("conversation_id")
                                    or app.get(APP_EVOLVE_AGENT_CONVO)
                                    or "",
                                    "project_root": session.get("project_root")
                                    or app.get(APP_EVOLVE_AGENT_PROJECT)
                                    or "",
                                    "settings": session.get("settings") or app.get(APP_EVOLVE_AGENT_SETTINGS) or {},
                                },
                                run_id,
                                sequence,
                            )
                        )
                    break
                await asyncio.sleep(0.05)
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
            pass
        return resp

    def _status_payload(sess: dict[str, Any], drain: Any, *, running: bool) -> dict[str, Any]:
        return {
            "ok": True,
            "running": running,
            **_recording_status(drain),
            "run_id": sess.get("run_id") or "",
            "generation": sess.get("generation") or 0,
            "session": {
                "message": sess.get("message", ""),
                "started_at": sess.get("started_at"),
                "project_root": sess.get("project_root", ""),
                # Lets a reloaded page reattach to the running run's conversation.
                "conversation_id": sess.get("conversation_id", ""),
            },
            "settings": sess.get("settings") or app.get(APP_EVOLVE_AGENT_SETTINGS) or {},
        }

    async def status(request: web.Request) -> web.Response:
        require_api_access(request)
        # Per-slot resolution: ?conversation_id= or ?run_id= answers for THAT
        # run; default keeps the legacy most-recent shape plus a runs[] list.
        wanted_cid = str(request.query.get("conversation_id") or "").strip()
        wanted_run = str(request.query.get("run_id") or "").strip()
        if wanted_cid or wanted_run:
            slot = _runs().get(wanted_cid) if wanted_cid else _slot_for_run_id(wanted_run)
            sess = (slot or {}).get("session") or {}
            return web.json_response(_status_payload(sess, (slot or {}).get("drain"), running=_slot_running(slot)))
        sess = app.get(APP_EVOLVE_AGENT_SESSION) or {}
        payload = _status_payload(sess, app.get(APP_EVOLVE_AGENT_DRAIN), running=_running())
        payload["runs"] = [
            {
                "run_id": str((slot.get("session") or {}).get("run_id") or ""),
                "conversation_id": str((slot.get("session") or {}).get("conversation_id") or ""),
                "project_root": str((slot.get("session") or {}).get("project_root") or ""),
                "started_at": (slot.get("session") or {}).get("started_at"),
                "message": str((slot.get("session") or {}).get("message") or "")[:120],
                "running": _slot_running(slot),
                "recording": _recording_active(slot.get("drain")),
            }
            for slot in _runs().values()
            if _slot_active(slot)
        ]
        return web.json_response(payload)

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
        receipt = await _terminate_process(proc)
        if receipt["termination_confirmed"]:
            receipt.update(await _await_recording(app.get(APP_EVOLVE_AGENT_DRAIN)))
        status_code = (
            200 if receipt["termination_confirmed"] else 202 if receipt["state"] == "termination_pending" else 409
        )
        return web.json_response(receipt, status=status_code)

    async def deliverables_list(request: web.Request) -> web.Response:
        """List real, openable Forge Code build outputs for the My Stuff surface.

        Walks the same roots ``conversations_list`` walks, for the same reason:
        a run records its deliverable in the PROJECT it worked in, and every
        task now gets its own folder. Reading the catalog root alone returned an
        empty list -- measured live, 0 returned while 16 sat across 4 project
        roots -- and an empty list reads as "nothing has been built".
        """
        require_api_access(request)
        catalog_root = _root()
        return web.json_response(
            {
                "ok": True,
                "deliverables": forge_code_deliverables.list_deliverables_across(
                    catalog_root,
                    forge_code_projects.conversation_roots(catalog_root),
                ),
            }
        )

    async def conversations_list(request: web.Request) -> web.Response:
        require_api_access(request)
        catalog_root = _root()
        by_id: dict[str, dict[str, Any]] = {}
        for project_root in forge_code_projects.conversation_roots(catalog_root):
            for summary in forge_code_store.list_conversations(project_root):
                cid = str(summary.get("id") or "")
                if not cid or cid in by_id:
                    continue
                metadata = forge_code_projects.conversation_metadata(catalog_root, cid) or {}
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
            project_root, conv = _load_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        if conv is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        metadata = forge_code_projects.conversation_metadata(_root(), cid) or {}
        enriched = dict(conv)
        enriched["project_root"] = str(project_root)
        enriched["settings"] = metadata.get("settings") or {}
        return web.json_response({"ok": True, "conversation": enriched})

    async def conversation_new(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        title = str((body or {}).get("title") or "").strip()
        source = (body or {}).get("source_evolve_item")
        if not isinstance(source, dict):
            source = None
        requested_root = _chosen_project((body or {}).get("project_root"))
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
                    fallback=_root(),
                    allow_without_history=(history_choice == "without"),
                )
            else:
                # Nothing was chosen, so this task gets its OWN folder instead of
                # the shared drawer. Resolved only in this branch, so a request
                # that names its project never pays for creating one it will not
                # use. It shells out to git, so it runs off the loop.
                project_root = await loop.run_in_executor(None, _new_task_project_root, _root(), title)
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
            _root(),
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
            project_root = _project_for_conversation(cid)
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
            project_root = _project_for_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        removed = forge_code_store.delete_conversation(project_root, cid)
        if not removed:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        forge_code_projects.forget_conversation(_root(), cid)
        return web.json_response({"ok": True, "deleted": True, "id": cid})

    async def conversation_tree(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        try:
            project_root, conv = _load_conversation(cid)
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
            project_root, conv = _load_conversation(cid)
            if conv is None:
                return web.json_response({"ok": False, "error": "not found"}, status=404)
            result = forge_code_tree.read_project_file(project_root, request.query.get("path", ""))
        except (forge_code_projects.ForgeCodeProjectError, forge_code_tree.ForgeCodeTreeError) as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "invalid_file_path"}, status=400)
        return web.json_response({"ok": True, **result})

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
        allowed = set()
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _PREVIEWABLE_SUFFIXES:
                continue
            rel = path.relative_to(root)
            # RELATIVE parts, not the absolute path's. Projects live under
            # ~/.thomas/projects/<name>, so testing the absolute parts matched
            # ".thomas" on every file in every project and left the allowlist
            # empty -- which the caller then papered over with a one-file
            # fallback. That served the entry page and nothing it referenced,
            # and, because the allowlist then differed per file, each file
            # minted its own origin and tore down the one before it. Opening
            # the game blanked the thumbnail still showing the shell page.
            if any(part in {".git", "node_modules", ".thomas"} for part in rel.parts):
                continue
            allowed.add(rel.as_posix())
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
            root = _project_for_conversation(str(cid)) if cid else Path(app.get(APP_EVOLVE_AGENT_PROJECT) or _root())
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
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
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
        replay = _action_receipt(_root(), "revert", request_id)
        if replay is not None:
            if replay.get("scope") != scope:
                return web.json_response(
                    {"ok": False, "error": "request_id belongs to another revert", "code": "idempotency_conflict"},
                    status=409,
                )
            return web.json_response({**(replay.get("result") or {}), "replayed": True})
        try:
            root, conversation = _load_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        if conversation is None:
            return web.json_response({"ok": False, "error": "not found", "code": "conversation_not_found"}, status=404)
        metadata = forge_code_projects.conversation_metadata(_root(), cid)
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
            _save_action_receipt(_root(), "revert", request_id, {"scope": scope, "result": result})
            return web.json_response(result)
        finally:
            approval = approvals.get(approval_id)
            _finish_approval_execution(approval, succeeded=isinstance(result, dict) and result.get("ok") is True)

    async def keep(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        file = str((body or {}).get("file") or "").strip()
        if not file:
            return web.json_response({"ok": False, "error": "no file"}, status=400)
        # Keep is a deliberate no-op on disk: the change already lives in the
        # working tree, so "keep" just acknowledges it and leaves it untouched.
        cid = str((body or {}).get("conversation_id") or app.get(APP_EVOLVE_AGENT_CONVO) or "")
        try:
            root = _project_for_conversation(cid) if cid else Path(app.get(APP_EVOLVE_AGENT_PROJECT) or _root())
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409)
        return web.json_response({"ok": True, "kept": True, "file": file, "project_root": str(root)})

    def _artifact_capability(cid: str, bucket: int | None = None) -> str:
        current_bucket = int(time.time() // artifact_capability_ttl_seconds) if bucket is None else bucket
        payload = f"{cid}:{current_bucket}".encode()
        return hmac.new(artifact_capability_secret, payload, hashlib.sha256).hexdigest()

    def _valid_artifact_capability(cid: str, capability: str) -> bool:
        current_bucket = int(time.time() // artifact_capability_ttl_seconds)
        return any(
            hmac.compare_digest(capability, _artifact_capability(cid, bucket))
            for bucket in (current_bucket, current_bucket - 1)
        )

    def _artifact_scope(cid: str, tail: str) -> tuple[Path, Path, set[str]]:
        try:
            root = _project_for_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            raise web.HTTPNotFound(text=str(exc)) from exc
        tail = str(tail or "").strip()
        if not tail:
            raise web.HTTPNotFound(text="no artifact path")
        rel = tail.replace("\\", "/")
        allowed = conversation_artifact_allowlist(root, forge_code_store.load_conversation(root, str(cid)))
        if rel not in allowed:
            raise web.HTTPNotFound(text="not an artifact of this build")
        root_resolved = root.resolve()
        target = (root_resolved / rel).resolve()
        if not target.is_file() or not target.is_relative_to(root_resolved):
            raise web.HTTPNotFound(text="artifact file not found")
        return root_resolved, target, allowed

    def _artifact_file_response(cid: str, tail: str) -> web.FileResponse:
        _root_resolved, target, _allowed = _artifact_scope(cid, tail)
        response = web.FileResponse(target)
        # 'unsafe-eval' for the same reason the deliverable preview grants it:
        # the browser smoke that CERTIFIES these pages already allows it, so
        # without it this route is stricter than the check the page passed, and
        # a verified build breaks the instant the owner opens it. A calculator
        # evaluating a typed expression is the ordinary case, and it failed here
        # with `EvalError` while verification reported `completed`.
        #
        # 'unsafe-inline' is already granted, so a page can run any JavaScript
        # it likes by writing it out; refusing to evaluate a STRING removes no
        # capability. What actually contains the page is untouched and is
        # stricter here than in the preview: default-src 'none', connect-src
        # 'none' (no network at all), form-action 'none', base-uri 'none'.
        response.headers["Content-Security-Policy"] = (
            "sandbox allow-scripts; default-src 'none'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' data:; img-src 'self' data:; font-src 'self' data:; "
            "media-src 'self'; connect-src 'none'; form-action 'none'; base-uri 'none'"
        )
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def artifact(request: web.Request) -> web.StreamResponse:
        """Enter an isolated preview origin or download one verified artifact."""
        require_api_access(request)
        cid = str(request.match_info.get("cid", "") or "")
        tail = str(request.match_info.get("tail", "") or "")
        if Path(tail).suffix.lower() not in {".html", ".htm"}:
            return _artifact_file_response(cid, tail)
        root, _target, allowed = _artifact_scope(cid, tail)
        preview_service = app.get(APP_DELIVERABLE_PREVIEW_SERVICE)
        if preview_service is None:
            raise web.HTTPServiceUnavailable(text="Code preview service is not ready")
        try:
            location = await preview_service.preview_directory_url(
                subject_id=f"code:{cid}",
                workspace=root,
                tail=tail,
                allowed_files=allowed,
            )
        except (FileNotFoundError, RuntimeError):
            raise web.HTTPServiceUnavailable(text="Code preview service is not ready") from None
        raise web.HTTPFound(
            location=location,
            headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache", "Expires": "0"},
        )

    async def artifact_content(request: web.Request) -> web.StreamResponse:
        """Serve one artifact only when its expiring conversation capability is valid."""
        require_api_access(request)
        cid = str(request.match_info.get("cid", "") or "")
        capability = str(request.match_info.get("capability", "") or "")
        if not _valid_artifact_capability(cid, capability):
            raise web.HTTPNotFound(text="preview capability expired or invalid")
        response = _artifact_file_response(cid, str(request.match_info.get("tail", "") or ""))
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    async def checkpoint(request: web.Request) -> web.Response:
        """Codex-parity checkpoint: commit the conversation's kept changes on a
        new thomas-code/ branch; include a PR-ready remote URL when one exists."""
        require_api_access(request)
        if _running():
            return web.json_response({"ok": False, "error": "wait for the run to finish first"}, status=409)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        cid = str((body or {}).get("conversation_id") or "").strip()
        message = str((body or {}).get("message") or "").strip() or "Thomas Code checkpoint"
        if not cid:
            return web.json_response({"ok": False, "error": "conversation_id required"}, status=400)
        try:
            project_root = _project_for_conversation(cid)
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
        "send": send,
        "approve": approve,
        "steer": steer,
        "stream": stream,
        "status": status,
        "stop": stop,
        "checkpoint": checkpoint,
        "deliverables_list": deliverables_list,
        "conversations_list": conversations_list,
        "conversation_get": conversation_get,
        "conversation_new": conversation_new,
        "conversation_rename": conversation_rename,
        "conversation_delete": conversation_delete,
        "conversation_tree": conversation_tree,
        "conversation_file": conversation_file,
        "conversation_preview": conversation_preview,
        "changes": changes,
        "revert": revert,
        "keep": keep,
        "artifact": artifact,
        "artifact_content": artifact_content,
    }


def register_evolve_agent_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> None:
    handlers = build_evolve_agent_handlers(app, require_api_access=require_api_access, root_resolver=root_resolver)
    register_evolve_agent_handler_map(app, handlers)
