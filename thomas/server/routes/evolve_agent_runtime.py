"""Process, transcript, and fail-closed safety helpers for directed Evolve routes."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.agent.loop_tool_protocol import is_inspection_tool
from thomas.forge.anvil import forge_code_deliverables, forge_code_git, forge_code_store, run_report
from thomas.server.app_keys import APP_ENGINE_MANAGER, APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE

from .evolve_agent_activity import (
    acquire_code_activity_lease as _acquire_code_activity_lease,
)
from .evolve_agent_activity import (
    acquire_code_activity_lease_async,
)
from .evolve_agent_activity import (
    attach_code_activity_release as _attach_code_activity_release,
)
from .evolve_agent_activity import (
    release_code_activity_lease as _release_code_activity_lease,
)
from .evolve_agent_receipts import (
    _action_receipt,
    _delete_action_receipt,
    _read_receipts,
    _receipt_path,
    _save_action_receipt,
)

log = logging.getLogger(__name__)


def _confirmed_conversation_reply(transcript: str, *, require_final: bool = False) -> bool:
    """Return true for a structured turn that answered without changing files.

    Reading is not a failed edit. A request to inspect and explain something
    must read files to answer it, and disqualifying any tool use meant those
    runs were recorded as "no change made" with the answer buried underneath.

    This mirrors the rule in dispatch_agent_loop and dispatch_claude_cli on
    purpose: three separate places decide this same question, and if they
    disagree the failure does not go away, it just moves to whichever one the
    request happened to take. Relaxed only on positive evidence -- tool names
    were present and every one of them was read-only.

    ``require_final`` narrows the evidence to ``final`` frames alone. The
    stream translator emits ``final`` only for a non-error CLI ``result``
    message, so it is protocol-level proof the answer arrived -- which is what
    lets a reply outvote a nonzero exit code. Streamed ``say`` text is not
    that proof: a run that crashed mid-narration has ``say`` frames too.
    """

    saw_reply = False
    saw_tool = False
    saw_named_tool = False
    saw_mutating_tool = False
    for raw in str(transcript or "").splitlines():
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("fc") or "")
        if kind in {"tool", "tool_result"}:
            saw_tool = True
            # Only the tool event carries a name; tool_result does not.
            name = str(event.get("name") or "").strip()
            if name and name != "tool":
                saw_named_tool = True
                # The agent-loop translator stamps `access` ("read"/"write")
                # onto tool events, classifying shell.exec by its COMMAND
                # rather than its name. Trust the stamp when it is present:
                # without it, an explain-only run whose shell ran `dir` was
                # disqualified here and filed as a fabricated exit-1 failure
                # even after dispatch_agent_loop learned better. Name-based
                # classification stays as the fallback for older transcripts
                # and the claude-CLI path, which does not stamp.
                access = str(event.get("access") or "").strip()
                if access == "write":
                    saw_mutating_tool = True
                elif access != "read" and not is_inspection_tool(name):
                    saw_mutating_tool = True
        elif kind in {"final", "say"} and str(event.get("text") or "").strip():
            if kind == "final" or not require_final:
                saw_reply = True
    if saw_tool and not (saw_named_tool and not saw_mutating_tool):
        return False
    return saw_reply


async def _release_code_start_gate(
    app: web.Application,
    proc: Any,
    start_token: str,
    oauth_access_token: str,
    run_id: str,
    goal: str,
    release_state: dict[str, Any] | None = None,
) -> str:
    activity_token = ""
    try:
        activity_token = await acquire_code_activity_lease_async(app, run_id)
        await _release_start_gate(
            proc,
            start_token,
            oauth_access_token=oauth_access_token,
            goal=goal,
            release_state=release_state,
        )
        return activity_token
    except asyncio.CancelledError:
        if release_state is not None and release_state.get("payload_write_attempted"):
            release_state["activity_token"] = activity_token
        else:
            _release_code_activity_lease(app, activity_token)
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        if release_state is not None and release_state.get("payload_write_attempted"):
            release_state["activity_token"] = activity_token
        else:
            _release_code_activity_lease(app, activity_token)
        raise


async def _keep_code_run_active(app: web.Application, proc: Any, *, interval_s: float = 5.0) -> None:
    """Prevent idle engines from committing or rewriting an active Code run."""
    manager = app.get(APP_ENGINE_MANAGER)
    if manager is None:
        return
    while getattr(proc, "returncode", None) is None:
        manager.record_user_message()
        await asyncio.sleep(max(0.05, float(interval_s)))


def _code_action_hash(message: str, payload: dict[str, Any] | None) -> str:
    """Bind one approval to the exact requested action, project, and policy."""

    body = payload or {}
    action = {
        "message": str(message or "").strip(),
        "conversation_id": str(body.get("conversation_id") or "").strip(),
        "project_root": str(body.get("project_root") or "").strip(),
        "engine": str(body.get("engine") or "auto").strip().lower(),
        "model": str(body.get("model") or "auto").strip().lower(),
        "model_id": str(body.get("model_id") or "").strip().lower(),
        "reasoning_effort": str(body.get("reasoning_effort", body.get("effort")) or "medium").strip().lower(),
        "autonomy_level": str(body.get("autonomy_level") or "3").strip(),
        "file_access": str(body.get("file_access") or "project").strip().lower(),
        "memory": str(body.get("memory") if "memory" in body else True).strip().lower(),
        "guardrails": str(body.get("thomas_guardrails", body.get("guardrails")) or "guarded").strip().lower(),
        "token_economy": str(body.get("token_economy") or "balanced").strip().lower(),
    }
    encoded = json.dumps(action, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_repo_file(file: str) -> str:
    """Return one safe repository-relative POSIX path, or an empty string."""

    value = str(file or "").strip().replace("\\", "/")
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return ""
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def _conversation_changed_files(conversation: dict[str, Any] | None) -> set[str] | None:
    """Return only files attributed to agent turns in one conversation."""

    if conversation is None:
        return None
    files: set[str] = set()
    for turn in conversation.get("turns") or []:
        if turn.get("role") != "agent":
            continue
        for file in turn.get("changed_files") or []:
            normalized = _normalize_repo_file(str(file or ""))
            if normalized:
                files.add(normalized)
    return files


def _conversation_is_read_only(metadata: dict[str, Any] | None) -> bool:
    settings = (metadata or {}).get("settings") or {}
    effective = settings.get("effective") or {}
    requested = settings.get("requested") or {}
    return "read_only" in {
        str(effective.get("file_access") or "").strip().lower(),
        str(requested.get("file_access") or "").strip().lower(),
    }


def _revert_action_hash(root: Path, conversation_id: str, file: str) -> str:
    """Bind approval to the exact repo, conversation, path, and current diff."""

    target = root.resolve() / file
    if target.is_file():
        content_hash = hashlib.sha256()
        try:
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content_hash.update(chunk)
            content_state = content_hash.hexdigest()
        except OSError:
            content_state = "unreadable"
    else:
        content_state = "missing"
    payload = {
        "action": "revert_file",
        "conversation_id": conversation_id,
        "project_root": str(root.resolve()),
        "file": file,
        "untracked": forge_code_git.is_untracked(root, file),
        "diff": forge_code_git.unified_diff(root, file),
        "content": content_state,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authorize_conversation_revert(
    *,
    root: Path,
    conversation_id: str,
    file: str,
    conversation: dict[str, Any],
    metadata: dict[str, Any] | None,
    approvals: dict[str, dict[str, Any]],
    approval_id: str,
) -> tuple[str, dict[str, Any] | None, int]:
    """Validate policy and atomically claim an exact one-time approval."""

    normalized = _normalize_repo_file(file)
    if not normalized:
        return "", {"ok": False, "error": "unsafe file path", "code": "invalid_file_path"}, 400
    if _conversation_is_read_only(metadata):
        return (
            normalized,
            {
                "ok": False,
                "error": "read-only Code conversations cannot revert files",
                "code": "read_only_mode",
            },
            403,
        )
    owned = _conversation_changed_files(conversation) or set()
    if normalized not in owned:
        return (
            normalized,
            {
                "ok": False,
                "error": "file was not changed by this Code conversation",
                "code": "file_not_owned_by_conversation",
            },
            403,
        )
    if not forge_code_git.file_is_dirty(root, normalized):
        return (
            normalized,
            {
                "ok": False,
                "error": "file is no longer changed",
                "code": "file_not_dirty",
            },
            409,
        )

    action_hash = _revert_action_hash(root, conversation_id, normalized)
    approval = approvals.get(approval_id) if approval_id else None
    valid = bool(
        isinstance(approval, dict)
        and approval.get("state") == "approved"
        and approval.get("action_hash") == action_hash
        and float(approval.get("expires_at") or 0) >= time.time()
    )
    if valid:
        approval["state"] = "executing"
        approval["executing_at"] = time.time()
        return normalized, None, 0

    new_id = f"approval-{secrets.token_urlsafe(10)}"
    approvals[new_id] = {
        "id": new_id,
        "state": "pending",
        "action_hash": action_hash,
        "risk": "discard conversation-owned file changes",
        "summary": f"Revert {normalized}? This permanently discards its current changes.",
        "expires_at": time.time() + 600,
    }
    public = {key: value for key, value in approvals[new_id].items() if key != "action_hash"}
    return (
        normalized,
        {
            "ok": False,
            "error": "explicit approval is required to discard file changes",
            "code": "approval_required",
            "approval": public,
        },
        409,
    )


def _finish_approval_execution(approval: dict[str, Any] | None, *, succeeded: bool) -> None:
    """Consume a claimed approval only after its protected action starts or succeeds."""
    if not isinstance(approval, dict) or approval.get("state") != "executing":
        return
    approval.pop("executing_at", None)
    approval["state"] = "consumed" if succeeded else "approved"
    if succeeded:
        approval["consumed_at"] = time.time()


def _request_id(payload: dict[str, Any] | None, *, fallback: str = "") -> str:
    supplied = str((payload or {}).get("request_id") or fallback).strip()
    return supplied[:160] if supplied else f"request-{secrets.token_urlsafe(18)}"


def _agent_launch(
    settings: Any,
    project_root: Path,
    conversation_id: str,
    *,
    package_root: Path,
) -> tuple[list[str], dict[str, str]]:
    env = settings.child_environment(dict(os.environ))
    env["PYTHONPATH"] = os.pathsep.join(part for part in (str(package_root), env.get("PYTHONPATH", "")) if part)
    env.update(
        {
            "THOMAS_CLAUDE_BRIDGE_ENABLED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    command = [
        "-m",
        "thomas.forge.anvil.forge_code_runner",
        "--project-root",
        str(project_root),
        "--conversation-id",
        conversation_id,
        "--engine",
        settings.engine,
        "--family",
        settings.family,
        "--model",
        settings.dispatch_model.split(":", 1)[-1],
        "--profile",
        settings.gpt_profile or "openai_codex",
        "--autonomy",
        str(settings.autonomy_level),
        "--file-access",
        settings.file_access,
        "--memory",
        "on" if settings.memory else "off",
        "--guardrails",
        settings.guardrails,
        "--token-economy",
        settings.token_economy,
    ]
    return command, env


async def _release_start_gate(
    proc: Any,
    token: str,
    *,
    oauth_access_token: str = "",
    goal: str = "",
    release_state: dict[str, bool] | None = None,
) -> None:
    """Release a recorded run and hand its prompt/credential over on the one-use pipe."""

    writer = getattr(proc, "stdin", None)
    if writer is None:
        raise RuntimeError("Code runner start gate is unavailable")
    payload = json.dumps(
        {"gate_token": token, "oauth_access_token": str(oauth_access_token or ""), "goal": str(goal)},
        ensure_ascii=True,
        separators=(",", ":"),
    )
    writer.write(f"{payload}\n".encode())
    if release_state is not None:
        release_state["payload_write_attempted"] = True
    await writer.drain()
    writer.close()


def _sse_frame(payload: dict[str, Any], run_id: str, sequence: int) -> bytes:
    event_id = f"{run_id}:{sequence}"
    data = {**payload, "run_id": run_id, "event_id": event_id, "event_seq": sequence}
    return f"id: {event_id}\ndata: {json.dumps(data)}\n\n".encode()


def _recording_task(recording: Any) -> Any:
    return recording.get("task") if isinstance(recording, dict) else recording


def _recording_active(recording: Any) -> bool:
    task = _recording_task(recording)
    return bool(task is not None and not task.done())


def _run_replay_available(receipt: dict[str, Any], session: Any, running: bool, recording: Any) -> bool:
    state = receipt.get("state")
    if state in {"completed", "persistence_failed"}:
        return True
    if state not in {"launching", "running"}:
        return False
    response = receipt.get("response") if isinstance(receipt.get("response"), dict) else {}
    active_run = str((session or {}).get("run_id") or "")
    return active_run == str(response.get("run_id") or "") and (running or _recording_active(recording))


def _recording_status(recording: Any) -> dict[str, Any]:
    task = _recording_task(recording)
    if task is None:
        return {"recording": False, "persistence_confirmed": False, "persistence_state": "missing"}
    if not task.done():
        return {"recording": True, "persistence_confirmed": False, "persistence_state": "recording"}
    if task.cancelled():
        return {"recording": False, "persistence_confirmed": False, "persistence_state": "cancelled"}
    try:
        result = task.result()
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "recording": False,
            "persistence_confirmed": False,
            "persistence_state": "failed",
            "persistence_error": str(exc) or type(exc).__name__,
        }
    if not isinstance(result, dict) or result.get("persistence_confirmed") is not True:
        error = result.get("persistence_error") if isinstance(result, dict) else "invalid recorder result"
        return {
            **(result if isinstance(result, dict) else {}),
            "recording": False,
            "persistence_confirmed": False,
            "persistence_state": "failed",
            "persistence_error": error or "agent turn was not persisted",
        }
    return {**result, "recording": False, "persistence_state": "persisted"}


async def _await_recording(recording: Any) -> dict[str, Any]:
    task = _recording_task(recording)
    if task is None:
        return _recording_status(None)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        return {
            "recording": False,
            "persistence_confirmed": False,
            "persistence_state": "cancelled",
            "persistence_error": "recorder wait was cancelled",
        }
    return _recording_status(recording)


def _default_repo_root() -> Path:
    # thomas/server/routes/evolve_agent_routes.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _agent_dir(root: Path) -> Path:
    d = root / ".thomas" / "evolve" / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _transcript_path(root: Path, run_id: str = "") -> Path:
    suffix = f"-{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:16]}" if run_id else ""
    return _agent_dir(root) / f"transcript{suffix}.txt"


async def _drain(proc: Any, transcript: Path) -> bool:
    """Stream the agent's combined stdout into the transcript file, line by line,
    flushing so the SSE tail sees output as it happens."""
    transcript_confirmed = True
    try:
        with open(transcript, "ab") as fh:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                fh.write(line)
                fh.flush()
    except (AssertionError, OSError, RuntimeError):
        log.warning("evolve agent: transcript drain failed", exc_info=True)
        transcript_confirmed = False
    try:
        await proc.wait()
    except (ChildProcessError, OSError, RuntimeError):
        log.warning("evolve agent: process exit could not be confirmed", exc_info=True)
        return False
    return transcript_confirmed and proc.returncode is not None


def _agent_turn_is_in_store(root: Path, cid: str, turn: dict[str, Any]) -> bool:
    """Confirm from the STORE that one recorded agent turn is really on disk.

    This is a read, not a claim: the conversation file is re-parsed and the
    turn is matched on the identity its writer stamped onto it -- the
    microsecond timestamp plus this run's id. Matching one turn rather than
    comparing whole conversations is deliberate: a legitimate concurrent write
    (a rename, a later turn) must not read as a lost write, or every good run
    starts reporting failure, which is worse than the bug this closes.
    """

    stamp = str(turn.get("ts") or "")
    if not stamp:
        return False
    run_id = str(turn.get("run_id") or "")
    saved = forge_code_store.load_conversation(root, cid)
    if not isinstance(saved, dict):
        return False
    return any(
        isinstance(candidate, dict)
        and candidate.get("role") == "agent"
        and str(candidate.get("ts") or "") == stamp
        and str(candidate.get("run_id") or "") == run_id
        for candidate in saved.get("turns") or []
    )


# The failures a run-store write can realistically produce. Named rather than a bare
# `except Exception`, so a bug in the recorder still surfaces while a storage hiccup
# never breaks a run. Mirrors chat_v2_run_store's set.
_RUN_STORE_ERRORS = (AttributeError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError)


def _finalize_code_run(app: web.Application, run_id: str, *, ok: bool, reason: str) -> None:
    """Close the run-store row for a finished Code run.

    Without this a row opened at launch is swept as stale after ten idle minutes and
    written as `ok = 0` -- so a run that built a working page is filed as a failure.
    Recording must never be the reason a run appears to have gone wrong.
    """

    if not run_id:
        return
    module = app.get(APP_RUN_STORE_MODULE)
    if not bool(app.get(APP_RUN_STORE_ENABLED, False)) or module is None:
        return
    try:
        module.finalize_run(
            run_id,
            bool(ok),
            None if ok else (reason or "run did not complete successfully"),
            None,
            None,
            None,
        )
    except _RUN_STORE_ERRORS as exc:
        log.warning("Code run not finalized (run store write failed): %s", exc)


async def _drain_and_record(
    proc: Any,
    transcript: Path,
    root: Path,
    cid: str,
    model: str,
    snap: dict[str, str],
    app: web.Application,
    *,
    catalog_root: Path | None = None,
    request_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Drain the live transcript, then record the run outcome onto the conversation.

    The outcome is computed from *evidence* at the moment the build finishes,
    and the exit code is the weakest evidence there is: the Claude CLI exits 1
    even when the files landed and work, which is how successful runs were
    being filed as failures. Git truth outranks it -- changed files mean the
    run did something, whatever the code says (the code stays visible in the
    reason). A confirmed ``final`` reply outranks it too. A clean exit that
    touched nothing is a no-op; a dirty exit with nothing to show for it is a
    failure; an interruption the person asked for is ``stopped``, in those
    words. Recording is wrapped so a bad store/git call can never crash the
    server or lose the transcript.
    """
    activity_task = asyncio.create_task(_keep_code_run_active(app, proc))
    try:
        run_capture_confirmed = await _drain(proc, transcript)
    finally:
        activity_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await activity_task
    result: dict[str, Any]
    try:
        rc = proc.returncode
        text = transcript.read_text(encoding="utf-8", errors="replace")
        changed = forge_code_git.project_delta_since(root, snap)
        # "stop" | "steer" | "" -- stamped onto the process by the stop endpoint
        # and the steer handler before they kill it. An interruption someone
        # asked for used to be recorded as `failed / exited 1`, which reads as
        # the run's error when it was the person's decision.
        interrupted = str(getattr(proc, "thomas_stop_requested", "") or "")
        conversation_reply = (
            run_capture_confirmed
            and not changed
            and not interrupted
            and _confirmed_conversation_reply(text, require_final=rc != 0)
        )
        noop = run_capture_confirmed and rc == 0 and not changed and not conversation_reply and not interrupted
        ok = run_capture_confirmed and rc is not None and not interrupted and (bool(changed) or conversation_reply)
        if not run_capture_confirmed or rc is None:
            reason = "process output or exit could not be confirmed"
            outcome = "failed"
        elif interrupted:
            outcome = "stopped"
            reason = "stopped for your steering update" if interrupted == "steer" else "stopped by you"
            if changed:
                # The interrupted work is still named, so Keep/Revert has a
                # subject rather than a mystery.
                reason += f" — {len(changed)} file(s) had already changed"
        elif conversation_reply:
            reason = "Thomas replied without changing files"
            outcome = "conversation"
        elif noop:
            reason = "no change made"
            outcome = "noop"
        elif changed:
            reason = f"{len(changed)} file(s) changed"
            if rc:
                # The exit code stays on the record -- visible, no longer a
                # verdict. The Claude CLI exits 1 on runs whose files landed
                # and work, and requiring rc == 0 here filed those successes
                # as failures.
                reason += f" (build process exited {rc})"
            outcome = "completed"
        else:
            reason = f"exited {rc}"
            outcome = "failed"
        # CAP-141: structured post-run report, built from the run's REAL recorded
        # data (forge events + git truth). The goal is the conversation's latest
        # user message — the completion criteria this run was given.
        prior_turns = (forge_code_store.load_conversation(root, cid) or {}).get("turns") or []
        goal_text = next((str(t.get("text") or "") for t in reversed(prior_turns) if t.get("role") == "user"), "")
        report = run_report.build_run_report(
            goal=goal_text,
            transcript=text,
            changed_files=changed,
            returncode=rc,
            ok=ok,
            outcome=outcome,
            reason=reason,
            # Projects are shared, so a build can silently replace another
            # task's work. This does not prevent the write; it makes it visible.
            foreign_writes=forge_code_store.files_written_by_another_task(root, cid, changed),
        )
        persisted = forge_code_store.append_agent_turn(
            root,
            cid,
            model=model,
            transcript=text,
            changed_files=changed,
            returncode=rc,
            ok=ok,
            noop=noop,
            reason=reason,
            run_id=run_id,
            report=report,
            outcome=outcome,
        )
        if persisted is None:
            raise RuntimeError("agent turn store returned no persisted conversation")
        # The confirmation is taken HERE, from a store read, and as close to the
        # write as it can be taken. `append_agent_turn` hands back the
        # conversation it wrote; its last turn is the one this run added, and
        # `_agent_turn_is_in_store` goes back to disk to find it again.
        recorded_turn = (persisted.get("turns") or [{}])[-1]
        persistence_confirmed = _agent_turn_is_in_store(root, cid, recorded_turn)
        # Close the run-store row opened at launch, with the outcome computed above
        # from git truth. This is the other half of _record_code_run_start, and
        # leaving it out was actively harmful rather than merely incomplete: a row
        # with no end time is swept by reconcile_stale_runs() after ten idle minutes,
        # and mark_run_dead() writes `ok = 0`. So every SUCCESSFUL Code run was being
        # recorded as a failure ten minutes later. Verified on a real run that built
        # a working tip calculator and landed in the ledger as ok=0.
        #
        # Placed here rather than at the SSE "done" frame because the browser can
        # disconnect; this path runs whether or not anyone is watching.
        _finalize_code_run(app, run_id, ok=bool(ok), reason=str(reason or ""))
        # Close the loop into "My Stuff": a SUCCESSFUL run that produced a coherent
        # deliverable (the detector decides -- a built page/doc/image/data file, not
        # a code-only edit) becomes a durable, openable entry pointing back at this
        # conversation. A code-only or failed run registers nothing. The title is the
        # conversation's own (model-derived) name -- the build's purpose.
        if ok:
            conv = forge_code_store.load_conversation(root, cid) or {}
            forge_code_deliverables.register_from_run(
                root,
                conversation_id=cid,
                changed_files=changed,
                title=str(conv.get("title") or ""),
                model=model,
            )
        # This flag used to be set True because execution REACHED this line,
        # while every other branch returned it False with a persistence_state.
        # That made the confirmation CIRCULAR: `_await_recording` awaits the
        # recorder and then calls `_recording_status`, which decides by reading
        # `persistence_confirmed` off this very dict. The status check asked the
        # result whether it saved, and on this path the result always said yes,
        # so no amount of tightening `_recording_status` or waiting longer could
        # ever catch a lost write. The truth now enters above, from a store read.
        #
        # A correction to the note that used to stand here, because it named
        # evidence that does not hold. It cited
        # tests/test_evolve_agent_persistence.py:277 -- persistence_confirmed
        # True while list_conversations() returned [] -- as proof the flag can be
        # true against an empty store. Measured: it is not. That request sends no
        # project_root, so the run is recorded into the scratch project
        # (~/.thomas/code_scratch), while the assertion reads the CATALOG root.
        # The turn was written; the test looked in the wrong place. So no case of
        # this flag lying has actually been demonstrated -- not under
        # cancellation, not on an ordinary run. The self-certifying assignment
        # was still wrong, and is now gone, but it is a closed hole rather than a
        # reproduced failure, and the next reader should not go hunting for a
        # data-loss bug that this evidence never showed.
        result = {
            "persistence_confirmed": persistence_confirmed,
            "returncode": rc,
            "changed_files": changed,
            "artifacts": forge_code_store.detect_artifacts(changed),
            "ok": ok,
            "noop": noop,
            "outcome": outcome,
            "report": report,
        }
        if not persistence_confirmed:
            # A run whose turn cannot be found in the store did not finish,
            # whatever the process exit code says. Report it exactly as the
            # store-failure branch below does, so status, stop and the SSE done
            # frame all agree.
            result.update(
                {
                    "persistence_error": "recorded agent turn was not found in the store",
                    "ok": False,
                    "noop": False,
                    "outcome": "persistence_failed",
                }
            )
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning("evolve agent: recording run outcome failed", exc_info=True)
        result = {
            "persistence_confirmed": False,
            "persistence_error": str(exc) or type(exc).__name__,
            "returncode": getattr(proc, "returncode", None),
            "changed_files": [],
            "artifacts": [],
            "ok": False,
            "noop": False,
            "outcome": "persistence_failed",
        }
    if request_id and catalog_root is not None:
        try:
            receipt = _action_receipt(catalog_root, "run", request_id) or {}
            receipt.update({"state": "completed" if result["persistence_confirmed"] else "persistence_failed"})
            receipt["persistence"] = result
            _save_action_receipt(catalog_root, "run", request_id, receipt)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning("evolve agent: run receipt update failed", exc_info=True)
            error = str(exc) or type(exc).__name__
            result.update(
                {
                    "persistence_confirmed": False,
                    "persistence_error": f"run receipt update failed: {error}",
                    "receipt_error": error,
                    "ok": False,
                    "noop": False,
                    "outcome": "persistence_failed",
                }
            )
    return result


def _kill_tree(proc: Any) -> None:
    """Kill the whole build process tree -- the dispatch python AND any
    ``claude -p`` grandchild -- not just the immediate child.

    The claude brain spawns a headless ``claude -p`` child; the GPT brain runs
    in-process (no grandchild). Stopping only ``proc`` would orphan a headless CLI
    it spawned, leaving the real build still running. Prefer psutil (cross-platform
    recursive kill);
    fall back to ``taskkill /T`` on Windows and ``terminate()`` elsewhere. Every
    path is defensive: a process that already exited must not raise.
    """
    try:
        import psutil
    except ImportError:
        psutil = None

    if psutil is not None:
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.Error, OSError):
                    child.kill()
            with contextlib.suppress(psutil.Error, OSError):
                parent.kill()
            return
        except (psutil.Error, OSError, ProcessLookupError, RuntimeError):
            pass

    with contextlib.suppress(OSError, ProcessLookupError, RuntimeError):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            proc.terminate()


def _mark_stop_requested(proc: Any, kind: str = "stop") -> None:
    """Stamp WHY a process is about to be killed, before it is killed.

    The recorder reads this stamp to file "stopped by you" (or "stopped for
    your steering update") instead of "failed / exited 1" -- an interruption
    someone asked for is not an error the run committed. Stamped by the STOP
    and STEER routes only, never inside ``_terminate_process``: that helper is
    also how an aborted LAUNCH cleans up after itself, and a launch nobody
    managed to start is not a run somebody chose to stop. A stamp already in
    place is kept, so steer's mark survives the stop machinery running after it.
    """
    with contextlib.suppress(AttributeError, TypeError):
        proc.thomas_stop_requested = str(getattr(proc, "thomas_stop_requested", "") or "") or kind


def _mark_steer_requested(proc: Any) -> None:
    _mark_stop_requested(proc, "steer")


async def _terminate_process(proc: Any, *, timeout_s: float = 5.0) -> dict[str, Any]:
    """Request termination and return only evidence the process actually supplied.

    A kill request is not a stop receipt. The process must expose a terminal
    return code before ``stopped`` can become true; otherwise callers receive a
    truthful ``termination_pending`` receipt and may keep observing the run.
    """

    if proc is None or getattr(proc, "returncode", None) is not None:
        return {
            "ok": False,
            "stopped": False,
            "termination_confirmed": False,
            "state": "not_running",
            "code": "no_active_run",
            "returncode": getattr(proc, "returncode", None) if proc is not None else None,
        }

    await asyncio.to_thread(_kill_tree, proc)
    wait = getattr(proc, "wait", None)
    if callable(wait):
        try:
            await asyncio.wait_for(wait(), timeout=max(0.01, float(timeout_s)))
        except TimeoutError:
            pass
        except (ChildProcessError, OSError, RuntimeError):
            log.warning("evolve agent: process wait failed after termination request", exc_info=True)

    returncode = getattr(proc, "returncode", None)
    if returncode is not None:
        return {
            "ok": True,
            "stopped": True,
            "termination_confirmed": True,
            "state": "terminated",
            "code": "terminated",
            "returncode": int(returncode),
        }
    return {
        "ok": False,
        "stopped": False,
        "termination_confirmed": False,
        "state": "termination_pending",
        "code": "termination_pending",
        "returncode": None,
    }
