"""Thomas counts the commits on a checkout by who made them, from what each commit already says about itself.

Proves thomas.core.contributors. Every repository below is a temporary one under tmp_path, built with plain git, so
nothing reads the real history. A commit is Thomas's when it carries a self-change trailer or Thomas's own address on
GitHub, an agent's when it names one, and yours when it names nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.core import contributors as who

DAY = 86400
NOW = 1_800_000_000.0


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,  # noqa: S603, S607
    )
    return done.stdout


def _commit(repo: Path, message: str, *, email: str = "you@example.com", age_days: float = 0.0) -> None:
    name = f"f{abs(hash(message))}.txt"  # a file of its own, so two branches never conflict
    (repo / name).write_text(message, encoding="utf-8")
    _git(repo, "add", name)
    when = f"{int(NOW - age_days * DAY)} +0000"
    import os

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Someone",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Someone",
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }
    _git(repo, "commit", "-q", "-m", message, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    return path


@pytest.mark.parametrize(
    ("email", "block", "expected"),
    [
        ("you@example.com", "", "you"),
        ("you@example.com", "Thomas-Agent: claude", "claude"),
        ("you@example.com", "Thomas-Agent: Codex", "codex"),
        ("you@example.com", "Thomas-Agent: gemini", "gemini"),
        ("you@example.com", "Thomas-Agent: claude-perf", "claude"),
        ("you@example.com", "Thomas-Agent: Codex-e2e-20260920", "codex"),
        ("you@example.com", "Thomas-Agent: human", "you"),
        ("you@example.com", "Thomas-Agent: claudette", "claudette"),
        ("you@example.com", "Thomas-Agent: thomas", "thomas"),
        ("you@example.com", "Thomas-Committed-By: self-change-promoter", "thomas"),
        ("you@example.com", "Thomas-Submitted-By: thomas", "thomas"),
        ("you@example.com", "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", "claude"),
        ("you@example.com", "Co-Authored-By: Codex <codex@openai.com>", "codex"),
        ("you@example.com", "Co-Authored-By: Someone Else <else@example.com>", "you"),
        (who.THOMAS_NOREPLY, "", "thomas"),
        (who.THOMAS_NOREPLY.upper(), "", "thomas"),
    ],
)
def test_a_commit_belongs_to_the_first_thing_it_says(email: str, block: str, expected: str) -> None:
    assert who.who_made(email, block) == expected


def test_thomas_work_wins_over_a_claude_co_author_line() -> None:
    block = "Thomas-Committed-By: self-change-promoter\nCo-Authored-By: Claude <noreply@anthropic.com>"
    assert who.who_made("you@example.com", block) == "thomas"


def test_an_agent_trailer_wins_over_a_co_author_line() -> None:
    block = "Thomas-Agent: codex\nCo-Authored-By: Claude <noreply@anthropic.com>"
    assert who.who_made("you@example.com", block) == "codex"


def test_an_empty_agent_trailer_falls_through_to_the_next_thing() -> None:
    assert who.who_made("you@example.com", "Thomas-Agent:\nCo-Authored-By: Claude <noreply@anthropic.com>") == "claude"


def test_every_commit_is_counted_once_under_who_made_it(repo: Path) -> None:
    _commit(repo, "plain change")
    _commit(repo, "claude one\n\nThomas-Agent: claude")
    _commit(repo, "claude two\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    _commit(repo, "thomas fix\n\nThomas-Committed-By: self-change-promoter")
    _commit(repo, "by his account", email=who.THOMAS_NOREPLY)
    tally = who.tally(repo, now=NOW)
    assert tally.error == ""
    assert tally.commits == 5
    assert tally.total == {"thomas": 2, "claude": 2, "codex": 0, "you": 1}


def test_the_recent_count_holds_only_the_last_thirty_days(repo: Path) -> None:
    _commit(repo, "old\n\nThomas-Agent: claude", age_days=40)
    _commit(repo, "new\n\nThomas-Agent: claude", age_days=2)
    _commit(repo, "new yours", age_days=1)
    tally = who.tally(repo, now=NOW)
    assert tally.total["claude"] == 2
    assert tally.recent == {"thomas": 0, "claude": 1, "codex": 0, "you": 1}


def test_an_agent_with_no_slot_of_its_own_is_still_counted(repo: Path) -> None:
    _commit(repo, "a third agent\n\nThomas-Agent: gemini")
    tally = who.tally(repo, now=NOW)
    assert tally.total["gemini"] == 1
    assert tally.recent["gemini"] == 1
    assert tally.recent["claude"] == 0


def test_merge_commits_are_not_counted(repo: Path) -> None:
    _commit(repo, "base")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side work\n\nThomas-Agent: claude")
    _git(repo, "checkout", "-q", "-")
    _commit(repo, "main work")
    _git(repo, "-c", "user.name=m", "-c", "user.email=m@example.com", "merge", "-q", "--no-ff", "side", "-m", "merge")
    tally = who.tally(repo, now=NOW)
    assert tally.commits == 3


def test_counting_changes_nothing_in_the_repository(repo: Path) -> None:
    _commit(repo, "one")
    before = (_git(repo, "rev-parse", "HEAD"), _git(repo, "status", "--porcelain"), _git(repo, "reflog"))
    who.tally(repo, now=NOW)
    after = (_git(repo, "rev-parse", "HEAD"), _git(repo, "status", "--porcelain"), _git(repo, "reflog"))
    assert before == after


def test_a_new_commit_is_counted_after_an_earlier_count(repo: Path) -> None:
    _commit(repo, "one")
    assert who.tally(repo, now=NOW).commits == 1
    _commit(repo, "two")
    assert who.tally(repo, now=NOW).commits == 2


def test_a_folder_with_no_repository_answers_with_an_error_and_no_counts(tmp_path: Path) -> None:
    empty = tmp_path / "nothing"
    empty.mkdir()
    tally = who.tally(empty, now=NOW)
    assert tally.error
    assert tally.commits == 0
    assert tally.total == {}


def test_a_folder_that_is_not_there_answers_with_an_error(tmp_path: Path) -> None:
    assert who.tally(tmp_path / "gone", now=NOW).error


def test_the_noreply_address_is_the_one_github_gave_thomas_agent() -> None:
    assert who.THOMAS_NOREPLY == "352198248+thomas-agent@users.noreply.github.com"
