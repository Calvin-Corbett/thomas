"""Review fixes to the gate runner (scripts/crew/brief/gate_runner.py): what a failing gate may stop, the machine-wide slots,
tuning values that must not crash it, and the switch back to the old behaviour.

Companion to tests/test_commit_gate_runner.py. Gates are `python -c` programs that leave marker files or timestamps.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from scripts.crew.brief import gate_runner, gate_slots
from scripts.crew.brief.gate_runner import Job

from tests.test_commit_gate_runner import PY, _program, _runner


def test_the_guard_is_left_to_finish_when_an_earlier_gate_fails_and_other_gates_are_stopped(tmp_path: Path) -> None:
    # Review finding: killing active_folder_guard mid-run can orphan its lock file, which every other agent's guard then
    # waits on for up to 60 s. It is never killed for an earlier gate's failure; any other running gate still is.
    guard_done, other_done = tmp_path / "guard.done", tmp_path / "other.done"
    jobs = [
        Job(0, "refuses", _program(sleep=1.2, exit_code=1, text="no")),  # long enough for the others to be running
        Job(1, "active_folder_guard", _program(sleep=2.5, marker=guard_done)),
        Job(2, "other_long", _program(sleep=8.0, marker=other_done)),
    ]
    started = time.monotonic()
    results = _runner(tmp_path, 3).run(jobs)
    assert [(r.name, r.ok) for r in results] == [("refuses", False)]  # the guard's own result is thrown away
    assert guard_done.exists(), "the guard was killed while it may have held the folder-claim lock"
    assert not other_done.exists(), "a gate that is not the guard was left running"
    assert time.monotonic() - started < 6.5


def test_a_guard_that_hangs_is_still_killed_by_the_timeout(tmp_path: Path) -> None:
    started = time.monotonic()
    [result] = _runner(tmp_path, 1, timeout=1.5).run([Job(0, "active_folder_guard", _program(sleep=8.0))])
    assert result.ok is False and "did not finish within" in result.output
    assert time.monotonic() - started < 7.0


def test_the_no_kill_list_is_exactly_the_gate_that_takes_the_lock() -> None:
    assert frozenset({"active_folder_guard"}) == gate_runner.NO_KILL


def _timed(stamps: Path, name: str, seconds: float = 0.6) -> tuple:
    code = (
        "import pathlib, time\n"
        f"folder = pathlib.Path({str(stamps)!r}); folder.mkdir(exist_ok=True)\n"
        f"t0 = time.time(); time.sleep({seconds}); t1 = time.time()\n"
        f"(folder / {name!r}).write_text(f'{{t0}} {{t1}}')"
    )
    return (PY, "-c", code)


def _intervals(stamps: Path) -> list[tuple[float, float]]:
    return sorted(tuple(map(float, f.read_text().split())) for f in stamps.iterdir())  # type: ignore[misc]


def test_pooled_gates_share_the_machine_wide_slots(tmp_path: Path) -> None:
    # Review finding: no machine-wide cap, so ten agents with four workers each ran forty gates at once.
    stamps = tmp_path / "stamps"
    pool = gate_slots.SlotPool(tmp_path / "slots", 1, wait_seconds=120)
    jobs = [Job(i, f"g{i}", _timed(stamps, f"g{i}")) for i in range(3)]
    results = _runner(tmp_path, 3, slots=pool).run(jobs)
    assert [r.ok for r in results] == [True, True, True]
    spans = _intervals(stamps)
    assert len(spans) == 3
    for (_s0, e0), (s1, _e1) in zip(spans, spans[1:], strict=False):
        assert e0 <= s1 + 0.01, "two gates ran at once with one slot"
    assert pool.gave_up == 0


def test_two_slots_let_two_gates_overlap_and_no_more(tmp_path: Path) -> None:
    stamps = tmp_path / "stamps"
    pool = gate_slots.SlotPool(tmp_path / "slots", 2, wait_seconds=120)
    jobs = [Job(i, f"g{i}", _timed(stamps, f"g{i}", 0.8)) for i in range(4)]
    assert all(r.ok for r in _runner(tmp_path, 4, slots=pool).run(jobs))
    spans = _intervals(stamps)
    peak = max(sum(1 for s, e in spans if s <= probe < e) for probe, _ in spans)
    assert peak <= 2, f"{peak} gates ran at once with two slots"


def test_a_gate_that_waited_for_a_slot_does_not_start_once_an_earlier_gate_has_failed(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    runner = _runner(tmp_path, 2, slots=gate_slots.SlotPool(tmp_path / "slots", 1))
    runner._limit = 0  # what a failure of gate 0 records while gate 1 is still waiting for its slot
    result = runner._one(Job(1, "late", _program(marker=marker)))
    assert result.cancelled is True and not marker.exists()


def test_a_slot_that_never_frees_up_delays_a_gate_by_the_wait_limit_and_no_longer(tmp_path: Path) -> None:
    # A limiter must not stop a landing: the machine's slots are all held, so the gate runs after the wait limit anyway.
    folder = tmp_path / "slots"
    held = gate_slots.SlotPool(folder, 1, wait_seconds=60)
    waiting = gate_slots.SlotPool(folder, 1, wait_seconds=0.4)
    started = time.monotonic()
    with held.hold() as got:
        assert got is True
        results = _runner(tmp_path, 2, slots=waiting).run([Job(0, "a", _program()), Job(1, "b", _program())])
    assert [r.ok for r in results] == [True, True]
    assert waiting.gave_up >= 1
    assert time.monotonic() - started < 20


def test_one_worker_is_not_throttled_by_the_slots(tmp_path: Path) -> None:
    class Never:
        def hold(self):
            raise AssertionError("the serial loop must not wait for a slot")

    results = _runner(tmp_path, 1, slots=Never()).run([Job(0, "a", _program())])  # type: ignore[arg-type]
    assert [r.ok for r in results] == [True]


def test_a_timeout_that_is_not_a_finite_number_does_not_crash_the_runner() -> None:
    # Review finding: THOMAS_COMMIT_GATE_TIMEOUT=inf raised OverflowError out of communicate().
    for text in ("inf", "-inf", "nan", "Infinity", "", "abc", "0", "-5"):
        assert gate_runner.gate_timeout({gate_runner.TIMEOUT_ENV: text}) == gate_runner.DEFAULT_TIMEOUT, text
    assert gate_runner.gate_timeout({gate_runner.TIMEOUT_ENV: "1e99"}) == gate_runner.MAX_TIMEOUT
    assert gate_runner.gate_timeout({gate_runner.TIMEOUT_ENV: "42"}) == 42.0


def test_the_legacy_switch_means_one_gate_at_a_time_whatever_else_is_set() -> None:
    for yes in ("1", "true", "YES", " on "):
        env = {gate_runner.LEGACY_ENV: yes, gate_runner.WORKERS_ENV: "6"}
        assert gate_runner.legacy_requested(env) is True and gate_runner.worker_count(env) == 1, yes
    for no in ("", "0", "false", "no", "off", "legacy"):
        assert gate_runner.legacy_requested({gate_runner.LEGACY_ENV: no}) is False, no
    assert gate_runner.worker_count({gate_runner.WORKERS_ENV: "6"}) == 6


class _FakeProc:
    pid = 4242

    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def test_a_posix_kill_takes_the_whole_process_group() -> None:
    # Written on Windows: this is the only coverage the POSIX branch has, with a fake in place of os.killpg.
    sent: list[tuple[int, int]] = []
    proc = _FakeProc()
    gate_runner._kill_group(proc, lambda pid, sig: sent.append((pid, sig)))  # type: ignore[arg-type]
    assert sent == [(4242, getattr(signal, "SIGKILL", signal.SIGTERM))] and proc.killed is False
    gate_runner._kill_group(proc, None)  # type: ignore[arg-type]
    assert proc.killed is True


def test_a_gate_starts_in_its_own_process_group_off_windows_only(tmp_path: Path, monkeypatch) -> None:
    seen: list[bool] = []
    real = subprocess.Popen

    def spy(*args, **kwargs):
        seen.append(bool(kwargs.get("start_new_session")))
        return real(*args, **kwargs)

    monkeypatch.setattr(gate_runner.subprocess, "Popen", spy)
    _runner(tmp_path, 1).run([Job(0, "a", _program())])
    assert seen == [os.name != "nt"]


def test_the_pool_is_none_when_the_limit_is_off_and_is_used_for_several_workers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(gate_slots.SLOTS_ENV, "0")
    assert gate_slots.pool() is None
    monkeypatch.setenv(gate_slots.SLOTS_ENV, "3")
    monkeypatch.setenv(gate_slots.DIR_ENV, str(tmp_path))
    pool = gate_slots.pool()
    assert pool is not None and pool.count == 3 and pool.directory == tmp_path / "thomas-gate-slots"
