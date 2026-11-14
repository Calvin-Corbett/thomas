"""A change's tests run as a separate, lower-privilege identity, never as the account that writes the answer.

Review B1 (2026-10-14): the checker (``thomas-checker``) writes the results and state folders, so a change whose own
code runs under that account while it is checked could write its own PASSED, or another job's. The fix runs every
test process as ``thomas-runner`` -- an account ``enable_window.ps1`` gives read on the repo and write only inside a
job's copy, never ``jobs``, ``results`` or ``state``. The account-sensitive tests fake the launch and identity;
the short-command regression also runs a real local pytest process without creating an account or changing an ACL.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import checker_launch as cl
from scripts.cage import checker_run as cr
from scripts.cage import checker_runner as crun

from tests.green_support import git, make_blue
from thomas.server import proof


def test_logon_line_stays_short_and_child_runs_an_unabridged_pytest_command(tmp_path: Path) -> None:
    test_file = tmp_path / "test_long_argv.py"
    test_file.write_text("def test_ran():\n    assert True\n", encoding="utf-8")
    report = tmp_path / "result.xml"
    payload = tmp_path / "runner.json"
    out = tmp_path / "runner.out"
    command = [sys.executable, "-m", "pytest", str(test_file), "-q", f"--junit-xml={report}"]
    command.extend(["-o", "addopts="] * 90)  # A real pytest invocation exceeding the logon API's limit.
    command.extend(["-p", "no:cacheprovider", "--rootdir", str(tmp_path)])
    assert len(subprocess.list2cmdline(command)) > 1024
    payload.write_text(json.dumps({"command": command, "out": str(out)}), encoding="utf-8")
    line = cl._child_command(payload).value
    assert len(line) + 1 <= 1024
    assert str(test_file) not in line
    # The runner runs a script beside its payload, never a file of the checker's own (protected) scripts\cage.
    assert Path(cl.__file__).name not in line
    child = payload.with_suffix(".py")
    assert str(child) in line
    assert subprocess.run([sys.executable, "-I", str(child), str(payload)], check=False).returncode == 0
    assert "1 passed" in out.read_text(encoding="utf-8")
    assert 'tests="1"' in report.read_text(encoding="utf-8")


def _commit(repo: Path, rel: str, text: str) -> tuple[str, str]:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"change {rel}")
    return git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_blue(tmp_path)


def _job(repo: Path) -> cj.Job:
    base = git(repo, "rev-parse", "HEAD")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_fix_me.py").write_text(
        "from thomas import fix_me\n\n\ndef test_value():\n    assert fix_me.VALUE == 2\n", encoding="utf-8"
    )
    (repo / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change with a covering test")
    commit, tree = git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")
    return cj.Job(
        "a" * 24, cj.CHECK, base, commit, tree, ("thomas/fix_me.py", "tests/test_fix_me.py"), (), posted_at=1.0
    )


def _configure(state: Path) -> None:
    (state).mkdir(parents=True, exist_ok=True)
    cj.write_json(
        state / crun.CONFIG_NAME,
        {"schema": crun.SCHEMA, "account": "TESTPC\\thomas-runner", "credential": "Thomas-Checker-Runner"},
    )


def test_a_configured_runner_is_available_and_an_unconfigured_one_is_not(tmp_path: Path) -> None:
    runner = crun.Runner(tmp_path / "state", launch=lambda *a, **k: (0, ""))
    assert not runner.configured and not runner.available()
    assert runner.reason()  # it says why, for the UNAVAILABLE answer
    _configure(tmp_path / "state")
    ready = crun.Runner(tmp_path / "state", launch=lambda *a, **k: (0, ""))
    assert ready.configured and ready.available()


def test_every_test_process_of_a_job_launches_through_the_runner(repo: Path, tmp_path: Path) -> None:
    """The seam: run_job runs its tests, re-runs and boot check only through the runner's launch, as its account."""
    state = tmp_path / "state"
    _configure(state)
    launched: list[tuple[str, list[str]]] = []

    def launch(command: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float, identity: crun.Identity):
        launched.append((identity.account, list(command)))
        # A real pytest would write a report; answer "nothing collected" so the run settles without a report reader.
        return proof.environment.NOT_STARTED, "fake launch: no process really ran"

    runner = crun.Runner(state, launch=launch)
    result = cr.run_job(
        _job(repo), repo=repo, copies=tmp_path / "copies", python="py", runner=runner, clock=lambda: 9.0
    )
    assert launched, "no test process was launched"
    assert all(account == "TESTPC\\thomas-runner" for account, _ in launched), launched
    # Nothing ran as the checker's own interpreter path outside the runner.
    assert result.verdict == cj.UNAVAILABLE


def test_without_a_runner_identity_a_job_is_unavailable_and_no_test_runs(repo: Path, tmp_path: Path) -> None:
    """Fail closed: with no isolated identity the checker answers UNAVAILABLE and never runs the tests as itself."""
    ran: list[str] = []

    def launch(*_a: object, **_k: object) -> tuple[int, str]:
        ran.append("launched")
        return 0, ""

    runner = crun.Runner(tmp_path / "state", launch=launch)  # not configured
    assert not runner.available()
    result = cr.run_job(
        _job(repo), repo=repo, copies=tmp_path / "copies", python="py", runner=runner, clock=lambda: 9.0
    )
    assert result.verdict == cj.UNAVAILABLE
    assert "isolated" in result.why or "runner" in result.why
    assert ran == [], "a job with no isolated identity must not launch any test process"
    assert not (tmp_path / "copies").exists(), "no copy is made when the checker cannot run tests safely"


def test_the_runner_tools_route_the_subprocess_run_but_keep_selection(tmp_path: Path) -> None:
    _configure(tmp_path / "state")
    seen: list[list[str]] = []
    runner = crun.Runner(tmp_path / "state", launch=lambda command, **k: seen.append(list(command)) or (0, ""))
    tools = runner.tools()
    assert tools.select is proof.select and tools.confirm is proof.confirm
    code, _ = tools.run(["py", "-c", "pass"], cwd=tmp_path, env={}, timeout_s=1.0)
    assert code == 0 and seen == [["py", "-c", "pass"]]


def test_a_command_the_runner_cannot_start_says_why_instead_of_passing_as_pytest(tmp_path: Path) -> None:
    payload = tmp_path / "runner.json"
    out = tmp_path / "runner.out"
    missing = str(tmp_path / "no-such-python.exe")
    payload.write_text(json.dumps({"command": [missing, "-m", "pytest"], "out": str(out)}), encoding="utf-8")
    cl._child_command(payload)
    code = subprocess.run([sys.executable, "-I", str(payload.with_suffix(".py")), str(payload)], check=False).returncode
    assert code == cl._CHILD_NOT_STARTED
    assert "could not start the test command" in out.read_text(encoding="utf-8")
