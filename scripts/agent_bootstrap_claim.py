#!/usr/bin/env python3
"""Bootstrap an agent session with a WIP workboard claim."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

try:
    from scripts import agent_identity
    from scripts import workboard_claim as claim_tool
except Exception:  # pragma: no cover
    import agent_identity  # type: ignore
    import workboard_claim as claim_tool  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_TASK_MANAGER_AGENT = getattr(claim_tool, "DEFAULT_TASK_MANAGER_AGENT", "task-manager-agent")
DEFAULT_DISPATCH_TARGET_WORKERS = getattr(claim_tool, "DEFAULT_DISPATCH_TARGET_WORKERS", 2)
DEFAULT_AUTO_DISPATCH_TARGET_WORKERS = max(int(DEFAULT_DISPATCH_TARGET_WORKERS), 3)
DEFAULT_MIN_AUTO_DISPATCH_TARGET_WORKERS = 2
DEFAULT_DISPATCHER_NAME = "dispatcher"
DEFAULT_DISPATCH_MAX_SUGGESTIONS = getattr(claim_tool, "DEFAULT_DISPATCH_MAX_SUGGESTIONS", 5)
CLAIM_ROLE_VALUES = tuple(getattr(claim_tool, "CLAIM_ROLE_VALUES", ("solo", "parent", "worker")))
DEFAULT_TASK_MANAGER_LOOP_INTERVAL_SECONDS = 30.0
DEFAULT_WORKER_LOOP_POLL_SECONDS = 15.0


def _agent_key(value: str | None) -> str:
    return str(value or "").strip().lower()


def _is_task_manager_agent(agent: str | None) -> bool:
    return _agent_key(agent) in {_agent_key(DEFAULT_TASK_MANAGER_AGENT), "task-manager-agent", "task-manager"}


def _resolve_agent(explicit_agent: str | None) -> str | None:
    return agent_identity.resolve_agent(explicit_agent, include_name_fallback=True)


def _detect_branch_name() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        branch = str(proc.stdout or "").strip()
    except Exception:
        branch = ""
    if branch and branch.upper() != "HEAD":
        return branch
    return "unknown-branch"


def _default_ticket() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"HSK-{stamp}"


def _build_task(task: str | None, ticket: str | None) -> str:
    base = str(task or "").strip()
    if not base:
        base = f"branch {_detect_branch_name()}"
    if base.startswith("[WIP]"):
        return base
    ticket_id = str(ticket or "").strip() or _default_ticket()
    return f"[WIP][{ticket_id}] {base}"


def _resolve_role(agent: str, role: str | None, parent: str | None) -> str | None:
    if role:
        return role
    if parent and _agent_key(parent) not in {"", "none"}:
        return None
    if not _is_task_manager_agent(agent):
        return "parent"
    return None


def _resolve_name(
    agent: str,
    explicit_name: str | None,
    *,
    role: str | None,
) -> str:
    normalized = _normalize_scope_name(explicit_name)
    if normalized:
        return normalized
    if role == "parent" and not _is_task_manager_agent(agent):
        return DEFAULT_DISPATCHER_NAME
    return ""


def _name_resolution_source(
    explicit_name: str | None,
    *,
    role: str | None,
    agent: str,
    auto_dispatch: bool,
) -> str:
    if _normalize_scope_name(explicit_name):
        return "explicit"
    if role == "parent" and not _is_task_manager_agent(agent):
        return "dispatcher-default" if auto_dispatch else "dispatcher-default-no-auto"
    return "agent-id"


def _to_bool(value: bool | int | None) -> bool:
    return bool(value)


def _spawn_worker_loop(
    *,
    workboard_path: Path,
    worker_agent: str,
    task_manager_agent: str,
    poll_seconds: float,
) -> tuple[bool, dict[str, object] | None, str | None]:
    worker_script = (ROOT / "scripts" / "workboard_worker.py").resolve()
    command = [
        sys.executable,
        str(worker_script),
        "--workboard",
        str(workboard_path),
        "--agent",
        str(worker_agent),
        "--task-manager-agent",
        str(task_manager_agent),
        "--cycles",
        "0",
        "--poll-seconds",
        str(float(poll_seconds)),
    ]
    creation_flags = 0
    close_fds = True
    if os.name == "nt":
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creation_flags |= subprocess.DETACHED_PROCESS
        close_fds = False
    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=close_fds,
            creationflags=creation_flags,
        )
    except Exception as exc:
        return False, None, str(exc)
    return (
        True,
        {
            "agent": str(worker_agent),
            "pid": int(process.pid),
            "command": " ".join(command),
            "poll_seconds": float(poll_seconds),
        },
        None,
    )


def _spawn_task_manager_loop(
    *,
    workboard_path: Path,
    task_manager_agent: str,
    interval_seconds: float,
) -> tuple[bool, dict[str, object] | None, str | None]:
    manager_script = (ROOT / "scripts" / "workboard_task_manager.py").resolve()
    command = [
        sys.executable,
        str(manager_script),
        "--workboard",
        str(workboard_path),
        "--monitor",
        "--apply",
        "--cycles",
        "0",
        "--interval-seconds",
        str(float(interval_seconds)),
        "--task-manager-agent",
        task_manager_agent,
    ]
    creation_flags = 0
    close_fds = True
    if os.name == "nt":
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creation_flags |= subprocess.DETACHED_PROCESS
        close_fds = False
    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=close_fds,
            creationflags=creation_flags,
        )
    except Exception as exc:
        return False, None, str(exc)
    return (
        True,
        {
            "agent": str(task_manager_agent),
            "pid": int(process.pid),
            "command": " ".join(command),
            "interval_seconds": float(interval_seconds),
        },
        None,
    )


def _normalize_scope_name(value: str | None) -> str:
    return str(value or "").strip()


def _normalize_dispatch_target_workers(value: int | None) -> int:
    return max(DEFAULT_MIN_AUTO_DISPATCH_TARGET_WORKERS, int(value or DEFAULT_AUTO_DISPATCH_TARGET_WORKERS))


def _is_worker_claim(role: str | None, parent: str | None) -> bool:
    if _agent_key(role) == "worker":
        return True
    return _agent_key(parent) not in {"", "none"}


def _extract_claim_agent(claim_row: object) -> str:
    if claim_row is None:
        return ""
    if isinstance(claim_row, str):
        raw = str(claim_row).strip()
        if raw.startswith("- "):
            raw = raw[2:]
        for piece in raw.split(";"):
            if "=" not in piece:
                continue
            key, value = piece.split("=", 1)
            if key.strip().lower() == "agent":
                return value.strip()
        return ""
    if isinstance(claim_row, dict):
        return str(claim_row.get("agent", "") or "")
    return str(getattr(claim_row, "agent", "") or "")


def _is_task_manager_claimed(workboard_path: Path, task_manager_agent: str) -> bool:
    manager_key = _agent_key(task_manager_agent)
    try:
        ok, active_claims = claim_tool.list_claims(workboard_path)  # type: ignore[misc]
    except Exception:
        return False
    if not ok or not isinstance(active_claims, Sequence):
        return False
    for row in active_claims:
        if _agent_key(_extract_claim_agent(row)) == manager_key:
            return True
    return False


def _default_task_manager_scope(workboard_path: Path) -> str:
    try:
        scoped = workboard_path.parent.resolve().relative_to(ROOT.resolve())
        return str(scoped).replace("\\", "/")
    except Exception:
        return str(workboard_path.parent).replace("\\", "/")


def _claim_task_manager_position(
    *,
    workboard_path: Path,
    task_manager_agent: str,
) -> tuple[bool, str]:
    claim_scope = _default_task_manager_scope(workboard_path)
    ok, message = claim_tool.claim(
        workboard_path,
        agent=task_manager_agent,
        scope=claim_scope,
        task="[WIP][TM] task-manager control loop",
        name=task_manager_agent,
        role="solo",
        parent="none",
    )
    if not ok:
        return False, str(message)
    return True, str(message)


def _start_task_manager_loop(
    *,
    workboard_path: Path,
    task_manager_agent: str,
    interval_seconds: float = DEFAULT_TASK_MANAGER_LOOP_INTERVAL_SECONDS,
) -> tuple[bool, str, int]:
    manager_script = (ROOT / "scripts" / "workboard_task_manager.py").resolve()
    command = [
        sys.executable,
        str(manager_script),
        "--workboard",
        str(workboard_path),
        "--monitor",
        "--apply",
        "--cycles",
        "0",
        "--interval-seconds",
        str(float(interval_seconds)),
        "--task-manager-agent",
        task_manager_agent,
    ]
    try:
        process = subprocess.run(command, cwd=str(ROOT), check=False)
    except FileNotFoundError as exc:
        return False, str(exc), 1
    return True, "", int(process.returncode or 0)


def _start_worker_loop(
    *,
    workboard_path: Path,
    agent: str,
    poll_seconds: float = 15.0,
) -> tuple[bool, str, int]:
    worker_script = (ROOT / "scripts" / "workboard_worker.py").resolve()
    command = [
        sys.executable,
        str(worker_script),
        "--workboard",
        str(workboard_path),
        "--agent",
        agent,
        "--cycles",
        "0",
        "--poll-seconds",
        str(float(poll_seconds)),
    ]
    try:
        process = subprocess.run(command, cwd=str(ROOT), check=False)
    except FileNotFoundError as exc:
        return False, str(exc), 1
    return True, "", int(process.returncode or 0)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a WIP claim for the current agent and print env exports."
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    parser.add_argument(
        "--agent",
        default="",
        help=(
            "Agent id override (otherwise resolved from "
            f"{agent_identity.resolution_help(include_name_fallback=True)})."
        ),
    )
    parser.add_argument(
        "--scope",
        required=True,
        help="Claim scope path(s), comma-separated.",
    )
    parser.add_argument(
        "--task",
        default="",
        help="Task description. If omitted, defaults to current branch.",
    )
    parser.add_argument(
        "--name",
        help="Claim name/callsign (defaults to resolved agent id when omitted).",
    )
    parser.add_argument(
        "--role",
        choices=list(CLAIM_ROLE_VALUES),
        help="Claim role when bootstrapping (defaults to parent for non-task-manager agents).",
    )
    parser.add_argument(
        "--parent",
        help="Parent agent id for worker role claims.",
    )
    parser.add_argument(
        "--ticket",
        default="",
        help="Handshake ticket id (default: generated HSK-YYYYMMDD-HHMMSS).",
    )
    parser.add_argument(
        "--auto-dispatch",
        dest="auto_dispatch",
        action="store_true",
        help="Run automatic sub-agent dispatch after claiming. Enabled by default for non-task-manager agents.",
    )
    parser.add_argument(
        "--no-auto-dispatch",
        dest="auto_dispatch",
        action="store_false",
        help="Disable automatic dispatch after bootstrap claim.",
    )
    parser.set_defaults(
        auto_dispatch=True,
        dispatch_no_temp_creator=False,
        dispatch_release_ready=True,
    )
    parser.add_argument(
        "--dispatch-target-workers",
        type=int,
        default=DEFAULT_AUTO_DISPATCH_TARGET_WORKERS,
        help="Target active workers for bootstrap auto-dispatch (default: handful, currently 3).",
    )
    parser.add_argument(
        "--dispatch-dry-run",
        action="store_true",
        help="Evaluate delegation readiness without claiming worker lanes.",
    )
    parser.add_argument(
        "--start-worker-loops",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When dispatching, auto-start detached worker loops for newly claimed lanes.",
    )
    parser.add_argument(
        "--worker-loop-poll-seconds",
        type=float,
        default=DEFAULT_WORKER_LOOP_POLL_SECONDS,
        help="Poll interval for auto-started worker loops (default: 15.0).",
    )
    parser.add_argument(
        "--dispatch-max-suggestions",
        type=int,
        default=DEFAULT_DISPATCH_MAX_SUGGESTIONS,
        help=(
            f"Max delegation suggestions considered during bootstrap dispatch "
            f"(default: {DEFAULT_DISPATCH_MAX_SUGGESTIONS})."
        ),
    )
    parser.add_argument(
        "--dispatch-release-ready",
        dest="dispatch_release_ready",
        action="store_true",
        help="With auto-dispatch, release READY worker claims before re-filling (default: enabled).",
    )
    parser.add_argument(
        "--no-dispatch-release-ready",
        dest="dispatch_release_ready",
        action="store_false",
        help="With auto-dispatch, keep READY worker claims in place.",
    )
    parser.add_argument(
        "--dispatch-no-temp-creator",
        action="store_true",
        help="With auto-dispatch, skip temporary task-creator fallback when no delegated task is available.",
    )
    parser.add_argument(
        "--dispatch-allow-temp-creator",
        dest="dispatch_no_temp_creator",
        action="store_false",
        help="With auto-dispatch, allow temporary task-creator fallback when no delegated task is available.",
    )
    parser.add_argument(
        "--dispatch-no-temp-creator-notice",
        action="store_true",
        help="With auto-dispatch and fallback, skip coordination notice to task manager.",
    )
    parser.add_argument(
        "--dispatch-task-manager-agent",
        default=DEFAULT_TASK_MANAGER_AGENT,
        help=(
            "Task-manager agent for temp task-creator coordination during bootstrap dispatch "
            f"(default: {DEFAULT_TASK_MANAGER_AGENT})."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Emit extra claim/dispatch diagnostics for rapid troubleshooting.",
    )
    parser.add_argument(
        "--run-worker-loop",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For worker-role claims, start a persistent `workboard_worker.py --cycles 0` loop after bootstrap.",
    )
    parser.add_argument(
        "--run-task-manager-loop",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "When task-manager claim is empty or agent is an orchestrator identity, "
            "start a persistent `workboard_task_manager.py --monitor --cycles 0` loop."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    agent = _resolve_agent(args.agent)
    if not agent:
        message = (
            "agent id is required; set THOMAS_AGENT_ID or AGENT_ID "
            "(CODEX_AGENT_ID/GEMINI_AGENT_ID/CLAUDE_AGENT_ID also supported) "
            "or pass --agent"
        )
        if args.json:
            payload = {
                "ok": False,
                "agent": "",
                "workboard": str(workboard_path),
                "error": message,
            }
            print(json.dumps(payload, sort_keys=True))
            return 1
        else:
            print("Agent bootstrap claim: FAIL")
            print(f"- {message}")
        return 1

    task_manager_agent = _normalize_scope_name(args.dispatch_task_manager_agent or DEFAULT_TASK_MANAGER_AGENT)
    if not task_manager_agent:
        task_manager_agent = DEFAULT_TASK_MANAGER_AGENT

    should_auto_claim_task_manager = (
        not args.json
        and _to_bool(args.run_task_manager_loop)
        and not _is_task_manager_agent(agent)
        and not args.role
        and not _normalize_scope_name(args.parent)
    )
    task_manager_bootstrapped = False
    task_manager_loop_payload: dict[str, object] | None = None
    task_manager_loop_error: str | None = None
    if should_auto_claim_task_manager and not _is_task_manager_claimed(workboard_path, task_manager_agent):
        ok_claim_manager, claim_manager_message = _claim_task_manager_position(
            workboard_path=workboard_path,
            task_manager_agent=task_manager_agent,
        )
        if ok_claim_manager:
            task_manager_bootstrapped = True
            print("- auto-claimed missing task orchestrator position:")
            print(f"  - {claim_manager_message}")
            if _to_bool(args.run_task_manager_loop):
                print("- starting persistent task-manager loop:")
                print(
                    f"  - command: python scripts/workboard_task_manager.py --monitor --apply --cycles 0 "
                    f"--interval-seconds 30 --task-manager-agent \"{task_manager_agent}\""
                )
                ok_loop, loop_payload, loop_error = _spawn_task_manager_loop(
                    workboard_path=workboard_path,
                    task_manager_agent=task_manager_agent,
                    interval_seconds=DEFAULT_TASK_MANAGER_LOOP_INTERVAL_SECONDS,
                )
                if not ok_loop:
                    task_manager_loop_error = str(loop_error or "")
                    print(f"- task manager loop failed: {task_manager_loop_error}")
                    return 1
                task_manager_loop_payload = loop_payload
                if loop_payload:
                    print(f"  - pid={int(loop_payload.get('pid') or 0)}")
        else:
            print(f"- unable to auto-claim task manager position: {claim_manager_message}")

    role = _resolve_role(agent, args.role, args.parent)
    claim_name = _resolve_name(agent, args.name, role=role)
    name_source = _name_resolution_source(
        args.name,
        role=role,
        agent=agent or "",
        auto_dispatch=_to_bool(args.auto_dispatch),
    )
    task = _build_task(args.task, args.ticket)
    ok, message = claim_tool.claim(
        workboard_path,
        agent=agent,
        scope=args.scope,
        task=task,
        name=claim_name,
        role=role,
        parent=args.parent,
    )
    if not ok:
        if args.json:
            payload = {
                "ok": False,
                "agent": agent,
                "scope": args.scope,
                "task": task,
                "workboard": str(workboard_path),
                "error": message,
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Agent bootstrap claim: FAIL")
            print(f"- {message}")
        return 1

    do_dispatch = (
        _to_bool(args.auto_dispatch)
        and role == "parent"
        and not _is_task_manager_agent(agent)
    )

    dispatch_target_workers = _normalize_dispatch_target_workers(args.dispatch_target_workers)
    start_worker_loops = bool(args.start_worker_loops)
    dispatch_result: dict[str, object] | None = None
    dispatch_error: str | None = None
    dispatch_mode = "disabled"
    started_worker_loops: list[dict[str, object]] = []
    worker_loop_failures: list[str] = []
    if do_dispatch:
        if _to_bool(args.dispatch_dry_run):
            dispatch_mode = "dry-run"
            ok_suggest, suggest_result = claim_tool.suggest_delegation(
                workboard_path,
                parent_agent=agent,
                max_suggestions=max(1, int(args.dispatch_max_suggestions or DEFAULT_DISPATCH_MAX_SUGGESTIONS)),
            )
            if not ok_suggest:
                dispatch_error = str(suggest_result)
                dispatch_result = {"error": dispatch_error}
            else:
                result_payload = dict(suggest_result) if isinstance(suggest_result, dict) else {}
                dispatch_result = {
                    "ready_suggestion_count": len(list(result_payload.get("ready_suggestions") or [])),
                    "ready_suggestions": list(result_payload.get("ready_suggestions") or []),
                    "blocked_candidates": list(result_payload.get("blocked_candidates") or []),
                    "generated_claim_commands": list(result_payload.get("generated_claim_commands") or []),
                    "ready_count": len(list(result_payload.get("ready_suggestions") or [])),
                }
        else:
            dispatch_mode = "live"
            ok_dispatch, dispatch_payload = claim_tool.dispatch_workers(
                workboard_path,
                parent_agent=agent,
                target_workers=dispatch_target_workers,
                max_suggestions=int(args.dispatch_max_suggestions or DEFAULT_DISPATCH_MAX_SUGGESTIONS),
                release_ready=_to_bool(args.dispatch_release_ready),
                enable_temp_creator=not _to_bool(args.dispatch_no_temp_creator),
                task_manager_agent=_normalize_scope_name(
                    args.dispatch_task_manager_agent or DEFAULT_TASK_MANAGER_AGENT
                ),
                notify_task_manager=not _to_bool(args.dispatch_no_temp_creator_notice),
            )
            dispatch_error = None if ok_dispatch else str(dispatch_payload)
            if isinstance(dispatch_payload, dict):
                dispatch_result = dict(dispatch_payload)
            else:
                dispatch_result = {"error": str(dispatch_payload)}
            if not ok_dispatch:
                dispatch_result = {"error": dispatch_error}
            if start_worker_loops and isinstance(dispatch_result, dict):
                claimed_workers = list(dispatch_result.get("claimed_workers") or [])
                for item in claimed_workers:
                    if not isinstance(item, dict):
                        continue
                    worker_agent = str(item.get("agent") or "").strip()
                    if not worker_agent:
                        continue
                    ok_loop, loop_payload, loop_error = _spawn_worker_loop(
                        workboard_path=workboard_path,
                        worker_agent=worker_agent,
                        task_manager_agent=_normalize_scope_name(
                            args.dispatch_task_manager_agent or DEFAULT_TASK_MANAGER_AGENT
                        ),
                        poll_seconds=max(1.0, float(args.worker_loop_poll_seconds)),
                    )
                    if ok_loop and isinstance(loop_payload, dict):
                        started_worker_loops.append(loop_payload)
                    else:
                        worker_loop_failures.append(f"{worker_agent}: {loop_error or 'unknown spawn error'}")
            if worker_loop_failures and isinstance(dispatch_result, dict):
                dispatch_result["worker_loop_failures"] = worker_loop_failures

    ps_cmd = f'$env:AGENT_ID="{agent}"; $env:THOMAS_AGENT_ID="{agent}"'
    if args.json:
        payload = {
            "ok": True,
            "agent": agent,
            "scope": args.scope,
            "task": task,
            "role": role,
            "parent": _normalize_scope_name(args.parent or "none"),
            "name": claim_name,
            "auto_dispatch_enabled": _to_bool(args.auto_dispatch),
            "auto_dispatch_release_ready": _to_bool(args.dispatch_release_ready),
            "dispatch_target_workers": dispatch_target_workers,
            "dispatch_mode": dispatch_mode,
            "dispatch_dry_run": _to_bool(args.dispatch_dry_run),
            "auto_dispatched": bool(do_dispatch),
            "start_worker_loops": start_worker_loops,
            "worker_loop_count": len(started_worker_loops),
            "task_manager": task_manager_agent,
            "task_manager_auto_claimed": task_manager_bootstrapped,
            "task_manager_loop": task_manager_loop_payload or {},
            "task_manager_loop_error": task_manager_loop_error,
            "dispatch_error": dispatch_error,
            "dispatch": dispatch_result,
            "spawned_worker_loops": started_worker_loops,
            "workboard": str(workboard_path),
            "claim_result": message,
            "powershell_export": ps_cmd,
        }
        if args.debug:
            payload["debug"] = {
                "resolved_name": claim_name,
                "name_resolution_source": name_source,
                "dispatch_called": bool(do_dispatch),
                "dispatch_mode": dispatch_mode,
                "dispatch_target_workers": dispatch_target_workers,
                "auto_dispatch_target_workers": int(dispatch_target_workers),
                "auto_dispatch_requested": _to_bool(args.auto_dispatch),
                "run_task_manager_loop": bool(_is_task_manager_agent(agent) and _to_bool(args.run_task_manager_loop)),
                "run_worker_loop": bool(_is_worker_claim(role, args.parent) and _to_bool(args.run_worker_loop)),
                "dispatch_dry_run": _to_bool(args.dispatch_dry_run),
                "start_worker_loops": start_worker_loops,
                "worker_loop_count": len(started_worker_loops),
                "worker_loop_failures": worker_loop_failures,
                "task_manager_bootstrapped": task_manager_bootstrapped,
                "task_manager_loop": task_manager_loop_payload or {},
                "task_manager_loop_error": task_manager_loop_error,
            }
        print(json.dumps(payload, sort_keys=True))
        return 0 if dispatch_error is None else 1

    if _is_worker_claim(role, args.parent) and _to_bool(args.run_worker_loop) and not _is_task_manager_agent(agent):
        print("- starting persistent worker loop:")
        print("  - command: python scripts/workboard_worker.py --agent \"...\" --cycles 0 --poll-seconds 15")
        ok_loop, loop_error, loop_rc = _start_worker_loop(
            workboard_path=workboard_path,
            agent=agent,
        )
        if not ok_loop:
            print(f"- worker loop failed: {loop_error}")
            return 1
        if loop_rc:
            print(f"- worker loop exited with code {loop_rc}")
            return loop_rc

    if _is_task_manager_agent(agent) and _to_bool(args.run_task_manager_loop) and not args.json:
        print("- starting persistent task-manager loop:")
        print(
            f"  - command: python scripts/workboard_task_manager.py --monitor --apply --cycles 0 "
            f"--interval-seconds 30 --task-manager-agent \"{task_manager_agent}\""
        )
        ok_loop, loop_payload, loop_error = _spawn_task_manager_loop(
            workboard_path=workboard_path,
            task_manager_agent=task_manager_agent,
            interval_seconds=DEFAULT_TASK_MANAGER_LOOP_INTERVAL_SECONDS,
        )
        if not ok_loop:
            print(f"- task manager loop failed: {loop_error}")
            return 1
        task_manager_loop_payload = loop_payload
        if task_manager_loop_payload:
            print(f"  - pid={int(task_manager_loop_payload.get('pid') or 0)}")

    print("Agent bootstrap claim: PASS")
    print(f"- agent: {agent}")
    print(f"- task: {task}")
    print(f"- role: {role or 'auto'}")
    if args.parent:
        print(f"- parent: {_normalize_scope_name(args.parent)}")
    if claim_name:
        print(f"- name: {claim_name}")
    print(f"- {message}")
    if args.debug:
        print("- debug mode: enabled")
        print(f"- resolved name: {claim_name}")
        print(f"- name resolution source: {name_source}")
        print(f"- run worker loop: {_is_worker_claim(role, args.parent) and _to_bool(args.run_worker_loop)}")
        print(f"- run task-manager loop: {_is_task_manager_agent(agent) and _to_bool(args.run_task_manager_loop)}")
        print(f"- task-manager auto-claimed: {task_manager_bootstrapped}")
        if task_manager_loop_payload:
            loop_pid = int(task_manager_loop_payload.get("pid") or 0)
            if loop_pid:
                print(f"- task-manager loop pid: {loop_pid}")
        if task_manager_loop_error:
            print(f"- task-manager loop error: {task_manager_loop_error}")
    if do_dispatch:
        if dispatch_error:
            print(f"- dispatch: FAIL ({dispatch_error})")
        else:
            print(f"- dispatch: PASS ({dispatch_mode})")
            if dispatch_mode != "dry-run":
                print("- handoff intent: automatically request reassignment after each completion")
            if dispatch_result:
                claimed_workers = list(dispatch_result.get("claimed_workers") or [])
                released_workers = list(dispatch_result.get("released_workers") or [])
                if released_workers:
                    print("- released READY workers:")
                    for worker in released_workers:
                        print(f"  - {worker}")
                if claimed_workers:
                    print("- dispatched workers:")
                    for item in claimed_workers:
                        if isinstance(item, dict):
                            child_agent = str(item.get("agent") or "").strip()
                            task_id = str(item.get("task_id") or "").strip()
                            scope = str(item.get("scope") or "").strip()
                            print(f"  - {child_agent} => {task_id} ({scope})")
                else:
                    print("- no worker claims created in this dispatch pass")
                temp_payload = dispatch_result.get("temp_task_creator")
                if isinstance(temp_payload, dict):
                    temp_status = str(temp_payload.get("status") or "").strip()
                    holder = str(temp_payload.get("holder_agent") or "").strip()
                    manager = str(temp_payload.get("manager_agent") or "").strip()
                    if temp_status and temp_status not in {"disabled"}:
                        print(
                            f"- temp-task-creator={temp_status}; holder={holder or 'none'}; "
                            f"manager={manager or 'none'}"
                        )
                if _to_bool(args.dispatch_dry_run):
                    ready = int(dispatch_result.get("ready_suggestion_count") or 0)
                    blocked = list(dispatch_result.get("blocked_candidates") or [])
                    print(f"- ready suggestions: {ready}")
                    if blocked:
                        print(f"- blocked candidates: {len(blocked)}")
                if start_worker_loops:
                    if started_worker_loops:
                        print(f"- started {len(started_worker_loops)} worker loop(s)")
                        for loop_payload in started_worker_loops:
                            loop_agent = str(loop_payload.get("agent") or "").strip()
                            loop_pid = int(loop_payload.get("pid") or 0)
                            if loop_agent and loop_pid:
                                print(f"  - {loop_agent}: pid={loop_pid}")
                    elif dispatch_mode == "live":
                        print("- worker loops: not started (no newly claimed workers)")
                if worker_loop_failures:
                    print("- worker loop startup failures:")
                    for item in worker_loop_failures:
                        print(f"  - {item}")
    else:
        print("- auto-dispatch: skipped")
    print("- set explicit id for this shell:")
    print(f"  {ps_cmd}")
    return 1 if dispatch_error else 0


if __name__ == "__main__":
    raise SystemExit(run())
