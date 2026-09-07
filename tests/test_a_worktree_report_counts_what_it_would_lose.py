"""A worktree report must count dirty files and unique commits before anyone
deletes anything -- 'removable' may only mean: nothing would be lost."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "scripts" / "forge" / "worktree_triage.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _make_repo_with_worktrees(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base")
    # clean worktree, no unique commits -> removable
    _git(repo, "worktree", "add", str(tmp_path / "wt_clean"), "-b", "wt-clean")
    # dirty worktree with a unique commit -> needs-review
    _git(repo, "worktree", "add", str(tmp_path / "wt_dirty"), "-b", "wt-dirty")
    wt_dirty = tmp_path / "wt_dirty"
    (wt_dirty / "b.txt").write_text("unique\n", encoding="utf-8")
    _git(wt_dirty, "add", "b.txt")
    _git(wt_dirty, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "unique")
    (wt_dirty / "c.txt").write_text("uncommitted\n", encoding="utf-8")
    return repo


def test_clean_merged_worktree_is_removable_and_dirty_one_is_not(tmp_path):
    repo = _make_repo_with_worktrees(tmp_path)
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.forge.worktree_triage import triage

    rows = {Path(r["path"]).name: r for r in triage(repo)}
    assert rows["wt_clean"]["dirty_files"] == 0
    assert rows["wt_clean"]["unique_commits"] == 0
    assert rows["wt_clean"]["disposition"] == "removable"
    assert rows["wt_dirty"]["dirty_files"] == 1
    assert rows["wt_dirty"]["unique_commits"] == 1
    assert rows["wt_dirty"]["disposition"] == "needs-review"


def test_cli_always_exits_zero_and_prints_every_worktree(tmp_path):
    repo = _make_repo_with_worktrees(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "wt_clean" in proc.stdout and "wt_dirty" in proc.stdout


def test_a_worktree_the_tool_cannot_read_is_never_removable(tmp_path, monkeypatch):
    """If git fails when assessing a worktree, disposition must be
    'needs-review', never 'removable' -- a triage tool that cannot read a
    worktree must never claim it is safe to delete."""
    repo = _make_repo_with_worktrees(tmp_path)
    sys.path.insert(0, str(REPO_ROOT))
    import scripts.forge.worktree_triage as worktree_triage

    real_git = worktree_triage._git

    def flaky_git(cwd, *args):
        if Path(cwd).name == "wt_clean" and args[:1] == ("status",):
            return None  # simulate a failing `git status` for this worktree
        return real_git(cwd, *args)

    monkeypatch.setattr(worktree_triage, "_git", flaky_git)

    rows = {Path(r["path"]).name: r for r in worktree_triage.triage(repo)}
    assert rows["wt_clean"]["assessment_failed"] is True
    assert rows["wt_clean"]["disposition"] == "needs-review"
    # a worktree git could read fine is unaffected
    assert rows["wt_dirty"]["assessment_failed"] is False
    assert rows["wt_dirty"]["disposition"] == "needs-review"


def test_a_failed_listing_prints_a_loud_line_and_produces_no_rows(tmp_path, capsys, monkeypatch):
    """If `git worktree list --porcelain` itself fails, triage() must not
    render an empty table as if there were simply no worktrees -- it must
    say the listing failed and produce zero rows, not a silent empty
    report."""
    repo = _make_repo_with_worktrees(tmp_path)
    sys.path.insert(0, str(REPO_ROOT))
    import scripts.forge.worktree_triage as worktree_triage

    real_git = worktree_triage._git

    def flaky_listing(cwd, *args):
        if args[:2] == ("worktree", "list"):
            return None
        return real_git(cwd, *args)

    monkeypatch.setattr(worktree_triage, "_git", flaky_listing)
    rows = worktree_triage.triage(repo)

    assert rows == []
    captured = capsys.readouterr()
    assert "worktree listing FAILED" in captured.out


def test_cli_still_exits_zero_when_the_listing_call_fails(tmp_path):
    """The tool never blocks -- even a listing failure must exit 0, per the
    module's own contract ('Always exits 0 ... this is an instrument')."""
    repo = _make_repo_with_worktrees(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--repo-root", str(repo / "does-not-exist")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions only")
def test_a_windows_junction_venv_is_detected_as_a_venv_junction(tmp_path):
    """Path.is_symlink() returns False for real Windows junctions (verified
    empirically: mklink /J then Path.is_symlink() -> False on this machine),
    so has_venv_junction must use os.path.isjunction() or it always reads
    'no' for the exact hazard it exists to flag."""
    repo = _make_repo_with_worktrees(tmp_path)
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.forge.worktree_triage import triage

    wt_clean = tmp_path / "wt_clean"
    junction = wt_clean / ".venv"
    target = tmp_path / "junction_target"
    target.mkdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )

    rows = {Path(r["path"]).name: r for r in triage(repo)}
    assert rows["wt_clean"]["has_venv_junction"] is True
