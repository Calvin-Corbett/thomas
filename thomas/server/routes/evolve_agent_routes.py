"""Directed Evolve-agent HTTP API for Thomas's live self-builder.

This module owns ONE job: starting a Code run and driving it while it lives -- the launch checks, the subprocess, the
transcript stream, steering, stopping, and the per-conversation run registry that lets several runs exist at once.

Everything a run is looked at THROUGH was moved to siblings, because it served a different question and the file
had grown past the 1500-line ceiling the architecture gate enforces:

* ``evolve_agent_control_routes``      -- approving, steering and stopping a run
* ``evolve_agent_preview_routes``      -- isolated conversation previews
* ``evolve_agent_project_selection``   -- deliberate or per-task project selection
* ``evolve_agent_watch_routes``        -- the live SSE feed and the status snapshot
* ``evolve_agent_conversation_routes`` -- the sidebar and the file browser
* ``evolve_agent_workspace_routes``    -- changes, revert, keep, checkpoint, deliverables
* ``evolve_agent_artifact_routes``     -- serving one built file, under capability and CSP
* ``evolve_agent_playtest_routes``     -- Thomas playing a game it built
* ``evolve_agent_run_state``           -- the app-state keys and the run registry

They are built here and their handlers merged into one map, so registration is unchanged:
``evolve_agent_registration`` still resolves every route by name out of a single dict.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.event_loop_offload import off_loop
from thomas.core.machine_capacity import admission_refusal, await_room_for_run, max_concurrent_runs
from thomas.core.pause import REFUSAL, paused
from thomas.forge.anvil import forge_code_git, forge_code_projects, forge_code_store, run_control
from thomas.forge.anvil.agent_continuity import keep_conversation_agent

# The SSE line decoder and payload translator moved with `stream` into
# evolve_agent_watch_routes; they stay importable from here because callers and
# tests have always reached them at this path.
from thomas.forge.anvil.forge_code_http_stream import IncrementalLineDecoder as _IncrementalLineDecoder
from thomas.forge.anvil.forge_code_http_stream import line_to_sse_payload as _line_to_sse_payload
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError
from thomas.server.dial_elevation import cap_payload
from thomas.server.praxis.launch import attach_cleanup, bind_internal_start, local_port, prepare_launch

from . import evolve_agent_autopilot
from .evolve_agent_agents_routes import install_saved_anthropic_key_reader
from .evolve_agent_artifact_routes import build_evolve_agent_artifact_handlers
from .evolve_agent_control_routes import build_evolve_agent_control_handlers
from .evolve_agent_conversation_routes import build_evolve_agent_conversation_handlers
from .evolve_agent_http_support import (
    _record_code_run_start,
    attachment_goal_note,
    code_execution_settings_response,
    git_status_unavailable_response,
    prepare_code_oauth_credential,
    stage_code_attachments,
)
from .evolve_agent_playtest_routes import build_evolve_agent_playtest_handlers
from .evolve_agent_preview_routes import (  # noqa: F401
    _PREVIEW_PRUNED_DIRS,
    _PREVIEWABLE_SUFFIXES,
    _preview_allowlist,
    build_evolve_agent_preview_handlers,
)
from .evolve_agent_project_selection import _chosen_project, new_task_project_root, unspecified_project_root
from .evolve_agent_queued import busy_answer
from .evolve_agent_registration import register_evolve_agent_handler_map
from .evolve_agent_run_control_routes import build_run_control_handlers

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
    _code_action_hash,
    _default_repo_root,
    _delete_action_receipt,
    _drain,
    _drain_and_record,
    _kill_tree,
    _recording_active,
    _release_code_activity_lease,
    _release_code_start_gate,
    _request_id,
    _run_replay_available,
    _save_action_receipt,
    _terminate_process,
    _transcript_path,
)
from .evolve_agent_self_edit_actions import build_self_edit_handlers
from .evolve_agent_self_edit_runs import prepare_run
from .evolve_agent_stop import stop_code_run
from .evolve_agent_watch_routes import build_evolve_agent_watch_handlers
from .evolve_agent_workspace_routes import build_evolve_agent_workspace_handlers

log = logging.getLogger(__name__)


def _is_thomas_source(path: Any) -> bool:
    """Identify the source checkout, refusing to guess when it cannot be inspected."""
    try:
        source = forge_code_projects.thomas_source_repo_root()
        if source is None or not path:
            return False
        return Path(str(path)).expanduser().resolve() == source.resolve()
    except (OSError, ValueError) as exc:
        raise forge_code_projects.ForgeCodeInspectionUnavailable("Thomas source root could not be inspected") from exc


def _unspecified_project_root(root: Path) -> Path:
    return unspecified_project_root(root, _is_thomas_source=_is_thomas_source)


def _new_task_project_root(root: Path, task: str) -> Path:
    return new_task_project_root(root, task, _is_thomas_source=_is_thomas_source)


def find_conversation(catalog: Path, cid: str) -> tuple[Path, dict[str, Any] | None]:
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
        return find_conversation(_root(), cid)

    def _project_for_conversation(cid: str) -> Path:
        return _load_conversation(cid)[0]

    def _running() -> bool:
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        return proc is not None and proc.returncode is None

    # ── Per-conversation run registry (parallel Code runs, Codex-style) ──
    # The rules live in evolve_agent_run_state so the watch handlers read the registry the way this module
    # writes it; these are the app-bound spellings the launch path uses.
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
        app[APP_EVOLVE_AGENT_SESSION] = session
        app[APP_EVOLVE_AGENT_TASK], app[APP_EVOLVE_AGENT_CONVO] = proc, cid
        app[APP_EVOLVE_AGENT_PROJECT] = str(project_root)
        app[APP_EVOLVE_AGENT_SETTINGS] = settings
        proc.thomas_agent = str(((settings or {}).get("effective") or {}).get("agent") or "")
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
        attach_cleanup(app, task, run_id, proc, session=session)
        _attach_code_activity_release(task, app, activity_token)
        evolve_agent_autopilot.attach_after_run(app, task, project_root, catalog_root, cid)
        drain = {"generation": generation, "run_id": run_id, "task": task}
        app[APP_EVOLVE_AGENT_DRAIN] = drain
        _prune_runs()[cid] = {"session": session, "drain": drain}

    async def send(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            # missing/invalid body -> treat as empty (same set the other body readers in this module name).
            body = {}
        message = str((body or {}).get("message") or "").strip()
        if not message:
            return web.json_response({"ok": False, "error": "empty message"}, status=400)
        async with app[APP_EVOLVE_AGENT_LOCK]:
            return await _start_run(body if isinstance(body, dict) else {}, message, local_port=local_port(request))

    async def _start_run(body: dict[str, Any], message: str, *, local_port: int) -> web.Response:
        evolve_agent_autopilot.remember_port(app, local_port)  # fixed for the server's life; 0 is never pinned
        body = cap_payload(body)  # raised dials need a Hello approval (dial_elevation)
        catalog_root = _root()
        request_id = _request_id(body)
        action_hash = _code_action_hash(message, body)
        if (replay := await asyncio.to_thread(_action_receipt, catalog_root, "run", request_id)) is not None:
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
        if paused():  # a new run is not started while Thomas is paused; runs already going are left alone
            return web.json_response({"ok": False, "error": REFUSAL, "code": "paused"}, status=503)
        await await_room_for_run(any(_slot_active(slot) for slot in _prune_runs().values()))  # under 90% (10-25)
        from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN, drain_signal_path

        if app.get(APP_LANDED_CODE_DRAIN):
            if body.get(
                "queue_if_busy"
            ):  # the Build composer: the message waits and runs after the reload, never refused
                return busy_answer(body, "reload_draining", "landed code is reloading; your message runs right after")
            return web.json_response(
                {"ok": False, "error": "landed code is reloading; retry after restart", "code": "reload_draining"},
                status=503,
                headers={"Retry-After": "30"},
            )
        active_slots = {cid_key: slot for cid_key, slot in _prune_runs().items() if _slot_active(slot)}
        requested_cid = str(body.get("conversation_id") or "").strip()
        target_slot = active_slots.get(requested_cid) if requested_cid else None
        if target_slot is not None:
            code = "agent_result_recording" if not _slot_running(target_slot) else "agent_already_running"
            return busy_answer(body, code, "another Code run is still active")
        refusal = admission_refusal(len(active_slots))
        if refusal is not None:
            return busy_answer(body, "agent_already_running", refusal, full=True)
        # Legacy safety net: a live run not present in the registry (pre-registry
        # state or tests seeding only the legacy keys) still blocks, with the
        # original running-vs-recording distinction preserved.
        legacy_recording = _recording_active(app.get(APP_EVOLVE_AGENT_DRAIN))
        if not active_slots and (_running() or legacy_recording):
            code = "agent_result_recording" if legacy_recording and not _running() else "agent_already_running"
            return busy_answer(body, code, "another Code run is still active")
        try:
            settings = ForgeCodeSettings.from_payload(body)
        except ForgeCodeSettingsError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "invalid_settings"}, status=400)

        settings_block = code_execution_settings_response(settings)
        if settings_block is not None:
            return settings_block

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
                    _repo = await loop.run_in_executor(None, forge_code_projects.thomas_source_repo_root)
                    if _repo is not None and project_root == _repo:
                        project_root = await loop.run_in_executor(None, _new_task_project_root, catalog_root, message)
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
                    _repo = await loop.run_in_executor(None, forge_code_projects.thomas_source_repo_root)
                    if _repo is not None and project_root == _repo and not conv.get("self_edit"):
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
                    allow_without_history=(history_choice in ("setup", "without")),
                )
                if history_choice == "setup":
                    project_root = await loop.run_in_executor(
                        None, forge_code_projects.initialize_history, project_root
                    )
                # HARD SAFETY NET: a stale client localStorage (or catalog root)
                # can still resolve to Thomas's own source repo, which Code must
                # never edit. If it does, substitute this task's own project.
                _repo = await loop.run_in_executor(None, forge_code_projects.thomas_source_repo_root)
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
        settings = keep_conversation_agent(settings, conv)  # an unpicked conversation keeps its agent
        run_id = f"run-{secrets.token_urlsafe(12)}"
        self_edit_record = None
        execution_root = project_root
        if conv.get("self_edit"):
            try:
                source_is_selected = _is_thomas_source(project_root)
            except forge_code_projects.ForgeCodeProjectError as exc:
                return web.json_response({"ok": False, "error": str(exc), "code": "invalid_project_root"}, status=400)
            if (
                not source_is_selected
                or settings.family != "gpt"
                or settings.engine != "agent"
                or settings.guardrails == "open"
                or settings.file_access not in {"workspace", "project"}
            ):
                return web.json_response(
                    {"ok": False, "error": "Edit Thomas requires GPT, confined file access and guarded tools"},
                    status=409,
                )
            try:
                self_edit_record = await asyncio.to_thread(prepare_run, project_root, catalog_root, conv, run_id)
                execution_root = Path(self_edit_record["candidate_root"])
            except (OSError, RuntimeError, ValueError) as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=409)
        capability_report = settings.capability_report()
        # Stage user attachments (photos as files, docs as text) into the project
        # BEFORE the git snapshot: they are inputs the agent reads, and must not
        # surface later as run outputs/artifacts in the change delta.
        try:
            staged_attachments = stage_code_attachments(execution_root, body)
        except OSError:
            log.warning("Code attachments could not be staged", exc_info=True)
            staged_attachments = []
        goal_message = message + attachment_goal_note(staged_attachments)
        if self_edit_record:
            goal_message += (
                "\nWork only in this private candidate. Change only these exact files: "
                + ", ".join(self_edit_record["scope"])
                + ". Do not change tests, policy or live source. Independent checks and Apply happen after this run."
            )
        try:
            # git status plus a content hash of every changed file, taken at the
            # moment a build starts -- so it lands on the loop exactly when the
            # person is waiting to see the run appear.
            snap = await off_loop("code_launch.snapshot", forge_code_git.snapshot, project_root)
        except forge_code_git.ForgeCodeGitError as exc:
            log.warning("Code launch could not confirm Git workspace state: %s", exc)
            return git_status_unavailable_response(exc)
        transcript = _transcript_path(catalog_root, run_id)
        oauth_access_token, auth_error = await prepare_code_oauth_credential(app, settings.family, agent=settings.agent)
        if auth_error is not None:
            return auth_error
        cmd, env = _agent_launch(
            settings,
            execution_root,
            cid,
            package_root=Path(__file__).resolve().parents[3],
        )
        env["THOMAS_CODE_RELOAD_DRAIN_SIGNAL"] = str(drain_signal_path())
        env[run_control.CONTROL_DIR_ENV] = str(run_control.control_dir(catalog_root, run_id))  # pause, messages
        if self_edit_record:
            cmd.extend(["--history-root", str(project_root)])
        start_token, channel_registry = prepare_launch(
            app, settings, project_root, run_id, request_id, env, local_port, message, cid
        )
        # Make this run visible to Thomas's own instruments.
        # Until now the run store was wired to the Chat path ONLY -- start_chat_v2_run
        # is called from chat_v2.py and workspace_specialist_runtime.py, and nothing
        # anywhere on the Code path. So Code runs, the ones that actually build
        # things, were never recorded at all. On 2026-08-04 a real Code run built a
        # working clock.html and the run count in runs.sqlite3 went 408 -> 408.
        # The damage is not to the user, it is to everyone reasoning ABOUT Thomas.
        # The newest row in that database was 2026-07-29, which reads as "Thomas has
        # been idle for six days" when it actually means "Chat has been idle and Code
        # has never been visible". A day was spent drawing conclusions from it, by me
        # and by fourteen agents, none of whom could see the mode being used.
        # Deliberately fails silent-but-visible rather than silent: a run row with no
        # end time is obviously incomplete and reconcile_stale_runs() already exists
        # to close those.
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
            "controls": run_control.controls_for_agent(settings.agent),
        }
        reservation = {"state": "launching", "action_hash": action_hash, "response": response}
        proc, persisted, activity_token, gate_release_state = None, None, "", {"payload_write_attempted": False}
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                *cmd,
                cwd=str(execution_root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                # Its own hidden console: on a shared one, a console Ctrl+C from anything in any run's tree
                # stopped every run the server hosted at once (2026-09-26, every few minutes).
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            proc.thomas_acceptance = body.get("acceptance") if isinstance(body.get("acceptance"), list) else []
            if self_edit_record:
                proc.thomas_self_edit = self_edit_record
            before_user_turn = await asyncio.to_thread(forge_code_store.load_conversation, project_root, cid)
            await asyncio.to_thread(_save_action_receipt, catalog_root, "run", request_id, reservation)
            if await asyncio.to_thread(_action_receipt, catalog_root, "run", request_id) != reservation:
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
            running = {**reservation, "state": "running"}  # receipts are saved off the loop (evolve_agent_receipts)
            await asyncio.to_thread(_save_action_receipt, catalog_root, "run", request_id, running)
            activity_token = await _release_code_start_gate(
                app, proc, start_token, oauth_access_token, run_id, goal_message, gate_release_state
            )
        except (asyncio.CancelledError, OSError, RuntimeError, TypeError, ValueError):
            if channel_registry is not None:
                await channel_registry.close(run_id)
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
                    project_root, cid, request_id, before=before_user_turn, after=persisted
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

    # The siblings are built with the SAME resolvers this module uses, passed in
    # rather than re-derived, so every Code route still agrees about where a
    # conversation lives and whether a run is in flight. Their handlers join one
    # map because registration looks routes up by name in a single dict.
    handlers: dict[str, Any] = {"send": send}
    handlers.update(
        build_self_edit_handlers(
            app, require_api_access=require_api_access, catalog_root=_root, load_conversation=_load_conversation
        )
    )
    handlers.update(
        build_evolve_agent_control_handlers(
            app,
            require_api_access=require_api_access,
            _slot_for_run_id=_slot_for_run_id,
            _running=_running,
            _kill_tree=_kill_tree,
        )
    )
    handlers.update(
        build_evolve_agent_preview_handlers(
            require_api_access=require_api_access,
            _load_conversation=_load_conversation,
            _is_thomas_source=_is_thomas_source,
        )
    )
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
    bind_internal_start(app, _start_run, app[APP_EVOLVE_AGENT_LOCK], stop=stop_code_run)
    return handlers


def register_evolve_agent_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
    routes_on: Any = None,
) -> None:
    handlers = build_evolve_agent_handlers(app, require_api_access=require_api_access, root_resolver=root_resolver)
    install_saved_anthropic_key_reader(app)
    handlers.update(build_run_control_handlers(app, require_api_access, root_resolver, find_conversation))
    register_evolve_agent_handler_map(app if routes_on is None else routes_on, handlers)
