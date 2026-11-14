"""Shared patch bytes must not share a repository's mutable state or hand-in metadata."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks

from tests import shared_card_support as support
from tests.green_support import git
from tests.shared_card_support import _submit, blue, shared_card_seed  # noqa: F401


def test_cached_patch_reuses_equivalent_settings_in_distinct_git_homes(
    blue: Path, shared_card_seed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    support._SUBMISSIONS.clear()
    files = {"thomas/reuse.py": "REUSE = 1\n"}
    first = _submit(blue, "exec-home-first", files)
    other_root = blue.parent / "next-test"
    other_root.mkdir()
    other = other_root / "blue"
    shutil.copytree(shared_card_seed, other)
    with monkeypatch.context() as environment:
        environment.setenv("THOMAS_CAGE_ROOT", str(other_root / "cage"))
        support._git_home(other_root, environment)
        with environment.context() as no_git:

            def unexpected_git(*args, **kwargs):
                pytest.fail("equivalent settings in a fresh test must reuse the patch without Git")

            no_git.setattr(subprocess, "run", unexpected_git)
            second = _submit(other, "exec-home-second", files)
    assert (first / "change.patch").read_bytes() == (second / "change.patch").read_bytes()
    record = json.loads((second / "submission.json").read_text(encoding="utf-8"))
    assert record["execution_id"] == "exec-home-second"
    assert second.parent == other_root / "cage" / "inbox"


def test_submission_leaves_staged_and_untracked_work_untouched(blue: Path) -> None:
    (blue / "README.md").write_text("staged work\n", encoding="utf-8")
    git(blue, "add", "README.md")
    (blue / "untracked.txt").write_text("untracked work\n", encoding="utf-8")
    head_before = git(blue, "rev-parse", "HEAD")
    status_before = git(blue, "status", "--porcelain")
    index_before = (blue / ".git/index").read_bytes()

    sub = _submit(blue, "exec-private-index", {"thomas/new.py": "NEW = 1\n"})

    assert (blue / ".git/index").read_bytes() == index_before
    assert git(blue, "rev-parse", "HEAD") == head_before
    assert git(blue, "status", "--porcelain") == status_before
    assert (blue / "README.md").read_text(encoding="utf-8") == "staged work\n"
    assert (blue / "untracked.txt").read_text(encoding="utf-8") == "untracked work\n"
    record = json.loads((sub / "submission.json").read_text(encoding="utf-8"))
    assert record["files"] == ["thomas/new.py"]


def test_cached_submission_preserves_current_base_and_chat(blue: Path) -> None:
    files = {"thomas/fix_me.py": "VALUE = 2\n"}
    first = _submit(blue, "exec-first", files, chat="chat-first")
    cached = _submit(blue, "exec-cached", files, chat="chat-second")
    assert json.loads((cached / "submission.json").read_text())["chat"] == "chat-second"
    assert (first / "change.patch").read_bytes() == (cached / "change.patch").read_bytes()
    (blue / "thomas/fix_me.py").write_text("VALUE = 3\n", encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "move base")
    head = git(blue, "rev-parse", "HEAD")
    moved = _submit(blue, "exec-moved", files)
    record = json.loads((moved / "submission.json").read_text())
    assert record["base"] == head
    assert (moved / "change.patch").read_bytes() != (first / "change.patch").read_bytes()
    tree = checks.derive_tree(blue, head, (moved / "change.patch").read_bytes())
    assert checks.run_git(blue, "show", f"{tree}:thomas/fix_me.py").stdout == "VALUE = 2\n"
