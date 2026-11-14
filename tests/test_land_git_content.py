"""'Already landed' without --include, and a landing that dev later reverted (second review H4 and M1)."""

from __future__ import annotations

import subprocess

from scripts.crew.brief import land_commit, land_git

from tests.test_land_git import KEY, land, repo  # noqa: F401 - `repo` is a fixture


def test_a_completed_landing_reads_as_landed_when_unrelated_files_are_dirty_and_there_is_no_include(repo):
    sha = land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    (repo / "someone_elses.txt").write_text(
        "a colleague's work in the shared checkout\n"
    )  # the shared checkout always has some
    (repo / "base.txt").write_text("base, edited by another agent\n")
    assert (
        land_git.find_landed(repo, KEY, []) is None
    )  # no staged set to prove it: unproven means not landed (the re-run decides)
    assert land_git.find_landed(repo, KEY, [], staged=lambda: []) == sha  # the dry run says nothing of mine is pending


def test_what_the_landing_actually_stages_decides_not_the_whole_checkout(repo):
    land(repo, {"notes.txt": "A\n"}, "docs: update notes", KEY)
    (repo / "next.txt").write_text("this change was never landed\n")
    assert (
        land_git.find_landed(repo, KEY, [], staged=lambda: ["next.txt"]) is None
    )  # the landing would stage it: not landed
    assert land_git.find_landed(repo, KEY, [], staged=lambda: None) is None  # unknown: unproven means not landed


def test_a_landing_that_dev_later_reverted_does_not_count_and_is_landed_again(repo):
    land(repo, {"notes.txt": "X\n"}, "docs: update notes", KEY)
    land(repo, {"notes.txt": None}, "revert: drop the notes", "lq-other")  # dev reverts it
    (repo / "notes.txt").write_text("X\n")  # the agent applies the same change again with the same message
    assert (
        land_git.find_landed(repo, KEY, ["notes.txt"]) is None
    )  # was: the OLD sha, "already landed", the work silently dropped
    assert land_git.find_landed(repo, KEY, []) is None


def test_a_landing_that_is_still_in_effect_counts_even_after_unrelated_history(repo):
    sha = land(repo, {"notes.txt": "X\n"}, "docs: update notes", KEY)
    land(repo, {"elsewhere.txt": "y\n"}, "feat: unrelated", "lq-other")
    assert land_git.find_landed(repo, KEY, ["notes.txt"]) == sha


def test_a_non_ascii_path_is_compared_by_its_real_name(repo):
    sha = land(repo, {"notes/café.txt": "A\n"}, "docs: cafe", KEY)
    assert land_git.find_landed(repo, KEY, ["notes"]) == sha  # was: quoted by git, so its blobs read as missing


def test_the_commit_tools_staged_paths_are_read_from_its_json():
    text = 'warning: noise\n{"ok": false, "blocker_class": "no_claimed_changes", "selected_paths": ["a.py", "b.py"]}\ntrailing\n'
    assert land_commit.selected_paths(text) == ["a.py", "b.py"]
    assert land_commit.selected_paths('{"ok": true}') is None
    assert land_commit.selected_paths("not json") is None
    assert subprocess is not None
