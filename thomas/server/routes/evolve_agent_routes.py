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
    _risky_code_action,
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

    def _project_for_conversation(cid: str) -> Path:
        return forge_code_projects.conversation_project(_root(), cid)

    def _load_conversation(cid: str) -> tuple[Path, dict[str, Any] | None]:
        project = _project_for_conversation(cid)
        return project, forge_code_store.load_conversation(project, cid)

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
        approval_id = str(body.get("approval_id") or "").strip()
        request_id = _request_id(body, fallback=approval_id)
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
        approval_to_consume: dict[str, Any] | None = None
        risk = _risky_code_action(message)
        if risk:
            approvals = app[APP_EVOLVE_AGENT_APPROVALS]
            approval = approvals.get(approval_id) if approval_id else None
            valid = bool(
                isinstance(approval, dict)
                and approval.get("state") == "approved"
                and approval.get("action_hash") == action_hash
                and float(approval.get("expires_at") or 0) >= time.time()
            )
            if not valid:
                approval_id = f"approval-{secrets.token_urlsafe(10)}"
                approvals[approval_id] = {
                    "id": approval_id,
                    "state": "pending",
                    "action_hash": action_hash,
                    "risk": risk,
                    "summary": f"Allow Code mode to {risk}?",
                    "expires_at": time.time() + 600,
                }
                return web.json_response(
                    {
                        "ok": False,
                        "error": "explicit approval is required for this external or destructive action",
                        "code": "approval_required",
                        "approval": {
                            key: value for key, value in approvals[approval_id].items() if key != "action_hash"
                        },
                    },
                    status=409,
                )
            approval_to_consume = approval
        try:
            settings = ForgeCodeSettings.from_payload(body)
        except ForgeCodeSettingsError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "invalid_settings"}, status=400)

        conversation_id = str(body.get("conversation_id") or "").strip()
        source_evolve_item = body.get("source_evolve_item")
        source_evolve_item = source_evolve_item if isinstance(source_evolve_item, dict) else None

        requested_project = body.get("project_root")
        try:
            if conversation_id:
                project_root, conv = _load_conversation(conversation_id)
                if conv is None:
                    project_root = forge_code_projects.validate_project_root(
                        requested_project,
                        fallback=catalog_root,
                    )
                    _repo = forge_code_projects.thomas_source_repo_root()
                    if _repo is not None and project_root == _repo:
                        project_root = forge_code_projects.default_scratch_project(catalog_root)
                elif requested_project:
                    selected = forge_code_projects.validate_project_root(requested_project, fallback=catalog_root)
                    if selected != project_root:
                        return web.json_response(
                            {
                                "ok": False,
                                "error": "project_root cannot change inside an existing Code conversation",
                                "code": "project_change_requires_new_conversation",
                            },
                            status=409,
                        )
            else:
                # New conversation, no explicit project -> scratch repo, never
                # Thomas's own source tree (the catalog root).
                _fallback = (
                    catalog_root if requested_project else forge_code_projects.default_scratch_project(catalog_root)
                )
                project_root = forge_code_projects.validate_project_root(requested_project, fallback=_fallback)
                # HARD SAFETY NET: a stale client localStorage (or catalog root)
                # can still resolve to Thomas's own source repo, which Code must
                # never edit. If it does, silently substitute a scratch project.
                _repo = forge_code_projects.thomas_source_repo_root()
                if _repo is not None and project_root == _repo:
                    project_root = forge_code_projects.default_scratch_project(catalog_root)
                conv = None
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
        if approval_to_consume is not None:
            approval_to_consume.update({"state": "executing", "executing_at": time.time()})
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
                    settings.model_id or settings.dispatch_model,
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
            _finish_approval_execution(approval_to_consume, succeeded=delivered)
            raise
        _finish_approval_execution(approval_to_consume, succeeded=True)
        _track_process(
            proc,
            transcript,
            project_root,
            cid,
            settings.model_id or settings.dispatch_model,
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
        """List real, openable Forge Code build outputs for the My Stuff surface."""
        require_api_access(request)
        return web.json_response({"ok": True, "deliverables": forge_code_deliverables.list_deliverables(_root())})

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
        requested_root = (body or {}).get("project_root")
        try:
            # Everything Thomas builds lands in ~/.thomas/workspaces/<exec-id>,
            # which is never a git repo -- so every app Thomas made for the user
            # was unopenable until now. Prepare Thomas's own folders on demand.
            # Folders outside ~/.thomas belong to the user and are left alone.
            if requested_root:
                await asyncio.get_running_loop().run_in_executor(
                    None, forge_code_projects.ensure_git_repo, requested_root
                )
            # Choosing nothing must never mean "edit Thomas's own source". The
            # fallback is _root(), and in a normal install that IS the Thomas
            # checkout -- so any turn arriving without a project, including one
            # whose JSON failed to parse and was treated as an empty body,
            # silently bound the product tree and returned 200. That is how a
            # worker's deliverable ends up written next to the code that wrote
            # it. Working on Thomas stays available; it has to be asked for.
            #
            # Only that specific case is redirected. When _root() is some other
            # repository it is a deliberate configuration and remains the
            # default, which is also what the route's callers rely on.
            fallback_root = _root()
            if _is_thomas_source(fallback_root):
                fallback_root = await asyncio.get_running_loop().run_in_executor(
                    None, forge_code_projects.default_scratch_project, _root()
                )
            project_root = forge_code_projects.validate_project_root(requested_root, fallback=fallback_root)
            settings = ForgeCodeSettings.from_payload(body if isinstance(body, dict) else {})
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
        forge_code_projects.bind_conversation(_root(), conv["id"], project_root, settings=report)
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
        response.headers["Content-Security-Policy"] = (
            "sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; "
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
