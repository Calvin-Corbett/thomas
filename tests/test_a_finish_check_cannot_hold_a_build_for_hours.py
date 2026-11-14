"""A finish check cannot hold a Build run for hours.

Measured 2026-10-07 on the live caged server: all four Thomas Build runs held at their finish for about 3 hours. Each
team's VERIFY was a bare `python -m pytest`, the whole ~13k-test suite. `default_runner` ran it through
`subprocess.run(shell=True, capture_output=True, timeout=...)`; on Windows the timeout killed only cmd.exe, the venv's
python launcher and the interpreter under it lived on holding the output pipes, and the second `communicate()` inside
`subprocess.run` waited for the whole suite (the runner stack dumps showed default_runner -> evaluate_contract ->
hold_at_finish for 8-9 consecutive 20-minute dumps). A whole-suite pytest still runs; at the clock it is told what to
run instead.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import psutil
import pytest

from thomas.core import acceptance_contract as ac

# The real shape: cmd.exe -> the venv launcher -> python -> the venv launcher -> python, all holding stdout.
CHILD = """import os, subprocess, sys, time
open('child.pid', 'w').write(str(os.getpid()))
grandchild = subprocess.Popen([sys.executable, 'grandchild.py'])
while not os.path.exists('grandchild.pid'):
    time.sleep(0.05)
print('child started its grandchild', flush=True)
if sys.argv[1] == 'waits':
    grandchild.wait()
"""
GRANDCHILD = """import os, time
open('grandchild.tmp', 'w').write(str(os.getpid()))
os.replace('grandchild.tmp', 'grandchild.pid')
time.sleep(60)
"""


def _alive(pid: int, script: str) -> bool:
    try:
        proc = psutil.Process(pid)
        return proc.status() != psutil.STATUS_ZOMBIE and any(script in part for part in proc.cmdline())
    except psutil.Error:
        return False


def _pids(ws: Path) -> dict[str, int]:
    names = [name for name in ("child", "grandchild") if (ws / f"{name}.pid").is_file()]
    return {name: int((ws / f"{name}.pid").read_text()) for name in names}


@pytest.mark.parametrize(
    ("mode", "clock", "expected"),
    [
        ("waits", 2.0, (124, "timed out after 2s")),
        ("leaves", 60.0, (0, "child started its grandchild\n")),
    ],
)
def test_nothing_the_command_starts_outlives_it_or_holds_the_check_past_its_clock(tmp_path, mode, clock, expected):
    (tmp_path / "child.py").write_text(CHILD)
    (tmp_path / "grandchild.py").write_text(GRANDCHILD)
    started = time.monotonic()
    try:
        result = ac.default_runner(f"python child.py {mode}", tmp_path, clock)
        elapsed = time.monotonic() - started
        assert result == expected
        assert elapsed < 25, f"returned after {elapsed:.0f}s; the grandchild sleeps 60s"
        pids = _pids(tmp_path)
        assert set(pids) == {"child", "grandchild"}, "the grandchild never started"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(_alive(pid, f"{name}.py") for name, pid in pids.items()):
            time.sleep(0.2)
        assert not [name for name, pid in pids.items() if _alive(pid, f"{name}.py")], "a process outlived the check"
    finally:
        for name, pid in _pids(tmp_path).items():
            if _alive(pid, f"{name}.py"):
                psutil.Process(pid).kill()


def test_a_command_keeps_its_exit_code_and_the_tail_of_its_output(tmp_path):
    script = "import sys; print('x' * 3000); sys.stderr.write('ERR-END'); sys.exit(3)"
    assert ac.default_runner(f'python -c "{script}"', tmp_path, 60.0) == (3, "x" * 1492 + "\nERR-END")
    assert ac.default_runner('python -c "print(42)"', tmp_path, 60.0) == (0, "42\n")
    assert ac.default_runner('python -c "pass"', tmp_path / "missing", 60.0)[0] == 127


CLOCK = (124, "timed out after 180s")


def _evaluate(tmp_path: Path, items: list[ac.ContractItem], result: tuple[int, str]):
    ran: list[str] = []

    def runner(cmd: str, cwd: Path, timeout: float) -> tuple[int, str]:
        ran.append(cmd)
        return result

    return ac.evaluate_contract(items, workspace=tmp_path, run_commands=True, runner=runner), ran


def _finish(tmp_path: Path, command: str, result: tuple[int, str]) -> tuple[ac.ContractItem, list[str]]:
    items = ac.with_finish_items([], f"EVIDENCE: done\n\nVERIFY: {command}")
    evaluated, ran = _evaluate(tmp_path, items, result)
    return evaluated[-1], ran


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest",
        "pytest",
        "python -m pytest -q",
        "python -m pytest -x -p no:cacheprovider",
        ".venv/Scripts/python.exe -m pytest -q",
        '"C:/Python312/python.exe" -m pytest -q',
        pytest.param(".venv\\Scripts\\python.exe -m pytest", marks=pytest.mark.skipif(os.name != "nt", reason="cmd")),
        "py -m pytest",
        "cd sub && python -m pytest",
        "python3 -m pytest --tb=short 2>&1",
        "pytest .",
    ],
)
def test_a_whole_suite_pytest_runs_and_at_the_clock_is_told_to_name_its_tests(tmp_path, command):
    """It still runs: in a small project the whole suite passes in seconds, and a refusal would cost a whole pass."""
    item, ran = _finish(tmp_path, command, (0, "5 passed"))
    assert item.satisfied and ran == [command]
    item, _ = _finish(tmp_path, command, CLOCK)
    assert not item.satisfied and item.detail.startswith("exit 124: timed out after 180s; ")
    assert "runs the whole test suite" in item.detail and "name the test files this work changed" in item.detail


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest tests/test_x.py",
        "python -m pytest -q -p no:cacheprovider tests/test_x.py::test_y",
        "pytest -k smoke",
        "python -m pytest --keyword=smoke -q",
        'python -m pytest -k "smoke|fast"',
        "pytest tests",
    ],
)
def test_a_named_pytest_run_at_the_clock_is_told_to_narrow_it(tmp_path, command):
    item, ran = _finish(tmp_path, command, (0, "1 passed"))
    assert item.satisfied and ran == [command]
    item, _ = _finish(tmp_path, command, CLOCK)
    assert item.detail.startswith("exit 124: timed out after 180s; ") and "narrow it to the tests" in item.detail
    assert "whole test suite" not in item.detail


@pytest.mark.parametrize("command", ["node build.js", 'python -c "import time; time.sleep(9)"', "pip install pytest"])
def test_a_timeout_that_is_not_pytest_keeps_the_plain_text(tmp_path, command):
    assert _finish(tmp_path, command, CLOCK)[0].detail == "exit 124: timed out after 180s"


def test_only_the_clock_gets_guidance(tmp_path):
    assert _finish(tmp_path, "python -m pytest", (1, "2 failed"))[0].detail == "exit 1: 2 failed"


def test_a_whole_suite_pytest_in_the_request_is_a_contract_command_and_gets_the_same_guidance(tmp_path):
    items = ac.build_contract("Run `python -m pytest` before you finish.", tmp_path)
    evaluated, ran = _evaluate(tmp_path, items, CLOCK)
    item = next(it for it in evaluated if it.item_id == "command:python -m pytest")
    assert ran == ["python -m pytest"] and item.detail.startswith("exit 124: timed out after 180s; ")
    assert "runs the whole test suite" in item.detail
