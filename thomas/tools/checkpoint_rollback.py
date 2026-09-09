"""CAP-086: Checkpoints & rollback with selective undo.

Capture a named checkpoint spanning THREE independent kinds of state and later
restore any subset of them:

- **repository** -- the contents of every git-tracked file under a repo root
  (captured as a byte-for-byte snapshot, so it survives even a ``git reset``);
- **environment** -- a point-in-time copy of a provided environment-variable
  mapping;
- **conversation** -- a point-in-time copy of a provided list of turns.

Everything is persisted durably under a checkpoint directory (JSON manifest +
per-file byte snapshots), so a checkpoint outlives the process that made it.
The directory defaults to ``$THOMAS_CHECKPOINT_DIR`` (falling back to a
``thomas_checkpoints`` folder in the system temp dir) and is overridable per
manager instance.

Selective undo is the point: :meth:`CheckpointManager.rollback` takes an
explicit set of ``kinds`` and restores ONLY those, leaving the others exactly
as the caller left them. Restoring ``repository`` rewrites files on disk;
restoring ``environment`` / ``conversation`` mutates the live mapping / list the
caller hands in (so a repo-only rollback never touches them, and an
environment-only rollback never touches the working tree).

This module depends only on the standard library and the ``git`` binary (tools
layer rule: no imports from agent/server/cli).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KIND_REPOSITORY = "repository"
KIND_ENVIRONMENT = "environment"
KIND_CONVERSATION = "conversation"
ALL_KINDS: tuple[str, ...] = (KIND_REPOSITORY, KIND_ENVIRONMENT, KIND_CONVERSATION)

_ENV_DIR_VAR = "THOMAS_CHECKPOINT_DIR"
_MANIFEST_NAME = "manifest.json"
_REPO_SUBDIR = "repo"
_ENV_FILE = "environment.json"
_CONVERSATION_FILE = "conversation.json"


class CheckpointError(Exception):
    """Base class for checkpoint/rollback failures."""


class CheckpointNotFoundError(CheckpointError):
    """Raised when a rollback/inspect targets a checkpoint that does not exist."""


class UnknownKindError(CheckpointError):
    """Raised when a checkpoint/rollback is asked for a state kind we don't handle."""


@dataclass
class RepoFileRecord:
    """One git-tracked file captured in a checkpoint (path + integrity hash)."""

    path: str
    sha256: str


@dataclass
class CheckpointInfo:
    """Summary of a stored checkpoint (what it holds, when it was made)."""

    name: str
    created_at: float
    kinds: list[str]
    repo_file_count: int = 0
    env_var_count: int = 0
    conversation_turn_count: int = 0


@dataclass
class RollbackResult:
    """Outcome of a selective rollback: exactly which kinds were restored.

    Attributes:
        name: The checkpoint that was rolled back to.
        restored: The kinds actually restored, in canonical order.
        repo_files_restored: Number of tracked files rewritten on disk.
        env_restored: Whether the provided env mapping was restored in place.
        conversation_restored: Whether the provided turns list was restored.
    """

    name: str
    restored: list[str]
    repo_files_restored: int = 0
    env_restored: bool = False
    conversation_restored: bool = False


@dataclass
class _Manifest:
    name: str
    created_at: float
    kinds: list[str]
    repo_files: list[RepoFileRecord] = field(default_factory=list)
    env_var_count: int = 0
    conversation_turn_count: int = 0


def _default_root() -> Path:
    override = str(os.environ.get(_ENV_DIR_VAR, "") or "").strip()
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "thomas_checkpoints"


def _validate_kinds(kinds: Iterable[str]) -> list[str]:
    """Return the requested kinds in canonical order, rejecting unknown ones."""
    requested = set(kinds)
    unknown = requested - set(ALL_KINDS)
    if unknown:
        raise UnknownKindError(f"unknown state kind(s): {sorted(unknown)}")
    return [k for k in ALL_KINDS if k in requested]


def _git_tracked_files(repo_root: Path) -> list[str]:
    """List git-tracked file paths (repo-relative, forward slashes, sorted)."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    raw = proc.stdout.decode("utf-8", errors="replace")
    files = [p for p in raw.split("\0") if p]
    return sorted(files)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CheckpointManager:
    """Capture and selectively restore repository, environment, and conversation state.

    Args:
        root: Directory under which checkpoints are stored. Defaults to
            ``$THOMAS_CHECKPOINT_DIR`` or a temp folder. Each checkpoint lives in
            its own ``<root>/<name>/`` subdirectory.
        clock: Injectable time source (seconds); defaults to ``time.time``.
    """

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root) if root is not None else _default_root()
        self._clock = clock
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _dir_for(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise CheckpointError(f"invalid checkpoint name: {name!r}")
        return self._root / name

    # -- capture -----------------------------------------------------------

    def checkpoint(
        self,
        name: str,
        *,
        repo_root: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        conversation: Sequence[Any] | None = None,
    ) -> CheckpointInfo:
        """Capture a named checkpoint across all supplied state kinds.

        Any kind whose source is ``None`` is simply omitted from the checkpoint.
        A previously stored checkpoint with the same name is replaced.

        Args:
            name: Checkpoint identifier (also its on-disk subdirectory).
            repo_root: Root of a git repo whose tracked files are snapshotted.
            env: Environment-variable mapping to snapshot (copied, not held).
            conversation: List of conversation turns to snapshot (deep-copied).

        Returns:
            A :class:`CheckpointInfo` describing what was captured.
        """
        target = self._dir_for(name)
        if target.exists():
            self._remove_tree(target)
        target.mkdir(parents=True)

        kinds: list[str] = []
        repo_files: list[RepoFileRecord] = []
        env_count = 0
        turn_count = 0

        if repo_root is not None:
            repo_files = self._capture_repo(Path(repo_root), target)
            kinds.append(KIND_REPOSITORY)
        if env is not None:
            env_count = self._capture_env(env, target)
            kinds.append(KIND_ENVIRONMENT)
        if conversation is not None:
            turn_count = self._capture_conversation(conversation, target)
            kinds.append(KIND_CONVERSATION)

        manifest = _Manifest(
            name=name,
            created_at=float(self._clock()),
            kinds=[k for k in ALL_KINDS if k in kinds],
            repo_files=repo_files,
            env_var_count=env_count,
            conversation_turn_count=turn_count,
        )
        self._write_manifest(target, manifest)
        logger.info(
            "checkpoint %r captured (%s)",
            name,
            ", ".join(manifest.kinds) or "empty",
        )
        return self._info_from_manifest(manifest)

    def _capture_repo(self, repo_root: Path, target: Path) -> list[RepoFileRecord]:
        repo_snapshot = target / _REPO_SUBDIR
        repo_snapshot.mkdir(parents=True, exist_ok=True)
        records: list[RepoFileRecord] = []
        for rel in _git_tracked_files(repo_root):
            source = repo_root / rel
            if not source.is_file():
                # Tracked but absent from the working tree (e.g. deleted); skip.
                continue
            data = source.read_bytes()
            dest = repo_snapshot / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            records.append(RepoFileRecord(path=rel, sha256=_sha256_bytes(data)))
        return records

    def _capture_env(self, env: Mapping[str, str], target: Path) -> int:
        snapshot = {str(k): str(v) for k, v in env.items()}
        (target / _ENV_FILE).write_text(
            json.dumps(snapshot, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return len(snapshot)

    def _capture_conversation(self, conversation: Sequence[Any], target: Path) -> int:
        snapshot = copy.deepcopy(list(conversation))
        (target / _CONVERSATION_FILE).write_text(
            json.dumps(snapshot, indent=2),
            encoding="utf-8",
        )
        return len(snapshot)

    # -- selective restore -------------------------------------------------

    def rollback(
        self,
        name: str,
        kinds: Iterable[str] | None = None,
        *,
        repo_root: str | os.PathLike[str] | None = None,
        env: dict[str, str] | None = None,
        conversation: list[Any] | None = None,
    ) -> RollbackResult:
        """Restore ONLY the selected state kinds from a stored checkpoint.

        Selective undo: pass ``kinds=[KIND_REPOSITORY]`` to restore just the
        working tree, ``kinds=[KIND_CONVERSATION]`` to restore just the turns,
        and so on. Kinds not listed are left completely untouched. A kind can
        only be restored if it is both requested and present in the checkpoint.

        Restoring ``repository`` rewrites tracked files under ``repo_root``.
        Restoring ``environment`` / ``conversation`` mutates the provided
        ``env`` mapping / ``conversation`` list **in place** (cleared, then
        repopulated from the snapshot), so the caller's live objects reflect the
        rollback while unrelated objects stay as they are.

        Args:
            name: Checkpoint to roll back to.
            kinds: Which kinds to restore; defaults to every kind the checkpoint
                holds.
            repo_root: Working tree to restore into (required if restoring the
                repository kind).
            env: Live env mapping to restore in place (required to restore env).
            conversation: Live turns list to restore in place (required to
                restore conversation).

        Returns:
            A :class:`RollbackResult` naming exactly what was restored.

        Raises:
            CheckpointNotFoundError: If no checkpoint named ``name`` exists.
            UnknownKindError: If ``kinds`` names a kind we don't handle.
            CheckpointError: If a requested kind lacks the object needed to
                restore it (e.g. env requested but ``env`` is ``None``).
        """
        target = self._dir_for(name)
        if not (target / _MANIFEST_NAME).is_file():
            raise CheckpointNotFoundError(f"no checkpoint named {name!r}")
        manifest = self._read_manifest(target)

        requested = _validate_kinds(kinds) if kinds is not None else list(manifest.kinds)
        effective = [k for k in requested if k in manifest.kinds]

        result = RollbackResult(name=name, restored=[])
        for kind in effective:
            if kind == KIND_REPOSITORY:
                if repo_root is None:
                    raise CheckpointError("repo_root is required to restore repository state")
                result.repo_files_restored = self._restore_repo(Path(repo_root), target, manifest)
                result.restored.append(kind)
            elif kind == KIND_ENVIRONMENT:
                if env is None:
                    raise CheckpointError("env mapping is required to restore environment state")
                self._restore_env(env, target)
                result.env_restored = True
                result.restored.append(kind)
            elif kind == KIND_CONVERSATION:
                if conversation is None:
                    raise CheckpointError("conversation list is required to restore conversation state")
                self._restore_conversation(conversation, target)
                result.conversation_restored = True
                result.restored.append(kind)

        logger.info(
            "rollback %r restored: %s",
            name,
            ", ".join(result.restored) or "nothing",
        )
        return result

    def _restore_repo(self, repo_root: Path, target: Path, manifest: _Manifest) -> int:
        repo_snapshot = target / _REPO_SUBDIR
        restored = 0
        for record in manifest.repo_files:
            source = repo_snapshot / record.path
            data = source.read_bytes()
            dest = repo_root / record.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            restored += 1
        return restored

    def _restore_env(self, env: dict[str, str], target: Path) -> None:
        snapshot = json.loads((target / _ENV_FILE).read_text(encoding="utf-8"))
        env.clear()
        env.update({str(k): str(v) for k, v in snapshot.items()})

    def _restore_conversation(self, conversation: list[Any], target: Path) -> None:
        snapshot = json.loads((target / _CONVERSATION_FILE).read_text(encoding="utf-8"))
        conversation.clear()
        conversation.extend(snapshot)

    # -- list / inspect ----------------------------------------------------

    def list_checkpoints(self) -> list[CheckpointInfo]:
        """Return every stored checkpoint, sorted by name."""
        infos: list[CheckpointInfo] = []
        for child in sorted(self._root.iterdir() if self._root.exists() else []):
            manifest_path = child / _MANIFEST_NAME
            if child.is_dir() and manifest_path.is_file():
                infos.append(self._info_from_manifest(self._read_manifest(child)))
        return infos

    def inspect(self, name: str) -> CheckpointInfo:
        """Return the :class:`CheckpointInfo` for one checkpoint.

        Raises:
            CheckpointNotFoundError: If no such checkpoint exists.
        """
        target = self._dir_for(name)
        if not (target / _MANIFEST_NAME).is_file():
            raise CheckpointNotFoundError(f"no checkpoint named {name!r}")
        return self._info_from_manifest(self._read_manifest(target))

    def exists(self, name: str) -> bool:
        """Whether a checkpoint with this name is stored."""
        return (self._dir_for(name) / _MANIFEST_NAME).is_file()

    # -- manifest / fs helpers --------------------------------------------

    def _info_from_manifest(self, manifest: _Manifest) -> CheckpointInfo:
        return CheckpointInfo(
            name=manifest.name,
            created_at=manifest.created_at,
            kinds=list(manifest.kinds),
            repo_file_count=len(manifest.repo_files),
            env_var_count=manifest.env_var_count,
            conversation_turn_count=manifest.conversation_turn_count,
        )

    def _write_manifest(self, target: Path, manifest: _Manifest) -> None:
        payload = {
            "name": manifest.name,
            "created_at": manifest.created_at,
            "kinds": manifest.kinds,
            "repo_files": [{"path": r.path, "sha256": r.sha256} for r in manifest.repo_files],
            "env_var_count": manifest.env_var_count,
            "conversation_turn_count": manifest.conversation_turn_count,
        }
        (target / _MANIFEST_NAME).write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _read_manifest(self, target: Path) -> _Manifest:
        try:
            payload = json.loads((target / _MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CheckpointError(f"corrupt checkpoint manifest in {target}: {exc}") from exc
        return _Manifest(
            name=str(payload["name"]),
            created_at=float(payload["created_at"]),
            kinds=[str(k) for k in payload.get("kinds", [])],
            repo_files=[
                RepoFileRecord(path=str(r["path"]), sha256=str(r["sha256"])) for r in payload.get("repo_files", [])
            ],
            env_var_count=int(payload.get("env_var_count", 0)),
            conversation_turn_count=int(payload.get("conversation_turn_count", 0)),
        )

    def _remove_tree(self, path: Path) -> None:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
