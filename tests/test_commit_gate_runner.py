"""The gate runner: several gates at once, with the verdict the serial loop gave.

scripts/crew/brief/gate_runner.py runs the commit tool's local gates. These tests pin what concurrency must NOT change
(the failure reported is the first in registry order, gates after it are not left running, board readers wait for the gate
that writes the board) and what it adds (no console windows, a timeout that fails closed, a taint flag for a gate that ran
while the branch tip moved). Gates here are `python -c` programs that leave marker files, so every claim is checked on
disk and none depends on how fast the machine is.
"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scripts.crew.brief import gate_runner
from scripts.crew.brief.gate_runner import Job, Runner

PY = sys.executable


def _program(*, sleep: float = 0.0, exit_code: int = 0, text: str = "", marker: Path | None = None, needs=()) -> tuple:
    """A gate: wait for every file in `needs`, sleep, leave a marker, print, exit."""
    lines = ["import pathlib, sys, time", f"time.sleep({sleep})"]
    for needed in needs:
        lines.append(
            f"if not pathlib.Path({str(needed)!r}).exists(): print('missing {Path(needed).name}'); sys.exit(1)"
        )
    if marker is not None:
        lines.append(f"pathlib.Path({str(marker)!r}).write_text('x')")
    lines += [f"print({text!r})", f"sys.exit({exit_code})"]
    return (PY, "-c", "\n".join(lines))


def _runner(tmp_path: Path, workers: int, **kwargs) -> Runner:
    return Runner(cwd=str(tmp_path), env=dict(os.environ), workers=workers, timeout=kwargs.pop("timeout", 60), **kwargs)


def test_pooled_reports_the_first_failure_in_registry_order_not_the_first_to_finish(tmp_path: Path) -> None:
    jobs = [
        Job(0, "slow_fail", _program(sleep=1.0, exit_code=1, text="slow")),
        Job(1, "fast_fail", _program(exit_code=1, text="fast")),
        Job(2, "fine", _program(sleep=0.1)),
    ]
    failure = gate_runner.first_failure(_runner(tmp_path, 3).run(jobs))
    assert failure is not None
    assert (failure.name, failure.output) == ("slow_fail", "slow")


def test_a_failure_stops_the_gates_after_it_and_never_starts_the_rest(tmp_path: Path) -> None:
    markers = [tmp_path / f"done{i}" for i in range(6)]
    jobs = [Job(0, "refuses", _program(exit_code=1, text="no"))]
    jobs += [Job(i, f"later{i}", _program(sleep=4.0, marker=markers[i])) for i in range(1, 6)]
    started = time.monotonic()
    results = _runner(tmp_path, 2).run(jobs)
    elapsed = time.monotonic() - started
    assert [r.name for r in results] == ["refuses"]
    assert not any(m.exists() for m in markers[1:]), "a gate after the failure ran to the end"
    assert elapsed < 3.5, "the runner waited for gates it no longer needed"


def test_a_gate_before_the_failure_still_runs_to_the_end(tmp_path: Path) -> None:
    marker = tmp_path / "early_done"
    jobs = [
        Job(0, "early", _program(sleep=0.8, marker=marker)),
        Job(1, "refuses", _program(exit_code=1, text="no")),
    ]
    results = _runner(tmp_path, 2).run(jobs)
    assert marker.exists()
    assert [r.name for r in results] == ["early", "refuses"]
    assert results[0].ok


def test_board_readers_wait_for_the_gate_that_writes_the_board(tmp_path: Path) -> None:
    wrote, read = tmp_path / "guard.done", tmp_path / "claims.done"
    jobs = [
        Job(0, "ruff", _program(sleep=0.1)),
        Job(1, "active_folder_guard", _program(sleep=0.8, marker=wrote)),
        Job(2, "workboard_claims", _program(needs=[wrote], marker=read)),
        Job(3, "workboard_inbox_final", _program(needs=[read])),
    ]
    results = _runner(tmp_path, 4).run(jobs)
    assert [(r.name, r.ok) for r in results] == [(j.name, True) for j in jobs], [r.output for r in results]


def test_the_long_gate_starts_first_so_it_is_not_the_one_left_behind() -> None:
    jobs = [Job(i, f"quick{i}", (PY, "-c", "pass")) for i in range(6)]
    jobs += [Job(6, "problem_closure", (PY, "-c", "pass")), Job(7, "active_folder_guard", (PY, "-c", "pass"))]
    order = [job.name for job in gate_runner.start_order(jobs)]
    assert order[:2] == ["active_folder_guard", "problem_closure"]
    assert order[2:] == [f"quick{i}" for i in range(6)]  # the rest keep registry order


def test_one_worker_is_the_old_loop_in_registry_order_that_stops_at_the_first_failure(tmp_path: Path) -> None:
    log = tmp_path / "ran.log"

    def logging(name: str, code: int) -> tuple:
        return (PY, "-c", f"import sys\nopen({str(log)!r}, 'a').write({name!r} + chr(10))\nsys.exit({code})")

    jobs = [Job(2, "c", logging("c", 0)), Job(0, "a", logging("a", 0)), Job(1, "b", logging("b", 1))]
    results = _runner(tmp_path, 1).run(jobs)
    assert log.read_text().split() == ["a", "b"]
    assert [(r.name, r.ok) for r in results] == [("a", True), ("b", False)]


def test_a_gate_that_ran_while_the_tip_moved_is_marked_and_one_that_did_not_is_not(tmp_path: Path) -> None:
    readings = iter(["base", "base", "base", "moved"])  # two readings per gate: before and after
    results = _runner(tmp_path, 1, base="base", probe=lambda: next(readings)).run(
        [Job(0, "steady", _program()), Job(1, "unlucky", _program())]
    )
    assert [(r.name, r.tainted) for r in results] == [("steady", False), ("unlucky", True)]


def test_a_gate_that_never_finishes_is_stopped_and_fails_closed(tmp_path: Path) -> None:
    started = time.monotonic()
    [result] = _runner(tmp_path, 1, timeout=1.5).run([Job(0, "hangs", _program(sleep=8.0, text="late"))])
    assert result.ok is False
    assert "did not finish within" in result.output
    assert time.monotonic() - started < 7.0


def test_gate_output_reads_as_it_did_in_text_mode(tmp_path: Path) -> None:
    code = "import sys\nsys.stdout.buffer.write(b'one\\r\\ntwo\\r\\n')\nsys.stderr.write('err')\nsys.exit(1)"
    [result] = _runner(tmp_path, 1).run([Job(0, "crlf", (PY, "-c", code))])
    assert result.output == "one\ntwo\nerr"


def test_a_dash_in_a_refusal_survives_as_the_serial_loop_decoded_it(tmp_path: Path) -> None:
    # Measured on the real gates: the bulk-commit refusal prints an em dash; the serial loop showed it, UTF-8 decoding did not.
    encoding = locale.getpreferredencoding(False)
    code = f"import sys\nsys.stdout.buffer.write({'refused — 53 files'.encode(encoding, 'replace')!r})\nsys.exit(1)"
    [result] = _runner(tmp_path, 1).run([Job(0, "dash", (PY, "-c", code))])
    assert result.output == "refused — 53 files".encode(encoding, "replace").decode(encoding)


@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW is a Windows flag")
def test_every_child_starts_without_a_console_window(tmp_path: Path, monkeypatch) -> None:
    seen: list[int] = []
    real = subprocess.Popen

    def spy(*args, **kwargs):
        seen.append(int(kwargs.get("creationflags") or 0))
        return real(*args, **kwargs)

    monkeypatch.setattr(gate_runner.subprocess, "Popen", spy)
    _runner(tmp_path, 2).run([Job(0, "a", _program()), Job(1, "b", _program())])
    assert seen and all(flags & 0x08000000 for flags in seen), seen


def test_pooled_children_do_not_fight_over_the_index_lock_and_one_worker_is_left_alone(tmp_path: Path) -> None:
    assert _runner(tmp_path, 4).env["GIT_OPTIONAL_LOCKS"] == "0"
    assert "GIT_OPTIONAL_LOCKS" not in {k: v for k, v in _runner(tmp_path, 1).env.items() if k not in os.environ}


def test_a_gate_that_cannot_be_started_is_a_fault_not_a_pass(tmp_path: Path) -> None:
    missing = Job(0, "ghost", (str(tmp_path / "no-such-program.exe"),))
    for workers in (1, 3):
        with pytest.raises(OSError):
            _runner(tmp_path, workers).run([missing, Job(1, "other", _program())])


def test_plan_jobs_asks_git_once_and_leaves_out_an_unreviewed_gate(tmp_path: Path) -> None:
    gates = [
        ("one", (PY, "scripts/a.py")),
        ("two", (PY, "scripts/b.py")),
        ("three", (PY, "-c", "pass")),
        ("four", (PY, "scripts/d.py")),
    ]
    asked: list[set[str]] = []

    def tracked(paths):
        asked.append(set(paths))
        return {"scripts/a.py", "scripts/d.py"}

    jobs, unreviewed = gate_runner.plan_jobs(
        gates,
        applies=lambda name: name != "four",
        resolve=lambda name, command: command,
        script_of=lambda command: next((c for c in command if c.endswith(".py") and c != PY), ""),
        tracked=tracked,
        skips={},
    )
    assert asked == [{"scripts/a.py", "scripts/b.py"}]  # one question, only for gates that apply and name a script
    assert [j.name for j in jobs] == ["one", "three"]
    assert unreviewed == ["two (scripts/b.py)"]


def test_plan_jobs_runs_everything_when_git_cannot_say_what_is_tracked() -> None:
    jobs, unreviewed = gate_runner.plan_jobs(
        [("one", (PY, "scripts/a.py"))],
        applies=lambda name: True,
        resolve=lambda name, command: command,
        script_of=lambda command: "scripts/a.py",
        tracked=lambda paths: None,
        skips={},
    )
    assert [j.name for j in jobs] == ["one"] and unreviewed == []


def test_plan_jobs_leaves_out_a_proven_no_op_but_not_an_unlisted_gate() -> None:
    jobs, _ = gate_runner.plan_jobs(
        [("problem_closure", (PY, "-c", "pass")), ("ruff", (PY, "-c", "pass"))],
        applies=lambda name: True,
        resolve=lambda name, command: command,
        script_of=lambda command: "",
        tracked=lambda paths: set(),
        skips={"problem_closure": "provable no-op"},
    )
    assert [j.name for j in jobs] == ["ruff"]


def test_worker_count_and_timeout_come_from_the_environment_and_stay_bounded() -> None:
    assert gate_runner.worker_count({gate_runner.WORKERS_ENV: "3"}) == 3
    assert gate_runner.worker_count({gate_runner.WORKERS_ENV: "0"}) == 1
    assert gate_runner.worker_count({gate_runner.WORKERS_ENV: "99"}) == gate_runner.MAX_WORKERS
    assert 1 <= gate_runner.worker_count({gate_runner.WORKERS_ENV: "nonsense"}) <= 2
    assert gate_runner.gate_timeout({gate_runner.TIMEOUT_ENV: "12.5"}) == 12.5
    assert gate_runner.gate_timeout({gate_runner.TIMEOUT_ENV: "-3"}) == gate_runner.DEFAULT_TIMEOUT
    assert gate_runner.gate_timeout({}) == gate_runner.DEFAULT_TIMEOUT


def test_stage_of_puts_board_readers_after_the_writer_and_the_last_look_last() -> None:
    assert gate_runner.stage_of("active_folder_guard") == 0
    assert gate_runner.stage_of("some_new_gate") == 0
    for name in ("workboard_claims", "workboard_task_problems", "workboard_changed_files", "workboard_agent_claim"):
        assert gate_runner.stage_of(name) == 1
    assert gate_runner.stage_of("workboard_inbox_final") == 2


def test_the_default_is_two_workers_whatever_the_core_count(monkeypatch) -> None:
    """Two per commit call by default (your decision after the performance review), one on a small machine."""
    for cores, expected in ((64, 2), (16, 2), (8, 2), (4, 1), (1, 1), (None, 1)):
        monkeypatch.setattr(gate_runner.os, "cpu_count", lambda cores=cores: cores)
        assert gate_runner.worker_count({}) == expected, cores
    assert gate_runner.DEFAULT_MAX_WORKERS == 2
    monkeypatch.setattr(gate_runner.os, "cpu_count", lambda: 64)
    assert gate_runner.worker_count({gate_runner.WORKERS_ENV: "4"}) == 4, "an explicit setting still wins"
