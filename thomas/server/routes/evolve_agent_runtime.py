"""Process, transcript, and fail-closed safety helpers for directed Evolve routes."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import (
    forge_code_deliverables,
    forge_code_git,
    forge_code_projects,
    forge_code_store,
    run_report,
)
from thomas.server.app_keys import APP_ENGINE_MANAGER, APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE
from thomas.server.routes.evolve_verdict import (
    _terminal_engine_verdict,
    _unstructured_engine_error,
)

from . import evolve_agent_revert as _evolve_agent_revert
from . import evolve_agent_run_status as _evolve_agent_run_status
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

# Split out (evolve_agent_revert.py, evolve_agent_run_status.py; landing this
# session, worker.py precedent) past the monolith guard's 800-line soft limit --
# see their docstrings. Re-exported under original names so no caller changed.
_normalize_repo_file = _evolve_agent_revert._normalize_repo_file
_conversation_changed_files = _evolve_agent_revert._conversation_changed_files
_conversation_is_read_only = _evolve_agent_revert._conversation_is_read_only
_revert_action_hash = _evolve_agent_revert._revert_action_hash
_authorize_conversation_revert = _evolve_agent_revert._authorize_conversation_revert
_finish_approval_execution = _evolve_agent_revert._finish_approval_execution
_confirmed_conversation_reply = _evolve_agent_run_status._confirmed_conversation_reply
_recording_task = _evolve_agent_run_status._recording_task
_recording_active = _evolve_agent_run_status._recording_active
_run_replay_available = _evolve_agent_run_status._run_replay_available
_recording_status = _evolve_agent_run_status._recording_status
_await_recording = _evolve_agent_run_status._await_recording


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

    The outcome is computed from *evidence* at the moment the build finishes.
    A marked successful engine verdict can outrank the Claude CLI's unreliable
    exit 1 when files landed or a confirmed final reply arrived. A nonzero exit
    without that verdict fails closed, even when partial files exist. A clean
    exit that
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
        terminal_ok, terminal_cause = _terminal_engine_verdict(text)
        unstructured_cause = _unstructured_engine_error(text)
        # A nonzero process exit needs positive terminal success evidence.
        # Partial files are useful recovery material, not proof that the run
        # reached a successful verdict.
        missing_terminal_failure = rc not in (None, 0) and terminal_ok is not True
        engine_failed = terminal_ok is False or missing_terminal_failure
        crash_cause = terminal_cause or unstructured_cause
        if missing_terminal_failure and not crash_cause:
            crash_cause = f"build process exited {rc} without a terminal engine verdict"
        noop = run_capture_confirmed and rc == 0 and not changed and not conversation_reply and not interrupted
        ok = (
            run_capture_confirmed
            and rc is not None
            and not interrupted
            and not engine_failed
            and (bool(changed) or conversation_reply)
        )
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
        elif engine_failed:
            # The engine itself declared the run dead. Files that landed first
            # are named (they are real work worth keeping), but a crash is
            # never "completed" — that filing is how a crashed one-pass build
            # got presented as a finished deliverable.
            outcome = "failed"
            reason = f"the run crashed before finishing — {crash_cause}"
            if changed:
                reason += f"; {len(changed)} file(s) had changed by then"
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
            if changed:
                # A finished run in a TASK-BORN project becomes a real commit.
                # Before this, such a project's only commit was the empty birth
                # baseline, so when a later run overwrote a finished deliverable,
                # Keep/Revert could only offer the empty tree back (P1, measured
                # twice). The helper refuses user-picked projects (their history
                # is theirs; the Checkpoint button remains their path) and never
                # raises -- and the guard stands anyway, because preserving
                # history must never rewrite a successful outcome as a failure.
                try:
                    forge_code_git.commit_run_snapshot(root, run_id=run_id, reason=reason)
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    # Named, not broad: the helper already degrades internally;
                    # this is the last line of defense and it must never
                    # rewrite a successful outcome as a failure.
                    log.warning("evolve agent: run snapshot commit failed: %s", exc, exc_info=True)
        if outcome == "conversation":
            # A question asked with nothing selected minted this folder moments
            # ago and left it holding nothing but .git and .thomas internals
            # (measured live 3x, 2026-08-05: siblings "...tell me what",
            # "...tell me what 2", "...tell me what 3"). The transcript lives
            # INSIDE the folder, so it is never deleted -- instead it is marked
            # free, and the next same-named question reuses it rather than
            # minting the next sibling. Best-effort and never a gate: the
            # helper refuses user-picked folders and folders with any real
            # files, and an unmarked folder only means the next question mints
            # its own, exactly as before.
            forge_code_projects.mark_workspace_reusable(root)
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
