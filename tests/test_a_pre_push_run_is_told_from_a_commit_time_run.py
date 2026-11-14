"""A gate tells a real pre-push run from a commit-time run, and a git error is never read as nothing staged.

Proves scripts.forge.gates._commit_base: pre_push_range names a range only for a pre-push run with both refs, neither
all-zero, over a range git can read that holds a commit; staged_names answers None when git cannot say.
"""

from __future__ import annotations

import subprocess

import pytest
from scripts.forge.gates import _commit_base

ENV = (
    "PRE_COMMIT_FROM_REF",
    "PRE_COMMIT_TO_REF",
    "PRE_COMMIT_REMOTE_NAME",
    "PRE_COMMIT_REMOTE_URL",
    "PRE_COMMIT_HOOK_STAGE",
)


def _git(repo, *args):
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    for n in (1, 2):
        (tmp_path / "f.txt").write_text(f"{n}\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-qm", f"c{n}")
    return tmp_path


def _refs(monkeypatch, base, head):
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head)


def test_a_range_over_a_real_pre_push_run_is_named(repo, monkeypatch):
    _refs(monkeypatch, "HEAD~1", "HEAD")
    monkeypatch.setenv("PRE_COMMIT_HOOK_STAGE", "pre-push")
    assert _commit_base.pre_push_range(repo) == ("HEAD~1", "HEAD")


def test_pre_commits_remote_pair_says_pre_push_and_the_name_alone_does_not(repo, monkeypatch):
    _refs(monkeypatch, "HEAD~1", "HEAD")
    monkeypatch.setenv("PRE_COMMIT_REMOTE_NAME", "origin")
    assert _commit_base.pre_push_range(repo) is None
    monkeypatch.setenv("PRE_COMMIT_REMOTE_URL", "u")
    assert _commit_base.pre_push_range(repo) == ("HEAD~1", "HEAD")


def test_refs_without_a_pre_push_signal_are_not_a_push_unless_the_hook_forces_it(repo, monkeypatch):
    _refs(monkeypatch, "HEAD~1", "HEAD")
    assert _commit_base.pre_push_range(repo) is None
    assert _commit_base.pre_push_range(repo, forced=True) == ("HEAD~1", "HEAD")


def test_the_to_ref_alone_is_not_a_push(repo, monkeypatch):
    monkeypatch.setenv("PRE_COMMIT_HOOK_STAGE", "pre-push")
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "HEAD")
    assert _commit_base.pre_push_range(repo) is None


@pytest.mark.parametrize("base, head", [("0" * 40, "HEAD"), ("HEAD~1", "0" * 40), ("HEAD", "HEAD"), ("nope", "HEAD")])
def test_a_range_that_is_new_empty_or_unreadable_is_not_a_push(repo, monkeypatch, base, head):
    _refs(monkeypatch, base, head)
    monkeypatch.setenv("PRE_COMMIT_HOOK_STAGE", "pre-push")
    assert _commit_base.pre_push_range(repo) is None


def test_staged_names_lists_what_is_staged(repo):
    (repo / "g.txt").write_text("x\n")
    _git(repo, "add", "g.txt")
    assert _commit_base.staged_names(repo) == ["g.txt"]


def test_staged_names_is_none_when_git_cannot_say(tmp_path):
    assert _commit_base.staged_names(tmp_path / "not-a-repo-and-not-there") is None
