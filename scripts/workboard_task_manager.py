#!/usr/bin/env python3
"""Task-manager automation for WORKBOARD execution protocol.

This script provides seven operations:
1) Ensure every active/up-for-grabs task has durable PLAN.md and PROBLEM.md scaffolds.
2) Detect stale/offline agents and move their work to a recoverable state.
3) Reactivate a parked task for an agent.
4) Sync visible agent session registry (alias + session id lifecycle).
5) Capture task-orchestration preferences with summary+verbatim weighting.
6) Sync task-to-specialist routing rows on the board.
7) Resolve the specialist route for a specific task or ad-hoc task description.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

try:
    import scripts.workboard_task_manager_sweep as workboard_task_manager_sweep
    from scripts.workboard_task_manager_base import (
        DEFAULT_MAX_AGENT_SILENCE_MINUTES,
        DEFAULT_MAX_DISPATCH_PER_CYCLE,
        DEFAULT_MAX_IDLE_MINUTES,
        DEFAULT_MONITOR_CYCLES,
        DEFAULT_MONITOR_INTERVAL_SECONDS,
        DEFAULT_PLAN_ROOT,
        DEFAULT_PROBLEM_ROOT,
        DEFAULT_SESSION_LEASE_MINUTES,
        DEFAULT_TASK_MANAGER_AGENT,
        DEFAULT_WORKBOARD,
        ROOT,
        _is_orchestrator_agent,
        _line_commit_unix,
        _parse_now,
    )
    from scripts.workboard_task_manager_messages import (
        _capture_task_ecosystem_preference,
        _monitor_loop,
        _specialist_for_task,
        _sync_task_specialists,
    )
    from scripts.workboard_task_manager_plans import _sync_task_plans
    from scripts.workboard_task_manager_reactivate import (
        _auto_start_task_for_agent,
        _reactivate_task,
        _resolve_auto_start_agent,
        set_task_status,
    )
    from scripts.workboard_task_manager_sessions import (
        _sync_agent_sessions,
        _sync_inferred_presence_claims,
    )

    _sweep_inactive = workboard_task_manager_sweep._sweep_inactive
except Exception:  # pragma: no cover
    import workboard_task_manager_sweep  # type: ignore
    from workboard_task_manager_base import (
        DEFAULT_MAX_AGENT_SILENCE_MINUTES,
        DEFAULT_MAX_DISPATCH_PER_CYCLE,
        DEFAULT_MAX_IDLE_MINUTES,
        DEFAULT_MONITOR_CYCLES,
        DEFAULT_MONITOR_INTERVAL_SECONDS,
        DEFAULT_PLAN_ROOT,
        DEFAULT_PROBLEM_ROOT,
        DEFAULT_SESSION_LEASE_MINUTES,
        DEFAULT_TASK_MANAGER_AGENT,
        DEFAULT_WORKBOARD,
        ROOT,
        _is_orchestrator_agent,
        _line_commit_unix,
        _parse_now,
    )
    from workboard_task_manager_messages import (
        _capture_task_ecosystem_preference,
        _monitor_loop,
        _specialist_for_task,
        _sync_task_specialists,
    )
    from workboard_task_manager_plans import _sync_task_plans
    from workboard_task_manager_reactivate import (
        _auto_start_task_for_agent,
        _reactivate_task,
        _resolve_auto_start_agent,
        set_task_status,
    )
    from workboard_task_manager_sessions import (
        _sync_agent_sessions,
        _sync_inferred_presence_claims,
    )

    _sweep_inactive = workboard_task_manager_sweep._sweep_inactive


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task-manager automation for WORKBOARD protocols.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--auto-start",
        action="store_true",
        help="Auto-claim and move a task to in_progress for --agent when no working task is active.",
    )
    actions.add_argument("--sync-plans", action="store_true", help="Ensure per-task plan entries/files exist.")
    actions.add_argument("--sweep-inactive", action="store_true", help="Detect and process inactive agents.")
    actions.add_argument("--reactivate", action="store_true", help="Reactivate a task from Up For Grabs.")
    actions.add_argument("--sync-sessions", action="store_true", help="Sync active/inactive agent sessions.")
    actions.add_argument(
        "--monitor",
        action="store_true",
        help=(
            "Run monitor loop: sync board, recover swarms, auto-start claimed agents, "
            "ping silence, sweep inactive, and dispatch idle agents."
        ),
    )
    actions.add_argument(
        "--sync-inferred", action="store_true", help="Sync inferred presence claims/tasks into the board."
    )
    actions.add_argument(
        "--sync-specialists",
        action="store_true",
        help="Sync task-type specialist routes for active/up-for-grabs tasks.",
    )
    actions.add_argument(
        "--specialist-for-task",
        action="store_true",
        help="Return specialist route for one board task id or ad-hoc scope/summary text.",
    )
    actions.add_argument(
        "--capture-preference",
        action="store_true",
        help="Store task-orchestration preference (summary + verbatim) in preferences.",
    )

    parser.add_argument("--apply", action="store_true", help="Apply mutations instead of dry-run checks.")
    parser.add_argument("--now", default="", help="Optional ISO now override for deterministic checks.")

    parser.add_argument("--plan-root", default=DEFAULT_PLAN_ROOT, help="Plan root path for generated PLAN.md files.")
    parser.add_argument(
        "--problem-root",
        default=DEFAULT_PROBLEM_ROOT,
        help="Problem root path for generated PROBLEM.md files.",
    )

    parser.add_argument(
        "--max-idle-minutes",
        type=float,
        default=DEFAULT_MAX_IDLE_MINUTES,
        help="Idle threshold in minutes for inactive-agent detection (default: 1).",
    )
    parser.add_argument(
        "--task-manager-agent",
        default=DEFAULT_TASK_MANAGER_AGENT,
        help="Agent id assigned as issue owner/notification target.",
    )
    parser.add_argument(
        "--max-agent-silence-minutes",
        type=float,
        default=DEFAULT_MAX_AGENT_SILENCE_MINUTES,
        help="Silence threshold before pinging active-task agents (default: 5).",
    )
    parser.add_argument(
        "--session-lease-minutes",
        type=float,
        default=DEFAULT_SESSION_LEASE_MINUTES,
        help="Lease TTL for active sessions before they are considered expired (default: 5).",
    )
    parser.add_argument(
        "--max-dispatch-per-cycle",
        type=int,
        default=DEFAULT_MAX_DISPATCH_PER_CYCLE,
        help="Maximum up-for-grabs tasks to auto-dispatch per monitor cycle (default: 2).",
    )
    parser.add_argument(
        "--online-lookback-minutes",
        type=float,
        default=30.0,
        help="Lookback window used to consider an agent online via message traffic (default: 30).",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=DEFAULT_MONITOR_CYCLES,
        help="Monitor cycle count (0 means run continuously; default: 1).",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_MONITOR_INTERVAL_SECONDS,
        help="Delay between monitor cycles (default: 30).",
    )
    parser.add_argument(
        "--no-swarm-recovery",
        action="store_true",
        help="Disable automatic swarm missing-agent relaunch in --monitor mode.",
    )
    parser.add_argument(
        "--no-idle-dispatch",
        action="store_true",
        help="Disable automatic up-for-grabs dispatch to online idle agents in --monitor mode.",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Disable automatic claimed-agent auto-start in --monitor mode.",
    )

    parser.add_argument("--task-id", default="", help="Task id for --reactivate or --specialist-for-task.")
    parser.add_argument("--agent", default="", help="Agent id for --reactivate.")
    parser.add_argument("--summary", default="", help="Optional summary override for --reactivate.")
    parser.add_argument("--scope", default="", help="Optional scope override for --reactivate.")
    parser.add_argument("--task-scope", default="", help="Scope text for ad-hoc --specialist-for-task routing.")
    parser.add_argument("--task-summary", default="", help="Summary text for ad-hoc --specialist-for-task routing.")
    parser.add_argument("--name", default="", help="Optional claim display name for --reactivate.")
    parser.add_argument("--role", default="", help="Optional role for --reactivate (solo|parent|worker).")
    parser.add_argument("--parent", default="", help="Optional parent id for --reactivate worker role.")
    parser.add_argument("--user-id", default="default", help="Preferences user id for --capture-preference.")
    parser.add_argument(
        "--preference-summary",
        default="",
        help="Preference summary used as primary weighted instruction for --capture-preference.",
    )
    parser.add_argument(
        "--preference-verbatim",
        default="",
        help="Verbatim user instruction to retain for audit context with --capture-preference.",
    )

    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists():
        payload = {
            "action": "workboard_task_manager",
            "ok": False,
            "error": f"missing workboard file: {workboard_path}",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    try:
        now = _parse_now(args.now)
    except Exception as exc:
        payload = {"action": "workboard_task_manager", "ok": False, "error": f"invalid --now value: {exc}"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    if args.max_idle_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--max-idle-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.max_agent_silence_minutes <= 0:
        payload = {
            "action": "workboard_task_manager",
            "ok": False,
            "error": "--max-agent-silence-minutes must be > 0",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.max_dispatch_per_cycle < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--max-dispatch-per-cycle must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.session_lease_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--session-lease-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.online_lookback_minutes <= 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--online-lookback-minutes must be > 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.cycles < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--cycles must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1
    if args.interval_seconds < 0:
        payload = {"action": "workboard_task_manager", "ok": False, "error": "--interval-seconds must be >= 0"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: FAIL")
            print(f"- {payload['error']}")
        return 1

    if args.monitor:
        now_seed = now if str(args.now).strip() else None
        ok_plan_sync, plan_sync_details = _sync_task_plans(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            require_claims_to_have_active_task=False,
            apply=bool(args.apply),
            now=now,
        )
        if not ok_plan_sync:
            payload = {
                "action": "monitor",
                "ok": False,
                "workboard": str(workboard_path),
                "plan_sync": plan_sync_details,
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- plan sync failed: {payload.get('error', plan_sync_details.get('error', 'unknown'))}")
            return 1
        ok, details = _monitor_loop(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            task_manager_agent=str(args.task_manager_agent),
            max_idle_minutes=float(args.max_idle_minutes),
            max_agent_silence_minutes=float(args.max_agent_silence_minutes),
            session_lease_minutes=float(args.session_lease_minutes),
            max_dispatch_per_cycle=int(args.max_dispatch_per_cycle),
            online_lookback_minutes=float(args.online_lookback_minutes),
            run_swarm_recovery=not bool(args.no_swarm_recovery),
            run_auto_start=not bool(args.no_auto_start),
            run_idle_dispatch=not bool(args.no_idle_dispatch),
            require_claims_to_have_active_task=False,
            cycles=int(args.cycles),
            interval_seconds=float(args.interval_seconds),
            now_seed=now_seed,
            apply=bool(args.apply),
        )
        payload = {
            "action": "monitor",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            "plan_sync": plan_sync_details,
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            print(
                f"- cycles run: {payload.get('cycle_count', 0)}; "
                f"swarm recovery: {payload.get('run_swarm_recovery')}; "
                f"auto-start: {payload.get('run_auto_start')}; "
                f"idle dispatch: {payload.get('run_idle_dispatch')}"
            )
            if ok_plan_sync:
                print(
                    "- plan sync: "
                    f"tracked={payload.get('plan_sync', {}).get('tracked_task_count', 0)}; "
                    f"created plans={payload.get('plan_sync', {}).get('created_plan_count', 0)}; "
                    f"created problems={payload.get('plan_sync', {}).get('created_problem_count', 0)}; "
                    f"missing plans={payload.get('plan_sync', {}).get('missing_plan_count', 0)}; "
                    f"missing problems={payload.get('plan_sync', {}).get('missing_problem_count', 0)}"
                )
        return 0 if ok else 1

    if args.sync_plans:
        ok, details = _sync_task_plans(
            workboard_path=workboard_path,
            plan_root=str(args.plan_root),
            problem_root=str(args.problem_root),
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
            now=now,
        )
        payload = {"action": "sync_plans", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- tracked tasks: {payload.get('tracked_task_count', 0)}; "
                    f"plan entries: {payload.get('plan_entry_count', 0)}; "
                    f"created plans: {payload.get('created_plan_count', 0)}; "
                    f"problem entries: {payload.get('problem_entry_count', 0)}; "
                    f"created problems: {payload.get('created_problem_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync plans failed')}")
        return 0 if ok else 1

    if args.sync_sessions:
        ok, details = _sync_agent_sessions(
            workboard_path=workboard_path,
            now=now,
            session_lease_minutes=float(args.session_lease_minutes),
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sync_sessions", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- session entries: {payload.get('session_entry_count', 0)}; "
                    f"created session ids: {payload.get('created_session_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync sessions failed')}")
        return 0 if ok else 1

    if args.sync_inferred:
        ok, details = _sync_inferred_presence_claims(
            workboard_path=workboard_path,
            now=now,
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sync_inferred", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- inferred candidates: {payload.get('candidate_count', 0)}; "
                    f"applied: {payload.get('applied_count', 0)}; "
                    f"suppressed: {payload.get('suppressed_count', 0)}; "
                    f"expired: {payload.get('expired_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync inferred failed')}")
        return 0 if ok else 1

    if args.sync_specialists:
        ok, details = _sync_task_specialists(
            workboard_path=workboard_path,
            now=now,
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sync_specialists", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- routed tasks: {payload.get('routed_task_count', 0)}; "
                    f"tracked tasks: {payload.get('tracked_task_count', 0)}"
                )
            else:
                print(f"- {payload.get('error', 'sync specialists failed')}")
        return 0 if ok else 1

    if args.specialist_for_task:
        ok, details = _specialist_for_task(
            workboard_path=workboard_path,
            task_id=str(args.task_id).strip(),
            task_scope=str(args.task_scope).strip(),
            task_summary=str(args.task_summary).strip(),
        )
        payload = {"action": "specialist_for_task", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(f"- task `{payload.get('task_id')}` -> {payload.get('task_type')} / {payload.get('specialist')}")
            else:
                print(f"- {payload.get('error', 'specialist resolution failed')}")
        return 0 if ok else 1

    if args.sweep_inactive:
        workboard_task_manager_sweep._line_commit_unix = _line_commit_unix
        ok, details = _sweep_inactive(
            workboard_path=workboard_path,
            max_idle_minutes=float(args.max_idle_minutes),
            task_manager_agent=str(args.task_manager_agent),
            now=now,
            require_claims_to_have_active_task=True,
            apply=bool(args.apply),
        )
        payload = {"action": "sweep_inactive", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            print(
                f"- stale claims: {payload.get('stale_claim_count', 0)} (threshold {float(args.max_idle_minutes):.2f}m)"
            )
            if args.apply:
                print(
                    f"- moved tasks: {payload.get('moved_task_count', 0)}; "
                    f"released agents: {payload.get('released_agent_count', 0)}"
                )
                print(f"- coordination pings: {payload.get('sent_message_count', 0)}")
            if not ok:
                for item in payload.get("errors", []):
                    print(f"- {item}")
        return 0 if ok else 1

    if args.auto_start:
        ok_agent, resolved_agent, agent_error = _resolve_auto_start_agent(args.agent)
        if not ok_agent:
            payload = {"action": "auto_start", "ok": False, "error": agent_error}
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1

        ok, details = _auto_start_task_for_agent(
            workboard_path=workboard_path,
            agent=resolved_agent,
            task_manager_agent=str(args.task_manager_agent),
            require_claims_to_have_active_task=False,
        )
        payload = {
            "action": "auto_start",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            "agent": resolved_agent,
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                source = str(details.get("source") or "unknown")
                print(f"- started task `{details.get('task_id')}` for `{resolved_agent}` (source: {source})")
            else:
                print(f"- {details.get('error', 'auto-start failed')}")
        return 0 if ok else 1

    if args.reactivate:
        if _is_orchestrator_agent(str(args.agent)):
            payload = {
                "action": "reactivate",
                "ok": False,
                "error": "reactivate is disabled for orchestrator agents",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1
        if not str(args.task_id).strip() or not str(args.agent).strip():
            payload = {
                "action": "reactivate",
                "ok": False,
                "error": "--task-id and --agent are required for --reactivate",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard task manager: FAIL")
                print(f"- {payload['error']}")
            return 1
        ok, details = _reactivate_task(
            workboard_path=workboard_path,
            task_id=str(args.task_id).strip(),
            agent=str(args.agent).strip(),
            task_summary=str(args.summary).strip() or None,
            scope_override=str(args.scope).strip() or None,
            name=str(args.name).strip() or None,
            role=str(args.role).strip() or None,
            parent=str(args.parent).strip() or None,
        )
        if ok:
            task_id = str(details.get("task_id") or args.task_id).strip()
            ok_status, payload_status = set_task_status(
                workboard_path,
                task_id=task_id,
                status="in_progress",
                actor=str(args.agent).strip(),
                enforce_transition=True,
            )
            if not ok_status:
                details = {
                    "error": "reactivation succeeded but transition to in_progress failed",
                    "reactivation": details,
                    "status_error": payload_status,
                }
                ok = False

        payload = {"action": "reactivate", "ok": bool(ok), "workboard": str(workboard_path), **details}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(f"- reactivated task `{payload.get('task_id')}` for `{payload.get('agent')}`")
            else:
                print(f"- {payload.get('error', 'reactivation failed')}")
        return 0 if ok else 1

    if args.capture_preference:
        ok, details = _capture_task_ecosystem_preference(
            user_id=str(args.user_id).strip() or "default",
            summary=str(args.preference_summary).strip(),
            verbatim=str(args.preference_verbatim).strip(),
            now=now,
        )
        payload = {
            "action": "capture_preference",
            "ok": bool(ok),
            "workboard": str(workboard_path),
            **details,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task manager: PASS" if ok else "Workboard task manager: FAIL")
            if ok:
                print(
                    f"- captured preference for user `{payload.get('user_id')}` "
                    f"(total stored: {payload.get('saved_preference_count', 0)})"
                )
            else:
                print(f"- {payload.get('error', 'capture preference failed')}")
        return 0 if ok else 1

    payload = {"action": "workboard_task_manager", "ok": False, "error": "no action selected"}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Workboard task manager: FAIL")
        print(f"- {payload['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
