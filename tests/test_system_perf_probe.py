from __future__ import annotations

from thomas.system.perf_profiler import PerfOptions, run_perf_probe


class _Result:
    def __init__(self, code: int) -> None:
        self.returncode = code


def test_perf_probe_reports_percentiles_and_success_rate() -> None:
    durations = [10.0, 20.0, 30.0, 40.0, 50.0]
    idx = {"value": 0}

    def _runner(command: str, timeout_seconds: float):
        _ = command, timeout_seconds
        i = idx["value"]
        idx["value"] = i + 1
        return _Result(0 if i < 4 else 1)

    # We only control return codes here; duration values are produced by wall clock,
    # so this test focuses on shape and success accounting.
    report = run_perf_probe(PerfOptions(command="noop", runs=len(durations), timeout_seconds=2.0), runner=_runner)
    summary = report["summary"]

    assert summary["runs"] == 5
    assert summary["success_count"] == 4
    assert summary["failure_count"] == 1
    assert 0.0 <= summary["p50_ms"] <= summary["max_ms"]
    assert 0.0 <= summary["p95_ms"] <= summary["max_ms"]
    assert summary["success_rate"] == 0.8
