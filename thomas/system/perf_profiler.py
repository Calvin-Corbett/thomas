"""Latency/perf probe utilities for command-level baselining."""

from __future__ import annotations

import argparse
import json
import shlex
import statistics
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Runner = Callable[[str, float], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class PerfOptions:
    command: str
    runs: int
    timeout_seconds: float


def _default_runner(command: str, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        shlex.split(command),
        shell=False,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout_seconds)),
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    low = int(rank)
    high = min(len(ordered) - 1, low + 1)
    fraction = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * fraction)


def run_perf_probe(options: PerfOptions, *, runner: Runner = _default_runner) -> dict[str, Any]:
    durations_ms: list[float] = []
    success_count = 0

    for _ in range(max(1, int(options.runs))):
        started = time.time()
        result = runner(options.command, options.timeout_seconds)
        elapsed_ms = (time.time() - started) * 1000.0
        durations_ms.append(float(elapsed_ms))
        if int(result.returncode) == 0:
            success_count += 1

    total = len(durations_ms)
    failure_count = total - success_count
    success_rate = float(success_count / total) if total else 0.0

    return {
        "ok": True,
        "summary": {
            "runs": int(total),
            "success_count": int(success_count),
            "failure_count": int(failure_count),
            "success_rate": float(round(success_rate, 6)),
            "min_ms": float(round(min(durations_ms), 3)) if durations_ms else 0.0,
            "max_ms": float(round(max(durations_ms), 3)) if durations_ms else 0.0,
            "mean_ms": float(round(statistics.fmean(durations_ms), 3)) if durations_ms else 0.0,
            "p50_ms": float(round(_percentile(durations_ms, 0.5), 3)),
            "p95_ms": float(round(_percentile(durations_ms, 0.95), 3)),
        },
    }


def _format_text_report(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    return "\n".join(
        [
            "Perf probe complete",
            f"- runs: {summary.get('runs', 0)}",
            f"- success rate: {summary.get('success_rate', 0.0):.4f}",
            f"- min ms: {summary.get('min_ms', 0.0)}",
            f"- p50 ms: {summary.get('p50_ms', 0.0)}",
            f"- p95 ms: {summary.get('p95_ms', 0.0)}",
            f"- max ms: {summary.get('max_ms', 0.0)}",
            f"- mean ms: {summary.get('mean_ms', 0.0)}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a command multiple times and report latency percentiles.")
    parser.add_argument("--command", required=True, help="Command to execute.")
    parser.add_argument("--runs", type=int, default=25, help="Number of runs (default: 25).")
    parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Per-run timeout in seconds.")
    parser.add_argument("--min-success-rate", type=float, default=1.0, help="Fail if success rate below threshold.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    options = PerfOptions(
        command=str(args.command),
        runs=max(1, int(args.runs)),
        timeout_seconds=max(1.0, float(args.timeout_seconds)),
    )
    report = run_perf_probe(options)

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(report))

    success_rate = float((report.get("summary") or {}).get("success_rate") or 0.0)
    return 0 if success_rate >= float(args.min_success_rate) else 3


if __name__ == "__main__":
    raise SystemExit(main())
