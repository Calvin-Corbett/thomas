"""check.run answers before the agent loop gives up on it, and takes the read-only options teams reach for (2026-10-27).

The agent loop stops waiting on any tool after 600 s (thomas/agent/loop_core.py), while check.run allowed itself 900:
in four days 96 check.run calls ended "Tool timed out after 600s", with no output and no word of which test was
slow. In the same days 53 calls were refused for read-only options (``git diff --``, ``--cached``, ``--check``,
``--name-only``, ``git status --short``, ``pytest --durations=N``, ``-vv``), each a turn spent on nothing.

Since 2026-11-13 a test run waits its turn in the one line of test runs (machine_load.Line) and then has all of its
own time: the wait is no longer taken out of it (tests/test_test_runs_wait_in_one_line.py).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.tools import check_run
from thomas.tools.check_run import CheckRefused, CheckRunTool

LOOP_TOOL_LIMIT_S = 600  # loop_core.default_tool_timeout_s


def test_the_whole_budget_ends_before_the_loop_gives_up(tmp_path: Path) -> None:
    assert CheckRunTool(tmp_path).timeout + 30 <= LOOP_TOOL_LIMIT_S


def _run_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waited: float, exit_code: int | None) -> Any:
    (tmp_path / "test_x.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    seen: dict[str, float] = {}

    clock = [0.0]

    class Line:
        def join(self, _label: str) -> int:
            return 1

        def look(self, _ticket: int) -> tuple[bool, int]:
            clock[0] += waited
            return True, 0

        def leave(self, _ticket: int) -> None:
            pass

    def run(argv: list[str], cwd: Path, timeout: float, started: dict[str, Any]) -> tuple[int | None, str]:
        seen["timeout"] = timeout
        return exit_code, "partial output"

    monkeypatch.setattr(check_run.machine_load, "line", lambda: Line())
    monkeypatch.setattr(check_run, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(check_run, "_JOBS", {})
    monkeypatch.setattr(check_run, "_run_blocking", run)
    result = asyncio.run(CheckRunTool(tmp_path, timeout=540).execute({"check": "pytest", "args": ["test_x.py"]}))
    return result, seen["timeout"]


def test_the_wait_for_its_turn_takes_nothing_from_the_runs_own_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, timeout = _run_with(monkeypatch, tmp_path, waited=100.0, exit_code=0)
    assert result.ok and timeout == 540
    assert "waited 100 s for its turn" in result.data["waited_for_room"]


def test_a_run_out_of_time_says_how_long_it_had(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result, timeout = _run_with(monkeypatch, tmp_path, waited=100.0, exit_code=None)
    assert not result.ok and timeout == 540
    assert "timed out after 540 s" in (result.error or "") and "partial output" in (result.error or "")


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--"], ["diff", "--no-ext-diff", "--"]),
        (["--", "a.py"], ["diff", "--no-ext-diff", "--", "a.py"]),
        (["--cached", "--", "a.py"], ["diff", "--no-ext-diff", "--cached", "--", "a.py"]),
        (["--staged"], ["diff", "--no-ext-diff", "--cached", "--"]),
        (["--stat", "--check"], ["diff", "--no-ext-diff", "--stat", "--check", "--"]),
        (["--name-only", "a.py"], ["diff", "--no-ext-diff", "--name-only", "--", "a.py"]),
        (["--name-status"], ["diff", "--no-ext-diff", "--name-status", "--"]),
    ],
)
def test_git_diff_takes_its_read_only_options(tmp_path: Path, args: list[str], expected: list[str]) -> None:
    argv = check_run.build_argv("git_diff", args, tmp_path)
    assert argv[argv.index("diff") :] == expected


@pytest.mark.parametrize("bad", ["--output=x.txt", "--ext-diff", "--no-index", "-c", "--exit-code"])
def test_git_diff_still_refuses_any_other_option(tmp_path: Path, bad: str) -> None:
    with pytest.raises(CheckRefused):
        check_run.build_argv("git_diff", [bad], tmp_path)


def test_git_status_takes_short_which_it_already_is(tmp_path: Path) -> None:
    assert check_run.build_argv("git_status", ["--short"], tmp_path)[-2:] == ["status", "--short"]
    with pytest.raises(CheckRefused):
        check_run.build_argv("git_status", ["--porcelain"], tmp_path)


@pytest.mark.parametrize("flag", ["--durations=0", "--durations=10", "--durations=50", "-vv"])
def test_pytest_takes_durations_and_vv(tmp_path: Path, flag: str) -> None:
    (tmp_path / "test_x.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    assert flag in check_run.build_argv("pytest", ["test_x.py", flag], tmp_path)


@pytest.mark.parametrize("flag", ["--durations=51", "--durations=x", "--durations-min=1", "-vvv"])
def test_pytest_refuses_other_durations(tmp_path: Path, flag: str) -> None:
    (tmp_path / "test_x.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    with pytest.raises(CheckRefused):
        check_run.build_argv("pytest", ["test_x.py", flag], tmp_path)
