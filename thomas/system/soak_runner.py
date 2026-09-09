"""Long-running soak runner utilities for Thomas operations."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Runner = Callable[[str, float], subprocess.CompletedProcess[str]]
ProbeHook = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class SoakOptions:
    command: str
    duration_seconds: float
    iterations: int
    interval_seconds: float
    failure_command: str
    inject_failure_every: int
    timeout_seconds: float
    log_file: Path | None
    probe_command: str = ""
    probe_every: int = 1


def _default_runner(command: str, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    command = command.replace("{python}", sys.executable)
    return subprocess.run(
        shlex.split(command, posix=(sys.platform != "win32")),
        shell=False,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout_seconds)),
    )


def _append_jsonl(path: Path | None, row: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_probe_hook_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"ok": True}
    if isinstance(payload, bool):
        return {"ok": bool(payload)}
    if isinstance(payload, dict):
        out = dict(payload)
        out["ok"] = bool(out.get("ok", True))
        return out
    return {
        "ok": False,
        "error": f"Unsupported probe payload type: {type(payload).__name__}",
    }


def run_soak(
    options: SoakOptions,
    *,
    runner: Runner = _default_runner,
    probe_hook: ProbeHook | None = None,
) -> dict[str, Any]:
    started_at = time.time()
    deadline = started_at + max(0.0, float(options.duration_seconds)) if options.duration_seconds > 0 else None

    iteration = 0
    success_count = 0
    failure_count = 0
    consecutive_failures = 0
    max_consecutive_failures = 0
    injected_count = 0
    probe_runs = 0
    probe_failure_count = 0
    consecutive_probe_failures = 0
    max_consecutive_probe_failures = 0
    rows: list[dict[str, Any]] = []
    probe_every = max(1, int(options.probe_every))

    while True:
        iteration += 1
        if options.iterations > 0 and iteration > options.iterations:
            break
        if deadline is not None and time.time() > deadline:
            break

        injected = False
        if (
            options.failure_command
            and options.inject_failure_every > 0
            and iteration % options.inject_failure_every == 0
        ):
            injected = True
            injected_count += 1
            inject_started = time.time()
            inject_result = runner(options.failure_command, options.timeout_seconds)
            inject_duration_ms = int((time.time() - inject_started) * 1000)
            _append_jsonl(
                options.log_file,
                {
                    "type": "failure_injection",
                    "iteration": iteration,
                    "command": options.failure_command,
                    "exit_code": int(inject_result.returncode),
                    "duration_ms": inject_duration_ms,
                },
            )

        began = time.time()
        result = runner(options.command, options.timeout_seconds)
        duration_ms = int((time.time() - began) * 1000)

        ok = int(result.returncode) == 0
        if ok:
            success_count += 1
            consecutive_failures = 0
        else:
            failure_count += 1
            consecutive_failures += 1
            if consecutive_failures > max_consecutive_failures:
                max_consecutive_failures = consecutive_failures

        row = {
            "type": "soak_run",
            "iteration": iteration,
            "command": options.command,
            "ok": bool(ok),
            "exit_code": int(result.returncode),
            "duration_ms": duration_ms,
            "injected": bool(injected),
        }

        probe_events: list[dict[str, Any]] = []
        if options.probe_command and iteration % probe_every == 0:
            probe_runs += 1
            probe_started = time.time()
            probe_result = runner(options.probe_command, options.timeout_seconds)
            probe_duration_ms = int((time.time() - probe_started) * 1000)
            probe_ok = int(probe_result.returncode) == 0
            if not probe_ok:
                probe_failure_count += 1
            probe_event = {
                "type": "soak_probe",
                "source": "command",
                "iteration": iteration,
                "command": options.probe_command,
                "ok": bool(probe_ok),
                "exit_code": int(probe_result.returncode),
                "duration_ms": probe_duration_ms,
            }
            probe_events.append(probe_event)
            _append_jsonl(options.log_file, probe_event)

        if probe_hook is not None:
            probe_runs += 1
            hook_started = time.time()
            try:
                raw_payload = probe_hook(dict(row))
                hook_payload = _normalize_probe_hook_payload(raw_payload)
            except Exception as exc:
                hook_payload = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            hook_duration_ms = int((time.time() - hook_started) * 1000)
            hook_ok = bool(hook_payload.get("ok", True))
            if not hook_ok:
                probe_failure_count += 1
            probe_event = {
                "type": "soak_probe",
                "source": "hook",
                "iteration": iteration,
                "ok": bool(hook_ok),
                "duration_ms": hook_duration_ms,
            }
            extra = {k: v for k, v in hook_payload.items() if k != "ok"}
            if extra:
                probe_event["details"] = extra
            probe_events.append(probe_event)
            _append_jsonl(options.log_file, probe_event)

        if probe_events:
            iteration_probe_ok = all(bool(event.get("ok")) for event in probe_events)
            iteration_probe_failures = sum(1 for event in probe_events if not bool(event.get("ok")))
            row["probe_ok"] = iteration_probe_ok
            row["probe_failure_count"] = iteration_probe_failures
            if iteration_probe_ok:
                consecutive_probe_failures = 0
            else:
                consecutive_probe_failures += 1
                if consecutive_probe_failures > max_consecutive_probe_failures:
                    max_consecutive_probe_failures = consecutive_probe_failures
        rows.append(row)
        _append_jsonl(options.log_file, row)

        if options.interval_seconds > 0:
            time.sleep(max(0.0, float(options.interval_seconds)))

    completed_at = time.time()
    total_runs = success_count + failure_count
    failure_rate = (float(failure_count) / float(total_runs)) if total_runs else 0.0
    probe_failure_rate = (float(probe_failure_count) / float(probe_runs)) if probe_runs else 0.0
    avg_duration_ms = int(sum(int(row["duration_ms"]) for row in rows) / max(1, len(rows))) if rows else 0

    return {
        "ok": True,
        "summary": {
            "total_runs": int(total_runs),
            "success_count": int(success_count),
            "failure_count": int(failure_count),
            "failure_rate": float(round(failure_rate, 6)),
            "avg_duration_ms": int(avg_duration_ms),
            "injected_failures": int(injected_count),
            "probe_runs": int(probe_runs),
            "probe_failure_count": int(probe_failure_count),
            "probe_failure_rate": float(round(probe_failure_rate, 6)),
            "max_consecutive_failures": int(max_consecutive_failures),
            "max_consecutive_probe_failures": int(max_consecutive_probe_failures),
            "started_at_epoch": float(started_at),
            "completed_at_epoch": float(completed_at),
            "elapsed_seconds": float(round(completed_at - started_at, 3)),
        },
    }


def _format_text_report(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    lines = [
        "Soak run complete",
        f"- total runs: {summary.get('total_runs', 0)}",
        f"- successes: {summary.get('success_count', 0)}",
        f"- failures: {summary.get('failure_count', 0)}",
        f"- failure rate: {summary.get('failure_rate', 0.0):.4f}",
        f"- avg duration ms: {summary.get('avg_duration_ms', 0)}",
        f"- injected failures: {summary.get('injected_failures', 0)}",
        f"- probe runs: {summary.get('probe_runs', 0)}",
        f"- probe failures: {summary.get('probe_failure_count', 0)}",
        f"- probe failure rate: {summary.get('probe_failure_rate', 0.0):.4f}",
        f"- max consecutive failures: {summary.get('max_consecutive_failures', 0)}",
        f"- max consecutive probe failures: {summary.get('max_consecutive_probe_failures', 0)}",
        f"- elapsed seconds: {summary.get('elapsed_seconds', 0.0)}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a command repeatedly for soak testing with optional failure injection."
    )
    parser.add_argument("--command", required=True, help="Command to execute each iteration.")
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="Optional run duration in seconds.")
    parser.add_argument("--iterations", type=int, default=100, help="Maximum number of iterations (default: 100).")
    parser.add_argument("--interval-seconds", type=float, default=0.0, help="Sleep between iterations.")
    parser.add_argument("--failure-command", default="", help="Optional failure-injection command.")
    parser.add_argument(
        "--inject-failure-every", type=int, default=0, help="Inject failure command every N iterations."
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Per-command timeout in seconds.")
    parser.add_argument("--log-file", default="", help="Optional JSONL output path.")
    parser.add_argument("--probe-command", default="", help="Optional probe command to execute during soak.")
    parser.add_argument("--probe-every", type=int, default=1, help="Run --probe-command every N iterations.")
    parser.add_argument(
        "--max-failure-rate", type=float, default=1.0, help="Fail run if failure rate exceeds this threshold."
    )
    parser.add_argument(
        "--max-probe-failure-rate",
        type=float,
        default=1.0,
        help="Fail run if probe failure rate exceeds this threshold.",
    )
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=-1,
        help="Fail run if consecutive primary failures exceed this threshold (negative disables).",
    )
    parser.add_argument(
        "--max-consecutive-probe-failures",
        type=int,
        default=-1,
        help="Fail run if consecutive probe failures exceed this threshold (negative disables).",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    options = SoakOptions(
        command=str(args.command),
        duration_seconds=max(0.0, float(args.duration_seconds)),
        iterations=max(1, int(args.iterations)),
        interval_seconds=max(0.0, float(args.interval_seconds)),
        failure_command=str(args.failure_command or ""),
        inject_failure_every=max(0, int(args.inject_failure_every)),
        timeout_seconds=max(1.0, float(args.timeout_seconds)),
        log_file=Path(args.log_file).resolve() if str(args.log_file or "").strip() else None,
        probe_command=str(args.probe_command or ""),
        probe_every=max(1, int(args.probe_every)),
    )

    report = run_soak(options)
    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(report))

    summary = dict(report.get("summary") or {})
    failure_rate = float(summary.get("failure_rate") or 0.0)
    probe_failure_rate = float(summary.get("probe_failure_rate") or 0.0)
    max_consecutive_failures = int(summary.get("max_consecutive_failures") or 0)
    max_consecutive_probe_failures = int(summary.get("max_consecutive_probe_failures") or 0)
    failure_within_limit = failure_rate <= float(args.max_failure_rate)
    probe_within_limit = probe_failure_rate <= float(args.max_probe_failure_rate)
    consecutive_within_limit = int(args.max_consecutive_failures) < 0 or max_consecutive_failures <= int(
        args.max_consecutive_failures
    )
    probe_consecutive_within_limit = int(
        args.max_consecutive_probe_failures
    ) < 0 or max_consecutive_probe_failures <= int(args.max_consecutive_probe_failures)
    return (
        0
        if (failure_within_limit and probe_within_limit and consecutive_within_limit and probe_consecutive_within_limit)
        else 3
    )


if __name__ == "__main__":
    raise SystemExit(main())
