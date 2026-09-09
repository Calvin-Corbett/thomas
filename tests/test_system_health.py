from __future__ import annotations

import thomas.system.soak_runner as soak_mod
from thomas.system.soak_runner import SoakOptions, run_soak


class _Result:
    def __init__(self, code: int) -> None:
        self.returncode = code


def test_default_runner_expands_python_placeholder(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        captured["args"] = list(args)
        captured["kwargs"] = dict(kwargs)
        return _Result(0)

    monkeypatch.setattr(soak_mod.subprocess, "run", _fake_run)

    soak_mod._default_runner("{python} -m thomas status", 2.0)

    assert captured["args"][0] == soak_mod.sys.executable


def test_soak_runner_probe_hook_tracks_failures() -> None:
    probe_calls: list[int] = []

    def _runner(command: str, timeout_seconds: float):
        _ = command, timeout_seconds
        return _Result(0)

    def _probe_hook(row: dict[str, object]) -> dict[str, object]:
        iteration = int(row["iteration"])
        probe_calls.append(iteration)
        return {"ok": iteration % 2 == 1, "probe": "health"}

    report = run_soak(
        SoakOptions(
            command="main",
            duration_seconds=0.0,
            iterations=4,
            interval_seconds=0.0,
            failure_command="",
            inject_failure_every=0,
            timeout_seconds=2.0,
            log_file=None,
        ),
        runner=_runner,
        probe_hook=_probe_hook,
    )

    summary = report["summary"]
    assert probe_calls == [1, 2, 3, 4]
    assert summary["probe_runs"] == 4
    assert summary["probe_failure_count"] == 2
    assert summary["probe_failure_rate"] == 0.5


def test_soak_runner_probe_command_runs_on_configured_cadence() -> None:
    state = {"probe_calls": 0}

    def _runner(command: str, timeout_seconds: float):
        _ = timeout_seconds
        if command == "probe":
            state["probe_calls"] += 1
            return _Result(1 if state["probe_calls"] == 2 else 0)
        return _Result(0)

    report = run_soak(
        SoakOptions(
            command="main",
            duration_seconds=0.0,
            iterations=5,
            interval_seconds=0.0,
            failure_command="",
            inject_failure_every=0,
            timeout_seconds=2.0,
            log_file=None,
            probe_command="probe",
            probe_every=2,
        ),
        runner=_runner,
    )

    summary = report["summary"]
    assert state["probe_calls"] == 2
    assert summary["probe_runs"] == 2
    assert summary["probe_failure_count"] == 1
    assert summary["probe_failure_rate"] == 0.5


def test_soak_runner_probe_hook_exception_counts_as_probe_failure() -> None:
    def _runner(command: str, timeout_seconds: float):
        _ = command, timeout_seconds
        return _Result(0)

    def _probe_hook(row: dict[str, object]) -> dict[str, object]:
        _ = row
        raise RuntimeError("probe exploded")

    report = run_soak(
        SoakOptions(
            command="main",
            duration_seconds=0.0,
            iterations=3,
            interval_seconds=0.0,
            failure_command="",
            inject_failure_every=0,
            timeout_seconds=2.0,
            log_file=None,
        ),
        runner=_runner,
        probe_hook=_probe_hook,
    )

    summary = report["summary"]
    assert summary["probe_runs"] == 3
    assert summary["probe_failure_count"] == 3
    assert summary["probe_failure_rate"] == 1.0


def test_soak_runner_tracks_max_consecutive_failure_streaks() -> None:
    state = {"main_calls": 0}

    def _runner(command: str, timeout_seconds: float):
        _ = timeout_seconds
        if command == "probe":
            return _Result(1 if state["main_calls"] in {1, 2} else 0)
        state["main_calls"] += 1
        return _Result(1 if state["main_calls"] in {2, 3, 4} else 0)

    report = run_soak(
        SoakOptions(
            command="main",
            duration_seconds=0.0,
            iterations=5,
            interval_seconds=0.0,
            failure_command="",
            inject_failure_every=0,
            timeout_seconds=2.0,
            log_file=None,
            probe_command="probe",
            probe_every=1,
        ),
        runner=_runner,
    )

    summary = report["summary"]
    assert summary["max_consecutive_failures"] == 3
    assert summary["max_consecutive_probe_failures"] == 2


def test_main_enforces_consecutive_failure_thresholds(monkeypatch) -> None:
    def _fake_run_soak(options: SoakOptions, **kwargs: object) -> dict[str, object]:
        _ = options, kwargs
        return {
            "ok": True,
            "summary": {
                "failure_rate": 0.1,
                "probe_failure_rate": 0.1,
                "max_consecutive_failures": 4,
                "max_consecutive_probe_failures": 3,
            },
        }

    monkeypatch.setattr(soak_mod, "run_soak", _fake_run_soak)
    rc = soak_mod.main(
        [
            "--command",
            "echo ok",
            "--iterations",
            "1",
            "--max-failure-rate",
            "1.0",
            "--max-probe-failure-rate",
            "1.0",
            "--max-consecutive-failures",
            "2",
            "--max-consecutive-probe-failures",
            "2",
            "--json",
        ]
    )
    assert rc == 3
