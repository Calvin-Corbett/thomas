"""The Build agent can run the project's tests and ruff, and nothing else.

A live probe at Full autonomy: asked to run pytest, the builder said it could
not. Its only command tool was ``shell.exec``, registered only at guardrails
``open``, and the prompt said "Direct shell is unavailable". Approved answer:
"Narrow check tool (Recommended): A new tool that only runs: pytest on paths or
-k selections, ruff check / format --check, and read-only git (status, diff,
log). It runs in the project folder with a 15-minute limit and capped output,
at Agent autonomy and above. No other commands."
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from thomas.tools import check_run
from thomas.tools.check_run import OUTPUT_CAP_CHARS, CheckRunTool

_SAMPLE_TESTS = """
def test_passes():
    assert 1 + 1 == 2


def test_fails():
    assert 1 + 1 == 3, "arithmetic is broken"
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "test_sample.py").write_text(_SAMPLE_TESTS, encoding="utf-8")
    return tmp_path


def _run(tool: CheckRunTool, check: str, args: list[str]) -> Any:
    return asyncio.run(tool.safe_execute({"check": check, "args": args}))


# -- it runs the checks it is meant to run -----------------------------------


def test_a_passing_selection_reports_exit_zero(project: Path) -> None:
    result = _run(CheckRunTool(project), "pytest", ["-q", "-p", "no:cacheprovider", "test_sample.py::test_passes"])
    assert result.ok, result.error
    assert result.data["exit_code"] == 0
    assert "1 passed" in result.data["output"]


def test_a_failing_test_is_a_successful_call_with_a_nonzero_exit(project: Path) -> None:
    result = _run(CheckRunTool(project), "pytest", ["-q", "-p", "no:cacheprovider", "test_sample.py"])
    assert result.ok, "a red test run is a successful tool call; the exit code carries the verdict"
    assert result.data["exit_code"] == 1
    assert result.data["passed"] is False
    assert "1 failed" in result.data["output"]
    assert "arithmetic is broken" in result.data["output"]


def test_a_k_selection_runs_only_what_it_names(project: Path) -> None:
    result = _run(CheckRunTool(project), "pytest", ["-q", "-p", "no:cacheprovider", "-k", "passes"])
    assert result.ok, result.error
    assert result.data["exit_code"] == 0
    assert "1 passed" in result.data["output"]


def test_ruff_check_runs_on_a_relative_path(project: Path) -> None:
    (project / "bad.py").write_text("import os\n", encoding="utf-8")
    result = _run(CheckRunTool(project), "ruff_check", ["bad.py"])
    assert result.ok, result.error
    assert result.data["exit_code"] != 0
    assert "F401" in result.data["output"]


def test_ruff_format_check_never_rewrites_the_file(project: Path) -> None:
    ugly = "x=1\n"
    (project / "ugly.py").write_text(ugly, encoding="utf-8")
    result = _run(CheckRunTool(project), "ruff_format_check", ["ugly.py"])
    assert result.ok, result.error
    assert result.data["exit_code"] != 0
    assert (project / "ugly.py").read_text(encoding="utf-8") == ugly
    assert "-x=1" in result.data["output"]
    assert "+x = 1" in result.data["output"]
    assert "+x = 1" in result.to_content()[:5000], "The repair must reach the builder's tool context"


def test_formatted_file_has_no_repair_diff_and_stays_unchanged(project: Path) -> None:
    clean = "x = 1\n"
    (project / "clean.py").write_text(clean, encoding="utf-8")
    result = _run(CheckRunTool(project), "ruff_format_check", ["clean.py"])
    assert result.ok and result.data["passed"]
    assert result.data["exit_code"] == 0
    assert (project / "clean.py").read_text(encoding="utf-8") == clean
    assert "@@" not in result.data["output"]


def test_read_only_git_runs(project: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    result = _run(CheckRunTool(project), "git_status", [])
    assert result.ok, result.error
    assert result.data["exit_code"] == 0
    assert "test_sample.py" in result.data["output"]


# -- it refuses everything else, before anything runs ------------------------


@pytest.mark.parametrize(
    ("check", "args", "named"),
    [
        ("pytest", ["--rootdir=x"], "--rootdir=x"),
        ("pytest", ["-c", "other.ini"], "-c"),
        ("pytest", ["--confcutdir", "x"], "--confcutdir"),
        ("pytest", ["-p", "evil_plugin"], "evil_plugin"),
        ("pytest", ["../outside.py"], "../outside.py"),
        ("pytest", ["/abs/path.py"], "/abs/path.py"),
        ("pytest", ["C:\\abs\\path.py"], "C:\\abs\\path.py"),
        ("pytest", ["; rm"], "; rm"),
        ("pytest", ["@args.txt"], "@args.txt"),
        ("pytest", ["-k", "@args.txt"], "@args.txt"),
        ("pytest", ["-k"], "-k"),
        ("pytest", ["--maxfail=abc"], "--maxfail=abc"),
        ("pytest", ["--tb=long"], "--tb=long"),
        ("ruff_check", ["--fix", "a.py"], "--fix"),
        ("ruff_check", ["../a.py"], "../a.py"),
        ("ruff_format_check", ["--diff"], "--diff"),
        ("git_status", ["push"], "push"),
        ("git_diff", ["--no-index"], "--no-index"),
        ("git_diff", ["--output=x"], "--output=x"),
        ("git_log", ["-n", "500"], "500"),
        ("git_log", ["--all"], "--all"),
        ("git_push", [], "git_push"),
        ("shell", ["echo hi"], "shell"),
    ],
)
def test_anything_off_the_allowlist_is_refused_and_nothing_runs(
    project: Path, monkeypatch: pytest.MonkeyPatch, check: str, args: list[str], named: str
) -> None:
    launched: list[Any] = []

    def _no_launch(*a: Any, **k: Any) -> Any:
        launched.append(a)
        raise AssertionError("a refused check must not start a process")

    monkeypatch.setattr(check_run.subprocess, "Popen", _no_launch)
    result = _run(CheckRunTool(project), check, args)
    assert not result.ok
    assert named in (result.error or ""), result.error
    assert not launched


@pytest.mark.parametrize(
    "args",
    [["-q", "-p", "no:cacheprovider", "--no-header", "--tb=short"], [], ["-x", "."], ["./"]],
    ids=["the-live-call", "no-args", "dot", "dot-slash"],
)
def test_a_pytest_check_that_names_no_test_is_refused_because_the_whole_suite_cannot_finish(
    project: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """2026-10-07, live: a Build team's check.run of `pytest -q -p no:cacheprovider --no-header --tb=short` with no
    target ran the whole ~13k-test suite (about 53 minutes) against the 15-minute limit, so it could never pass."""
    launched: list[Any] = []
    monkeypatch.setattr(check_run.subprocess, "Popen", lambda *a, **k: launched.append(a))
    result = _run(CheckRunTool(project), "pytest", args)
    assert not result.ok and not launched
    assert "whole test suite" in result.error and "too large to run here" in result.error
    assert "name the test files you changed" in result.error and "tests/test_x.py" in result.error


@pytest.mark.parametrize(
    "args", [["-q", "tests/test_x.py"], ["tests/test_x.py::test_y", "--tb=short"], ["-k", "smoke"], ["tests"]]
)
def test_a_pytest_check_that_names_its_tests_is_still_accepted(project: Path, args: list[str]) -> None:
    argv = check_run.build_argv("pytest", args, project)
    assert argv[:3] == [sys.executable, "-m", "pytest"] and argv[3:] == args


def test_it_never_uses_a_shell(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    real_popen = subprocess.Popen

    def _spy(argv: Any, **kwargs: Any) -> Any:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(check_run.subprocess, "Popen", _spy)
    result = _run(CheckRunTool(project), "pytest", ["-q", "-p", "no:cacheprovider", "test_sample.py::test_passes"])
    assert result.ok, result.error
    assert isinstance(seen["argv"], list)
    assert seen["argv"][:3] == [sys.executable, "-m", "pytest"]
    assert not seen["kwargs"].get("shell")
    assert Path(seen["kwargs"]["cwd"]) == project.resolve()
    assert "PYTHONSAFEPATH" not in seen["kwargs"]["env"]


# -- output and time are bounded ---------------------------------------------


def test_output_is_capped_to_its_tail(project: Path) -> None:
    (project / "test_loud.py").write_text(
        'def test_loud():\n    assert False, "HEAD" + "x" * 60000 + "TAILMARK"\n', encoding="utf-8"
    )
    result = _run(CheckRunTool(project), "pytest", ["-q", "-p", "no:cacheprovider", "--tb=short", "test_loud.py"])
    assert result.ok, result.error
    output = result.data["output"]
    assert "[output truncated: showing last" in output
    assert len(output) <= OUTPUT_CAP_CHARS + 200
    assert "1 failed" in output, "the tail, where pytest prints its verdict, must survive the cap"


def test_the_verdict_leads_the_result_so_the_loop_cannot_cut_it_off(project: Path) -> None:
    """The agent loop keeps only the first 5,000 characters of a tool result."""
    result = _run(CheckRunTool(project), "pytest", ["-q", "-p", "no:cacheprovider", "test_sample.py"])
    head = result.to_content()[:5000]
    assert '"exit_code": 1' in head
    assert "1 failed" in head


def test_a_run_past_its_limit_is_killed_and_reported(project: Path) -> None:
    (project / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(60)\n", encoding="utf-8")
    result = _run(CheckRunTool(project, timeout=3), "pytest", ["-q", "-p", "no:cacheprovider", "test_slow.py"])
    assert not result.ok
    assert "timed out" in (result.error or "")


def test_the_default_limit_is_nine_minutes(project: Path) -> None:
    # Inside the agent loop's 600 s limit for a tool (test_check_run_answers_inside_the_loops_limit.py).
    assert CheckRunTool(project).timeout == 540


# -- it is registered exactly where the run may edit -------------------------
