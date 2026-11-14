"""A failed commit must not be able to delete uncommitted work.

Measured 2026-09-09, repeatedly: a commit that fails a gate leaves pre-commit
restoring its stash, and where hook auto-fixes conflict it runs
``git checkout -- .``, which discards working-tree changes. Seven separate edits
were wiped this way in one session, and ``git status`` afterwards showed the
files UNMODIFIED -- so the loss reads as "nothing changed" rather than as damage,
and retrying destroys the next attempt too. Another agent filed a p0 for the same
behaviour within minutes.

pre-commit is not ours to patch, so the tree is photographed before the hooks
run. A snapshot is worthless if taking it can itself fail a commit, so capture
never raises and never blocks.

Every git command below runs against a throwaway repo under ``tmp_path``; none of
them touch this checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.forge.worktree_safety import capture, latest, prune, restore


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)

    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (root / "kept.py").write_text("original\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    return root


def _wipe_the_way_precommit_does(root: Path) -> None:
    subprocess.run(["git", "checkout", "--", "."], cwd=root, capture_output=True, check=True)


def test_a_wiped_edit_can_be_brought_back(tmp_path: Path):
    root = _repo(tmp_path)
    out = tmp_path / "snapshots"
    (root / "kept.py").write_text("the work I would have lost\n", encoding="utf-8")

    patch = capture(root, out)
    assert patch is not None and patch.exists()

    _wipe_the_way_precommit_does(root)
    assert (root / "kept.py").read_text(encoding="utf-8") == "original\n", "the wipe happened"

    assert restore(root, patch) is True
    assert (root / "kept.py").read_text(encoding="utf-8") == "the work I would have lost\n"


def test_a_staged_edit_is_captured_too(tmp_path: Path):
    """Staged work was lost as well, so a diff against the index is not enough."""
    root = _repo(tmp_path)
    out = tmp_path / "snapshots"
    (root / "kept.py").write_text("staged work\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)

    patch = capture(root, out)
    assert patch is not None
    subprocess.run(["git", "reset", "-q", "--hard", "HEAD"], cwd=root, capture_output=True, check=True)
    assert restore(root, patch) is True
    assert (root / "kept.py").read_text(encoding="utf-8") == "staged work\n"


def test_an_untracked_file_is_not_silently_promised(tmp_path: Path):
    """A snapshot that is offered for an untracked file must really bring it back.

    `git diff HEAD` cannot see untracked files, and this test used to hold that an
    untracked-only tree therefore yields no snapshot. fb75d087 (2026-09-09) made
    capture() copy untracked files into a sidecar beside the patch, because the
    accident this tool exists for turns a tracked file into an untracked one. The
    promise is now kept instead of refused: if a snapshot exists for an
    untracked-only tree, restoring it returns the file.
    """
    root = _repo(tmp_path)
    out = tmp_path / "snapshots"
    (root / "brand_new.py").write_text("untracked\n", encoding="utf-8")
    patch = capture(root, out)
    assert patch is not None, "an untracked-only tree is rescued through the sidecar"
    assert patch.stat().st_size == 0, "the patch itself promises nothing: git diff cannot see the file"
    (root / "brand_new.py").unlink()
    assert restore(root, patch) is True
    assert (root / "brand_new.py").read_text(encoding="utf-8") == "untracked\n"


def test_a_clean_tree_writes_no_snapshot(tmp_path: Path):
    assert capture(_repo(tmp_path), tmp_path / "snapshots") is None


def test_capture_never_raises_on_a_broken_repo(tmp_path: Path):
    """A safety net that can fail a commit is worse than no safety net."""
    not_a_repo = tmp_path / "nope"
    not_a_repo.mkdir()
    assert capture(not_a_repo, tmp_path / "snapshots") is None


def test_the_newest_snapshot_is_the_one_offered(tmp_path: Path):
    root = _repo(tmp_path)
    out = tmp_path / "snapshots"
    (root / "kept.py").write_text("first\n", encoding="utf-8")
    first = capture(root, out)
    (root / "kept.py").write_text("second\n", encoding="utf-8")
    second = capture(root, out)
    assert first != second
    assert latest(out) == second


def test_old_snapshots_are_pruned_but_never_the_newest(tmp_path: Path):
    root = _repo(tmp_path)
    out = tmp_path / "snapshots"
    made = []
    for n in range(6):
        (root / "kept.py").write_text(f"edit {n}\n", encoding="utf-8")
        made.append(capture(root, out, keep=3))
    prune(out, keep=3)
    remaining = sorted(out.glob("*.patch"))
    assert len(remaining) == 3
    assert made[-1] in remaining, "the newest snapshot must survive pruning"


def test_restoring_a_missing_snapshot_reports_failure_rather_than_pretending(tmp_path: Path):
    assert restore(_repo(tmp_path), tmp_path / "absent.patch") is False
