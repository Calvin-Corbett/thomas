"""CAP-086 L2: checkpoint repository, environment, and conversation state with selective undo.

Proves, against a hermetic temp git repo with an injected clock:

- A single checkpoint captures all three kinds (repo tracked files, an env
  mapping, and a conversation turns list).
- After mutating all three, a full rollback restores all three.
- SELECTIVE rollback of only ``repository`` restores the files on disk while
  leaving the (already-changed) env mapping and conversation list untouched.
- SELECTIVE rollback of only ``conversation`` restores the turns while leaving
  the (already-changed) working-tree files untouched.
- Rolling back an unknown checkpoint signals cleanly (typed exception).
- The checkpoint list round-trips what was stored.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.tools.checkpoint_rollback import (
    KIND_CONVERSATION,
    KIND_ENVIRONMENT,
    KIND_REPOSITORY,
    CheckpointManager,
    CheckpointNotFoundError,
    UnknownKindError,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Thomas")
    (root / "alpha.txt").write_text("alpha-v1", encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "beta.txt").write_text("beta-v1", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def _manager(tmp_path: Path) -> CheckpointManager:
    return CheckpointManager(tmp_path / "checkpoints", clock=_Clock())


def test_checkpoint_captures_all_three_kinds(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    env = {"MODE": "prod", "TOKEN": "abc"}
    conversation = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}]

    info = mgr.checkpoint("cp1", repo_root=repo, env=env, conversation=conversation)

    assert info.kinds == [KIND_REPOSITORY, KIND_ENVIRONMENT, KIND_CONVERSATION]
    assert info.repo_file_count == 2  # alpha.txt + pkg/beta.txt
    assert info.env_var_count == 2
    assert info.conversation_turn_count == 2
    assert mgr.exists("cp1")


def test_full_rollback_restores_all_three(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    env = {"MODE": "prod"}
    conversation = [{"role": "user", "text": "original"}]
    mgr.checkpoint("cp1", repo_root=repo, env=env, conversation=conversation)

    # Mutate all three.
    (repo / "alpha.txt").write_text("alpha-CHANGED", encoding="utf-8")
    env["MODE"] = "dev"
    env["EXTRA"] = "x"
    conversation.append({"role": "assistant", "text": "new turn"})

    result = mgr.rollback("cp1", repo_root=repo, env=env, conversation=conversation)

    assert set(result.restored) == {KIND_REPOSITORY, KIND_ENVIRONMENT, KIND_CONVERSATION}
    assert (repo / "alpha.txt").read_text(encoding="utf-8") == "alpha-v1"
    assert env == {"MODE": "prod"}
    assert conversation == [{"role": "user", "text": "original"}]


def test_selective_rollback_repo_only_leaves_env_and_conversation(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    env = {"MODE": "prod"}
    conversation = [{"role": "user", "text": "original"}]
    mgr.checkpoint("cp1", repo_root=repo, env=env, conversation=conversation)

    # Change all three, then roll back ONLY the repository.
    (repo / "alpha.txt").write_text("alpha-CHANGED", encoding="utf-8")
    env["MODE"] = "dev"
    conversation.append({"role": "assistant", "text": "new"})

    result = mgr.rollback(
        "cp1",
        kinds=[KIND_REPOSITORY],
        repo_root=repo,
        env=env,
        conversation=conversation,
    )

    assert result.restored == [KIND_REPOSITORY]
    assert result.repo_files_restored == 2
    # Files restored...
    assert (repo / "alpha.txt").read_text(encoding="utf-8") == "alpha-v1"
    # ...but env and conversation left as the caller changed them.
    assert env == {"MODE": "dev"}
    assert conversation == [{"role": "user", "text": "original"}, {"role": "assistant", "text": "new"}]
    assert result.env_restored is False
    assert result.conversation_restored is False


def test_selective_rollback_conversation_only_leaves_files(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    env = {"MODE": "prod"}
    conversation = [{"role": "user", "text": "original"}]
    mgr.checkpoint("cp1", repo_root=repo, env=env, conversation=conversation)

    (repo / "alpha.txt").write_text("alpha-CHANGED", encoding="utf-8")
    env["MODE"] = "dev"
    conversation.append({"role": "assistant", "text": "new"})

    result = mgr.rollback(
        "cp1",
        kinds=[KIND_CONVERSATION],
        repo_root=repo,
        env=env,
        conversation=conversation,
    )

    assert result.restored == [KIND_CONVERSATION]
    # Conversation restored...
    assert conversation == [{"role": "user", "text": "original"}]
    # ...but the working-tree file left changed, and env left changed.
    assert (repo / "alpha.txt").read_text(encoding="utf-8") == "alpha-CHANGED"
    assert env == {"MODE": "dev"}


def test_unknown_checkpoint_signals_cleanly(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    with pytest.raises(CheckpointNotFoundError):
        mgr.rollback("does-not-exist", kinds=[KIND_CONVERSATION], conversation=[])
    with pytest.raises(CheckpointNotFoundError):
        mgr.inspect("does-not-exist")


def test_unknown_kind_signals_cleanly(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    mgr.checkpoint("cp1", repo_root=repo)
    with pytest.raises(UnknownKindError):
        mgr.rollback("cp1", kinds=["filesystem"], repo_root=repo)


def test_checkpoint_list_round_trips(repo: Path, tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    mgr.checkpoint("first", repo_root=repo, env={"A": "1"})
    mgr.checkpoint("second", conversation=[{"role": "user", "text": "hey"}])

    listed = mgr.list_checkpoints()
    names = [c.name for c in listed]
    assert names == ["first", "second"]

    by_name = {c.name: c for c in listed}
    assert by_name["first"].kinds == [KIND_REPOSITORY, KIND_ENVIRONMENT]
    assert by_name["first"].env_var_count == 1
    assert by_name["second"].kinds == [KIND_CONVERSATION]
    assert by_name["second"].conversation_turn_count == 1

    # A fresh manager over the same root sees the same checkpoints (durable).
    reopened = CheckpointManager(tmp_path / "checkpoints")
    assert [c.name for c in reopened.list_checkpoints()] == ["first", "second"]


def test_env_dir_override(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "via-env"
    monkeypatch.setenv("THOMAS_CHECKPOINT_DIR", str(custom))
    mgr = CheckpointManager()
    mgr.checkpoint("cp1", repo_root=repo)
    assert (custom / "cp1" / "manifest.json").is_file()
