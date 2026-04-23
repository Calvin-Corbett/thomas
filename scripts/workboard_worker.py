#!/usr/bin/env python3
"""Persistent worker loop for workboard-dispatched agent lanes.

This runner keeps one agent alias online, waits for tasks assigned to that
agent in WORKBOARD.md, executes task command pipelines, reports completion or
blockers, and optionally releases the claim so task manager can dispatch the
next lane.
"""

from __future__ import annotations

import argparse as _argparse
import importlib
import subprocess as _subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

argparse = _argparse
subprocess = _subprocess

try:
    from scripts.workboard_paths import (
        command_catalog_path_for,
        default_workboard_path,
        worker_log_dir_for,
    )
except ImportError:  # pragma: no cover
    from workboard_paths import command_catalog_path_for, default_workboard_path, worker_log_dir_for  # type: ignore

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import workboard_claim, workboard_message, workboard_task_manager
    from scripts import workboard_worker_services as _worker_services
    from scripts import workboard_worker_types as _worker_types
    from thomas.core import task_bot_runtime
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_claim  # type: ignore
    import workboard_message  # type: ignore
    import workboard_task_manager  # type: ignore
    import workboard_worker_services as _worker_services  # type: ignore
    import workboard_worker_types as _worker_types  # type: ignore

    from thomas.core import task_bot_runtime  # type: ignore

AssignedTask = _worker_types.AssignedTask
CommandRun = _worker_types.CommandRun
_load_command_catalog = _worker_services._load_command_catalog
_norm = _worker_services._norm
_now_iso = _worker_services._now_iso
_resolve_task_commands = _worker_services._resolve_task_commands
_run_command_pipeline = _worker_services._run_command_pipeline
_sanitize_token = _worker_services._sanitize_token
_task_priority_rank = _worker_services._task_priority_rank
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_WORKBOARD = default_workboard_path(ROOT)
DEFAULT_COMMAND_CATALOG = command_catalog_path_for(DEFAULT_WORKBOARD, repo_root=ROOT)
DEFAULT_TASK_MANAGER_AGENT = "thomas"
DEFAULT_POLL_SECONDS = 15.0
DEFAULT_IDLE_HEARTBEAT_SECONDS = 300.0
DEFAULT_LOG_DIR = worker_log_dir_for(DEFAULT_WORKBOARD, repo_root=ROOT)

def _load_assigned_tasks(workboard_path: Path, *, agent: str) -> tuple[bool, dict[str, object]]:
    violations, _claims, active_tasks, _up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}

    agent_key = _norm(agent)
    tasks: list[AssignedTask] = []
    for row in active_tasks:
        if _norm(row.agent) != agent_key:
            continue
        tasks.append(
            AssignedTask(
                line_no=int(row.line_no),
                task_id=str(row.task_id).strip(),
                scope=",".join([str(item) for item in list(row.scopes)]),
                summary=str(row.summary).strip(),
            )
        )

    tasks.sort(key=lambda item: (_task_priority_rank(item.summary), item.line_no, _norm(item.task_id)))
    return True, {"tasks": tasks, "task_count": len(tasks)}
def _write_run_log(
    *,
    log_root: Path,
    agent: str,
    task: AssignedTask,
    command_source: str,
    runs: Sequence[CommandRun],
    ok: bool,
) -> str:
    agent_slug = _sanitize_token(agent)
    task_slug = _sanitize_token(task.task_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = log_root / agent_slug
    path.mkdir(parents=True, exist_ok=True)
    log_path = path / f"{stamp}-{task_slug}.log"
    lines: list[str] = [
        f"agent={agent}",
        f"task_id={task.task_id}",
        f"scope={task.scope}",
        f"summary={task.summary}",
        f"command_source={command_source}",
        f"ok={str(bool(ok)).lower()}",
        f"created_at={_now_iso()}",
        "",
    ]
    for idx, run in enumerate(runs, start=1):
        lines.extend(
            [
                f"[command {idx}] {run.command}",
                f"returncode={run.returncode}; elapsed_seconds={run.elapsed_seconds:.3f}; timed_out={str(run.timed_out).lower()}",
                "--- stdout ---",
                run.stdout,
                "--- stderr ---",
                run.stderr,
                "",
            ]
        )
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return str(log_path)


def _send_message_safe(
    *,
    workboard_path: Path,
    sender: str,
    recipient: str,
    task_id: str,
    summary: str,
    kind: str,
    priority: str,
    requested_action: str,
    decision: str,
) -> tuple[bool, str]:
    ok, payload = workboard_message.send_message(
        workboard_path,
        sender=sender,
        recipient=recipient,
        summary=summary,
        task_id=task_id,
        kind=kind,
        priority=priority,
        requested_action=requested_action,
        decision=decision,
    )
    if ok:
        return True, ""
    message = str(payload.get("error", "message send failed")) if isinstance(payload, dict) else str(payload)
    return False, message


def _release_claim_safe(
    *,
    workboard_path: Path,
    agent: str,
    allow_dirty_release: bool,
    dirty_release_reason: str,
    require_done_state: bool = False,
) -> tuple[bool, str]:
    _ = require_done_state
    ok, payload = workboard_claim.release(
        workboard_path,
        agent=agent,
        allow_dirty=bool(allow_dirty_release),
        dirty_reason=str(dirty_release_reason or ""),
    )
    if ok:
        return True, ""
    return False, str(payload)


def _set_task_status_safe(
    *,
    workboard_path: Path,
    task_id: str,
    status: str,
    actor: str,
    enforce_transition: bool = True,
) -> tuple[bool, str]:
    ok, payload = workboard_task_manager.set_task_status(
        workboard_path,
        task_id=task_id,
        status=status,
        actor=actor,
        enforce_transition=bool(enforce_transition),
    )
    if ok:
        return True, ""
    message = str(payload.get("error", "task status update failed")) if isinstance(payload, dict) else str(payload)
    return False, message


def _runtime_execution_id(task_id: str) -> str:
    try:
        payload = task_bot_runtime.find_by_task_id(task_id, repo_root=ROOT)
    except (OSError, RuntimeError, ValueError):
        return ""
    return str((payload or {}).get("execution_id") or "").strip()


def _runtime_execution_record(task_id: str) -> dict[str, object]:
    try:
        payload = task_bot_runtime.find_by_task_id(task_id, repo_root=ROOT)
    except (OSError, RuntimeError, ValueError):
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _should_use_runtime_task_runner(record: dict[str, object]) -> bool:
    if not isinstance(record, dict) or not record:
        return False
    request_text = str(record.get("request_text") or "").strip()
    intent = str(record.get("execution_intent") or "").strip().lower()
    return bool(request_text) and intent in {"chat_task", "production_task", "task"}


def _run_runtime_task_pipeline(*, task_id: str, worker_agent: str) -> tuple[bool, dict[str, object]]:
    started = time.monotonic()
    command = (
        "python scripts/worker_run_chat_task.py "
        f"--task-id {task_id} --worker-agent {worker_agent} --engine guarded_loop"
    )
    try:
        runner = importlib.import_module("scripts.worker_run_chat_task")
        final_text = str(
            runner.execute_task_sync(
                task_id,
                worker_agent=worker_agent,
                engine="guarded_loop",
                emit_stdout=False,
            )
            or ""
        ).strip()
        elapsed = time.monotonic() - started
        run = CommandRun(
            command=command,
            returncode=0,
            elapsed_seconds=float(elapsed),
            timed_out=False,
            stdout=final_text,
            stderr="",
        )
        return True, {"runs": [run]}
    except (ImportError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        elapsed = time.monotonic() - started
        run = CommandRun(
            command=command,
            returncode=1,
            elapsed_seconds=float(elapsed),
            timed_out=False,
            stdout="",
            stderr=str(exc),
        )
        return False, {"runs": [run], "failed_index": 1, "failed_command": command}


def _request_immediate_dispatch(
    *,
    workboard_path: Path,
    agent: str,
    task_manager_agent: str,
    task_id: str,
    dispatch_lookback_minutes: float,
) -> tuple[bool, dict[str, object]]:
    _send_message_safe(
        workboard_path=workboard_path,
        sender=agent,
        recipient=task_manager_agent,
        task_id="none",
        summary="worker online and waiting for assignment",
        kind="coordination",
        priority="p1",
        requested_action="none",
        decision="pending",
    )
    _send_message_safe(
        workboard_path=workboard_path,
        sender=agent,
        recipient=task_manager_agent,
        task_id=task_id,
        summary=f"request immediate redispatch after completing `{task_id}`",
        kind="coordination",
        priority="p1",
        requested_action="assign next available task",
        decision="pending",
    )
    ok_dispatch, payload_dispatch = workboard_task_manager.dispatch_idle_agents_once(
        workboard_path=workboard_path,
        task_manager_agent=task_manager_agent,
        max_dispatch_per_cycle=0,
        online_lookback_minutes=max(1.0, float(dispatch_lookback_minutes)),
        apply=True,
    )
    if not ok_dispatch:
        return False, payload_dispatch
    return True, payload_dispatch


def _worker_loop(
    *,
    workboard_path: Path,
    agent: str,
    task_manager_agent: str,
    catalog: dict[str, object],
    default_commands: Sequence[str],
    poll_seconds: float,
    idle_heartbeat_seconds: float,
    command_timeout_seconds: float,
    auto_release_success: bool,
    auto_release_failure: bool,
    release_on_no_command: bool,
    allow_dirty_release: bool,
    dirty_release_reason: str,
    stop_on_failure: bool,
    send_online_message: bool,
    send_start_message: bool,
    request_dispatch_on_complete: bool,
    dispatch_lookback_minutes: float,
    cycles: int,
    max_completions: int,
    log_dir: Path,
) -> tuple[bool, dict[str, object]]:
    cycle_count = 0
    completion_count = 0
    failure_count = 0
    noop_count = 0
    heartbeat_count = 0
    dispatch_request_count = 0
    dispatch_assigned_count = 0
    attempted_markers: set[str] = set()
    errors: list[str] = []
    last_task_id = ""
    last_summary = ""
    idle_heartbeat_interval = max(0.0, float(idle_heartbeat_seconds))
    poll_interval = max(0.0, float(poll_seconds))
    last_heartbeat_at = 0.0
    online_notified = False

    while True:
        if int(cycles) > 0 and cycle_count >= int(cycles):
            break
        if int(max_completions) > 0 and completion_count >= int(max_completions):
            break
        cycle_count += 1

        ok_tasks, payload_tasks = _load_assigned_tasks(workboard_path, agent=agent)
        if not ok_tasks:
            failure_count += 1
            message = str(payload_tasks.get("error", "failed to load assigned tasks"))
            errors.append(message)
            if stop_on_failure:
                break
            if poll_interval > 0:
                time.sleep(poll_interval)
            continue

        tasks = [item for item in list(payload_tasks.get("tasks") or []) if isinstance(item, AssignedTask)]
        live_markers = {f"{task.line_no}:{_norm(task.task_id)}" for task in tasks}
        attempted_markers.intersection_update(live_markers)

        if not tasks:
            if send_online_message and not online_notified:
                ok_msg, err_msg = _send_message_safe(
                    workboard_path=workboard_path,
                    sender=agent,
                    recipient=task_manager_agent,
                    task_id="none",
                    summary="worker online and waiting for assignment",
                    kind="coordination",
                    priority="p1",
                    requested_action="none",
                    decision="pending",
                )
                if not ok_msg and err_msg:
                    errors.append(err_msg)
                online_notified = True
                last_heartbeat_at = time.monotonic()
            elif idle_heartbeat_interval > 0:
                now_tick = time.monotonic()
                if now_tick - last_heartbeat_at >= idle_heartbeat_interval:
                    ok_msg, err_msg = _send_message_safe(
                        workboard_path=workboard_path,
                        sender=agent,
                        recipient=task_manager_agent,
                        task_id="none",
                        summary="worker heartbeat: waiting for assignment",
                        kind="ping",
                        priority="p1",
                        requested_action="none",
                        decision="pending",
                    )
                    if ok_msg:
                        heartbeat_count += 1
                    elif err_msg:
                        errors.append(err_msg)
                    last_heartbeat_at = now_tick
            if poll_interval > 0:
                time.sleep(poll_interval)
            continue

        task = tasks[0]
        marker = f"{task.line_no}:{_norm(task.task_id)}"
        if marker in attempted_markers:
            if poll_interval > 0:
                time.sleep(poll_interval)
            continue
        attempted_markers.add(marker)
        last_task_id = task.task_id
        last_summary = task.summary
        runtime_record = _runtime_execution_record(task.task_id)
        runtime_execution_id = str(runtime_record.get("execution_id") or "").strip()

        commands, command_source = _resolve_task_commands(
            task=task,
            catalog=catalog,
            cli_default_commands=default_commands,
        )
        context = {
            "agent": agent,
            "task_id": task.task_id,
            "scope": task.scope,
            "summary": task.summary,
            "workboard": str(workboard_path),
            "root": str(ROOT),
        }

        use_runtime_task_runner = not commands and _should_use_runtime_task_runner(runtime_record)

        if not commands:
            if use_runtime_task_runner:
                command_source = "runtime.chat_task.guarded_loop"
            else:
                noop_count += 1
                _set_task_status_safe(
                    workboard_path=workboard_path,
                    task_id=task.task_id,
                    status="blocked",
                    actor=agent,
                    enforce_transition=True,
                )
                _send_message_safe(
                    workboard_path=workboard_path,
                    sender=agent,
                    recipient=task_manager_agent,
                    task_id=task.task_id,
                    summary=f"no automation command configured for `{task.task_id}`",
                    kind="coordination",
                    priority="p1",
                    requested_action="provide worker command mapping",
                    decision="pending",
                )
                if runtime_execution_id:
                    with suppress(Exception):
                        task_bot_runtime.update_execution(
                            runtime_execution_id,
                            state="blocked",
                            progress_summary=f"Worker blocked: no automation command configured for `{task.task_id}`.",
                            blocker="no_worker_command_configured",
                            actor=agent,
                            repo_root=ROOT,
                            force=True,
                        )
                if release_on_no_command:
                    ok_release, err_release = _release_claim_safe(
                        workboard_path=workboard_path,
                        agent=agent,
                        allow_dirty_release=allow_dirty_release,
                        dirty_release_reason=dirty_release_reason,
                        require_done_state=False,
                    )
                    if not ok_release and err_release:
                        errors.append(err_release)
                        failure_count += 1
                        if stop_on_failure:
                            break
                if poll_interval > 0:
                    time.sleep(poll_interval)
                continue

        ok_status, err_status = _set_task_status_safe(
            workboard_path=workboard_path,
            task_id=task.task_id,
            status="in_progress",
            actor=agent,
            enforce_transition=True,
        )
        if not ok_status:
            failure_count += 1
            errors.append(err_status)
            _send_message_safe(
                workboard_path=workboard_path,
                sender=agent,
                recipient=task_manager_agent,
                task_id=task.task_id,
                summary=f"unable to transition `{task.task_id}` to in_progress",
                kind="blocker",
                priority="p0",
                requested_action="repair task status transition",
                decision="pending",
            )
            if stop_on_failure:
                break
            if poll_interval > 0:
                time.sleep(poll_interval)
            continue

        if send_start_message:
            _send_message_safe(
                workboard_path=workboard_path,
                sender=agent,
                recipient=task_manager_agent,
                task_id=task.task_id,
                summary=f"starting `{task.task_id}` using {len(commands)} command(s) from {command_source}",
                kind="status",
                priority="p1",
                requested_action="none",
                decision="pending",
            )

        if use_runtime_task_runner:
            ok_run, payload_run = _run_runtime_task_pipeline(task_id=task.task_id, worker_agent=agent)
        else:
            ok_run, payload_run = _run_command_pipeline(
                commands=commands,
                context=context,
                timeout_seconds=float(command_timeout_seconds),
                root=ROOT,
            )
        runs = [item for item in list(payload_run.get("runs") or []) if isinstance(item, CommandRun)]
        log_path = _write_run_log(
            log_root=log_dir,
            agent=agent,
            task=task,
            command_source=command_source,
            runs=runs,
            ok=ok_run,
        )
        if runtime_execution_id:
            with suppress(Exception):
                task_bot_runtime.attach_proof(
                    runtime_execution_id,
                    artifacts=[
                        {
                            "kind": "worker_log",
                            "path": log_path,
                            "command_source": command_source,
                            "run_count": len(runs),
                            "ok": bool(ok_run),
                        }
                    ],
                    summary=f"Worker run log recorded at {log_path}.",
                    status="attached" if ok_run else "failed",
                    actor=agent,
                    repo_root=ROOT,
                )

        if ok_run:
            completion_count += 1
            elapsed_total = sum(float(item.elapsed_seconds) for item in runs)
            ok_review, err_review = _set_task_status_safe(
                workboard_path=workboard_path,
                task_id=task.task_id,
                status="review",
                actor=agent,
                enforce_transition=True,
            )
            if not ok_review and err_review:
                errors.append(err_review)
            ok_done, err_done = _set_task_status_safe(
                workboard_path=workboard_path,
                task_id=task.task_id,
                status="done",
                actor=agent,
                enforce_transition=True,
            )
            if not ok_done and err_done:
                errors.append(err_done)
            completion_summary = f"Worker completed `{task.task_id}` in {elapsed_total:.2f}s."
            if runtime_execution_id:
                with suppress(Exception):
                    runtime_payload = task_bot_runtime.get_execution(runtime_execution_id, repo_root=ROOT) or {}
                    runtime_progress = str(runtime_payload.get("progress_summary") or "").strip()
                    if runtime_progress:
                        completion_summary = runtime_progress
            if runtime_execution_id:
                with suppress(Exception):
                    task_bot_runtime.complete_execution(
                        runtime_execution_id,
                        actor=agent,
                        summary=completion_summary,
                        repo_root=ROOT,
                    )
            _send_message_safe(
                workboard_path=workboard_path,
                sender=agent,
                recipient=task_manager_agent,
                task_id=task.task_id,
                summary=(
                    f"completed `{task.task_id}` using {len(runs)} command(s) in {elapsed_total:.2f}s "
                    f"(log: {log_path})"
                ),
                kind="status",
                priority="p1",
                requested_action="none",
                decision="approved",
            )
            if auto_release_success:
                ok_release, err_release = _release_claim_safe(
                    workboard_path=workboard_path,
                    agent=agent,
                    allow_dirty_release=allow_dirty_release,
                    dirty_release_reason=dirty_release_reason,
                    require_done_state=True,
                )
                if not ok_release:
                    failure_count += 1
                    if err_release:
                        errors.append(err_release)
                    _send_message_safe(
                        workboard_path=workboard_path,
                        sender=agent,
                        recipient=task_manager_agent,
                        task_id=task.task_id,
                        summary=f"completed `{task.task_id}` but failed to release claim",
                        kind="blocker",
                        priority="p0",
                        requested_action="release claim manually",
                        decision="pending",
                    )
                    if stop_on_failure:
                        break
                elif request_dispatch_on_complete:
                    dispatch_request_count += 1
                    ok_dispatch, payload_dispatch = _request_immediate_dispatch(
                        workboard_path=workboard_path,
                        agent=agent,
                        task_manager_agent=task_manager_agent,
                        task_id=task.task_id,
                        dispatch_lookback_minutes=dispatch_lookback_minutes,
                    )
                    if ok_dispatch:
                        dispatch_assigned_count += int(payload_dispatch.get("assigned_count", 0) or 0)
                    else:
                        failure_count += 1
                        errors.append(str(payload_dispatch.get("error", "immediate dispatch request failed")))
                        _send_message_safe(
                            workboard_path=workboard_path,
                            sender=agent,
                            recipient=task_manager_agent,
                            task_id=task.task_id,
                            summary="immediate redispatch request failed",
                            kind="coordination",
                            priority="p1",
                            requested_action="run task manager monitor/dispatch cycle",
                            decision="pending",
                        )
                        if stop_on_failure:
                            break
        else:
            failure_count += 1
            failed_index = int(payload_run.get("failed_index", len(runs) or 1) or 1)
            failed_command = str(payload_run.get("failed_command", "")).strip()
            _set_task_status_safe(
                workboard_path=workboard_path,
                task_id=task.task_id,
                status="blocked",
                actor=agent,
                enforce_transition=True,
            )
            _send_message_safe(
                workboard_path=workboard_path,
                sender=agent,
                recipient=task_manager_agent,
                task_id=task.task_id,
                summary=(f"automation failed for `{task.task_id}` at command {failed_index} " f"(log: {log_path})"),
                kind="blocker",
                priority="p1",
                requested_action="triage failed worker command and update mapping",
                decision="pending",
            )
            if runtime_execution_id:
                with suppress(Exception):
                    task_bot_runtime.fail_execution(
                        runtime_execution_id,
                        actor=agent,
                        summary=(
                            f"Automation failed for `{task.task_id}` at command {failed_index}: "
                            f"{failed_command or 'worker command'}"
                        ),
                        blocker="worker_command_failed",
                        proof_status="failed",
                        repo_root=ROOT,
                    )
            if auto_release_failure:
                ok_release, err_release = _release_claim_safe(
                    workboard_path=workboard_path,
                    agent=agent,
                    allow_dirty_release=allow_dirty_release,
                    dirty_release_reason=dirty_release_reason,
                    require_done_state=False,
                )
                if not ok_release and err_release:
                    errors.append(err_release)
            if stop_on_failure:
                break

        if poll_interval > 0:
            time.sleep(poll_interval)

    ok = failure_count == 0
    payload: dict[str, object] = {
        "agent": agent,
        "ok": bool(ok),
        "workboard": str(workboard_path),
        "cycle_count": cycle_count,
        "completed_count": completion_count,
        "failure_count": failure_count,
        "no_command_count": noop_count,
        "heartbeat_count": heartbeat_count,
        "dispatch_request_count": dispatch_request_count,
        "dispatch_assigned_count": dispatch_assigned_count,
        "last_task_id": last_task_id,
        "last_summary": last_summary,
        "errors": errors,
    }
    return ok, payload


def run(argv: Iterable[str] | None = None) -> int:
    cli = importlib.import_module("scripts.workboard_worker_cli")
    return int(cli.main(module=sys.modules[__name__], argv=argv))


if __name__ == "__main__":
    raise SystemExit(run())
