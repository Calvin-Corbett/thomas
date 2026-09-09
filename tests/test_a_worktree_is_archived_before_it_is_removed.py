"""A worktree must be provably archived -- unique commits AND dirty state
captured as git refs -- before anything removes it. Removal without an
intact archive is a loss no one asked for."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "scripts" / "forge" / "worktree_salvage.py"

sys.path.insert(0, str(REPO_ROOT))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _git_out(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _ref_returncode(repo: Path, ref: str) -> int:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", ref],
        capture_output=True,
        text=True,
    )
    return proc.returncode


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    # Pin autocrlf explicitly so these tests are deterministic regardless
    # of the host machine's global git config -- otherwise a host with
    # core.autocrlf=true can make a file that was never touched look
    # "modified" by nothing more than a CRLF/LF normalization difference.
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base")
    return repo


def _make_dirty_worktree_with_unique_commit(repo: Path, tmp_path: Path, wt_name: str = "wt-dirty") -> Path:
    """A linked worktree (git worktree add) with: a unique commit, a
    modified tracked file, an untracked non-ignored file, and an
    untracked ignored file that must NOT be archived."""
    wt = tmp_path / wt_name
    _git(repo, "worktree", "add", str(wt), "-b", f"{wt_name}-branch")
    (wt / "b.txt").write_text("unique\n", encoding="utf-8")
    _git(wt, "add", "b.txt")
    _git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "unique commit")
    (wt / "a.txt").write_text("hello\nmodified\n", encoding="utf-8")
    (wt / "untracked.txt").write_text("keep me\n", encoding="utf-8")
    (wt / ".gitignore").write_text("*.ignoreme\n", encoding="utf-8")
    (wt / "junk.ignoreme").write_text("must not be archived\n", encoding="utf-8")
    return wt


def _run_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
    )


def test_dirty_worktree_with_unique_commits_gets_both_refs_with_exact_dirty_tree(tmp_path):
    """Contract 1: salvage of a dirty worktree with unique commits creates
    both refs on --apply; the dirty snapshot tree contains exactly the
    modified/untracked-non-ignored files (not the ignored one); a
    preceding dry run does not touch the worktree's own index/HEAD."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)
    head_before = _git_out(wt, "rev-parse", "HEAD")
    status_before = _git_out(wt, "status", "--porcelain")

    dry = _run_tool("salvage", str(wt), "--repo-root", str(repo))
    assert dry.returncode == 0, dry.stderr
    assert "SALVAGE OK wt-dirty head=" in dry.stdout
    assert f"head={head_before}" in dry.stdout
    assert "dirty=none" not in dry.stdout
    assert "removed=no" in dry.stdout  # dry-run: no --apply

    # worktree's own state is untouched by the dry run
    assert _git_out(wt, "rev-parse", "HEAD") == head_before
    assert _git_out(wt, "status", "--porcelain") == status_before

    applied = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert applied.returncode == 0, applied.stderr
    assert "SALVAGE OK wt-dirty head=" in applied.stdout
    assert "wt-dirty-2" not in applied.stdout  # idempotent: reused the dry run's name

    # both refs exist and resolve
    head_ref = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-dirty")
    dirty_ref = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-dirty-dirty")
    assert head_ref == head_before

    changed = set(_git_out(repo, "diff", "--name-only", head_ref, dirty_ref).splitlines())
    # a.txt (modified), untracked.txt (new, non-ignored), .gitignore itself
    # (new, untracked, not excluded by its own pattern) -- but NOT the
    # ignored junk file. The reserved bookkeeping entry (the independent
    # expected-files record living inside the tree) is real tree content
    # too and shows up in a raw tree diff same as any other file; it is
    # not part of the worktree's own dirty content, so it is asserted for
    # and then excluded before checking the "exactly these files" claim.
    assert "junk.ignoreme" not in changed
    assert ".praxis-salvage-expected-files" in changed
    changed.discard(".praxis-salvage-expected-files")
    assert changed == {"a.txt", "untracked.txt", ".gitignore"}

    # parent of the dirty snapshot commit is the worktree HEAD
    parent = _git_out(repo, "rev-parse", f"{dirty_ref}^")
    assert parent == head_before

    # author/committer identity
    author = _git_out(repo, "show", "-s", "--format=%an <%ae>", dirty_ref)
    assert "praxis-salvage" in author


def test_removal_only_happens_with_apply_after_verify_passes(tmp_path):
    """Contract 2: without --apply, nothing is removed (and no ref is
    written). With --apply, the worktree is removed only after
    in-process verify passes, using `git worktree remove --force`."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)

    dry = _run_tool("salvage", str(wt), "--repo-root", str(repo))
    assert dry.returncode == 0, dry.stderr
    assert "removed=no" in dry.stdout
    assert wt.exists()

    applied = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert applied.returncode == 0, applied.stderr
    assert "SALVAGE OK wt-dirty head=" in applied.stdout
    assert "wt-dirty-2" not in applied.stdout
    assert "removed=yes" in applied.stdout
    assert not wt.exists()

    # the archive still verifies after removal
    verify = _run_tool("verify", "wt-dirty", "--repo-root", str(repo))
    assert verify.returncode == 0, verify.stderr
    assert "VERIFY OK wt-dirty head=" in verify.stdout


def test_clean_worktree_still_gets_head_ref_archived_with_dirty_none(tmp_path):
    """Contract 3: a clean worktree (nothing dirty, no unique commits)
    still gets its HEAD ref archived on --apply; dirty ref stays none."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-clean"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-clean-branch")
    head = _git_out(wt, "rev-parse", "HEAD")

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert "SALVAGE OK wt-clean head=" in proc.stdout
    assert f"head={head}" in proc.stdout
    assert "dirty=none" in proc.stdout
    assert "changed=0" in proc.stdout

    assert _git_out(repo, "rev-parse", "refs/archive/worktree/wt-clean") == head
    assert _ref_returncode(repo, "refs/archive/worktree/wt-clean-dirty") != 0  # no dirty ref was created


def test_dry_run_creates_no_refs(tmp_path):
    """Fix 2a: dry-run must be ref-free -- it reports the would-be name
    and counts without writing any ref (loose objects are fine)."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert "SALVAGE OK wt-dirty head=" in proc.stdout
    assert "removed=no" in proc.stdout

    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty") != 0
    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty-dirty") != 0


def test_dry_run_then_apply_reuses_the_same_name_no_suffix(tmp_path):
    """Fix 2b: naming is idempotent per worktree path. A dry run followed
    by --apply against the SAME worktree at the SAME HEAD must reuse the
    dry run's name, never mint a -2. This is exactly Task 2's workflow
    (dry-run then --apply per worktree), so a bug here doubles every
    archive."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)

    dry = _run_tool("salvage", str(wt), "--repo-root", str(repo))
    assert dry.returncode == 0, dry.stderr
    assert "SALVAGE OK wt-dirty head=" in dry.stdout

    applied = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert applied.returncode == 0, applied.stderr
    assert "SALVAGE OK wt-dirty head=" in applied.stdout
    assert "wt-dirty-2" not in applied.stdout

    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty") == 0
    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty-2") != 0
    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty-dirty") == 0
    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty-2-dirty") != 0


def test_reapplying_salvage_on_changed_dirty_content_updates_the_dirty_ref(tmp_path):
    """Fix 2b: re-running --apply against a worktree already archived at
    the same HEAD reuses the name and, if the dirty content changed,
    updates the -dirty ref and reports updated=yes."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-reapply"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-reapply-branch")
    (wt / "a.txt").write_text("first change\n", encoding="utf-8")

    first = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert first.returncode == 0, first.stderr
    assert "SALVAGE OK wt-reapply head=" in first.stdout
    first_dirty = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-reapply-dirty")

    # the worktree was removed by --apply; recreate it at the SAME head to
    # simulate a retried salvage attempt (e.g. after a locked-worktree SKIP)
    head = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-reapply")
    _git(repo, "worktree", "add", "--detach", str(wt), head)
    (wt / "a.txt").write_text("second, different change\n", encoding="utf-8")

    second = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert second.returncode == 0, second.stderr
    assert "SALVAGE OK wt-reapply head=" in second.stdout
    assert "wt-reapply-2" not in second.stdout  # reused, not suffixed
    assert "updated=yes" in second.stdout

    second_dirty = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-reapply-dirty")
    assert second_dirty != first_dirty


def test_dirty_to_clean_reuse_deletes_the_stale_dirty_ref(tmp_path):
    """Fix round 2, finding 1: a worktree archived dirty, then salvaged
    again at the SAME HEAD but now clean, must not leave a stale -dirty
    ref behind. The printed dirty=none must match what the refs actually
    hold, and restore() must return the clean HEAD state, not the old
    dirty snapshot."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-cleanup"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-cleanup-branch")
    (wt / "a.txt").write_text("dirty change\n", encoding="utf-8")

    first = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert first.returncode == 0, first.stderr
    assert "SALVAGE OK wt-cleanup head=" in first.stdout
    assert "dirty=none" not in first.stdout
    assert _ref_returncode(repo, "refs/archive/worktree/wt-cleanup-dirty") == 0

    # recreate the worktree at the SAME archived head, now clean (nothing
    # touched after checkout -- simulates a retried salvage on a worktree
    # whose dirty edits were reverted or never reapplied)
    head = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-cleanup")
    _git(repo, "worktree", "add", "--detach", str(wt), head)

    second = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert second.returncode == 0, second.stderr
    assert "SALVAGE OK wt-cleanup head=" in second.stdout
    assert "wt-cleanup-2" not in second.stdout  # reused, not suffixed
    assert "dirty=none" in second.stdout
    assert "updated=yes" in second.stdout  # a ref changed: the dirty ref was deleted

    # the stale -dirty ref must actually be GONE, not just unmentioned
    assert _ref_returncode(repo, "refs/archive/worktree/wt-cleanup-dirty") != 0

    # restore must return the clean HEAD state, not the old dirty content
    restored_path = tmp_path / "restored_cleanup"
    restore_proc = _run_tool("restore", "wt-cleanup", str(restored_path), "--repo-root", str(repo), "--apply")
    assert restore_proc.returncode == 0, restore_proc.stderr
    assert (restored_path / "a.txt").read_text(encoding="utf-8") == "hello\n"


def test_reapplying_salvage_with_unchanged_dirty_content_reports_updated_no(tmp_path):
    """Cheap addition from the deferred list: reusing a name whose dirty
    content is identical to what was already archived must report
    updated=no and leave the -dirty ref pointing at the same content
    (compared by tree, not commit sha, since two commit-tree calls with
    identical content but different timestamps get different shas)."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-unchanged"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-unchanged-branch")
    (wt / "a.txt").write_text("same change every time\n", encoding="utf-8")

    first = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert first.returncode == 0, first.stderr
    assert "SALVAGE OK wt-unchanged head=" in first.stdout
    first_dirty_tree = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-unchanged-dirty^{tree}")

    head = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-unchanged")
    _git(repo, "worktree", "add", "--detach", str(wt), head)
    (wt / "a.txt").write_text("same change every time\n", encoding="utf-8")

    second = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert second.returncode == 0, second.stderr
    assert "SALVAGE OK wt-unchanged head=" in second.stdout
    assert "wt-unchanged-2" not in second.stdout
    assert "updated=no" in second.stdout

    second_dirty_tree = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-unchanged-dirty^{tree}")
    assert second_dirty_tree == first_dirty_tree


def test_crlf_bearing_file_salvages_correctly_under_ambient_autocrlf_true(tmp_path):
    """Coverage gap (round 2 fix, corrected in round 3): a fixture whose
    working copy differs from HEAD by ADDED TEXT is not a true-positive
    guard for the CRLF belt -- status and add -A agree it's modified under
    ANY autocrlf setting, so reverting either _git_raw call site back to
    ambient-config _git would still pass. This fixture instead differs
    from HEAD ONLY in line endings: the committed blob is LF
    ("hello\\nworld\\n"), the working copy is byte-identical text with
    CRLF endings only ("hello\\r\\nworld\\r\\n") -- no text added or
    removed. Under ambient core.autocrlf=true, that IS a real
    modification (git's own LF/CRLF bookkeeping disagrees about it) and
    is exactly the shape of difference a CRLF-normalized status vs a
    CRLF-blind add -A (or vice versa) would disagree about. Verified by
    the reviewer: this fixture DOES catch a revert of either _git_raw call
    site (SalvageError extra=/missing= under-capture) while the shipped
    forced-override code salvages it cleanly."""
    repo = _make_repo(tmp_path)
    _git(repo, "config", "core.autocrlf", "true")
    (repo / "a.txt").write_bytes(b"hello\nworld\n")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "LF baseline for the CRLF tripwire")

    wt = tmp_path / "wt-crlf"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-crlf-branch")
    _git(wt, "config", "core.autocrlf", "true")

    # Byte-identical TEXT, CRLF endings only -- no line added, none removed.
    (wt / "a.txt").write_bytes(b"hello\r\nworld\r\n")

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert "SALVAGE OK wt-crlf head=" in proc.stdout
    assert "SALVAGE SKIP" not in proc.stdout
    assert "dirty=none" not in proc.stdout


def test_restore_round_trips_a_removed_dirty_worktree(tmp_path):
    """Contract 4: restore recreates a worktree checked out to the dirty
    snapshot and prints the path; the known dirty file's content is back."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)
    expected_content = (wt / "untracked.txt").read_text(encoding="utf-8")

    applied = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert applied.returncode == 0, applied.stderr
    assert not wt.exists()

    restored_path = tmp_path / "restored_wt"
    proc = _run_tool("restore", "wt-dirty", str(restored_path), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert str(restored_path) in proc.stdout
    assert restored_path.exists()
    assert (restored_path / "untracked.txt").read_text(encoding="utf-8") == expected_content
    assert (restored_path / "a.txt").read_text(encoding="utf-8") == "hello\nmodified\n"


def test_restore_strips_the_reserved_bookkeeping_file_from_a_new_format_checkout(tmp_path):
    """Permanent pin for a behavior that was previously only proven live,
    never asserted by a test: a new-format dirty snapshot's tree contains
    the reserved .praxis-salvage-expected-files bookkeeping entry (see
    snapshot_worktree), and restore() must strip it from the checked-out
    worktree -- that file was never part of the worktree's own dirty
    content, and a restore is supposed to hand back exactly what was
    there, not archive-internal bookkeeping."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)

    applied = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert applied.returncode == 0, applied.stderr

    # confirm the fixture assumption: the archived tree DOES contain the
    # reserved entry (otherwise this test would trivially pass for the
    # wrong reason)
    dirty_ref = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-dirty-dirty")
    reserved_in_tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{dirty_ref}:.praxis-salvage-expected-files"],
        capture_output=True,
        text=True,
    )
    assert reserved_in_tree.returncode == 0

    restored_path = tmp_path / "restored_strip_check"
    proc = _run_tool("restore", "wt-dirty", str(restored_path), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert restored_path.exists()
    assert not (restored_path / ".praxis-salvage-expected-files").exists()
    # the real dirty content is still there -- stripping the bookkeeping
    # entry must not have taken anything else with it
    assert (restored_path / "a.txt").read_text(encoding="utf-8") == "hello\nmodified\n"


def _make_broken_archive(repo: Path, name: str) -> str:
    """A head ref plus a -dirty ref that is a PARENTLESS commit -- verify()
    fails on "dirty snapshot's parent is not the archived head" (head_sha
    still resolves, so --force has something to restore)."""
    head_sha = _git_out(repo, "rev-parse", "HEAD")
    tree_sha = _git_out(repo, "rev-parse", "HEAD^{tree}")
    orphan_commit = _git_out(repo, "commit-tree", tree_sha, "-m", "orphan, no parent")
    _git(repo, "update-ref", f"refs/archive/worktree/{name}", head_sha)
    _git(repo, "update-ref", f"refs/archive/worktree/{name}-dirty", orphan_commit)
    return head_sha


def test_restore_refuses_when_verify_fails_without_force(tmp_path):
    """Fix 3: restore refuses (nonzero exit) and loudly prints the verify
    failure reason when the archive it targets fails verify() and
    --force was not given."""
    repo = _make_repo(tmp_path)
    _make_broken_archive(repo, "broken")

    restored_path = tmp_path / "restored_broken"
    proc = _run_tool("restore", "broken", str(restored_path), "--repo-root", str(repo), "--apply")
    assert proc.returncode != 0
    assert "RESTORE REFUSED broken" in proc.stdout
    assert "reason=" in proc.stdout
    assert not restored_path.exists()


def test_restore_with_force_proceeds_and_marks_forced(tmp_path):
    """Fix 3: --force still restores past a failed verify, but the failure
    reason is printed and the result line is marked RESTORE FORCED."""
    repo = _make_repo(tmp_path)
    _make_broken_archive(repo, "broken")

    restored_path = tmp_path / "restored_broken_forced"
    proc = _run_tool("restore", "broken", str(restored_path), "--repo-root", str(repo), "--apply", "--force")
    assert proc.returncode == 0, proc.stderr
    assert "RESTORE FORCED broken" in proc.stdout
    assert "verify_reason=" in proc.stdout
    assert restored_path.exists()


def test_worktree_remove_failure_after_real_deregistration_reports_partial(tmp_path, monkeypatch):
    """Live-batch finding: `git worktree remove --force` can deregister a
    worktree (its .git/worktrees/<name> admin dir is gone, so `git
    worktree list` no longer shows it) while still failing to delete the
    directory itself -- e.g. a locked file blocking the final rmdir (a
    real case seen live: "error: failed to delete ...: Directory not
    empty" after the worktree had already vanished from the listing).
    SALVAGE SKIP would falsely claim the worktree was left fully in
    place; it must instead report SALVAGE PARTIAL, since the refs are
    safe but the directory is now an orphan with a dangling .git file.

    Simulated honestly rather than fully mocked: the remove call is
    allowed to run for real (registration genuinely drops, confirmed
    independently below via a real `git worktree list`), and only its
    reported RESULT is overridden to look like a failure -- standing in
    for the disk-level failure a real locked file would cause after
    registration has already dropped. This is a real assertion on the
    output contract, not a fabrication of both sides of it. (The
    directory itself does end up deleted in this fixture, since the real
    remove succeeds cleanly with nothing actually locked -- that part
    isn't what's under test; only the SKIP-vs-PARTIAL decision is.)"""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path, wt_name="wt-partial")

    import scripts.forge.worktree_salvage as worktree_salvage

    real_git = worktree_salvage._git

    def deregister_for_real_but_report_failure(cwd, *args, env=None):
        if args[:3] == ("worktree", "remove", "--force"):
            real_proc = real_git(cwd, *args, env=env)
            assert real_proc.returncode == 0, "fixture assumption broken: the real remove itself failed"
            return subprocess.CompletedProcess(
                args=["git", "worktree", "remove", "--force", args[3]],
                returncode=1,
                stdout="",
                stderr="error: failed to delete '...': Directory not empty\n",
            )
        return real_git(cwd, *args, env=env)

    monkeypatch.setattr(worktree_salvage, "_git", deregister_for_real_but_report_failure)

    line = worktree_salvage.salvage(repo, wt, apply=True)

    assert line.startswith("SALVAGE PARTIAL wt-partial ")
    assert "head=" in line
    assert "dirty=" in line
    assert f"dir={wt}" in line
    assert "Directory not empty" in line
    assert "SALVAGE SKIP" not in line

    # the archive refs are untouched by the failed-removal path and still verify
    verify_ok, verify_reason, *_ = worktree_salvage.verify(repo, "wt-partial")
    assert verify_ok is True, verify_reason

    # independently confirm (via a real, unpatched call) that the
    # worktree really is deregistered now -- this is the fact PARTIAL is
    # reporting, not an assumption baked into the mock
    listing = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    assert str(wt.resolve()).replace("\\", "/") not in listing.stdout.replace("\\", "/")


def test_worktree_remove_failure_while_still_registered_reports_skip(tmp_path, monkeypatch):
    """The counterpart to the PARTIAL test above: when `git worktree
    remove` fails and the worktree is STILL registered afterward (the
    ordinary case -- nothing deregistered), the tool must keep reporting
    SALVAGE SKIP, not PARTIAL."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path, wt_name="wt-still-registered")

    import scripts.forge.worktree_salvage as worktree_salvage

    real_git = worktree_salvage._git

    def fail_without_deregistering(cwd, *args, env=None):
        if args[:3] == ("worktree", "remove", "--force"):
            return subprocess.CompletedProcess(
                args=["git", "worktree", "remove", "--force", args[3]],
                returncode=1,
                stdout="",
                stderr="fatal: '...' is locked\n",
            )
        return real_git(cwd, *args, env=env)

    monkeypatch.setattr(worktree_salvage, "_git", fail_without_deregistering)

    line = worktree_salvage.salvage(repo, wt, apply=True)

    assert line.startswith("SALVAGE SKIP wt-still-registered ")
    assert "SALVAGE PARTIAL" not in line
    assert wt.exists()  # genuinely untouched


def test_git_failure_mid_salvage_skips_and_never_half_removes(tmp_path, monkeypatch, capsys):
    """Contract 5: any git failure mid-salvage produces a SALVAGE SKIP line
    and the worktree is never removed."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)

    import scripts.forge.worktree_salvage as worktree_salvage

    real_run = worktree_salvage._run

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "simulated write-tree failure"

    def flaky_run(cmd, **kwargs):
        if "write-tree" in cmd:
            return _Fail()
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(worktree_salvage, "_run", flaky_run)

    rc = worktree_salvage.main(["salvage", str(wt), "--repo-root", str(repo), "--apply"])
    assert rc == 0  # the tool itself does not crash/exit nonzero on a skip
    assert wt.exists()  # never half-removed

    captured = capsys.readouterr()
    assert "SALVAGE SKIP wt-dirty reason=" in captured.out

    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty-dirty") != 0


def test_add_a_warning_on_stderr_skips_even_with_exit_zero(tmp_path, monkeypatch, capsys):
    """Fix 1a: `add -A` exiting 0 is not trusted alone -- a warning: line
    on stderr (e.g. a long-path warning that silently drops a subtree)
    must skip the salvage, not archive a tree that under-captured."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)

    import scripts.forge.worktree_salvage as worktree_salvage

    real_run = worktree_salvage._run

    def warning_on_add(cmd, **kwargs):
        proc = real_run(cmd, **kwargs)
        if "add" in cmd and "-A" in cmd:
            proc = subprocess.CompletedProcess(
                cmd,
                0,
                stdout=proc.stdout,
                stderr=proc.stderr + "warning: simulated long-path warning: Filename too long\n",
            )
        return proc

    monkeypatch.setattr(worktree_salvage, "_run", warning_on_add)

    rc = worktree_salvage.main(["salvage", str(wt), "--repo-root", str(repo), "--apply"])
    assert rc == 0
    assert wt.exists()  # never half-removed

    captured = capsys.readouterr()
    assert "SALVAGE SKIP wt-dirty reason=" in captured.out
    assert "warning:" in captured.out

    assert _ref_returncode(repo, "refs/archive/worktree/wt-dirty") != 0


def test_verify_independently_catches_a_snapshot_that_lost_a_file(tmp_path):
    """Fix 1b (updated for the reserved-tree-entry format): verify() must
    catch a snapshot whose tree is missing a file the recorded
    expected-files list said should be there. The list's authoritative
    home is now a blob inside the snapshot's own tree (reserved path
    .praxis-salvage-expected-files), not the commit message -- so the
    tampering here targets that tree entry directly. Tampering the
    message instead would now be a no-op: new-format verify() never reads
    it."""
    repo = _make_repo(tmp_path)
    wt = _make_dirty_worktree_with_unique_commit(repo, tmp_path)

    applied = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert applied.returncode == 0, applied.stderr

    dirty_ref = "refs/archive/worktree/wt-dirty-dirty"
    dirty_sha = _git_out(repo, "rev-parse", dirty_ref)
    parent_sha = _git_out(repo, "rev-parse", f"{dirty_sha}^")

    # Replace the reserved tree entry's blob with one that claims an
    # extra file was expected that never actually made it into the tree
    # -- simulating a snapshot that silently under-captured.
    tampered_blob_content = "a.txt\nuntracked.txt\n.gitignore\nsubtree/lost_file.txt\n"
    scratch_index = tmp_path / "scratch-index-for-tamper"
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(scratch_index)
    subprocess.run(
        ["git", "-C", str(repo), "read-tree", f"{dirty_sha}^{{tree}}"],
        check=True,
        capture_output=True,
        env=env,
    )
    blob_proc = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
        input=tampered_blob_content,
        capture_output=True,
        text=True,
        env=env,
    )
    assert blob_proc.returncode == 0, blob_proc.stderr
    tampered_blob_sha = blob_proc.stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{tampered_blob_sha},.praxis-salvage-expected-files",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    tampered_tree_proc = subprocess.run(["git", "-C", str(repo), "write-tree"], capture_output=True, text=True, env=env)
    assert tampered_tree_proc.returncode == 0, tampered_tree_proc.stderr
    tampered_tree = tampered_tree_proc.stdout.strip()

    tampered_commit = _git_out(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit-tree",
        tampered_tree,
        "-p",
        parent_sha,
        "-m",
        "tampered snapshot",
    )
    _git(repo, "update-ref", dirty_ref, tampered_commit)

    verify = _run_tool("verify", "wt-dirty", "--repo-root", str(repo))
    assert verify.returncode != 0
    assert "VERIFY FAIL wt-dirty" in verify.stdout
    assert "subtree/lost_file.txt" in verify.stdout


def test_note_printed_when_core_longpaths_not_enabled(tmp_path):
    """core.longpaths not being true is the single most common cause of
    the exact silent-loss failure mode fix 1 defends against -- salvage
    must say so."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-note"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-note-branch")

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert "NOTE" in proc.stdout
    assert "core.longpaths" in proc.stdout


def test_venv_junction_rmdir_failure_is_reported_not_crashed(tmp_path, monkeypatch):
    """Fix 4: a plain OSError from os.rmdir (locked handle, AV scanner)
    must become a SALVAGE SKIP, never an uncaught crash."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-locked-venv"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-locked-venv-branch")

    target = tmp_path / "locked_target"
    target.mkdir()
    junction = wt / ".venv"
    if sys.platform == "win32":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        junction.symlink_to(target)

    import scripts.forge.worktree_salvage as worktree_salvage

    def raising_rmdir(path):
        raise PermissionError("simulated locked handle")

    monkeypatch.setattr(worktree_salvage.os, "rmdir", raising_rmdir)

    line = worktree_salvage.salvage(repo, wt, apply=True)
    assert line.startswith("SALVAGE SKIP wt-locked-venv")
    assert wt.exists()  # never half-removed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions only")
def test_venv_junction_is_unlinked_and_target_survives_removal(tmp_path):
    """Contract 6: when <wt>/.venv is a junction, salvage --apply removes
    the link (not the target), the target directory survives, and the
    worktree is still removed."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt_junction"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-junction-branch")

    target = tmp_path / "venv_target"
    target.mkdir()
    (target / "marker.txt").write_text("i am the real venv\n", encoding="utf-8")
    junction = wt / ".venv"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert junction.exists()

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert "removed=yes" in proc.stdout

    assert not wt.exists()  # the worktree is gone
    assert target.exists()  # the junction's TARGET survived
    assert (target / "marker.txt").read_text(encoding="utf-8") == "i am the real venv\n"
