"""The same test run on work that has not changed answers from its last result instead of running again.

Measured on your PC, 2026-11-09 17:30 to 21:30: Build agents called ``check.run`` 393 times for about 13 hours of
checking, and pytest was about 210 of those calls and 11 of the hours. 27 calls, about 2.6 hours, were the same call
a run had already made with nothing in the project changed in between: no file written, no command run. Tests are
what fill the PC's cores, so that time was spent finding out what was already known.

Only pytest is answered this way, because it is the slow one; ruff and the git reads always run. The answer says it
is a repeat and how old it is, and ``fresh`` runs it again regardless.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from thomas.tools import check_reuse, check_run


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "project"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    ran: list[list[str]] = []
    answer = {"code": 0, "text": "1 passed in 0.01s"}

    def run(argv, cwd, timeout, started):
        ran.append(list(argv))
        return answer["code"], answer["text"]

    async def room(**_kwargs):
        return 0.0, ""

    monkeypatch.setattr(check_run, "_run_blocking", run)
    monkeypatch.setattr(check_run.machine_load, "await_room", room)
    tool = check_run.CheckRunTool(repo, reuse_dir=tmp_path / "reuse")
    return repo, tool, ran, answer


def _check(tool, *args: str, check: str = "pytest", **more):
    return asyncio.run(tool.execute({"check": check, "args": list(args), **more}))


def test_the_same_tests_on_unchanged_work_are_not_run_twice(project) -> None:
    repo, tool, ran, _answer = project
    first = _check(tool, "tests/test_a.py", "-q")
    again = _check(tool, "tests/test_a.py", "-q")
    assert len(ran) == 1
    assert "reused" not in first.data
    assert again.ok and again.data["passed"] is True and again.data["exit_code"] == 0
    assert again.data["verdict_tail"] == first.data["verdict_tail"]
    assert "nothing in the project has changed" in again.data["reused"] and "fresh" in again.data["reused"]


def test_a_failure_is_repeated_too_and_says_how_to_run_it_again(project) -> None:
    repo, tool, ran, answer = project
    answer.update(code=1, text="1 failed in 0.01s")
    _check(tool, "tests/test_a.py")
    again = _check(tool, "tests/test_a.py")
    assert len(ran) == 1 and again.data["passed"] is False and again.data["exit_code"] == 1
    assert "fresh" in again.data["reused"]


@pytest.mark.parametrize("change", ["edit a tracked file", "add a new file", "delete a file", "commit"])
def test_any_change_to_the_project_runs_the_tests_again(project, change: str) -> None:
    repo, tool, ran, _answer = project
    _check(tool, "tests/test_a.py")
    if change == "edit a tracked file":
        (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    elif change == "add a new file":
        (repo / "new_module.py").write_text("NEW = 1\n", encoding="utf-8")
    elif change == "delete a file":
        (repo / "app.py").unlink()
    else:
        (repo / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
        _git(repo, "commit", "-qam", "a commit")
    again = _check(tool, "tests/test_a.py")
    assert len(ran) == 2 and "reused" not in again.data


def test_an_edit_that_is_then_put_back_still_runs_again_only_if_the_file_differs(project) -> None:
    repo, tool, ran, _answer = project
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _check(tool, "tests/test_a.py")
    (repo / "app.py").write_text("VALUE = 5\n", encoding="utf-8")  # same length, different content
    _check(tool, "tests/test_a.py")
    assert len(ran) == 2


def test_different_tests_or_flags_are_a_different_question(project) -> None:
    repo, tool, ran, _answer = project
    _check(tool, "tests/test_a.py")
    _check(tool, "tests/test_a.py", "-x")
    _check(tool, "tests/test_a.py::test_a")
    assert len(ran) == 3


def test_fresh_runs_it_again_regardless(project) -> None:
    repo, tool, ran, _answer = project
    _check(tool, "tests/test_a.py")
    again = _check(tool, "tests/test_a.py", fresh=True)
    assert len(ran) == 2 and "reused" not in again.data


def test_a_run_that_timed_out_is_never_an_answer(project) -> None:
    repo, tool, ran, answer = project
    answer.update(code=None, text="still running")
    assert _check(tool, "tests/test_a.py").ok is False
    answer.update(code=0, text="1 passed")
    again = _check(tool, "tests/test_a.py")
    assert len(ran) == 2 and "reused" not in again.data


def test_ruff_and_the_git_reads_always_run(project) -> None:
    repo, tool, ran, _answer = project
    for check, args in (("ruff_check", ["app.py"]), ("git_status", [])):
        _check(tool, *args, check=check)
        again = _check(tool, *args, check=check)
        assert "reused" not in again.data
    assert len(ran) == 4


def test_a_folder_that_is_not_a_git_project_always_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = tmp_path / "plain"
    (plain / "tests").mkdir(parents=True)
    (plain / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    ran: list[int] = []
    monkeypatch.setattr(check_run, "_run_blocking", lambda *a, **k: (ran.append(1), (0, "1 passed"))[1])

    async def room(**_kwargs):
        return 0.0, ""

    monkeypatch.setattr(check_run.machine_load, "await_room", room)
    tool = check_run.CheckRunTool(plain, reuse_dir=tmp_path / "reuse")
    _check(tool, "tests/test_a.py")
    _check(tool, "tests/test_a.py")
    assert len(ran) == 2
    assert check_reuse.fingerprint(plain) is None


def test_another_agent_in_the_same_project_gets_the_answer_too(project, tmp_path: Path) -> None:
    repo, tool, ran, _answer = project
    _check(tool, "tests/test_a.py")
    second = check_run.CheckRunTool(repo, reuse_dir=tmp_path / "reuse")
    again = _check(second, "tests/test_a.py")
    assert len(ran) == 1 and "reused" in again.data


def test_reading_the_state_runs_no_program_the_project_names_and_writes_nothing(project, monkeypatch) -> None:
    """A git project can name a program for git to run (core.fsmonitor), and the project is where the agent writes.
    The tool's own git checks turn that off; reading the state must too. It must not refresh the index either:
    another agent may be using it."""
    repo, _tool, _ran, _answer = project
    marker = repo / "ran-by-git.txt"
    _git(repo, "config", "core.fsmonitor", f"sh -c 'echo ran > {marker.as_posix()}'")
    seen: list[list[str]] = []
    real = check_reuse.subprocess.run

    def run(argv, **kwargs):
        seen.append(list(argv))
        return real(argv, **kwargs)

    monkeypatch.setattr(check_reuse.subprocess, "run", run)
    assert check_reuse.fingerprint(repo)
    assert seen and all("core.fsmonitor=false" in argv and "--no-optional-locks" in argv for argv in seen)
    assert not marker.exists()


def test_bytecode_and_pytest_cache_do_not_make_the_project_look_edited(tmp_path: Path) -> None:
    """A project that does not ignore them gets them from every test run: the run then looked like an edit."""
    import subprocess

    from thomas.tools import check_reuse

    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "mod.py").write_text("x = 1", encoding="utf-8")
    subprocess.run([*git, "add", "mod.py"], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    before = check_reuse.fingerprint(tmp_path)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"bytecode")
    assert before is not None and check_reuse.fingerprint(tmp_path) == before
    (tmp_path / "new.py").write_text("y = 2", encoding="utf-8")
    assert check_reuse.fingerprint(tmp_path) != before, "a file someone wrote still counts"
