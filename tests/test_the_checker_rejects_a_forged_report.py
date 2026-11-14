"""A report the test identity forges is not read as a pass (review B1, Finding A).

The checker reads its verdict from a JUnit report that pytest writes as ``thomas-runner`` -- the account whose change
is being checked. These tests plant a report through the run seam (as the runner would) and show the checker does not
trust it: a report a crashed process leaves, and a report carrying cases for files the checker did not run, are both
FAILED, never a pass. They use the real :func:`thomas.server.proof.runner.run_tests` and a real ``run`` stand-in that
writes the forged XML; nothing here runs a real account or a real pytest.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import checker_run as cr

from thomas.server import proof
from thomas.server.proof import runner


def _report_path(command: Sequence[str]) -> Path:
    for arg in command:
        if str(arg).startswith("--junit-xml="):
            return Path(str(arg).split("=", 1)[1])
    raise AssertionError(f"no --junit-xml in {command}")


def _xml(cases: list[tuple[str, str, bool]]) -> str:
    # cases: (classname, name, passed)
    body = ""
    for classname, name, passed in cases:
        inner = "" if passed else "<failure>boom</failure>"
        body += f'<testcase classname="{classname}" name="{name}" file="{classname.replace(".", "/")}.py">{inner}</testcase>'
    return f'<?xml version="1.0"?><testsuite tests="{len(cases)}">{body}</testsuite>'


def _forging_run(cases: list[tuple[str, str, bool]], code: int):
    def run(command: Sequence[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        _report_path(command).write_text(_xml(cases), encoding="utf-8")
        return code, "forged"

    return run


@pytest.fixture
def work(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_real.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return root


def test_a_clean_matching_report_is_a_pass(work: Path, tmp_path: Path) -> None:
    run = _forging_run([("tests.test_real", "test_ok", True)], 0)
    out = runner.run_tests(
        work, ["tests/test_real.py"], python="py", data_dir=tmp_path / "d", run=run, folder=True, strict_report=True
    )
    assert out.ran and not out.crashed and not out.unexpected and not out.failed


def test_a_report_a_crashed_process_left_is_not_a_pass(work: Path, tmp_path: Path) -> None:
    # The report says the one selected test passed, but the process exited 137 (killed): its report proves nothing.
    run = _forging_run([("tests.test_real", "test_ok", True)], 137)
    out = runner.run_tests(
        work, ["tests/test_real.py"], python="py", data_dir=tmp_path / "d", run=run, folder=True, strict_report=True
    )
    assert out.crashed == ("tests/test_real.py",)


def test_a_report_that_invents_cases_for_unselected_files_is_not_a_pass(work: Path, tmp_path: Path) -> None:
    # A forged report that claims a pass for a file the checker never selected.
    run = _forging_run([("tests.test_real", "test_ok", True), ("tests.test_evil", "test_fake", True)], 0)
    out = runner.run_tests(
        work, ["tests/test_real.py"], python="py", data_dir=tmp_path / "d", run=run, folder=True, strict_report=True
    )
    assert "tests.test_evil" in out.unexpected


def test_without_strict_report_the_live_check_is_unchanged(work: Path, tmp_path: Path) -> None:
    # The card check does not ask for strict_report, so these extra checks never change its result.
    run = _forging_run([("tests.test_real", "test_ok", True)], 137)
    out = runner.run_tests(work, ["tests/test_real.py"], python="py", data_dir=tmp_path / "d", run=run, folder=True)
    assert not out.crashed and not out.unexpected


class _CrashTools(cr.Tools):
    """A run that reports a pass but whose report a crashed process left (crashed set by run_tests)."""

    def __init__(self, *, crashed: tuple[str, ...] = (), unexpected: tuple[str, ...] = ()) -> None:
        def run_tests(work: Path, files: list[str], **kwargs: object) -> proof.ProofRun:
            return proof.ProofRun(True, "", (), 3, 1, crashed=crashed, unexpected=unexpected)

        super().__init__(
            select=lambda w, c: proof.Selection(("tests/test_real.py",)),
            run_tests=run_tests,
            run_one=lambda *a, **k: proof.PASSED,
            confirm=proof.confirm,
            run=lambda *a, **k: (0, ""),
        )


def _job(repo: Path) -> cj.Job:
    from tests.green_support import git

    base = git(repo, "rev-parse", "HEAD")
    (repo / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_real.py").write_text(
        "from thomas import fix_me\n\n\ndef test_ok():\n    assert fix_me.VALUE == 2\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")
    return cj.Job(
        "a" * 24, cj.CHECK, base, git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}"),
        ("thomas/fix_me.py", "tests/test_real.py"), (), posted_at=1.0,
    )  # fmt: skip


@pytest.mark.parametrize("field", ["crashed", "unexpected"])
def test_the_checker_answers_failed_when_the_report_is_not_trusted(tmp_path: Path, field: str) -> None:
    from tests.green_support import make_blue

    repo = make_blue(tmp_path)
    tools = _CrashTools(**{field: ("tests/test_real.py",)})
    result = cr.run_job(_job(repo), repo=repo, copies=tmp_path / "copies", python="py", tools=tools, clock=lambda: 9.0)
    assert result.verdict == cj.FAILED, result
    assert re.search(r"did not finish|did not run|report", result.why)
