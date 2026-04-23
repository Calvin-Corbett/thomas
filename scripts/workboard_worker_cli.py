"""CLI entrypoint for the persistent workboard worker."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _build_parser(module: Any):
    parser = module.argparse.ArgumentParser(description="Persistent worker loop for workboard-dispatched tasks.")
    parser.add_argument("--workboard", default=str(module.DEFAULT_WORKBOARD))
    parser.add_argument("--agent", required=True, help="Agent alias this worker loop serves.")
    parser.add_argument("--task-manager-agent", default=module.DEFAULT_TASK_MANAGER_AGENT)
    parser.add_argument(
        "--catalog",
        default="",
        help=(
            "Optional JSON command catalog. If omitted, defaults to "
            "the selected workboard's `worker_command_catalog.json` when present."
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
    parser.add_argument("--poll-seconds", type=float, default=module.DEFAULT_POLL_SECONDS)
    parser.add_argument("--idle-heartbeat-seconds", type=float, default=module.DEFAULT_IDLE_HEARTBEAT_SECONDS)
    parser.add_argument(
        "--command-timeout-seconds",
        type=float,
        default=0.0,
        help="Per-command timeout; 0 disables timeout.",
    )
    parser.add_argument(
        "--auto-release-success",
        action=module.argparse.BooleanOptionalAction,
        default=True,
        help="Release claim after successful task execution (default: true).",
    )
    parser.add_argument(
        "--auto-release-failure",
        action=module.argparse.BooleanOptionalAction,
        default=False,
        help="Release claim after failed task execution (default: false).",
    )
    parser.add_argument(
        "--release-on-no-command",
        action=module.argparse.BooleanOptionalAction,
        default=False,
        help="Release claim when no command mapping exists for assigned task (default: false).",
    )
    parser.add_argument(
        "--allow-dirty-release",
        action=module.argparse.BooleanOptionalAction,
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
        action=module.argparse.BooleanOptionalAction,
        default=False,
        help="Stop loop immediately when any failure occurs (default: false).",
    )
    parser.add_argument(
        "--send-online-message",
        action=module.argparse.BooleanOptionalAction,
        default=True,
        help="Send one online status + periodic idle heartbeat messages (default: true).",
    )
    parser.add_argument(
        "--send-start-message",
        action=module.argparse.BooleanOptionalAction,
        default=False,
        help="Send a start status message before executing task commands (default: false).",
    )
    parser.add_argument(
        "--request-dispatch-on-complete",
        action=module.argparse.BooleanOptionalAction,
        default=True,
        help="Trigger immediate idle-agent dispatch pass after successful completion/release (default: true).",
    )
    parser.add_argument(
        "--dispatch-lookback-minutes",
        type=float,
        default=120.0,
        help="Online lookback window for immediate redispatch requests (default: 120).",
    )
    parser.add_argument("--log-dir", default=str(module.DEFAULT_LOG_DIR))
    parser.add_argument("--json", action="store_true")
    return parser


def _print_payload(*, args: Any, payload: dict[str, object], ok: bool) -> None:
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    print("Workboard worker: PASS" if ok else "Workboard worker: FAIL")
    if "completed_count" in payload:
        print(
            f"- agent={payload.get('agent')}; completed={payload.get('completed_count')}; "
            f"failures={payload.get('failure_count')}; no_command={payload.get('no_command_count')}"
        )
        for item in list(payload.get("errors") or []):
            print(f"- error: {item}")
    else:
        print(f"- {payload['error']}")


def main(*, module: Any, argv: Iterable[str] | None = None) -> int:
    parser = _build_parser(module)
    args = parser.parse_args(list(argv) if argv is not None else None)

    workboard_path = Path(str(args.workboard)).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (module.ROOT / workboard_path).resolve()
    else:
        workboard_path = workboard_path.resolve()
    if not workboard_path.exists():
        payload = {"ok": False, "error": f"missing workboard file: {workboard_path}"}
        _print_payload(args=args, payload=payload, ok=False)
        return 1

    if args.poll_seconds < 0:
        payload = {"ok": False, "error": "--poll-seconds must be >= 0"}
        _print_payload(args=args, payload=payload, ok=False)
        return 1
    if args.idle_heartbeat_seconds < 0:
        payload = {"ok": False, "error": "--idle-heartbeat-seconds must be >= 0"}
        _print_payload(args=args, payload=payload, ok=False)
        return 1
    if args.command_timeout_seconds < 0:
        payload = {"ok": False, "error": "--command-timeout-seconds must be >= 0"}
        _print_payload(args=args, payload=payload, ok=False)
        return 1
    if args.dispatch_lookback_minutes <= 0:
        payload = {"ok": False, "error": "--dispatch-lookback-minutes must be > 0"}
        _print_payload(args=args, payload=payload, ok=False)
        return 1
    if args.cycles < 0:
        payload = {"ok": False, "error": "--cycles must be >= 0"}
        _print_payload(args=args, payload=payload, ok=False)
        return 1
    if args.max_completions < 0:
        payload = {"ok": False, "error": "--max-completions must be >= 0"}
        _print_payload(args=args, payload=payload, ok=False)
        return 1

    catalog_path: Path | None
    default_catalog_path = module.command_catalog_path_for(workboard_path, repo_root=module.ROOT)
    if str(args.catalog).strip():
        catalog_path = Path(str(args.catalog)).resolve()
    elif default_catalog_path.exists():
        catalog_path = default_catalog_path
    else:
        catalog_path = None

    ok_catalog, payload_catalog = module._load_command_catalog(catalog_path)
    if not ok_catalog:
        payload = {
            "ok": False,
            "error": str(payload_catalog.get("error", "catalog load failed")),
            "catalog_path": str(catalog_path) if catalog_path is not None else "",
        }
        _print_payload(args=args, payload=payload, ok=False)
        return 1

    default_log_dir = module.worker_log_dir_for(workboard_path, repo_root=module.ROOT)
    if str(args.log_dir).strip() and str(Path(str(args.log_dir)).resolve()) != str(module.DEFAULT_LOG_DIR.resolve()):
        log_dir = Path(str(args.log_dir)).resolve()
    else:
        log_dir = default_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    ok_loop, payload_loop = module._worker_loop(
        workboard_path=workboard_path,
        agent=str(args.agent).strip(),
        task_manager_agent=str(args.task_manager_agent).strip() or module.DEFAULT_TASK_MANAGER_AGENT,
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
    _print_payload(args=args, payload=payload, ok=ok_loop)
    return 0 if ok_loop else 1
