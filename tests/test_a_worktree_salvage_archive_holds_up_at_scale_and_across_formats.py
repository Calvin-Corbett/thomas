"""A worktree salvage must not choke at scale or on already-archived
data: a 2,000-file dirty worktree must not hit Windows' command-line
length limit, and archives created in the old inline-message format
(58 of them, pre-dating the WinError-206 fix) must keep verifying and
restoring without being re-salvaged."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "scripts" / "forge" / "worktree_salvage.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _git_out(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    # Pin autocrlf explicitly so these tests are deterministic regardless
    # of the host machine's global git config.
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base")
    return repo


def _run_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
    )


def test_verify_and_restore_still_support_the_old_inline_message_format(tmp_path):
    """Live-batch fix: 58 worktrees are already archived in the OLD format
    (expected-files list embedded inline in the commit message body, no
    reserved tree entry -- the format this tool used before the
    WinError-206 fix). verify() and restore() must keep working on those
    without requiring anyone to re-archive them."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-oldformat"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-oldformat-branch")
    (wt / "a.txt").write_text("old format dirty content\n", encoding="utf-8")

    head_sha = _git_out(wt, "rev-parse", "HEAD")
    _git(wt, "add", "-A")
    tree_sha = _git_out(wt, "write-tree")

    old_message = "praxis-salvage snapshot of wt-oldformat (1 files)\n\nexpected-files:\na.txt\n"
    dirty_sha = _git_out(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit-tree",
        tree_sha,
        "-p",
        head_sha,
        "-m",
        old_message,
    )
    _git(repo, "update-ref", "refs/archive/worktree/wt-oldformat", head_sha)
    _git(repo, "update-ref", "refs/archive/worktree/wt-oldformat-dirty", dirty_sha)

    # this tree has NO .praxis-salvage-expected-files entry -- confirm the
    # fixture itself is genuinely old-format before trusting the assertions below
    no_reserved_entry = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{dirty_sha}:.praxis-salvage-expected-files"],
        capture_output=True,
        text=True,
    )
    assert no_reserved_entry.returncode != 0

    verify_proc = _run_tool("verify", "wt-oldformat", "--repo-root", str(repo))
    assert verify_proc.returncode == 0, verify_proc.stderr
    assert "VERIFY OK wt-oldformat" in verify_proc.stdout

    restored_path = tmp_path / "restored_oldformat"
    restore_proc = _run_tool("restore", "wt-oldformat", str(restored_path), "--repo-root", str(repo), "--apply")
    assert restore_proc.returncode == 0, restore_proc.stderr
    assert (restored_path / "a.txt").read_text(encoding="utf-8") == "old format dirty content\n"


def test_scale_2000_dirty_files_salvages_without_command_line_limit(tmp_path):
    """Live-batch crash: a real 10,614-dirty-file worktree crashed
    snapshot_worktree()'s `git commit-tree -m <message>` with WinError 206
    (command line too long), because the expected-files list used to be
    embedded directly in the -m argument. 2,000 small generated files
    (~40-char paths) comfortably exceeds Windows' ~32K command-line limit
    if anything -- the message, or the file list itself -- is still
    passed as a command-line argument anywhere in the snapshot path."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-scale"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-scale-branch")

    generated = wt / "generated"
    generated.mkdir()
    for i in range(2000):
        (generated / f"generated-file-{i:05d}-with-a-reasonably-long-name.txt").write_text(
            f"content {i}\n", encoding="utf-8"
        )

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert "SALVAGE OK wt-scale head=" in proc.stdout
    assert "changed=2000" in proc.stdout

    verify_proc = _run_tool("verify", "wt-scale", "--repo-root", str(repo))
    assert verify_proc.returncode == 0, verify_proc.stderr
    assert "VERIFY OK wt-scale" in verify_proc.stdout


def test_ad_entry_staged_new_file_then_deleted_does_not_cause_a_false_refusal(tmp_path):
    """Reviewer-diagnosed live-batch finding: `git status --porcelain=v1
    -uall` reports "AD path" for a file that was `git add`-ed (staged as
    new in the index) and then deleted from disk before salvage ran. That
    path exists in NEITHER the HEAD tree NOR the snapshot's content tree
    -- `add -A` follows the working tree and drops it from the temp index
    too, so it can never appear in a tree diff either way. Counting it as
    "expected" produced a permanent, unfixable missing=[...] false SKIP
    (reproduced live: a 130-file batch refused this way). The AD path
    must land in neither the changed count nor the archive."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-ad"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-ad-branch")

    # a genuine dirty file too, so the worktree is dirty for a real reason
    (wt / "b.txt").write_text("real dirty content\n", encoding="utf-8")

    ghost = wt / "staged_then_deleted.txt"
    ghost.write_text("staged, then removed before salvage\n", encoding="utf-8")
    _git(wt, "add", "staged_then_deleted.txt")
    ghost.unlink()

    # confirm the fixture genuinely produces an AD entry before trusting
    # the assertions below
    status = _git_out(wt, "status", "--porcelain=v1")
    assert "AD staged_then_deleted.txt" in status

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert "SALVAGE OK wt-ad head=" in proc.stdout
    assert "SALVAGE SKIP" not in proc.stdout
    assert "changed=1" in proc.stdout  # b.txt only -- the AD phantom is excluded

    head_ref = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-ad")
    dirty_ref = _git_out(repo, "rev-parse", "refs/archive/worktree/wt-ad-dirty")
    changed = set(_git_out(repo, "diff", "--name-only", head_ref, dirty_ref).splitlines())
    assert "staged_then_deleted.txt" not in changed
    changed.discard(".praxis-salvage-expected-files")
    assert changed == {"b.txt"}


def test_dirty_file_with_non_ascii_name_salvages_ok(tmp_path):
    """Reviewer-diagnosed live-batch finding, same class as the AD fix:
    with the default core.quotepath=true, `git status` and `git diff`
    C-quote/octal-escape non-ASCII filenames for display, and the
    surrounding-quote stripping in _files_from_status does not decode
    those octal escapes -- so a single non-ASCII dirty filename could come
    out spelled two different ways on the status side vs the diff side, a
    permanent missing+extra false SKIP no amount of retrying fixes. Both
    call sites now force core.quotepath=false so names come through raw
    and identical on both sides."""
    repo = _make_repo(tmp_path)
    wt = tmp_path / "wt-nonascii"
    _git(repo, "worktree", "add", str(wt), "-b", "wt-nonascii-branch")

    (wt / "café.txt").write_text("un café dirty\n", encoding="utf-8")

    proc = _run_tool("salvage", str(wt), "--repo-root", str(repo), "--apply")
    assert proc.returncode == 0, proc.stderr
    assert "SALVAGE OK wt-nonascii head=" in proc.stdout
    assert "SALVAGE SKIP" not in proc.stdout
    assert "changed=1" in proc.stdout

    verify_proc = _run_tool("verify", "wt-nonascii", "--repo-root", str(repo))
    assert verify_proc.returncode == 0, verify_proc.stderr
    assert "VERIFY OK wt-nonascii" in verify_proc.stdout
