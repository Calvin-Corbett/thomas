"""A git question that gets no answer is never proof (CHECK F1, expbuild27): with an earlier landing of the same key in
dev's window, a git status, ls-tree or hash-object that times out or exits with an error reads as "not landed", and in
the slot the commit tool still runs. Real git; only the chosen git subcommands are made to give no answer."""

from __future__ import annotations

import subprocess

import pytest
from scripts.crew.brief import land_git, landing_proc
from scripts.crew.brief.landing_queue import Lane, Outcome
from scripts.crew.brief.landing_store import FileTicketStore

from tests._landing_fakes import sp

KEY = "lq-0123456789ab"
REAL = landing_proc.run


@pytest.fixture()
def landed(tmp_path):  # noqa: ANN001, ANN201
    """A repo whose last commit landed D/a.txt with this landing key."""
    repo = tmp_path / "repo"
    (repo / "D").mkdir(parents=True)
    for args in (
        ["init", "-q"],
        ["config", "user.name", "t"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "commit.gpgsign", "false"],
        ["config", "core.autocrlf", "false"],
    ):
        sp.run(["git", *args], cwd=repo, check=True)
    (repo / "D" / "a.txt").write_text("one\n")
    sp.run(["git", "add", "-A"], cwd=repo, check=True)
    sp.run(["git", "commit", "-q", "-m", f"feat: x\n\nLanding-Ticket: {KEY}\n"], cwd=repo, check=True)
    return repo


def no_answer(monkeypatch, *subcommands: str, code: int | None = None) -> None:  # noqa: ANN001
    """``git <subcommand>`` times out (code None) or exits with ``code``; every other git call is real."""

    def run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if len(cmd) > 1 and cmd[0] == "git" and cmd[1] in subcommands:
            if code is None:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 60))
            return subprocess.CompletedProcess(cmd, code, stdout="", stderr="fatal: no answer")
        return REAL(cmd, *args, **kwargs)

    monkeypatch.setattr(landing_proc, "run", run)


def test_control_with_nothing_pending_the_earlier_landing_is_found(landed):
    assert land_git.find_landed(landed, KEY, ["D"]) is not None


@pytest.mark.parametrize("code", [None, 128], ids=["timeout", "error-exit"])
def test_a_new_file_and_a_git_status_without_an_answer_is_not_already_landed(landed, monkeypatch, code):
    (landed / "D" / "new.txt").write_text("pending\n")
    no_answer(monkeypatch, "status", code=code)
    assert land_git.find_landed(landed, KEY, ["D"]) is None  # was: the earlier landing's sha, "already landed"


@pytest.mark.parametrize("slow", [("ls-tree", "hash-object"), ("ls-tree",), ("hash-object",)])
def test_an_edited_file_and_blob_reads_without_an_answer_is_not_already_landed(landed, monkeypatch, slow):
    (landed / "D" / "a.txt").write_text("two\n")
    no_answer(monkeypatch, *slow)
    assert land_git.find_landed(landed, KEY, ["D"]) is None  # was (both): nothing compared to nothing, "already landed"


def test_in_the_slot_a_git_status_without_an_answer_runs_the_commit_tool(landed, tmp_path, monkeypatch):
    (landed / "D" / "new.txt").write_text("pending\n")
    lane = Lane(
        FileTicketStore(tmp_path / "queue"),
        agent="a",
        find_landed=lambda key, includes=(), own=False: land_git.find_landed(landed, key, includes),
    )
    num = lane.enqueue(KEY, "feat: x", includes=["D"])
    assert lane.wait_turn(num) == "granted"
    no_answer(monkeypatch, "status")
    ran: list[int] = []
    verdict, _out = lane.hold(num, lambda: ran.append(1) or Outcome(False, blocker="refused", message="no"))
    assert ran == [1] and verdict == "refused"  # was: "already_landed", the commit tool skipped, D/new.txt never landed


def test_no_answer_is_never_the_same_as_empty_output(landed, monkeypatch):
    assert land_git.git(landed, "status", "--porcelain") == ""  # a clean tree: an answer, and it is empty
    no_answer(monkeypatch, "status", code=128)
    assert land_git.git(landed, "status", "--porcelain") is None
    assert land_git.commits_outside_queue(landed, 0) is not None
    no_answer(monkeypatch, "log")
    assert land_git.commits_outside_queue(landed, 0) is None  # unknown, not "0 commits"
