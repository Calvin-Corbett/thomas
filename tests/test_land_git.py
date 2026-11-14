"""'Already landed' against a REAL throwaway git history: the trailer alone proves nothing, the content must match (H1)."""

from __future__ import annotations

import subprocess

import pytest
from scripts.crew.brief import land_git

from tests._landing_fakes import sp


@pytest.fixture()
def repo(tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    for cmd in (
        ["init", "-q"],
        ["config", "user.email", "t@example.test"],
        ["config", "user.name", "t"],
        ["config", "commit.gpgsign", "false"],
        ["config", "core.autocrlf", "false"],
    ):
        sp.run(["git", *cmd], cwd=work, check=True)
    (work / "base.txt").write_text("base\n")
    sp.run(["git", "add", "-A"], cwd=work, check=True)
    sp.run(["git", "commit", "-q", "-m", "base"], cwd=work, check=True)
    return work


def land(work, files: dict[str, str | None], message: str, key: str) -> str:
    """Write the files, commit them with the idempotency trailer, return the sha."""
    for name, text in files.items():
        path = work / name
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    sp.run(["git", "add", "-A"], cwd=work, check=True)
    sp.run(["git", "commit", "-q", "-m", land_git.with_key(message, key)], cwd=work, check=True)
    return sp.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True, check=True).stdout.strip()


def noise(work, count: int) -> None:
    """``count`` empty commits on top of HEAD in one go (git fast-import): a 450-commit history costs a moment."""
    branch = sp.run(
        ["git", "symbolic-ref", "HEAD"], cwd=work, capture_output=True, text=True, check=True
    ).stdout.strip()
    lines = []
    for i in range(count):
        msg = f"other {i}"
        lines += [f"commit {branch}", f"committer t <t@example.test> {1700000000 + i} +0000", f"data {len(msg)}", msg]
        if i == 0:
            lines.append(
                "from "
                + sp.run(
                    ["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True, check=True
                ).stdout.strip()
            )
        lines.append("")
    sp.run(["git", "fast-import", "--quiet"], cwd=work, input=("\n".join(lines) + "\n").encode(), check=True)


KEY = land_git.intent_key("agent-x", "docs: update notes", [])


def test_the_same_change_is_already_landed_and_names_the_commit(repo):
    sha = land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    assert land_git.find_landed(repo, KEY, ["notes.txt"]) == sha


def test_a_different_change_with_the_same_words_is_not_already_landed(repo):
    land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    noise(repo, 30)
    (repo / "notes.txt").write_text("B, a different change\n")  # same message, same file, new content
    assert land_git.find_landed(repo, KEY, ["notes.txt"]) is None  # was: ALREADY_LANDED, and change B never landed


def test_a_different_change_in_another_file_with_the_same_words_is_not_already_landed(repo):
    land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    (repo / "other.txt").write_text("B\n")  # no --include: the new change lives in a file the old commit never touched
    assert (
        land_git.find_landed(repo, KEY, [], staged=lambda: ["other.txt"]) is None
    )  # the landing would also stage other.txt
    assert land_git.find_landed(repo, KEY, ["other.txt"]) is None


def test_a_still_modified_included_file_means_not_everything_landed(repo):
    land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    (repo / "second.txt").write_text("not yet landed\n")
    assert land_git.find_landed(repo, KEY, ["notes.txt", "second.txt"]) is None


def test_a_deleted_file_counts_when_the_working_tree_agrees(repo):
    sha = land(repo, {"base.txt": None}, "chore: drop base", land_git.intent_key("agent-x", "chore: drop base", []))
    assert land_git.find_landed(repo, land_git.intent_key("agent-x", "chore: drop base", []), ["base.txt"]) == sha


def test_content_that_dev_has_since_changed_again_still_reads_as_landed_when_nothing_is_pending(repo):
    sha = land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    land(repo, {"notes.txt": "A\nand a later change by someone else\n"}, "later", "lq-other")
    assert land_git.find_landed(repo, KEY, ["notes.txt"]) == sha


def test_an_empty_commit_with_the_trailer_proves_nothing(repo):
    sp.run(["git", "commit", "-q", "--allow-empty", "-m", land_git.with_key("empty", KEY)], cwd=repo, check=True)
    assert land_git.find_landed(repo, KEY, []) is None


def test_only_the_explicit_window_of_newest_commits_is_searched(repo):
    sha = land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    noise(repo, 30)
    assert land_git.find_landed(repo, KEY, ["notes.txt"], window=40) == sha
    assert (
        land_git.find_landed(repo, KEY, ["notes.txt"], window=10) is None
    )  # older than the window: not landed, try again


def test_a_key_older_than_the_window_is_not_reported_landed_and_the_work_is_tried_again(repo):
    land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    noise(repo, 450)
    assert (
        land_git.find_landed(repo, KEY, ["notes.txt"]) is None
    )  # default window is 400 commits; was: found, at any age


def test_the_match_is_on_the_whole_trailer_line_not_a_substring(repo):
    land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY + "9")
    assert land_git.find_landed(repo, KEY, ["notes.txt"]) is None


def test_the_trailer_is_added_to_an_existing_trailer_block_or_makes_its_own():
    assert land_git.with_key("subject\n\nbody", "lq-1") == "subject\n\nbody\n\nLanding-Ticket: lq-1\n"
    block = "subject\n\nbody\n\nCo-Authored-By: A <a@x>"
    assert land_git.with_key(block, "lq-1") == block + "\nLanding-Ticket: lq-1\n"
    assert land_git.with_key("one line", "lq-1") == "one line\n\nLanding-Ticket: lq-1\n"
    assert land_git.with_key("s\r\n\r\nb\r\n", "k").count("\r") == 0


def test_the_key_names_the_intent_not_the_attempt():
    k = land_git.intent_key("a", "msg", ["x.py", "y.py"])
    assert k == land_git.intent_key("a", "msg\n", ["y.py", "x.py"])
    assert k != land_git.intent_key("b", "msg", ["x.py", "y.py"])
    assert k != land_git.intent_key("a", "msg2", ["x.py", "y.py"])
    assert k != land_git.intent_key("a", "msg", ["x.py", "y.py"], salt="1")
