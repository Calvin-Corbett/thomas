"""Long-running soak runner utilities for Thomas operations."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


Runner = Callable[[str, float], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SoakOptions:
    command: str
    duration_seconds: float
    iterations: int
    interval_seconds: float
    failure_command: str
    inject_failure_every: int
    timeout_seconds: float
    log_file: Optional[Path]



def _default_runner(command: str, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout_seconds)),
    )



def _append_jsonl(path: Optional[Path], row: Dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")



def run_soak(options: SoakOptions, *, runner: Runner = _default_runner) -> Dict[str, Any]:
    started_at = time.time()
    deadline = started_at + max(0.0, float(options.duration_seconds)) if options.duration_seconds > 0 else None

    iteration = 0
    success_count = 0
    failure_count = 0
    injected_count = 0
    rows: List[Dict[str, Any]] = []

    while True:
        iteration += 1
        if options.iterations > 0 and iteration > options.iterations:
            break
        if deadline is not None and time.time() > deadline:
            break

        injected = False
        if options.failure_command and options.inject_failure_every > 0 and iteration % options.inject_failure_every == 0:
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
        else:
            failure_count += 1

        row = {
            "type": "soak_run",
            "iteration": iteration,
            "command": options.command,
            "ok": bool(ok),
            "exit_code": int(result.returncode),
            "duration_ms": duration_ms,
            "injected": bool(injected),
        }
        rows.append(row)
        _append_jsonl(options.log_file, row)

        if options.interval_seconds > 0:
            time.sleep(max(0.0, float(options.interval_seconds)))

    completed_at = time.time()
    total_runs = success_count + failure_count
    failure_rate = (float(failure_count) / float(total_runs)) if total_runs else 0.0
    avg_duration_ms = (
        int(sum(int(row["duration_ms"]) for row in rows) / max(1, len(rows))) if rows else 0
    )

    return {
        "ok": True,
        "summary": {
            "total_runs": int(total_runs),
            "success_count": int(success_count),
            "failure_count": int(failure_count),
            "failure_rate": float(round(failure_rate, 6)),
            "avg_duration_ms": int(avg_duration_ms),
            "injected_failures": int(injected_count),
            "started_at_epoch": float(started_at),
            "completed_at_epoch": float(completed_at),
            "elapsed_seconds": float(round(completed_at - started_at, 3)),
        },
    }



def _format_text_report(report: Dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    lines = [
        "Soak run complete",
        f"- total runs: {summary.get('total_runs', 0)}",
        f"- successes: {summary.get('success_count', 0)}",
        f"- failures: {summary.get('failure_count', 0)}",
        f"- failure rate: {summary.get('failure_rate', 0.0):.4f}",
        f"- avg duration ms: {summary.get('avg_duration_ms', 0)}",
        f"- injected failures: {summary.get('injected_failures', 0)}",
        f"- elapsed seconds: {summary.get('elapsed_seconds', 0.0)}",
    ]
    return "\n".join(lines)



def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run a command repeatedly for soak testing with optional failure injection.")
    parser.add_argument("--command", required=True, help="Command to execute each iteration.")
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="Optional run duration in seconds.")
    parser.add_argument("--iterations", type=int, default=100, help="Maximum number of iterations (default: 100).")
    parser.add_argument("--interval-seconds", type=float, default=0.0, help="Sleep between iterations.")
    parser.add_argument("--failure-command", default="", help="Optional failure-injection command.")
    parser.add_argument("--inject-failure-every", type=int, default=0, help="Inject failure command every N iterations.")
    parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Per-command timeout in seconds.")
    parser.add_argument("--log-file", default="", help="Optional JSONL output path.")
    parser.add_argument("--max-failure-rate", type=float, default=1.0, help="Fail run if failure rate exceeds this threshold.")
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
    )

    report = run_soak(options)
    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(report))

    failure_rate = float(((report.get("summary") or {}).get("failure_rate") or 0.0))
    return 0 if failure_rate <= float(args.max_failure_rate) else 3


if __name__ == "__main__":
    raise SystemExit(main())
