from __future__ import annotations

from thomas.system.soak_runner import SoakOptions, run_soak


class _Result:
    def __init__(self, code: int) -> None:
        self.returncode = code



def test_soak_runner_counts_failures_and_injection() -> None:
    state = {"calls": 0}

    def _runner(command: str, timeout_seconds: float):
        _ = command, timeout_seconds
        state["calls"] += 1
        # Every 3rd primary command fails.
        if command == "main" and state["calls"] % 3 == 0:
            return _Result(1)
        return _Result(0)

    report = run_soak(
        SoakOptions(
            command="main",
            duration_seconds=0.0,
            iterations=6,
            interval_seconds=0.0,
            failure_command="inject",
            inject_failure_every=2,
            timeout_seconds=2.0,
            log_file=None,
        ),
        runner=_runner,
    )

    summary = report["summary"]
    assert summary["total_runs"] == 6
    assert summary["injected_failures"] == 3
    assert summary["failure_count"] >= 1
    assert 0.0 <= summary["failure_rate"] <= 1.0
