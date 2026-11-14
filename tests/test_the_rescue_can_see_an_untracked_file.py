"""The snapshot must survive the accident it exists for.

`capture()` takes `git diff HEAD --binary`, which carries staged AND unstaged work.
What it cannot carry is UNTRACKED files: a diff against a commit has no untracked
side to report.

Normally a small gap. Here it is the whole thing, because the failure this tool
exists for converts a tracked file into an untracked one -- the index records a
deletion, the content lands back on disk unregistered, and `git status` prints `D`
and `??` for the same path at once. So at the moment the snapshot is most needed,
the file has just left the only set the diff can read.

Found by claude-perf on 2026-09-09, who proved it rather than argued it: none of
the five snapshots in runtime/commit_attempts contained any of the work lost during
the attempts that took them.

The copies are written beside the patch rather than staged with `git add -N`.
Intent-to-add would also work, but costs an index write -- and a locked index is
CORRELATED with this accident, not independent of it. A rescue that needs the lock
is unavailable exactly when it is needed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.forge import worktree_safety as ws


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "kept.txt").write_text("committed\n", encoding="utf-8")
    _git(root, "add", "kept.txt")
    _git(root, "commit", "-qm", "seed")
    return root


def test_the_accident_itself(tmp_path: Path):
    """A tracked file becomes untracked with its work in it. Save that work.

    This is the load-bearing case and the exact shape of the real failure.
    """
    root, snaps = _repo(tmp_path), tmp_path / "snaps"
    work = root / "kept.txt"
    work.write_text("committed\nthe work nobody wants to lose\n", encoding="utf-8")
    # The accident: the index forgets the path, the content stays on disk.
    _git(root, "rm", "--cached", "-q", "kept.txt")
    assert (
        "?? kept.txt"
        in subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
    ), "precondition: the file must now read as untracked"

    patch = ws.capture(root, snaps)
    assert patch is not None, "the snapshot must still be taken"

    work.unlink()  # now lose it, the way a failed commit does
    assert ws.restore(root, patch) is True
    assert "the work nobody wants to lose" in work.read_text(encoding="utf-8")


def test_a_plain_untracked_file_is_saved(tmp_path: Path):
    root, snaps = _repo(tmp_path), tmp_path / "snaps"
    (root / "new.py").write_text("print('new work')\n", encoding="utf-8")
    patch = ws.capture(root, snaps)
    assert patch is not None
    (root / "new.py").unlink()
    assert ws.restore(root, patch) is True
    assert (root / "new.py").read_text(encoding="utf-8") == "print('new work')\n"


def test_tracked_work_still_survives(tmp_path: Path):
    """Protection must not weaken: the original behaviour is intact."""
    root, snaps = _repo(tmp_path), tmp_path / "snaps"
    (root / "kept.txt").write_text("committed\nedited\n", encoding="utf-8")
    patch = ws.capture(root, snaps)
    assert patch is not None
    _git(root, "checkout", "--", "kept.txt")
    assert ws.restore(root, patch) is True
    assert "edited" in (root / "kept.txt").read_text(encoding="utf-8")


def test_an_ignored_file_is_not_hoarded(tmp_path: Path):
    """Build output and venvs are not work. Saving them would bloat every attempt."""
    root, snaps = _repo(tmp_path), tmp_path / "snaps"
    (root / ".gitignore").write_text("junk/\n", encoding="utf-8")
    (root / "junk").mkdir()
    (root / "junk" / "big.bin").write_bytes(b"x" * 4096)
    patch = ws.capture(root, snaps)
    assert patch is not None
    assert not (ws._sidecar_dir(patch) / "junk" / "big.bin").exists()


def test_a_file_that_came_back_is_never_clobbered(tmp_path: Path):
    """Restore runs after an accident; someone may have rewritten it by hand."""
    root, snaps = _repo(tmp_path), tmp_path / "snaps"
    (root / "new.py").write_text("original\n", encoding="utf-8")
    patch = ws.capture(root, snaps)
    assert patch is not None
    (root / "new.py").write_text("rewritten by a human\n", encoding="utf-8")
    assert ws.restore(root, patch) is True
    assert (root / "new.py").read_text(encoding="utf-8") == "rewritten by a human\n"


def test_nothing_to_save_is_still_nothing(tmp_path: Path):
    """A clean tree must not litter runtime/ with empty snapshots."""
    assert ws.capture(_repo(tmp_path), tmp_path / "snaps") is None


def test_pruning_takes_the_copies_with_it(tmp_path: Path):
    """A sidecar left behind after its patch is pruned would grow without bound."""
    root, snaps = _repo(tmp_path), tmp_path / "snaps"
    first = None
    for i in range(4):
        (root / f"f{i}.py").write_text(f"# {i}\n", encoding="utf-8")
        got = ws.capture(root, snaps, keep=2)
        first = first or got
    assert first is not None
    assert not first.exists(), "the oldest patch should be gone"
    assert not ws._sidecar_dir(first).exists(), "its copies should be gone too"
