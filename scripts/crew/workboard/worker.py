#!/usr/bin/env python3
"""Persistent worker loop for workboard-dispatched agent lanes.

This runner keeps one agent alias online, waits for tasks assigned to that
agent in WORKBOARD.md, executes task command pipelines, reports completion or
blockers, and optionally releases the claim so task manager can dispatch the
next lane.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: F401 -- re-exported: tests patch mod.subprocess.run (a process-global singleton)
import sys
import time
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.tasks import manager as workboard_task_manager
    from scripts.crew.workboard import worker_dispatch, worker_pipeline
    from scripts.forge.gates import workboard_claims as claims_gate
    from thomas.core import task_bot_runtime
except Exception:  # pragma: no cover
    from crew.tasks import manager as workboard_task_manager  # type: ignore
    from crew.workboard import worker_dispatch, worker_pipeline  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore

    from thomas.core import task_bot_runtime  # type: ignore

# Split out (worker_pipeline.py, worker_dispatch.py; phase-1.4 task-2) past the monolith guard's
# 800-line soft limit -- see their docstrings. Re-exported under original names; no caller changed.
AssignedTask, CommandRun = worker_pipeline.AssignedTask, worker_pipeline.CommandRun
_norm, _load_command_catalog = worker_pipeline._norm, worker_pipeline._load_command_catalog
_resolve_task_commands = worker_pipeline._resolve_task_commands
_run_command_pipeline, _write_run_log = worker_pipeline._run_command_pipeline, worker_pipeline._write_run_log
_send_message_safe, _release_claim_safe = worker_dispatch._send_message_safe, worker_dispatch._release_claim_safe
_set_task_status_safe, _git_head_sha = worker_dispatch._set_task_status_safe, worker_dispatch._git_head_sha
_runtime_execution_id, _inbox_interrupt = worker_dispatch._runtime_execution_id, worker_dispatch._inbox_interrupt
_request_immediate_dispatch = worker_dispatch._request_immediate_dispatch
_finalize_landed_done = worker_dispatch._finalize_landed_done

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_COMMAND_CATALOG = ROOT / "plans" / "thomas" / "worker_command_catalog.json"
DEFAULT_TASK_MANAGER_AGENT = "thomas"
DEFAULT_POLL_SECONDS = 15.0
DEFAULT_IDLE_HEARTBEAT_SECONDS = 300.0
DEFAULT_LOG_DIR = ROOT / "runtime" / "workers"


def _task_priority_rank(summary: str) -> tuple[int, int, str]:
    text = _norm(summary)
    priority = 1
    if "[p0]" in text:
        priority = 0
    elif "[p2]" in text:
        priority = 2

    urgency = 1
    if "[now]" in text:
        urgency = 0
    elif "[later]" in text:
        urgency = 2
    return priority, urgency, text


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
    stop_on_unread_message: bool,
    cycles: int,
    max_completions: int,
    log_dir: Path,
) -> tuple[bool, dict[str, object]]:
    cycle_count = 0
    completion_count = 0
    failure_count = 0
    held_count = 0
    refused_count = 0
    noop_count = 0
    heartbeat_count = 0
    dispatch_request_count = 0
    dispatch_assigned_count = 0
    inbox_blocked_count = 0
    attempted_markers: set[str] = set()
    errors: list[str] = []
    last_task_id = ""
    last_summary = ""
    last_inbox_message_ids: list[str] = []
    idle_heartbeat_interval = max(0.0, float(idle_heartbeat_seconds))
    poll_interval = max(0.0, float(poll_seconds))
    last_heartbeat_at = 0.0
    online_notified = False
    inbox_pause_notified = False

    while True:
        if int(cycles) > 0 and cycle_count >= int(cycles):
            break
        if int(max_completions) > 0 and completion_count >= int(max_completions):
            break
        cycle_count += 1

        ok_inbox, payload_inbox = _inbox_interrupt(workboard_path=workboard_path, agent=agent)
        unread_count = int(payload_inbox.get("unread_count") or 0)
        if not ok_inbox or unread_count:
            inbox_blocked_count += 1
            last_inbox_message_ids = [str(item) for item in list(payload_inbox.get("msg_ids") or [])]
            if not ok_inbox:
                errors.append(str(payload_inbox.get("error") or "failed to read worker inbox"))
            if not inbox_pause_notified:
                summary = (
                    f"worker paused: `{agent}` has {unread_count} unread workboard message(s)"
                    if ok_inbox
                    else f"worker paused: `{agent}` could not verify workboard inbox"
                )
                requested_action = (
                    f"Run `python scripts/crew/workboard/message.py --inbox --agent {agent}`, ack/respond, "
                    "then restart or let the worker continue."
                )
                ok_msg, err_msg = _send_message_safe(
                    workboard_path=workboard_path,
                    sender=agent,
                    recipient=task_manager_agent,
                    task_id="none",
                    summary=summary,
                    kind="coordination",
                    priority="p0" if unread_count else "p1",
                    requested_action=requested_action,
                    decision="pending",
                )
                if not ok_msg and err_msg:
                    errors.append(err_msg)
                inbox_pause_notified = True
            if stop_on_unread_message:
                break
            if poll_interval > 0:
                time.sleep(poll_interval)
            continue
        inbox_pause_notified = False

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
        runtime_execution_id = _runtime_execution_id(task.task_id)

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

        if not commands:
            noop_count += 1
            _set_task_status_safe(
                workboard_path=workboard_path, task_id=task.task_id, status="blocked", actor=agent,
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
                try:
                    task_bot_runtime.update_execution(
                        runtime_execution_id,
                        state="blocked",
                        progress_summary=f"Worker blocked: no automation command configured for `{task.task_id}`.",
                        blocker="no_worker_command_configured",
                        actor=agent,
                        repo_root=ROOT,
                        force=True,
                    )
                except Exception:
                    pass
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
            workboard_path=workboard_path, task_id=task.task_id, status="in_progress", actor=agent,
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

        # Proxy for claim/start time (AssignedTask has none); whole seconds since commit committer time is too.
        task_started_at = datetime.now(timezone.utc).replace(microsecond=0)
        head_before_run = _git_head_sha(ROOT)

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

        ok_run, payload_run = _run_command_pipeline(
            commands=commands,
            context=context,
            timeout_seconds=float(command_timeout_seconds),
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
            try:
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
            except Exception:
                pass

        if ok_run:
            completion_count += 1
            elapsed_total = sum(float(item.elapsed_seconds) for item in runs)
            ok_review, err_review = _set_task_status_safe(
                workboard_path=workboard_path, task_id=task.task_id, status="review", actor=agent,
                enforce_transition=True,
            )
            if not ok_review and err_review:
                errors.append(err_review)

            # Done now requires proof: auto-done only when the pipeline itself landed a commit (HEAD moved).
            head_after_run = _git_head_sha(ROOT)
            landed_sha = head_after_run if head_after_run and head_after_run != head_before_run else None

            if not landed_sha:
                # Held, not done: an honest regression from auto-done-on-exit-0. Mirrors the failure
                # branch -- no completed/approved message, no release (unfinished work keeps its claim
                # visible), and this counts as a non-clean loop outcome, never a silent success.
                held_count += 1
                print(f"REVIEW HOLD {task.task_id}: pipeline succeeded but landed no commit - done requires evidence")
                _send_message_safe(
                    workboard_path=workboard_path, sender=agent, recipient=task_manager_agent,
                    task_id=task.task_id,
                    summary=(
                        f"pipeline succeeded for `{task.task_id}` but landed no commit - "
                        "done withheld, task remains in review"
                    ),
                    kind="blocker", priority="p1", decision="pending",
                    requested_action="review pipeline output and land the missing commit, or reassign",
                )
            else:
                result = _finalize_landed_done(
                    workboard_path=workboard_path, task_id=task.task_id, agent=agent,
                    task_manager_agent=task_manager_agent, landed_sha=landed_sha,
                    evidence_not_before=task_started_at, runtime_execution_id=runtime_execution_id,
                    repo_root=ROOT, elapsed_total=elapsed_total, run_count=len(runs), log_path=str(log_path),
                    auto_release_success=auto_release_success, allow_dirty_release=allow_dirty_release,
                    dirty_release_reason=dirty_release_reason,
                    request_dispatch_on_complete=request_dispatch_on_complete,
                    dispatch_lookback_minutes=dispatch_lookback_minutes,
                )
                if result["refused"]:
                    # Refused, not done: mirrors the held branch's convention (review-round
                    # fix, coordinator-reviewed) -- no completed/approved message, no
                    # completion credit, its own blocker message, folds into `ok`. See
                    # _finalize_landed_done's docstring (worker_dispatch.py) for the full
                    # "why" this branch exists at all.
                    completion_count -= 1
                    refused_count += 1
                    if result["error"]:
                        errors.append(str(result["error"]))
                    print(f"DONE REFUSED {task.task_id}: {result['error']}")
                else:
                    if result["dispatch_requested"]:
                        dispatch_request_count += 1
                        dispatch_assigned_count += int(result["dispatch_assigned"] or 0)
                    if result["failure"]:
                        failure_count += 1
                        if result["error"]:
                            errors.append(str(result["error"]))
                        if stop_on_failure:
                            break
        else:
            failure_count += 1
            failed_index = int(payload_run.get("failed_index", len(runs) or 1) or 1)
            failed_command = str(payload_run.get("failed_command", "")).strip()
            _set_task_status_safe(
                workboard_path=workboard_path, task_id=task.task_id, status="blocked", actor=agent,
                enforce_transition=True,
            )
            _send_message_safe(
                workboard_path=workboard_path,
                sender=agent,
                recipient=task_manager_agent,
                task_id=task.task_id,
                summary=(f"automation failed for `{task.task_id}` at command {failed_index} (log: {log_path})"),
                kind="blocker",
                priority="p1",
                requested_action="triage failed worker command and update mapping",
                decision="pending",
            )
            if runtime_execution_id:
                try:
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
                except Exception:
                    pass
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

    # A held task (pipeline succeeded but landed no commit) is not a clean loop outcome -- it must
    # never read as silent success, so held_count folds into ok exactly like failure_count does.
    # A refused done (a commit DID land, but the done transition itself was refused -- e.g. the
    # evidence failed verification) is the same shape: not clean, folds into ok the same way.
    ok = failure_count == 0 and held_count == 0 and refused_count == 0 and inbox_blocked_count == 0
    payload: dict[str, object] = {
        "agent": agent,
        "ok": bool(ok),
        "workboard": str(workboard_path),
        "cycle_count": cycle_count,
        "completed_count": completion_count,
        "failure_count": failure_count,
        "held_count": held_count,
        "refused_count": refused_count,
        "no_command_count": noop_count,
        "heartbeat_count": heartbeat_count,
        "dispatch_request_count": dispatch_request_count,
        "dispatch_assigned_count": dispatch_assigned_count,
        "inbox_blocked_count": inbox_blocked_count,
        "last_inbox_message_ids": last_inbox_message_ids,
        "last_task_id": last_task_id,
        "last_summary": last_summary,
        "errors": errors,
    }
    return ok, payload


def run(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persistent worker loop for workboard-dispatched tasks.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--agent", required=True, help="Agent alias this worker loop serves.")
    parser.add_argument("--task-manager-agent", default=DEFAULT_TASK_MANAGER_AGENT)
    parser.add_argument(
        "--catalog",
        default="",
        help=(
            "Optional JSON command catalog. If omitted, defaults to "
            "`plans/thomas/worker_command_catalog.json` when present."
        ),
    )
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help=(
            "Default command template (repeatable) when catalog has no task match. "
            "Supports {agent}, {task_id}, {scope}, {summary}, {workboard}, {root}."
        ),
    )
    parser.add_argument("--cycles", type=int, default=0, help="Loop cycles (0 = continuous).")
    parser.add_argument(
        "--max-completions",
        type=int,
        default=0,
        help="Stop after this many successful task completions (0 = unlimited).",
    )
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--idle-heartbeat-seconds", type=float, default=DEFAULT_IDLE_HEARTBEAT_SECONDS)
    parser.add_argument(
        "--command-timeout-seconds",
        type=float,
        default=0.0,
        help="Per-command timeout; 0 disables timeout.",
    )
    parser.add_argument(
        "--auto-release-success",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Release claim after successful task execution (default: true).",
    )
    parser.add_argument(
        "--auto-release-failure",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Release claim after failed task execution (default: false).",
    )
    parser.add_argument(
        "--release-on-no-command",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Release claim when no command mapping exists for assigned task (default: false).",
    )
    parser.add_argument(
        "--allow-dirty-release",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Allow worker to release claim even with dirty claimed scope by writing audited "
            "override reason (default: false)."
        ),
    )
    parser.add_argument(
        "--dirty-release-reason",
        default="worker automation closeout to continue task dispatch loop",
        help="Reason string used when --allow-dirty-release is enabled.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Stop loop immediately when any failure occurs (default: false).",
    )
    parser.add_argument(
        "--send-online-message",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Send one online status + periodic idle heartbeat messages (default: true).",
    )
    parser.add_argument(
        "--send-start-message",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Send a start status message before executing task commands (default: false).",
    )
    parser.add_argument(
        "--request-dispatch-on-complete",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Trigger immediate idle-agent dispatch pass after successful completion/release (default: true).",
    )
    parser.add_argument(
        "--stop-on-unread-message",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Stop before loading or executing work when this worker has unread workboard messages "
            "(default: true). Use --no-stop-on-unread-message to pause/poll instead."
        ),
    )
    parser.add_argument(
        "--dispatch-lookback-minutes",
        type=float,
        default=120.0,
        help="Online lookback window for immediate redispatch requests (default: 120).",
    )
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    workboard_path = Path(str(args.workboard)).resolve()
    if not workboard_path.exists():
        payload = {"ok": False, "error": f"missing workboard file: {workboard_path}"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1

    if args.poll_seconds < 0:
        payload = {"ok": False, "error": "--poll-seconds must be >= 0"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.idle_heartbeat_seconds < 0:
        payload = {"ok": False, "error": "--idle-heartbeat-seconds must be >= 0"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.command_timeout_seconds < 0:
        payload = {"ok": False, "error": "--command-timeout-seconds must be >= 0"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.dispatch_lookback_minutes <= 0:
        payload = {"ok": False, "error": "--dispatch-lookback-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.cycles < 0:
        payload = {"ok": False, "error": "--cycles must be >= 0"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.max_completions < 0:
        payload = {"ok": False, "error": "--max-completions must be >= 0"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1

    catalog_path: Path | None
    if str(args.catalog).strip():
        catalog_path = Path(str(args.catalog)).resolve()
    elif DEFAULT_COMMAND_CATALOG.exists():
        catalog_path = DEFAULT_COMMAND_CATALOG
    else:
        catalog_path = None
    ok_catalog, payload_catalog = _load_command_catalog(catalog_path)
    if not ok_catalog:
        payload = {
            "ok": False,
            "error": str(payload_catalog.get("error", "catalog load failed")),
            "catalog_path": str(catalog_path) if catalog_path is not None else "",
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Workboard worker: FAIL")
            print(f"- {payload['error']}")
        return 1

    log_dir = Path(str(args.log_dir)).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    ok_loop, payload_loop = _worker_loop(
        workboard_path=workboard_path,
        agent=str(args.agent).strip(),
        task_manager_agent=str(args.task_manager_agent).strip() or DEFAULT_TASK_MANAGER_AGENT,
        catalog=payload_catalog,
        default_commands=[str(item).strip() for item in list(args.command or []) if str(item).strip()],
        poll_seconds=float(args.poll_seconds),
        idle_heartbeat_seconds=float(args.idle_heartbeat_seconds),
        command_timeout_seconds=float(args.command_timeout_seconds),
        auto_release_success=bool(args.auto_release_success),
        auto_release_failure=bool(args.auto_release_failure),
        release_on_no_command=bool(args.release_on_no_command),
        allow_dirty_release=bool(args.allow_dirty_release),
        dirty_release_reason=str(args.dirty_release_reason or ""),
        stop_on_failure=bool(args.stop_on_failure),
        send_online_message=bool(args.send_online_message),
        send_start_message=bool(args.send_start_message),
        request_dispatch_on_complete=bool(args.request_dispatch_on_complete),
        dispatch_lookback_minutes=float(args.dispatch_lookback_minutes),
        stop_on_unread_message=bool(args.stop_on_unread_message),
        cycles=int(args.cycles),
        max_completions=int(args.max_completions),
        log_dir=log_dir,
    )
    payload = {
        "action": "workboard_worker",
        "ok": bool(ok_loop),
        "catalog_path": str(catalog_path) if catalog_path is not None else "",
        "log_dir": str(log_dir),
        **payload_loop,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("Workboard worker: PASS" if ok_loop else "Workboard worker: FAIL")
        print(
            f"- agent={payload.get('agent')}; completed={payload.get('completed_count')}; "
            f"failures={payload.get('failure_count')}; held={payload.get('held_count')}; "
            f"refused={payload.get('refused_count')}; "
            f"no_command={payload.get('no_command_count')}; inbox_blocked={payload.get('inbox_blocked_count')}"
        )
        for item in list(payload.get("errors") or []):
            print(f"- error: {item}")
    return 0 if ok_loop else 1


if __name__ == "__main__":
    raise SystemExit(run())
