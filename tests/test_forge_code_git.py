"""Tests for the git-truth helpers behind Forge Code.

These exercise the helpers against a *real*, throwaway git repository created
in ``tmp_path``. Repo setup reuses the same :func:`_run_git` that the helpers
use -- the test process is allowed to run git, so this both bootstraps the
fixture and smoke-tests the argument shaping (``git -C <root> ...``).
"""

from __future__ import annotations

import pytest

from thomas.forge.anvil import forge_code_git
from thomas.forge.anvil.forge_code_git import (
    ForgeCodeGitError,
    _run_git,
    changed_files,
    delta_since,
    file_is_dirty,
    is_untracked,
    revert_file,
    snapshot,
    unified_diff,
)
from thomas.forge.anvil.forge_code_store import _agent_reply_text


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


def test_agent_reply_prefers_explicit_final_over_progress_and_legacy_reason():
    turn = {
        "transcript": "\n".join(
            [
                '{"fc":"say","text":"Inspecting the project."}',
                '{"fc":"say","text":"Running the browser proof."}',
                '{"fc":"final","text":"Built the game and verified Start, Pause, and Resume."}',
            ]
        ),
        "reason": "3 file(s) changed",
    }

    assert _agent_reply_text(turn) == "Built the game and verified Start, Pause, and Resume."


def test_agent_reply_uses_legacy_say_transcript_when_final_is_absent():
    turn = {
        "transcript": '{"fc":"say","text":"Legacy conversational handoff."}',
        "reason": "No file changes",
    }

    assert _agent_reply_text(turn) == "Legacy conversational handoff."


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

    assert changed == ["committed.txt", "newfile.txt"]

    assert is_untracked(repo, "newfile.txt") is True
    assert is_untracked(repo, "committed.txt") is False
    assert file_is_dirty(repo, "committed.txt") is True


def test_untracked_directory_is_expanded_to_individual_deliverables(tmp_path):
    repo = _new_repo(tmp_path)
    (repo / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(repo)
    snap = snapshot(repo)

    game = repo / "trey-viking-proof"
    game.mkdir()
    (game / "index.html").write_text("<main>Trey</main>\n", encoding="utf-8")
    (game / "styles.css").write_text("main { color: gold; }\n", encoding="utf-8")
    (game / "game.js").write_text("const playable = true;\n", encoding="utf-8")

    expected = [
        "trey-viking-proof/game.js",
        "trey-viking-proof/index.html",
        "trey-viking-proof/styles.css",
    ]
    assert changed_files(repo) == expected
    assert delta_since(repo, snap) == expected
    assert is_untracked(repo, "trey-viking-proof/index.html") is True


def test_unicode_artifact_path_round_trips_without_git_c_escaping(tmp_path):
    repo = _new_repo(tmp_path)
    (repo / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(repo)

    artifact = repo / "tréy-viking" / "index.html"
    artifact.parent.mkdir()
    artifact.write_text("<main>Tréy</main>\n", encoding="utf-8")

    assert changed_files(repo) == ["tréy-viking/index.html"]
    assert is_untracked(repo, "tréy-viking/index.html") is True
    assert "+<main>Tréy</main>" in unified_diff(repo, "tréy-viking/index.html")


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


def test_unified_diff_includes_staged_and_unstaged_changes(tmp_path):
    repo = _new_repo(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    _commit_all(repo)

    tracked.write_text("original\nstaged line\n", encoding="utf-8")
    _run_git(repo, ["add", "tracked.txt"])
    tracked.write_text("original\nstaged line\nunstaged line\n", encoding="utf-8")

    diff = unified_diff(repo, "tracked.txt")
    assert "+staged line" in diff
    assert "+unstaged line" in diff


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


def test_project_delta_excludes_thomas_code_bookkeeping(tmp_path):
    from thomas.forge.anvil.forge_code_git import project_delta_since

    repo = _new_repo(tmp_path)
    snap = snapshot(repo)
    runtime = repo / ".thomas" / "evolve" / "agent" / "conversations" / "turn.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("{}\n", encoding="utf-8")
    (repo / "game.js").write_text("window.ready = true;\n", encoding="utf-8")

    assert project_delta_since(repo, snap) == ["game.js"]


def test_delta_since_detects_a_second_edit_to_an_already_dirty_file(tmp_path):
    repo = _new_repo(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _commit_all(repo)
    tracked.write_text("dirty before run\n", encoding="utf-8")
    snap = snapshot(repo)

    tracked.write_text("changed by code run\n", encoding="utf-8")

    assert delta_since(repo, snap) == ["tracked.txt"]


def test_git_status_failure_is_never_reported_as_a_clean_tree(tmp_path, monkeypatch):
    repo = _new_repo(tmp_path)
    monkeypatch.setattr(forge_code_git, "_run_git", lambda *_args, **_kwargs: (128, "", "bad index"))

    with pytest.raises(ForgeCodeGitError, match="bad index"):
        snapshot(repo)
    with pytest.raises(ForgeCodeGitError, match="bad index"):
        changed_files(repo)


def test_git_diff_failure_is_never_reported_as_empty_evidence(tmp_path, monkeypatch):
    repo = _new_repo(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _commit_all(repo)
    tracked.write_text("changed\n", encoding="utf-8")
    original = forge_code_git._run_git

    def _fail_diff(root, args, timeout=30):
        if args and args[0] == "diff":
            return 128, "", "diff evidence unavailable"
        return original(root, args, timeout)

    monkeypatch.setattr(forge_code_git, "_run_git", _fail_diff)

    with pytest.raises(ForgeCodeGitError, match="diff evidence unavailable"):
        forge_code_git.unified_diff(repo, "tracked.txt")
