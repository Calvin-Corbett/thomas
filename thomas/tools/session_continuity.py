"""CAP-064: Local<->cloud session continuity via envelope + git-bundle handoff.

A task in progress on one host (``local``) can be moved to another host
(``cloud``) -- and back -- without losing context. Two artifacts travel
together:

- a **session envelope** -- a small, durable JSON record of *what the task is*:
  its id and objective, the still-pending steps, the working directory and the
  cwd-relative file refs it cares about, the *names* (never the values) of the
  environment variables it needs, and an opaque conversation/context reference;
- a **git bundle** -- a single-file, self-contained capture of the repository's
  commits and current HEAD tree, produced by ``git bundle create``. The bundle
  is what makes the destination working tree byte-for-byte identical to the
  source, with no network access to the origin remote.

The external edge -- the ``git`` binary -- sits behind the injectable
:class:`GitRunner` protocol. The real default, :class:`SubprocessGitRunner`,
shells out to ``git``; tests can inject a fake or (as the acceptance test does)
drive real temp repositories with no network. Time is injected too, so envelope
timestamps are deterministic.

Integrity is non-negotiable: the envelope carries a SHA-256 digest of the exact
bundle bytes. :meth:`ContinuityHandoff.resume` recomputes that digest *before*
touching git and refuses to unpack a bundle whose digest does not match -- so a
corrupted or tampered bundle is rejected outright, never silently
half-restored.

This module depends only on the standard library and the ``git`` binary (tools
layer rule: no imports from agent/server/cli).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DIGEST_ALGORITHM = "sha256"
_ENVELOPE_NAME = "session_envelope.json"
_BUNDLE_NAME = "session.bundle"
_READ_CHUNK = 1 << 20  # 1 MiB


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ContinuityError(Exception):
    """Base class for session-continuity failures."""


class GitCommandError(ContinuityError):
    """Raised when an underlying git invocation fails."""


class GitUnavailableError(ContinuityError):
    """Raised when the git binary cannot be located."""


class BundleIntegrityError(ContinuityError):
    """Raised when a bundle's digest does not match the envelope's -- resume aborts."""


class EnvelopeFormatError(ContinuityError):
    """Raised when an envelope payload is malformed or an unknown schema version."""


# ---------------------------------------------------------------------------
# Git adapter (injectable edge)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitResult:
    """Outcome of one git invocation."""

    returncode: int
    stdout: bytes
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


@runtime_checkable
class GitRunner(Protocol):
    """Injectable seam over the git binary.

    Implementations run a single git subcommand (``args`` excludes the leading
    ``git``) in ``cwd`` and return a :class:`GitResult`. The real default shells
    out; tests may substitute a fake.
    """

    def run(self, args: Sequence[str], cwd: Path | None = None) -> GitResult: ...


class SubprocessGitRunner:
    """Default :class:`GitRunner` that shells out to the ``git`` binary."""

    def __init__(self, git_executable: str = "git") -> None:
        self._git = git_executable

    def run(self, args: Sequence[str], cwd: Path | None = None) -> GitResult:
        cmd = [self._git, *args]
        try:
            proc = subprocess.run(  # noqa: S603 - args are fixed, not shell
                cmd,
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitUnavailableError(f"git executable not found: {self._git!r}") from exc
        return GitResult(
            returncode=proc.returncode,
            stdout=proc.stdout or b"",
            stderr=(proc.stderr or b"").decode("utf-8", errors="replace"),
        )


def _git_checked(git: GitRunner, args: Sequence[str], cwd: Path | None = None) -> GitResult:
    """Run git and raise :class:`GitCommandError` on a non-zero exit."""
    result = git.run(args, cwd)
    if not result.ok:
        detail = result.stderr.strip() or result.text().strip() or "unknown git error"
        raise GitCommandError(f"git {' '.join(args)} failed ({result.returncode}): {detail}")
    return result


# ---------------------------------------------------------------------------
# Session envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionEnvelope:
    """Durable, secret-free record of a task's resumable context.

    ``env_var_names`` holds only the *names* of required environment variables;
    secret values never enter the envelope. ``bundle_digest`` binds the envelope
    to the exact bytes of its companion git bundle.
    """

    task_id: str
    objective: str
    pending_steps: tuple[str, ...]
    cwd: str
    refs: tuple[str, ...]
    env_var_names: tuple[str, ...]
    context_ref: str
    source_host: str
    created_at: float
    bundle_digest: str
    bundle_algorithm: str = DIGEST_ALGORITHM
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "objective": self.objective,
            "pending_steps": list(self.pending_steps),
            "cwd": self.cwd,
            "refs": list(self.refs),
            "env_var_names": list(self.env_var_names),
            "context_ref": self.context_ref,
            "source_host": self.source_host,
            "created_at": self.created_at,
            "bundle_digest": self.bundle_digest,
            "bundle_algorithm": self.bundle_algorithm,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> SessionEnvelope:
        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            raise EnvelopeFormatError(f"unsupported envelope schema_version: {version!r}")
        try:
            return cls(
                task_id=str(payload["task_id"]),
                objective=str(payload["objective"]),
                pending_steps=tuple(str(s) for s in payload["pending_steps"]),  # type: ignore[union-attr]
                cwd=str(payload["cwd"]),
                refs=tuple(str(r) for r in payload["refs"]),  # type: ignore[union-attr]
                env_var_names=tuple(str(n) for n in payload["env_var_names"]),  # type: ignore[union-attr]
                context_ref=str(payload["context_ref"]),
                source_host=str(payload["source_host"]),
                created_at=float(payload["created_at"]),  # type: ignore[arg-type]
                bundle_digest=str(payload["bundle_digest"]),
                bundle_algorithm=str(payload.get("bundle_algorithm", DIGEST_ALGORITHM)),
                schema_version=SCHEMA_VERSION,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EnvelopeFormatError(f"malformed envelope payload: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> SessionEnvelope:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EnvelopeFormatError(f"invalid envelope JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise EnvelopeFormatError("envelope JSON must be an object")
        return cls.from_dict(payload)


# ---------------------------------------------------------------------------
# Handoff results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureResult:
    """Artifacts produced on the source host."""

    envelope: SessionEnvelope
    envelope_path: Path
    bundle_path: Path


@dataclass(frozen=True)
class ResumedSession:
    """Reconstructed task state on the destination host."""

    task_id: str
    objective: str
    pending_steps: tuple[str, ...]
    cwd: str
    refs: tuple[str, ...]
    env_var_names: tuple[str, ...]
    context_ref: str
    repo_root: Path
    head_commit: str


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------


def digest_file(path: Path, *, algorithm: str = DIGEST_ALGORITHM) -> str:
    """Streaming hex digest of a file's exact bytes."""
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _sorted_names(env: Mapping[str, str] | Iterable[str] | None) -> tuple[str, ...]:
    """Return sorted, de-duplicated variable *names* -- never values."""
    if env is None:
        return ()
    keys: Iterable[str]
    keys = env.keys() if isinstance(env, Mapping) else env
    return tuple(sorted({str(k) for k in keys}))


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


class ContinuityHandoff:
    """Capture and resume a task across hosts via envelope + git bundle.

    Args:
        git: Injectable git adapter; defaults to :class:`SubprocessGitRunner`.
        clock: Injectable time source (seconds); defaults to ``time.time``.
    """

    def __init__(
        self,
        *,
        git: GitRunner | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._git: GitRunner = git if git is not None else SubprocessGitRunner()
        self._clock = clock

    # -- capture (source host) --------------------------------------------

    def capture(
        self,
        *,
        repo_root: str | os.PathLike[str],
        out_dir: str | os.PathLike[str],
        task_id: str,
        objective: str,
        pending_steps: Sequence[str],
        source_host: str,
        cwd: str = ".",
        refs: Sequence[str] = (),
        env: Mapping[str, str] | Iterable[str] | None = None,
        context_ref: str = "",
    ) -> CaptureResult:
        """Produce a git bundle of ``repo_root`` and a matching session envelope.

        The bundle (``session.bundle``) and envelope (``session_envelope.json``)
        are written under ``out_dir``. Only environment-variable *names* are
        recorded from ``env`` -- values are never read into the envelope.
        """
        repo = Path(repo_root)
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)

        bundle_path = target / _BUNDLE_NAME
        self._create_bundle(repo, bundle_path)
        digest = digest_file(bundle_path)

        envelope = SessionEnvelope(
            task_id=task_id,
            objective=objective,
            pending_steps=tuple(str(s) for s in pending_steps),
            cwd=str(cwd),
            refs=tuple(str(r) for r in refs),
            env_var_names=_sorted_names(env),
            context_ref=str(context_ref),
            source_host=str(source_host),
            created_at=float(self._clock()),
            bundle_digest=digest,
        )
        envelope_path = target / _ENVELOPE_NAME
        envelope_path.write_text(envelope.to_json(), encoding="utf-8")

        logger.info(
            "captured session envelope for task %r (%d pending step(s), bundle %s=%s)",
            task_id,
            len(envelope.pending_steps),
            DIGEST_ALGORITHM,
            digest[:12],
        )
        return CaptureResult(
            envelope=envelope,
            envelope_path=envelope_path,
            bundle_path=bundle_path,
        )

    def _create_bundle(self, repo: Path, bundle_path: Path) -> None:
        if not (repo / ".git").exists():
            raise GitCommandError(f"not a git repository: {repo}")
        _git_checked(
            self._git,
            ["-C", str(repo), "bundle", "create", str(bundle_path), "--all"],
        )

    # -- resume (destination host) ----------------------------------------

    def resume(
        self,
        *,
        envelope: SessionEnvelope,
        bundle_path: str | os.PathLike[str],
        dest_root: str | os.PathLike[str],
    ) -> ResumedSession:
        """Verify + unpack a bundle on the destination host and rebuild task state.

        The bundle's digest is checked against the envelope *before* git is
        invoked; a mismatch raises :class:`BundleIntegrityError` and nothing is
        unpacked (no silent partial resume). On success the bundle is cloned
        into ``dest_root``, yielding a working tree identical to the source, and
        the pending task state is reconstructed from the envelope.
        """
        bundle = Path(bundle_path)
        if not bundle.is_file():
            raise BundleIntegrityError(f"bundle not found: {bundle}")

        actual = digest_file(bundle, algorithm=envelope.bundle_algorithm)
        if actual != envelope.bundle_digest:
            raise BundleIntegrityError(
                "bundle digest mismatch: envelope expected "
                f"{envelope.bundle_algorithm}={envelope.bundle_digest[:12]}... "
                f"but bundle is {actual[:12]}...; refusing to resume"
            )

        dest = Path(dest_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._verify_bundle(bundle)
        _git_checked(self._git, ["clone", str(bundle), str(dest)])
        head = self._head_commit(dest)

        logger.info(
            "resumed task %r into %s at HEAD %s",
            envelope.task_id,
            dest,
            head[:12],
        )
        return ResumedSession(
            task_id=envelope.task_id,
            objective=envelope.objective,
            pending_steps=envelope.pending_steps,
            cwd=envelope.cwd,
            refs=envelope.refs,
            env_var_names=envelope.env_var_names,
            context_ref=envelope.context_ref,
            repo_root=dest,
            head_commit=head,
        )

    def _verify_bundle(self, bundle: Path) -> None:
        """Ask git to self-verify the bundle; surfaces corruption git can detect."""
        result = self._git.run(["bundle", "verify", str(bundle)])
        if not result.ok:
            detail = result.stderr.strip() or result.text().strip() or "invalid bundle"
            raise BundleIntegrityError(f"git rejected bundle: {detail}")

    def _head_commit(self, repo: Path) -> str:
        return _git_checked(self._git, ["-C", str(repo), "rev-parse", "HEAD"]).text().strip()


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def load_envelope(path: str | os.PathLike[str]) -> SessionEnvelope:
    """Load and validate a serialized envelope from disk."""
    return SessionEnvelope.from_json(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class RepoState:
    """A committed snapshot identity for cross-host equality checks."""

    head_commit: str
    tree_hash: str
    commit_list: tuple[str, ...] = field(default_factory=tuple)


def repo_state(repo_root: str | os.PathLike[str], *, git: GitRunner | None = None) -> RepoState:
    """Capture a repository's HEAD commit, HEAD tree hash, and full commit list.

    Used to prove two hosts hold the same commits/tree after a handoff.
    """
    runner: GitRunner = git if git is not None else SubprocessGitRunner()
    repo = Path(repo_root)
    head = _git_checked(runner, ["-C", str(repo), "rev-parse", "HEAD"]).text().strip()
    tree = _git_checked(runner, ["-C", str(repo), "rev-parse", "HEAD^{tree}"]).text().strip()
    commits = _git_checked(runner, ["-C", str(repo), "rev-list", "--all"]).text().split()
    return RepoState(head_commit=head, tree_hash=tree, commit_list=tuple(commits))
