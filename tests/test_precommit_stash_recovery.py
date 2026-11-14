"""Recovering an edit that a failed commit really did destroy.

The point of these tests is that they drive the loss instead of describing it.
An earlier attempt at this problem shipped eight green tests that called the
capture function directly with unstaged changes still on disk -- the one state
pre-commit guarantees is gone by the time a hook runs. They passed and proved
nothing.

So the first test runs a real `git commit`, through a real installed
pre-commit, with a hook that auto-fixes and then fails, and asserts the edit is
GONE from the working tree before asserting anything about recovery. If the loss
ever stops reproducing, that assertion fails and the test says the premise died,
rather than quietly passing on a scenario that no longer exists.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_MOD = _ROOT / "scripts" / "forge" / "precommit_stash.py"
_spec = importlib.util.spec_from_file_location("precommit_stash_under_test", _MOD)
_stash = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_stash)

pytest.importorskip("pre_commit", reason="needs the real pre-commit to drive a real commit")

LOST = "PRECIOUS_UNSTAGED_WORK"


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False, env=env)


def _repo_with_a_hook_that_autofixes_then_fails(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")

    (repo / "a.txt").write_text("original\n", encoding="utf-8", newline="\n")
    (repo / "b.txt").write_text("original\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    # A hook that rewrites a file, stages the rewrite, then refuses the commit.
    # That is the shape whose stash pre-commit cannot put back.
    (repo / "boom.py").write_text(
        "import pathlib, subprocess, sys\n"
        "p = pathlib.Path('b.txt')\n"
        "p.write_text('HOOK_AUTOFIX\\n', encoding='utf-8', newline='\\n')\n"
        "subprocess.run(['git', 'add', 'b.txt'], check=False)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / ".pre-commit-config.yaml").write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: boom\n"
        "        name: boom\n"
        "        entry: python boom.py\n"
        "        language: system\n"
        "        pass_filenames: false\n"
        "        always_run: true\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add hook")

    env = dict(os.environ)
    env["PRE_COMMIT_HOME"] = str(tmp_path / "pc-cache")   # never touch the real cache
    subprocess.run(["python", "-m", "pre_commit", "install"], cwd=repo, capture_output=True, check=False, env=env)
    return repo, env


def test_a_failed_commit_really_destroys_the_edit_and_the_stash_still_has_it(tmp_path: Path) -> None:
    repo, env = _repo_with_a_hook_that_autofixes_then_fails(tmp_path)

    (repo / "a.txt").write_text("staged change\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "a.txt")
    (repo / "b.txt").write_text(f"{LOST}\n", encoding="utf-8", newline="\n")   # unstaged: the work at risk

    commit = _git(repo, "commit", "-m", "should fail", env=env)
    assert commit.returncode != 0, "the hook was supposed to refuse this commit"

    # THE LOSS, asserted before any claim about recovery. If this stops holding,
    # the premise is gone and the test must be revisited, not relaxed.
    assert LOST not in (repo / "b.txt").read_text(encoding="utf-8"), (
        "pre-commit no longer destroys the unstaged edit -- re-derive this tool's reason to exist"
    )

    # ...and pre-commit's own stash is where it survived.
    found = _stash.patches(Path(env["PRE_COMMIT_HOME"]))
    assert found, "pre-commit wrote no stash"
    assert any(LOST in p.read_bytes().decode("utf-8", "replace") for _, p in found)


def test_restore_puts_the_destroyed_edit_back(tmp_path: Path) -> None:
    repo, env = _repo_with_a_hook_that_autofixes_then_fails(tmp_path)
    (repo / "a.txt").write_text("staged change\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "a.txt")
    (repo / "b.txt").write_text(f"{LOST}\n", encoding="utf-8", newline="\n")
    _git(repo, "commit", "-m", "should fail", env=env)
    assert LOST not in (repo / "b.txt").read_text(encoding="utf-8")

    os.environ["PRE_COMMIT_HOME"] = env["PRE_COMMIT_HOME"]
    try:
        rc = _stash.run(["--repo-root", str(repo), "--restore"])
    finally:
        os.environ.pop("PRE_COMMIT_HOME", None)

    assert rc == 0
    assert LOST in (repo / "b.txt").read_text(encoding="utf-8"), "the edit was not recovered"


def test_a_stash_already_in_the_tree_is_not_offered_as_recoverable(tmp_path: Path) -> None:
    """The common case: pre-commit put the work back itself, so there is nothing
    to do. Reporting those as recoverable would bury the real ones."""
    repo, env = _repo_with_a_hook_that_autofixes_then_fails(tmp_path)
    (repo / "b.txt").write_text(f"{LOST}\n", encoding="utf-8", newline="\n")
    patch = Path(env["PRE_COMMIT_HOME"]) / "patch1700000000-1"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_bytes(_git(repo, "diff", "HEAD").stdout.encode("utf-8"))

    assert _stash.state(repo, patch) == "already-in-tree"


def test_a_conflicting_stash_is_never_reported_as_nothing_to_recover(tmp_path: Path, capsys) -> None:
    """A stash that will not apply is not the same as no work to recover, and
    saying so would be the reassuring-on-failure bug this tool exists to avoid."""
    repo, env = _repo_with_a_hook_that_autofixes_then_fails(tmp_path)
    (repo / "b.txt").write_text("one\n", encoding="utf-8", newline="\n")
    patch = Path(env["PRE_COMMIT_HOME"]) / "patch1700000001-1"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_bytes(_git(repo, "diff", "HEAD").stdout.encode("utf-8"))
    (repo / "b.txt").write_text("something else entirely\n", encoding="utf-8", newline="\n")

    assert _stash.state(repo, patch) == "conflicts"

    os.environ["PRE_COMMIT_HOME"] = env["PRE_COMMIT_HOME"]
    try:
        _stash.run(["--repo-root", str(repo)])
    finally:
        os.environ.pop("PRE_COMMIT_HOME", None)
    out = capsys.readouterr().out
    assert "Nothing to recover" not in out
    assert patch.name in out, "the stash that holds the work was not even named"
    assert "--restore" in out, "a conflicting stash must come with a way to act on it"


def test_recovery_does_not_throw_away_what_it_overwrites(tmp_path: Path) -> None:
    """--restore rewrites a file the hook had already rewritten. The hook's
    version is cheap to regenerate and the hand edit is not, so the hand edit
    wins -- but a recovery tool that destroys anything is not one, so the
    displaced content has to survive somewhere."""
    repo, env = _repo_with_a_hook_that_autofixes_then_fails(tmp_path)
    (repo / "a.txt").write_text("staged change", encoding="utf-8", newline=chr(10))
    _git(repo, "add", "a.txt")
    (repo / "b.txt").write_text(LOST, encoding="utf-8", newline=chr(10))
    _git(repo, "commit", "-m", "should fail", env=env)

    displaced = (repo / "b.txt").read_text(encoding="utf-8")
    assert "HOOK_AUTOFIX" in displaced, "the hook did not leave its own version behind"

    os.environ["PRE_COMMIT_HOME"] = env["PRE_COMMIT_HOME"]
    try:
        assert _stash.run(["--repo-root", str(repo), "--restore"]) == 0
    finally:
        os.environ.pop("PRE_COMMIT_HOME", None)

    assert LOST in (repo / "b.txt").read_text(encoding="utf-8")
    sidecar = repo / "b.txt.pre-restore"
    assert sidecar.exists(), "the overwritten content was destroyed, not set aside"
    assert sidecar.read_text(encoding="utf-8") == displaced


def test_a_stash_whose_pre_image_was_collected_is_reported_not_swallowed(tmp_path: Path) -> None:
    """Extraction depends on the pre-image blob still being in the object
    database. Old stashes outlive it. The one thing this must never do is say
    it recovered a file it could not read."""
    repo, env = _repo_with_a_hook_that_autofixes_then_fails(tmp_path)
    (repo / "b.txt").write_text("gone forever", encoding="utf-8", newline=chr(10))
    patch = Path(env["PRE_COMMIT_HOME"]) / "patch1700000002-1"
    patch.parent.mkdir(parents=True, exist_ok=True)
    # a well-formed patch whose pre-image hash names a blob nothing ever wrote
    body = _git(repo, "diff", "HEAD").stdout.replace("index ", "index dead1ee", 1)
    patch.write_bytes(body.encode("utf-8"))
    (repo / "b.txt").write_text("something else entirely", encoding="utf-8", newline=chr(10))

    results = _stash.extract(repo, patch)
    assert results, "the patch parsed into no files at all"
    # specifically unrecoverable -- "skipped" would mean the patch failed to
    # parse and this test proved nothing about the missing blob at all.
    assert [outcome for _, outcome, _ in results] == ["unrecoverable"], results
    assert "not in the object database" in results[0][2], results
    assert (repo / "b.txt").read_text(encoding="utf-8") == "something else entirely"


def test_dry_run_reports_the_same_files_it_would_write_and_writes_none(tmp_path: Path) -> None:
    """The listing says a stash conflicts; only a dry run says what recovering it
    would actually do to each file. It has to be exact and it has to be inert."""
    repo, env = _repo_with_a_hook_that_autofixes_then_fails(tmp_path)
    (repo / "a.txt").write_text("staged change", encoding="utf-8", newline=chr(10))
    _git(repo, "add", "a.txt")
    (repo / "b.txt").write_text(LOST, encoding="utf-8", newline=chr(10))
    _git(repo, "commit", "-m", "should fail", env=env)
    before = {f.name: f.read_bytes() for f in repo.iterdir() if f.is_file()}

    os.environ["PRE_COMMIT_HOME"] = env["PRE_COMMIT_HOME"]
    try:
        assert _stash.run(["--repo-root", str(repo), "--restore", "--dry-run"]) == 0
        planned = [row[0] for row in _stash.patches(Path(env["PRE_COMMIT_HOME"]))]
        assert planned, "no stash to dry-run against"
        after = {f.name: f.read_bytes() for f in repo.iterdir() if f.is_file()}
        assert after == before, "a dry run wrote to the working tree"
        assert not (repo / "b.txt.pre-restore").exists(), "a dry run left a backup behind"

        # ...and the plan it printed is the plan it carries out.
        assert _stash.run(["--repo-root", str(repo), "--restore"]) == 0
    finally:
        os.environ.pop("PRE_COMMIT_HOME", None)
    assert LOST in (repo / "b.txt").read_text(encoding="utf-8")
