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
import os
import shlex
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.forge.gates import workboard_claims as claims_gate
    from scripts import workboard_claim, workboard_message, workboard_task_manager
    from thomas.core import task_bot_runtime
except Exception:  # pragma: no cover
    from forge.gates import workboard_claims as claims_gate  # type: ignore
    import workboard_claim  # type: ignore
    import workboard_message  # type: ignore
    import workboard_task_manager  # type: ignore

    from thomas.core import task_bot_runtime  # type: ignore
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_COMMAND_CATALOG = ROOT / "plans" / "thomas" / "worker_command_catalog.json"
DEFAULT_TASK_MANAGER_AGENT = "thomas"
DEFAULT_POLL_SECONDS = 15.0
DEFAULT_IDLE_HEARTBEAT_SECONDS = 300.0
DEFAULT_LOG_DIR = ROOT / "runtime" / "workers"


@dataclass(frozen=True)
class AssignedTask:
    line_no: int
    task_id: str
    scope: str
    summary: str


@dataclass(frozen=True)
class CommandRun:
    command: str
    returncode: int
    elapsed_seconds: float
    timed_out: bool
    stdout: str
    stderr: str


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        return "{" + key + "}"


def _quote_for_shell(value: str) -> str:
    token = str(value or "")
    if os.name == "nt":
        return subprocess.list2cmdline([token])
    return shlex.quote(token)


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _sanitize_token(text: str) -> str:
    chars: list[str] = []
    for ch in str(text or "").strip().lower():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("-")
    out = "".join(chars).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "worker"


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _coerce_commands(raw: object, *, label: str) -> list[str]:
    out: list[str] = []
    if isinstance(raw, str):
        token = str(raw).strip()
        if token:
            out.append(token)
        return out
    if isinstance(raw, list):
        for idx, item in enumerate(raw, start=1):
            if not isinstance(item, str):
                raise ValueError(f"{label}[{idx}] must be a string command")
            token = str(item).strip()
            if token:
                out.append(token)
        return out
    if raw is None:
        return out
    raise ValueError(f"{label} must be a string or list of strings")


def _load_command_catalog(path: Path | None) -> tuple[bool, dict[str, object]]:
    payload: dict[str, object] = {
        "tasks": {},
        "task_prefixes": [],
        "default": [],
    }
    if path is None:
        return True, payload
    if not path.exists():
        return False, {"error": f"catalog file not found: {path}"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, {"error": f"failed to parse catalog json: {exc}"}
    if not isinstance(raw, dict):
        return False, {"error": "catalog root must be a JSON object"}

    tasks_raw = raw.get("tasks", {})
    if tasks_raw is None:
        tasks_raw = {}
    if not isinstance(tasks_raw, dict):
        return False, {"error": "`tasks` must be a JSON object"}
    task_commands: dict[str, list[str]] = {}
    for task_id, commands_raw in tasks_raw.items():
        task_key = _norm(str(task_id))
        if not task_key:
            continue
        commands = _coerce_commands(commands_raw, label=f"tasks.{task_id}")
        if commands:
            task_commands[task_key] = commands

    prefixes_raw = raw.get("task_prefixes", {})
    if prefixes_raw is None:
        prefixes_raw = {}
    if not isinstance(prefixes_raw, dict):
        return False, {"error": "`task_prefixes` must be a JSON object"}
    prefix_rows: list[tuple[str, list[str]]] = []
    for prefix, commands_raw in prefixes_raw.items():
        prefix_key = _norm(str(prefix))
        if not prefix_key:
            continue
        commands = _coerce_commands(commands_raw, label=f"task_prefixes.{prefix}")
        if commands:
            prefix_rows.append((prefix_key, commands))
    prefix_rows.sort(key=lambda item: (-len(item[0]), item[0]))

    default_commands = _coerce_commands(raw.get("default"), label="default")
    payload["tasks"] = task_commands
    payload["task_prefixes"] = prefix_rows
    payload["default"] = default_commands
    return True, payload


def _resolve_task_commands(
    *,
    task: AssignedTask,
    catalog: dict[str, object],
    cli_default_commands: Sequence[str],
) -> tuple[list[str], str]:
    task_key = _norm(task.task_id)
    task_map = dict(catalog.get("tasks") or {})
    if task_key in task_map:
        return list(task_map[task_key]), "catalog.tasks"

    prefix_rows: list[tuple[str, list[str]]] = []
    for item in list(catalog.get("task_prefixes") or []):
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], list):
            prefix_rows.append((item[0], [str(x) for x in item[1]]))
    for prefix, commands in prefix_rows:
        if task_key.startswith(_norm(prefix)):
            return list(commands), f"catalog.task_prefixes:{prefix}"

    defaults = [str(item).strip() for item in list(cli_default_commands or []) if str(item).strip()]
    if defaults:
        return defaults, "cli.default"

    catalog_defaults = [str(item).strip() for item in list(catalog.get("default") or []) if str(item).strip()]
    if catalog_defaults:
        return catalog_defaults, "catalog.default"
    return [], "none"


def _render_command(template: str, context: dict[str, str]) -> str:
    safe_context = {key: _quote_for_shell(value) for key, value in context.items()}
    return str(template).format_map(_SafeFormatDict(safe_context)).strip()


def _trim_log(text: str, *, limit: int = 2000) -> str:
    payload = str(text or "")
    if len(payload) <= limit:
        return payload
    return payload[:limit] + "...<trimmed>"


def _run_command_pipeline(
    *,
    commands: Sequence[str],
    context: dict[str, str],
    timeout_seconds: float,
) -> tuple[bool, dict[str, object]]:
    runs: list[CommandRun] = []
    timeout = None if float(timeout_seconds) <= 0 else float(timeout_seconds)
    for idx, template in enumerate(commands, start=1):
        rendered = _render_command(template, context)
        if not rendered:
            return False, {"error": f"command #{idx} rendered to empty text"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                rendered,
                cwd=ROOT,
                shell=True,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            elapsed = time.monotonic() - started
            run = CommandRun(
                command=rendered,
                returncode=int(completed.returncode),
                elapsed_seconds=float(elapsed),
                timed_out=False,
                stdout=_trim_log(completed.stdout or ""),
                stderr=_trim_log(completed.stderr or ""),
            )
            runs.append(run)
            if run.returncode != 0:
                return False, {"runs": runs, "failed_index": idx, "failed_command": rendered}
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            run = CommandRun(
                command=rendered,
                returncode=124,
                elapsed_seconds=float(elapsed),
                timed_out=True,
                stdout=_trim_log(str(exc.stdout or "")),
                stderr=_trim_log(str(exc.stderr or "")),
            )
            runs.append(run)
            return False, {"runs": runs, "failed_index": idx, "failed_command": rendered, "timed_out": True}

    return True, {"runs": runs}


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
    ok, payload = workboard_claim.release(
        workboard_path,
        agent=agent,
        allow_dirty=bool(allow_dirty_release),
        dirty_reason=str(dirty_release_reason or ""),
        require_done_state=bool(require_done_state),
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
    except Exception:
        return ""
    return str((payload or {}).get("execution_id") or "").strip()


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
        max_dispatch_per_cycle=1,
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
            if runtime_execution_id:
                try:
                    task_bot_runtime.complete_execution(
                        runtime_execution_id,
                        actor=agent,
                        summary=f"Worker completed `{task.task_id}` in {elapsed_total:.2f}s.",
                        repo_root=ROOT,
                    )
                except Exception:
                    pass
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
            f"failures={payload.get('failure_count')}; no_command={payload.get('no_command_count')}"
        )
        for item in list(payload.get("errors") or []):
            print(f"- error: {item}")
    return 0 if ok_loop else 1


if __name__ == "__main__":
    raise SystemExit(run())
