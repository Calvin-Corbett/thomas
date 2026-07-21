"""Automatic per-session git worktree lifecycle with safe cleanup.

Each *eligible* session gets exactly **one** git worktree, created on demand and
tracked durably in a small JSON state file. The mapping is idempotent: asking for
the same session id twice reuses the first worktree and never creates a second.
Ineligible sessions (per a caller-supplied predicate) get no worktree at all.

Cleanup is *safe* by construction. :meth:`SessionWorktreeManager.cleanup` removes
a session's worktree only when it is **clean** (``git status --porcelain`` empty)
or when ``force=True`` is explicitly passed. A dirty worktree is left on disk and
reported with a ``dirty`` signal so uncommitted work is never silently discarded.
:meth:`SessionWorktreeManager.cleanup_stale` sweeps worktrees whose sessions are
no longer active, applying the same clean/dirty guard to each one.

The module depends only on the standard library and shells out to ``git`` via
``subprocess`` (tools-layer rule: no imports from agent/server/cli). It operates
strictly on the repo and worktree paths it is given, so it is safe to drive
against a throwaway temp repository in tests.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

#: Environment variable that overrides the JSON state-file location.
STATE_ENV_VAR = "THOMAS_SESSION_WORKTREE_STATE"

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")

EligibilityPredicate = Callable[[str], bool]


class WorktreeError(RuntimeError):
    """A ``git worktree`` (or related git) command failed."""


@dataclass(frozen=True)
class SessionWorktree:
    """Durable record of one session's worktree."""

    session_id: str
    path: str
    branch: str
    created_at: str


@dataclass(frozen=True)
class EnsureOutcome:
    """Result of :meth:`SessionWorktreeManager.ensure`.

    ``status`` is one of ``"created"``, ``"reused"`` or ``"ineligible"``.
    ``worktree`` is ``None`` only for the ineligible case.
    """

    status: str
    worktree: SessionWorktree | None

    @property
    def created(self) -> bool:
        return self.status == "created"

    @property
    def eligible(self) -> bool:
        return self.status != "ineligible"


@dataclass(frozen=True)
class CleanupOutcome:
    """Result of a cleanup attempt for a single session.

    ``status`` is one of:

    * ``"removed"``  -- worktree existed, was clean (or forced), now gone.
    * ``"dirty"``    -- worktree had uncommitted changes and was **preserved**.
    * ``"missing"``  -- no worktree was tracked for this session.
    """

    session_id: str
    status: str
    path: str | None = None
    forced: bool = False

    @property
    def removed(self) -> bool:
        return self.status == "removed"

    @property
    def preserved_dirty(self) -> bool:
        return self.status == "dirty"


def _sanitize(session_id: str) -> str:
    slug = _SANITIZE_RE.sub("-", session_id).strip("-")
    return slug or "session"


class SessionWorktreeManager:
    """Create and safely clean one git worktree per eligible session.

    Parameters
    ----------
    repo_root:
        Path to the git repository these worktrees branch from.
    eligibility:
        Optional predicate ``session_id -> bool``. When it returns ``False`` the
        session gets no worktree. Defaults to "every session is eligible".
    state_path:
        Override for the JSON state file. Falls back to ``$THOMAS_SESSION_WORKTREE_STATE``
        and then to ``<repo_root>/.thomas/session_worktrees.json``.
    worktrees_root:
        Directory that holds the created worktrees. Defaults to a sibling of the
        repo (``<repo_root>-session-worktrees``) so the main working tree stays
        clean.
    branch_prefix:
        Prefix for the per-session branch name.
    """

    def __init__(
        self,
        repo_root: str | os.PathLike[str],
        *,
        eligibility: EligibilityPredicate | None = None,
        state_path: str | os.PathLike[str] | None = None,
        worktrees_root: str | os.PathLike[str] | None = None,
        branch_prefix: str = "session",
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._eligible: EligibilityPredicate = eligibility or (lambda _sid: True)
        self.branch_prefix = branch_prefix

        if worktrees_root is not None:
            self.worktrees_root = Path(worktrees_root).resolve()
        else:
            self.worktrees_root = self.repo_root.parent / f"{self.repo_root.name}-session-worktrees"

        self.state_path = self._resolve_state_path(state_path)
        self._state: dict[str, SessionWorktree] = self._load_state()

    # -- state persistence --------------------------------------------------

    def _resolve_state_path(self, override: str | os.PathLike[str] | None) -> Path:
        if override is not None:
            return Path(override).resolve()
        env = os.environ.get(STATE_ENV_VAR)
        if env:
            return Path(env).resolve()
        return self.repo_root / ".thomas" / "session_worktrees.json"

    def _load_state(self) -> dict[str, SessionWorktree]:
        if not self.state_path.exists():
            return {}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("session worktree state unreadable at %s: %s", self.state_path, exc)
            return {}
        out: dict[str, SessionWorktree] = {}
        for sid, rec in (raw.get("sessions") or {}).items():
            try:
                out[sid] = SessionWorktree(
                    session_id=sid,
                    path=rec["path"],
                    branch=rec["branch"],
                    created_at=rec.get("created_at", ""),
                )
            except (KeyError, TypeError):
                logger.warning("skipping malformed worktree record for session %s", sid)
        return out

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "sessions": {sid: asdict(wt) for sid, wt in self._state.items()}}
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # -- git helpers --------------------------------------------------------

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo_root),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise WorktreeError(
                f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout

    def _is_dirty(self, path: Path) -> bool:
        """True when the worktree has staged, unstaged, or untracked changes."""
        out = self._git("status", "--porcelain", cwd=path)
        return bool(out.strip())

    # -- public API ---------------------------------------------------------

    def get(self, session_id: str) -> SessionWorktree | None:
        """Return the tracked worktree for a session, or ``None``."""
        return self._state.get(session_id)

    def list_worktrees(self) -> dict[str, SessionWorktree]:
        """Return a copy of the session -> worktree mapping."""
        return dict(self._state)

    def ensure(self, session_id: str) -> EnsureOutcome:
        """Automatically create (or reuse) exactly one worktree for a session.

        Idempotent: the same ``session_id`` always maps to the same worktree.
        Ineligible sessions get none.
        """
        if not self._eligible(session_id):
            return EnsureOutcome(status="ineligible", worktree=None)

        existing = self._state.get(session_id)
        if existing is not None and Path(existing.path).exists():
            return EnsureOutcome(status="reused", worktree=existing)

        slug = _sanitize(session_id)
        branch = f"{self.branch_prefix}/{slug}"
        target = self.worktrees_root / slug

        # Reuse the on-disk worktree if a prior run left it (idempotent recovery).
        if existing is not None and not Path(existing.path).exists():
            logger.info("session %s worktree missing on disk; recreating", session_id)

        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        # ``-B`` resets/creates the branch so a leftover branch never blocks us.
        self._git("worktree", "add", "-B", branch, str(target), "HEAD")

        record = SessionWorktree(
            session_id=session_id,
            path=str(target.resolve()),
            branch=branch,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._state[session_id] = record
        self._save_state()
        return EnsureOutcome(status="created", worktree=record)

    def cleanup(self, session_id: str, *, force: bool = False) -> CleanupOutcome:
        """Safely remove a session's worktree.

        Removes the worktree only when it is clean or ``force=True``. A dirty
        worktree is preserved and reported with a ``dirty`` status so work is
        never silently discarded.
        """
        record = self._state.get(session_id)
        if record is None:
            return CleanupOutcome(session_id=session_id, status="missing")

        path = Path(record.path)
        if not path.exists():
            # Nothing on disk -- reconcile git's bookkeeping and drop the entry.
            self._prune_and_forget(session_id)
            return CleanupOutcome(session_id=session_id, status="removed", path=record.path)

        if not force and self._is_dirty(path):
            logger.info("session %s worktree dirty at %s; not removed", session_id, path)
            return CleanupOutcome(session_id=session_id, status="dirty", path=record.path)

        remove_args = ["worktree", "remove", str(path)]
        if force:
            remove_args.append("--force")
        self._git(*remove_args)
        self._state.pop(session_id, None)
        self._save_state()
        return CleanupOutcome(session_id=session_id, status="removed", path=record.path, forced=force)

    def cleanup_stale(self, active_session_ids: object, *, force: bool = False) -> list[CleanupOutcome]:
        """Clean worktrees whose sessions are no longer active.

        Applies the same clean/dirty safety as :meth:`cleanup` to every stale
        session (a session present in state but absent from ``active_session_ids``).
        """
        active = set(active_session_ids)
        stale = [sid for sid in self._state if sid not in active]
        return [self.cleanup(sid, force=force) for sid in stale]

    # -- internals ----------------------------------------------------------

    def _prune_and_forget(self, session_id: str) -> None:
        try:
            self._git("worktree", "prune")
        except WorktreeError as exc:
            logger.warning("worktree prune failed while forgetting %s: %s", session_id, exc)
        self._state.pop(session_id, None)
        self._save_state()
