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
import sys
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core import project_root
from thomas.core.claude_alias_ids import remember_engine_model
from thomas.core.event_loop_offload import off_loop
from thomas.forge.anvil import (
    forge_code_deliverables,
    forge_code_git,
    forge_code_projects,
    forge_code_store,
    run_report,
)
from thomas.forge.anvil.build_model_receipt import engine_model_from_transcript, started_model_in_transcript
from thomas.forge.anvil.run_files import agent_dir as _agent_dir
from thomas.forge.anvil.run_files import transcript_path as _transcript_path
from thomas.server.app_keys import APP_ENGINE_MANAGER, APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE
from thomas.server.praxis.launch import recovery_start_allowed
from thomas.server.routes.evolve_verdict import (
    _terminal_engine_verdict,
    _unstructured_engine_error,
)

from . import evolve_agent_revert as _evolve_agent_revert
from . import evolve_agent_run_status as _evolve_agent_run_status
from .evolve_agent_activity import (
    acquire_code_activity_lease as _acquire_code_activity_lease,
)
from .evolve_agent_activity import acquire_code_activity_lease_async
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
        if not recovery_start_allowed(consume=False):
            raise RuntimeError("Build recovery admission changed before the start gate opened")
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
        "build_roles": body.get("build_roles"),
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
    env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), env.get("PATH", "")))
    env["PYTHONPATH"] = os.pathsep.join(part for part in (str(package_root), env.get("PYTHONPATH", "")) if part)
    # `python -m` puts the working folder (the project) ahead of PYTHONPATH, so in
    # a project that is a copy of Thomas the copy's `thomas/` package won and the
    # runner ran the code it was editing. PYTHONSAFEPATH keeps the working folder
    # off sys.path for the runner only; the runner removes it again at startup so
    # the checks it launches still import the project's own code.
    env["PYTHONSAFEPATH"] = "1"
    # One per server process: a newly booted runner must not inherit a stale
    # drain marker left by the old server.
    from thomas.server.landed_code_reload import drain_signal_path

    env["THOMAS_CODE_RELOAD_DRAIN_SIGNAL"] = str(drain_signal_path())
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
        "--agent",
        settings.agent,
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
        {
            "gate_token": token,
            "oauth_access_token": str(oauth_access_token or ""),
            "goal": str(goal),
            "self_edit": {
                key: value
                for key, value in (getattr(proc, "thomas_self_edit", None) or {}).items()
                if key in {"candidate_root", "source_root"}
            },
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    if not recovery_start_allowed():
        raise RuntimeError("Build recovery admission changed before the start gate opened")
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
    return project_root.code_checkout()


_DRAIN_CHUNK_BYTES = 65536


async def _drain(proc: Any, transcript: Path) -> bool:
    """Stream the agent's combined stdout into the transcript file, flushing so
    the SSE tail sees output as it happens.

    Reads chunks, not lines. ``readline()`` raises once a single line passes the
    stream's 64 KiB limit (a long reasoning summary or tool result), and when
    that killed this reader nobody drained the pipe any more: the runner blocked
    on its next write and the Build tab showed "Working" forever. The SSE tail
    reassembles lines itself (``IncrementalLineDecoder``), so partial chunks are
    safe here."""
    transcript_confirmed = True
    try:
        with open(transcript, "ab") as fh:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(_DRAIN_CHUNK_BYTES)
                if not chunk:
                    break
                fh.write(chunk)
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
    """Drain a run, end caged project processes, and record its outcome."""
    activity_task = asyncio.create_task(_keep_code_run_active(app, proc))
    try:
        run_capture_confirmed = await _drain(proc, transcript)
    finally:
        activity_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await activity_task
        from thomas.tools.cage_shell import end_project_processes

        try:
            green = any(
                p.parent.name.lower() == "work" and p.parent.parent.name.lower() == "green"
                for p in (root, *root.parents)
            )
            process_cleanup = (
                await asyncio.to_thread(end_project_processes, root) if green else end_project_processes(root)
            )
        except (OSError, RuntimeError, ValueError) as exc:
            process_cleanup = f"cleanup unavailable: {exc}"
        log.info("Build project process cleanup: %s", process_cleanup)
    result: dict[str, Any]
    try:
        rc = proc.returncode
        text = await off_loop("code_run.transcript", transcript.read_text, encoding="utf-8", errors="replace")
        self_edit_record = getattr(proc, "thomas_self_edit", None)
        if self_edit_record:
            from thomas.forge.anvil.forge_code_self_edit import candidate_delta_since

            from .evolve_agent_self_edit_runs import candidate_for, finish_run

            candidate = candidate_for(self_edit_record)
            # Hashing a whole private copy of Thomas: measured 9.5-10.9 s for
            # 8,456 files and 11+ s for 9,524, once per self-edit run.
            changed = await off_loop(
                "self_edit.candidate_delta", candidate_delta_since, candidate.candidate_root, candidate.baseline
            )
        else:
            changed = await off_loop("code_run.project_delta", forge_code_git.project_delta_since, root, snap)
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
        yielded_for_reload = False
        runner_finished = False
        for line in text.splitlines():
            if line.lstrip().startswith("{"):
                with contextlib.suppress(json.JSONDecodeError):
                    event = json.loads(line)
                    if (
                        isinstance(event, dict)
                        and event.get("terminal") is True
                        and event.get("fc") in {"meta", "error"}
                    ):
                        runner_finished = True
                        yielded_for_reload = bool(event.get("yielded_for_reload")) and rc == 75
        unstructured_cause = _unstructured_engine_error(text)
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
        elif yielded_for_reload:
            outcome = "reload_yielded"
            reason = "Build yielded at a safe boundary for landed-code reload"
            ok = False
            noop = False
        elif interrupted:
            outcome = "stopped"
            reason = "stopped for your steering update" if interrupted == "steer" else "stopped by you"
            if changed:
                # The interrupted work is still named, so Keep/Revert has a
                # subject rather than a mystery.
                reason += f" — {len(changed)} file(s) had already changed"
        elif engine_failed:
            outcome = "failed"
            reason = (
                f"the run completed but its engine reported failure — {crash_cause}"
                if runner_finished and run_capture_confirmed
                else f"the run crashed before finishing — {crash_cause}"
            )
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
        cleanup_failed = process_cleanup.startswith("cleanup unavailable:") or (
            "processes left: [" in process_cleanup and not process_cleanup.endswith("[]")
        )
        if cleanup_failed:
            reason = f"{reason}; {process_cleanup}" if reason else process_cleanup
            ok = False
            noop = False
            if outcome != "stopped":
                outcome = "failed"
        # Build the post-run report from recorded events and the latest user goal.
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
            foreign_writes=forge_code_store.files_written_by_another_task(root, cid, changed),
        )
        from thomas.server.praxis.build_verifier import verify_build_checks

        report["verifier_receipts"] = verify_build_checks(
            root,
            acceptance=getattr(proc, "thomas_acceptance", []),
            changed_files=changed,
        )
        report["process_cleanup"] = process_cleanup
        covered = {
            name
            for receipt in report["verifier_receipts"]
            if receipt["status"] == "pass"
            for name in receipt["covered_files"]
        }
        if changed and set(changed) <= covered:
            report["open_risks"] = [
                risk for risk in report["open_risks"] if risk.get("risk") != "changed files were never validated"
            ]
        if self_edit_record:
            report["self_edit"] = await asyncio.to_thread(
                finish_run, catalog_root or root, self_edit_record, successful=bool(ok)
            )
            ok = report["self_edit"]["status"] == "ready"
            reason = report["self_edit"]["reason"]
            outcome = "completed" if ok else "failed"
            if cleanup_failed:
                reason = f"{reason}; {process_cleanup}"
                ok = False
                outcome = "failed"
            # Candidate edits are reviewed/applied separately, never ordinary Keep/Revert.
            report["changed_files"] = []
            changed = []
        # Read the engine's model from the transcript, not the requested alias.
        model_used = engine_model_from_transcript(text)
        # Taught HERE as well as in the runner: the runner is another process
        # (and a self-edit run has its own data folder), so only this call
        # updates the menu the running server serves without a restart. Taught
        # from the model the run STARTED, never a helper modelUsage also names.
        remember_engine_model(model, started_model_in_transcript(text))
        persisted = forge_code_store.append_agent_turn(
            root,
            cid,
            model=model,
            agent=str(getattr(proc, "thomas_agent", "") or ""),
            model_used=model_used,
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
        if ok and not self_edit_record:
            conv = forge_code_store.load_conversation(root, cid) or {}
            forge_code_deliverables.register_from_run(
                root,
                conversation_id=cid,
                changed_files=changed,
                title=str(conv.get("title") or ""),
                model=model,
            )
            if changed:
                # Save finished task-born work so Keep/Revert has a real baseline.
                # The helper refuses to commit user-picked projects.
                try:
                    # git add plus git commit over the run's whole output: the one
                    # place in run recording that WRITES, and the slowest.
                    await off_loop(
                        "code_run.snapshot_commit",
                        forge_code_git.commit_run_snapshot,
                        root,
                        run_id=run_id,
                        reason=reason,
                    )
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
        # Confirmation comes from the store read above, not from reaching this line.
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
            receipt = await asyncio.to_thread(_action_receipt, catalog_root, "run", request_id) or {}
            receipt.update(
                {
                    "state": "reload_yielded"
                    if result["persistence_confirmed"] and result.get("outcome") == "reload_yielded"
                    else "completed"
                    if result["persistence_confirmed"]
                    else "persistence_failed"
                }
            )
            receipt["persistence"] = result
            await asyncio.to_thread(_save_action_receipt, catalog_root, "run", request_id, receipt)
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
    result["process_cleanup"] = process_cleanup
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
