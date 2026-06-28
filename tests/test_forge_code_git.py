"""Tests for the git-truth helpers behind Forge Code.

These exercise the helpers against a *real*, throwaway git repository created
in ``tmp_path``. Repo setup reuses the same :func:`_run_git` that the helpers
use -- the test process is allowed to run git, so this both bootstraps the
fixture and smoke-tests the argument shaping (``git -C <root> ...``).
"""

from __future__ import annotations

from thomas.forge.anvil.forge_code_git import (
    _run_git,
    changed_files,
    delta_since,
    file_is_dirty,
    is_untracked,
    revert_file,
    snapshot,
    unified_diff,
)


def _init_repo(root) -> None:
    """Create a throwaway git repo with deterministic identity/signing."""
    _run_git(root, ["init"])
    _run_git(root, ["config", "user.email", "test@example.com"])
    _run_git(root, ["config", "user.name", "Forge Test"])
    # The developer's global config may force GPG signing; disable it so a
    # commit in a bare tmp repo cannot hang or fail for unrelated reasons.
    _run_git(root, ["config", "commit.gpgsign", "false"])


def _commit_all(root, message: str = "commit") -> None:
    _run_git(root, ["add", "-A"])
    _run_git(root, ["commit", "-m", message])


def _new_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    return repo


def test_changed_files_lists_untracked_and_modified(tmp_path):
    repo = _new_repo(tmp_path)
    committed = repo / "committed.txt"
    committed.write_text("original\n", encoding="utf-8")
    _commit_all(repo)

    # Modify the committed file and add a brand-new untracked file.
    committed.write_text("original\nmodified\n", encoding="utf-8")
    (repo / "newfile.txt").write_text("brand new\n", encoding="utf-8")

    changed = changed_files(repo)
    assert "committed.txt" in changed
    assert "newfile.txt" in changed

    # Ground truth: it matches exactly what raw git status reports.
    _rc, out, _err = _run_git(repo, ["status", "--porcelain"])
    git_paths = sorted({line[3:].strip() for line in out.splitlines() if line.strip()})
    assert changed == git_paths

    assert is_untracked(repo, "newfile.txt") is True
    assert is_untracked(repo, "committed.txt") is False
    assert file_is_dirty(repo, "committed.txt") is True


def test_unified_diff_modified_and_untracked(tmp_path):
    repo = _new_repo(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("line one\n", encoding="utf-8")
    _commit_all(repo)

    tracked.write_text("line one\nline two added\n", encoding="utf-8")
    diff = unified_diff(repo, "tracked.txt")
    assert "+line two added" in diff
    assert "tracked.txt" in diff

    (repo / "fresh.txt").write_text("fresh contents here\n", encoding="utf-8")
    new_diff = unified_diff(repo, "fresh.txt")
    # The whole new file shows up as added lines.
    assert "+fresh contents here" in new_diff


def test_revert_modified_tracked_file_makes_it_clean(tmp_path):
    repo = _new_repo(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _commit_all(repo)

    tracked.write_text("committed\nlocal edit\n", encoding="utf-8")
    assert file_is_dirty(repo, "tracked.txt") is True

    result = revert_file(repo, "tracked.txt")
    assert result["ok"] is True
    assert result["clean"] is True
    assert result["file"] == "tracked.txt"
    # The on-disk file is restored to its committed contents.
    assert tracked.read_text(encoding="utf-8") == "committed\n"
    assert "tracked.txt" not in changed_files(repo)


def test_revert_untracked_file_deletes_it(tmp_path):
    repo = _new_repo(tmp_path)
    (repo / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(repo)

    junk = repo / "junk.txt"
    junk.write_text("delete me\n", encoding="utf-8")
    assert is_untracked(repo, "junk.txt") is True

    result = revert_file(repo, "junk.txt")
    assert result["ok"] is True
    assert result["clean"] is True
    assert junk.exists() is False
    assert "junk.txt" not in changed_files(repo)


def test_revert_refuses_path_escaping_root(tmp_path):
    repo = _new_repo(tmp_path)
    (repo / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(repo)

    # A file that lives OUTSIDE the repo root must never be touched.
    outside = tmp_path / "secret.txt"
    outside.write_text("do not delete\n", encoding="utf-8")

    escaped = revert_file(repo, "../secret.txt")
    assert escaped["ok"] is False
    assert outside.exists() is True
    assert outside.read_text(encoding="utf-8") == "do not delete\n"

    # An absolute path is likewise refused.
    absolute = revert_file(repo, str(outside))
    assert absolute["ok"] is False
    assert outside.exists() is True


def test_delta_since_lists_only_newly_touched(tmp_path):
    repo = _new_repo(tmp_path)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _commit_all(repo)

    # Snapshot a clean tree, then introduce exactly one new file.
    snap = snapshot(repo)
    assert snap == {}

    (repo / "added.txt").write_text("added after snapshot\n", encoding="utf-8")
    assert delta_since(repo, snap) == ["added.txt"]
