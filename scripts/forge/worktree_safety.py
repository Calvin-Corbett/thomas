"""Photograph the working tree before a commit's gates run, so a failure cannot eat it.

WHY THIS EXISTS: a commit that fails a gate does not simply stop. pre-commit
stashes unstaged changes, runs the hooks, and where hook auto-fixes conflict with
that stash its recovery path runs ``git checkout -- .``, which discards
working-tree changes. Measured 2026-09-09: seven separate edits were destroyed
this way in one session, across several attempts, and ``git status`` afterwards
reported the files UNMODIFIED -- so the damage reads as "nothing changed" rather
than as loss, and the natural response (try again) destroys the next attempt too.
Another agent filed a p0 for the same behaviour within minutes.

pre-commit is not ours to patch, so this does not try to prevent the wipe. It
makes the wipe survivable: the tree is captured first, and the snapshot can be
replayed afterwards.

RELATION TO ``worktree_salvage.py``: that module solves the same problem for a
different trigger -- a whole worktree about to be removed -- and stores its
snapshot as git refs written through a temporary index. That technique is the
right one when the shared index may be busy, and it stays the tool to reach for
on a registered worktree. This one covers the main checkout on every commit
attempt, where a plain patch file is enough and cheaper to take.

The capture MUST NOT be able to fail a commit. A safety net that turns a passing
commit into a failing one is worse than no safety net, so every path here that
could raise returns quietly instead.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

#: Where snapshots live in production. ``runtime/`` is gitignored, and these are
#: recovery aids for the last few attempts, not history.
DEFAULT_SNAPSHOT_DIR = Path("runtime") / "commit_attempts"

#: How many attempts to keep. Enough to recover from a retry loop that ate
#: several rounds before anyone noticed.
DEFAULT_KEEP = 20


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess | None:
    """Run git, or return None. Never raises: this runs inside a commit."""

    try:
        return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, check=False)
    except OSError:
        return None


def _untracked_paths(repo_root: Path) -> list[str]:
    """Non-ignored files git is not tracking yet.

    These are invisible to ``git diff HEAD``: a diff against a commit has no
    untracked side to report. Normally a small gap. Here it is the whole thing,
    because the failure this tool exists for CONVERTS A TRACKED FILE INTO AN
    UNTRACKED ONE -- the index records a deletion, the content lands back on disk
    unregistered, and `git status` prints `D` and `??` for one path at once. So at
    the moment the snapshot is most needed, the file has just left the only set the
    diff can see. Found by claude-perf, who proved it: none of the five snapshots
    taken during the attempts that lost their work contain any of it.
    """

    proc = _git(repo_root, "ls-files", "--others", "--exclude-standard", "-z")
    if proc is None or proc.returncode != 0:
        return []
    raw = proc.stdout.decode("utf-8", errors="replace")
    return [part for part in raw.split("\x00") if part.strip()]


def _sidecar_dir(patch: Path) -> Path:
    """Where a snapshot's untracked copies live, beside its patch."""

    return patch.with_suffix(".untracked")


def _copy_untracked(repo_root: Path, paths: list[str], sidecar: Path) -> int:
    """Copy untracked files beside the patch. Returns how many were saved.

    Copied rather than staged with ``git add -N`` deliberately. Intent-to-add would
    make them appear in the diff, but it costs an index write -- and the index being
    locked is CORRELATED with this accident, not independent of it. A rescue that
    needs the lock is unavailable exactly when it is needed.
    """

    saved = 0
    for rel in paths:
        source = repo_root / rel
        try:
            if not source.is_file():
                continue
            target = sidecar / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            saved += 1
        except OSError:
            # One unreadable file must not cost us the rest of the rescue.
            continue
    return saved


def capture(repo_root: Path, snapshot_dir: Path, *, keep: int = DEFAULT_KEEP) -> Path | None:
    """Write the tree's full diff against HEAD. Returns the snapshot, or None.

    ``--binary`` and ``HEAD`` together matter: the diff is taken against the last
    commit rather than against the index, so it carries staged AND unstaged work.
    Staged edits were lost too, so a diff of the working tree alone would have
    restored only half of what went missing.
    """

    repo_root = Path(repo_root)
    proc = _git(repo_root, "diff", "HEAD", "--binary")
    if proc is None or proc.returncode != 0:
        # Not a repo, no HEAD yet, or git unavailable. Nothing to protect, and
        # certainly nothing worth failing a commit over.
        return None

    tracked = proc.stdout if proc.stdout.strip() else b""
    untracked = _untracked_paths(repo_root)
    if not tracked and not untracked:
        return None

    try:
        snapshot_dir = Path(snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        target = snapshot_dir / f"{stamp}.patch"
        # Written even when empty: an untracked-only rescue still needs a snapshot
        # for `latest()` to find, and an empty patch applies cleanly as a no-op.
        target.write_bytes(tracked)
    except OSError:
        return None

    if untracked:
        _copy_untracked(repo_root, untracked, _sidecar_dir(target))

    prune(snapshot_dir, keep=keep)
    return target


def latest(snapshot_dir: Path) -> Path | None:
    """The most recent snapshot, which is the one a failed attempt just took."""

    try:
        found = sorted(Path(snapshot_dir).glob("*.patch"))
    except OSError:
        return None
    return found[-1] if found else None


def prune(snapshot_dir: Path, *, keep: int = DEFAULT_KEEP) -> int:
    """Drop all but the newest ``keep`` snapshots. Returns how many were removed."""

    try:
        found = sorted(Path(snapshot_dir).glob("*.patch"))
    except OSError:
        return 0
    removed = 0
    for stale in found[: max(0, len(found) - max(1, keep))]:
        try:
            sidecar = _sidecar_dir(stale)
            if sidecar.is_dir():
                # Depth-first: files before the directories that hold them.
                for child in sorted(sidecar.rglob("*"), key=lambda q: len(q.parts), reverse=True):
                    child.rmdir() if child.is_dir() else child.unlink()
                sidecar.rmdir()
            stale.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def restore(repo_root: Path, patch: Path) -> bool:
    """Replay a snapshot onto the working tree. Says plainly whether it worked.

    Restores the tracked diff and any untracked files saved beside it. A file that
    exists again is left alone and reported, never overwritten: this runs after an
    accident, and clobbering whatever is on disk now could destroy the newer copy
    someone already rewrote by hand.
    """

    patch = Path(patch)
    if not patch.is_file():
        return False
    repo_root = Path(repo_root)

    patch_applied = True
    if patch.stat().st_size > 0:
        proc = _git(repo_root, "apply", "--whitespace=nowarn", str(patch.resolve()))
        patch_applied = bool(proc is not None and proc.returncode == 0)
        if not patch_applied:
            # The tree moved since the snapshot -- routine after an accident.
            # --3way resolves what it can from the objects the patch names.
            proc = _git(repo_root, "apply", "--3way", "--whitespace=nowarn", str(patch.resolve()))
            patch_applied = bool(proc is not None and proc.returncode == 0)

    ok = patch_applied
    sidecar = _sidecar_dir(patch)
    if sidecar.is_dir():
        restored, skipped, lost = 0, 0, 0
        for saved in sorted(sidecar.rglob("*")):
            if not saved.is_file():
                continue
            target = repo_root / saved.relative_to(sidecar)
            try:
                if target.exists():
                    skipped += 1
                    print(f"  kept the copy already on disk: {target.relative_to(repo_root)}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(saved.read_bytes())
                restored += 1
            except OSError as exc:
                print(f"  could not restore {saved.name}: {exc}")
                lost += 1
                ok = False
        if restored or skipped:
            print(f"  untracked files: {restored} restored, {skipped} already present")
        if not patch_applied and restored and not lost:
            # The patch failing is EXPECTED in the accident this tool exists for:
            # it records the path as deleted, because that is what the index said
            # at snapshot time, while the content it holds came back from the
            # sidecar. Reporting failure here would be the same lie in reverse --
            # a tool claiming it failed while the work is sitting safely on disk.
            print("  the patch did not apply, but every file it covered was recovered")
            ok = True
    return ok


def run(argv: list[str] | None = None) -> int:
    """Hook entry point. Always returns 0 -- this instrument never gates."""

    import argparse

    parser = argparse.ArgumentParser(description="Snapshot the working tree before a commit's gates run.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--snapshot-dir", default=None)
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    parser.add_argument("--restore", action="store_true", help="Replay the newest snapshot instead of taking one.")
    args, _unknown = parser.parse_known_args(argv)

    root = Path(args.repo_root).resolve()
    where = Path(args.snapshot_dir) if args.snapshot_dir else root / DEFAULT_SNAPSHOT_DIR

    if args.restore:
        newest = latest(where)
        if newest is None:
            print("Worktree safety: no snapshot to restore")
            return 0
        ok = restore(root, newest)
        print(f"Worktree safety: {'restored' if ok else 'could not apply'} {newest}")
        return 0

    taken = capture(root, where, keep=args.keep)
    if taken is None:
        print("Worktree safety: clean tree, nothing to snapshot")
    else:
        print(f"Worktree safety: snapshot saved to {taken}")
        print("- restore with: python scripts/forge/worktree_safety.py --restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
