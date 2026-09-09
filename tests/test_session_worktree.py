"""Hermetic tests for the automatic per-session worktree lifecycle.

Every test operates on a throwaway git repository created in a temp dir, so no
real repo worktrees are ever touched. ``git`` is invoked for real (the module
shells out to it) but nothing leaves the temp tree: no network, no push, no gh.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.tools.session_worktree import (
    STATE_ENV_VAR,
    SessionWorktreeManager,
    WorktreeError,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit on a stable branch."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tester")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "init")
    return root


def _manager(repo: Path, tmp_path: Path, **kw) -> SessionWorktreeManager:
    kw.setdefault("state_path", tmp_path / "state.json")
    kw.setdefault("worktrees_root", tmp_path / "wt")
    return SessionWorktreeManager(repo, **kw)


# -- creation & idempotency -------------------------------------------------


def test_eligible_session_auto_creates_one_worktree(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    out = mgr.ensure("sess-A")

    assert out.status == "created"
    assert out.created is True
    assert out.worktree is not None
    wt_path = Path(out.worktree.path)
    assert wt_path.is_dir()
    # It is a real linked worktree (has a .git file pointing back to the repo).
    assert (wt_path / ".git").exists()
    assert (wt_path / "README.md").exists()


def test_same_session_id_is_idempotent(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    first = mgr.ensure("sess-A")
    second = mgr.ensure("sess-A")

    assert first.status == "created"
    assert second.status == "reused"
    assert second.worktree is not None
    assert first.worktree.path == second.worktree.path
    # Exactly one worktree tracked for the session -> no second worktree.
    assert list(mgr.list_worktrees()) == ["sess-A"]
    # And git itself only knows about the main tree + the single session tree.
    porcelain = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert porcelain.count("worktree ") == 2


def test_ineligible_session_creates_none(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path, eligibility=lambda sid: sid != "blocked")
    out = mgr.ensure("blocked")

    assert out.status == "ineligible"
    assert out.eligible is False
    assert out.worktree is None
    assert mgr.list_worktrees() == {}
    assert not (tmp_path / "wt").exists()


# -- safe cleanup -----------------------------------------------------------


def test_cleanup_removes_a_clean_worktree(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    created = mgr.ensure("sess-A")
    wt_path = Path(created.worktree.path)
    assert wt_path.is_dir()

    outcome = mgr.cleanup("sess-A")

    assert outcome.status == "removed"
    assert outcome.removed is True
    assert not wt_path.exists()
    assert mgr.list_worktrees() == {}


def test_cleanup_preserves_a_dirty_worktree_with_signal(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    created = mgr.ensure("sess-A")
    wt_path = Path(created.worktree.path)
    # Introduce uncommitted work.
    (wt_path / "scratch.txt").write_text("unsaved work\n", encoding="utf-8")

    outcome = mgr.cleanup("sess-A")

    assert outcome.status == "dirty"
    assert outcome.preserved_dirty is True
    assert wt_path.exists(), "dirty worktree must not be discarded"
    assert (wt_path / "scratch.txt").exists()
    # Still tracked so the session can resume its work.
    assert "sess-A" in mgr.list_worktrees()


def test_cleanup_force_removes_even_when_dirty(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    created = mgr.ensure("sess-A")
    wt_path = Path(created.worktree.path)
    (wt_path / "scratch.txt").write_text("unsaved work\n", encoding="utf-8")

    outcome = mgr.cleanup("sess-A", force=True)

    assert outcome.status == "removed"
    assert outcome.forced is True
    assert not wt_path.exists()
    assert mgr.list_worktrees() == {}


def test_cleanup_missing_session_reports_missing(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    outcome = mgr.cleanup("never-existed")
    assert outcome.status == "missing"


# -- stale sweep ------------------------------------------------------------


def test_cleanup_stale_removes_only_inactive_and_clean(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    active = mgr.ensure("active")
    inactive_clean = mgr.ensure("inactive-clean")
    inactive_dirty = mgr.ensure("inactive-dirty")

    # Make the dirty-inactive one dirty.
    (Path(inactive_dirty.worktree.path) / "x.txt").write_text("wip\n", encoding="utf-8")

    outcomes = {o.session_id: o for o in mgr.cleanup_stale({"active"})}

    # The active session was never a candidate.
    assert "active" not in outcomes
    assert Path(active.worktree.path).is_dir()
    # Inactive + clean -> removed.
    assert outcomes["inactive-clean"].status == "removed"
    assert not Path(inactive_clean.worktree.path).exists()
    # Inactive + dirty -> preserved with signal.
    assert outcomes["inactive-dirty"].status == "dirty"
    assert Path(inactive_dirty.worktree.path).exists()

    remaining = set(mgr.list_worktrees())
    assert remaining == {"active", "inactive-dirty"}


# -- state durability -------------------------------------------------------


def test_state_file_round_trips(repo: Path, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    mgr = _manager(repo, tmp_path, state_path=state_path)
    created = mgr.ensure("sess-A")
    assert state_path.exists()

    # A fresh manager (new process semantics) reloads the mapping durably.
    reloaded = _manager(repo, tmp_path, state_path=state_path)
    got = reloaded.get("sess-A")
    assert got is not None
    assert got.path == created.worktree.path
    assert got.branch == created.worktree.branch
    # Reusing the session on the reloaded manager makes no second worktree.
    assert reloaded.ensure("sess-A").status == "reused"


def test_state_path_env_override(repo: Path, tmp_path: Path, monkeypatch) -> None:
    env_state = tmp_path / "env" / "state.json"
    monkeypatch.setenv(STATE_ENV_VAR, str(env_state))
    mgr = SessionWorktreeManager(repo, worktrees_root=tmp_path / "wt")
    mgr.ensure("sess-A")
    assert env_state.exists()


def test_missing_worktree_dir_is_reconciled_on_cleanup(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(repo, tmp_path)
    created = mgr.ensure("sess-A")
    # Simulate the directory vanishing out from under us.
    import shutil

    shutil.rmtree(created.worktree.path)

    outcome = mgr.cleanup("sess-A")
    assert outcome.status == "removed"
    assert mgr.list_worktrees() == {}


def test_bad_repo_raises_worktree_error(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    mgr = SessionWorktreeManager(
        not_a_repo,
        state_path=tmp_path / "s.json",
        worktrees_root=tmp_path / "wt",
    )
    with pytest.raises(WorktreeError):
        mgr.ensure("sess-A")
