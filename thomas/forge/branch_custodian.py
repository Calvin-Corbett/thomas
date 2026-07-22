"""Branch custodian -- the branch-sprawl detector and consolidator.

Thomas already had a *worktree* ledger and a debt alarm. Nothing counted
**branches**, so a repository could sit comfortably under the worktree ceiling
while 81 branches piled up unnoticed. The alarm was measuring the wrong number,
and the remedy it printed (``thomas consolidate``) was never implemented -- a
non-engineer following the instructions exactly would hit a dead end.

This module closes that loop. It answers three questions about every branch,
in the order that matters:

1. *Is anything here that trunk does not already have?*  -- classification
2. *What is the safe action?*                            -- planning
3. *Did it work?*                                        -- application + proof

Classification is deliberately conservative. A branch is only ever proposed for
deletion when its unique content is provably empty:

``CONTAINED``   no commits outside trunk -- deleting it cannot lose anything.
``SUPERSEDED``  commits outside trunk, but ``git diff trunk...branch`` is empty,
                so every change it carries already exists in trunk.
``UNIQUE_WORK`` carries content trunk does not have. NEVER auto-deleted; it is
                flagged for a real consolidation decision, with the exact file
                list so a human sees what is at stake.
``ACTIVE``      touched recently; left alone regardless of the above.
``TRUNK``       the trunk branch itself.

The git edge is injectable (``GitRunner``): the real default shells out, and
tests drive a hermetic fake, so the classification rules are provable without a
repository.
"""

from __future__ import annotations

import logging
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

# Placeholder recorded as a branch's "unique file" when git could not be read.
# Non-empty on purpose: it forces the branch to UNIQUE_WORK, which is never
# auto-deleted, and it tells a human exactly why.
_UNREADABLE = "<git-query-failed: treated as unique work>"

DEFAULT_TRUNK = "dev"
DEFAULT_ACTIVE_DAYS = 3
DEFAULT_BRANCH_CEILING = 10
_GIT_TIMEOUT_SECONDS = 120

# Faults a git invocation can realistically raise. A deliberately wide but
# concrete tuple -- never a bare ``except Exception``.
_GIT_FAULTS = (
    OSError,
    ValueError,
    TypeError,
    LookupError,
    RuntimeError,
    UnicodeDecodeError,
)


class BranchStatus(str, Enum):
    """How a branch relates to trunk."""

    TRUNK = "trunk"
    ACTIVE = "active"
    CONTAINED = "contained"
    SUPERSEDED = "superseded"
    UNIQUE_WORK = "unique_work"


class Action(str, Enum):
    """What the custodian proposes to do with a branch."""

    KEEP = "keep"
    DELETE = "delete"
    ARCHIVE_AND_DELETE = "archive_and_delete"
    FLAG_FOR_CONSOLIDATION = "flag_for_consolidation"


# Statuses that may never be deleted automatically, whatever the ceiling says.
_NEVER_AUTO_DELETE = frozenset({BranchStatus.TRUNK, BranchStatus.ACTIVE, BranchStatus.UNIQUE_WORK})


class BranchCustodianError(RuntimeError):
    """Raised when the custodian cannot complete a requested operation."""


@runtime_checkable
class GitRunner(Protocol):
    """The injectable git edge."""

    def __call__(self, args: Sequence[str]) -> str:  # pragma: no cover - protocol
        """Run a git command and return stdout. Raise on failure."""


@dataclass(frozen=True)
class BranchRow:
    """One branch, classified."""

    name: str
    sha: str
    unique_commits: int
    unique_files: tuple[str, ...]
    age_days: int
    status: BranchStatus

    @property
    def has_unique_content(self) -> bool:
        return bool(self.unique_files)

    @property
    def action(self) -> Action:
        if self.status in (BranchStatus.TRUNK, BranchStatus.ACTIVE):
            return Action.KEEP
        if self.status is BranchStatus.CONTAINED:
            return Action.DELETE
        if self.status is BranchStatus.SUPERSEDED:
            return Action.ARCHIVE_AND_DELETE
        return Action.FLAG_FOR_CONSOLIDATION

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "sha": self.sha,
            "unique_commits": self.unique_commits,
            "unique_files": list(self.unique_files),
            "age_days": self.age_days,
            "status": self.status.value,
            "action": self.action.value,
        }


@dataclass
class SprawlReport:
    """The ledger plus the circuit-breaker verdict."""

    trunk: str
    branches: tuple[BranchRow, ...]
    ceiling: int

    @property
    def total(self) -> int:
        return len(self.branches)

    def by_status(self, status: BranchStatus) -> tuple[BranchRow, ...]:
        return tuple(b for b in self.branches if b.status is status)

    def by_action(self, action: Action) -> tuple[BranchRow, ...]:
        return tuple(b for b in self.branches if b.action is action)

    @property
    def reclaimable(self) -> tuple[BranchRow, ...]:
        """Branches the custodian can retire without a human decision."""
        return tuple(b for b in self.branches if b.action in (Action.DELETE, Action.ARCHIVE_AND_DELETE))

    @property
    def needs_decision(self) -> tuple[BranchRow, ...]:
        return self.by_action(Action.FLAG_FOR_CONSOLIDATION)

    @property
    def over_ceiling(self) -> bool:
        """True when sprawl has crossed the ceiling -- trips the circuit breaker."""
        return self.total > self.ceiling

    def summary(self) -> str:
        """A plain-language line for someone who does not read git."""
        if not self.over_ceiling and not self.reclaimable and not self.needs_decision:
            return f"{self.total} branches -- tidy, nothing to do."
        parts = [f"{self.total} branches (ceiling {self.ceiling})"]
        if self.reclaimable:
            parts.append(f"{len(self.reclaimable)} safe to retire automatically")
        if self.needs_decision:
            parts.append(f"{len(self.needs_decision)} carry unique work and need your call")
        return "; ".join(parts) + "."

    def as_dict(self) -> dict[str, object]:
        return {
            "trunk": self.trunk,
            "total": self.total,
            "ceiling": self.ceiling,
            "over_ceiling": self.over_ceiling,
            "reclaimable": len(self.reclaimable),
            "needs_decision": len(self.needs_decision),
            "branches": [b.as_dict() for b in self.branches],
            "summary": self.summary(),
        }


def subprocess_git_runner(repo_root: str) -> GitRunner:
    """The real git edge: shells out to ``git`` in ``repo_root``.

    LIVE LANE -- requires a git binary and a real repository. Tests inject a
    fake instead, so every classification rule below is provable offline.
    """
    import subprocess

    def _run(args: Sequence[str]) -> str:
        cmd = ["git", "-C", repo_root, *args]
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                cmd,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("git failed: %s (%s)", shlex.join(cmd), exc)
            raise BranchCustodianError(f"git invocation failed: {exc}") from exc
        if proc.returncode != 0:
            raise BranchCustodianError(f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()}")
        return proc.stdout

    return _run


def _lines(raw: str) -> list[str]:
    return [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]


def classify_branch(
    name: str,
    *,
    sha: str,
    unique_commits: int,
    unique_files: Sequence[str],
    age_days: int,
    trunk: str,
    active_days: int,
) -> BranchStatus:
    """Decide a branch's status. Pure -- the heart of the custodian."""
    if name == trunk:
        return BranchStatus.TRUNK
    if age_days <= active_days:
        return BranchStatus.ACTIVE
    if unique_commits <= 0:
        return BranchStatus.CONTAINED
    if not unique_files:
        return BranchStatus.SUPERSEDED
    return BranchStatus.UNIQUE_WORK


def survey(
    git: GitRunner,
    *,
    trunk: str = DEFAULT_TRUNK,
    active_days: int = DEFAULT_ACTIVE_DAYS,
    ceiling: int = DEFAULT_BRANCH_CEILING,
    now_days: Callable[[], int] | None = None,
    namespace: str = "refs/heads",
) -> SprawlReport:
    """Enumerate and classify every branch in ``namespace`` against ``trunk``.

    ``namespace`` lets the same rules audit local branches (the default),
    ``refs/remotes`` (what is still on the server), or ``refs/archive``.
    """
    raw = git(["for-each-ref", "--format=%(refname:short)%09%(objectname)%09%(committerdate:unix)", namespace])
    today = now_days() if now_days is not None else _today_unix_days(git)

    rows: list[BranchRow] = []
    for line in _lines(raw):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, sha, ts_raw = parts[0], parts[1], parts[2]
        try:
            age_days = max(0, today - int(ts_raw) // 86400)
        except (TypeError, ValueError):
            age_days = 0

        unique_commits = 0
        unique_files: tuple[str, ...] = ()
        if name != trunk:
            unique_commits, commits_ok = _count_unique_commits(git, trunk, name)
            files_ok = True
            if unique_commits > 0:
                unique_files, files_ok = _unique_files(git, trunk, name)
            if not (commits_ok and files_ok):
                # Fail-safe: a branch we could not fully read is never
                # classified as deletable. Forcing non-empty unique_files
                # routes it to UNIQUE_WORK, which is only ever flagged.
                unique_files = (_UNREADABLE,)

        rows.append(
            BranchRow(
                name=name,
                sha=sha,
                unique_commits=unique_commits,
                unique_files=unique_files,
                age_days=age_days,
                status=classify_branch(
                    name,
                    sha=sha,
                    unique_commits=unique_commits,
                    unique_files=unique_files,
                    age_days=age_days,
                    trunk=trunk,
                    active_days=active_days,
                ),
            )
        )

    rows.sort(key=lambda r: (r.status.value, -len(r.unique_files), r.name))
    return SprawlReport(trunk=trunk, branches=tuple(rows), ceiling=ceiling)


def _today_unix_days(git: GitRunner) -> int:
    """Derive 'today' from git itself so the module needs no wall clock."""
    try:
        raw = git(["log", "-1", "--format=%ct", "HEAD"]).strip()
        return int(raw) // 86400
    except (*_GIT_FAULTS, BranchCustodianError):
        log.debug("could not read HEAD timestamp; treating all branches as aged")
        return 0


def _count_unique_commits(git: GitRunner, trunk: str, branch: str) -> tuple[int, bool]:
    """Return (count, ok). ``ok=False`` means the answer is not trustworthy."""
    try:
        return int(git(["rev-list", "--count", f"{trunk}..{branch}"]).strip() or 0), True
    except (*_GIT_FAULTS, BranchCustodianError):
        log.warning("could not count commits for %s; treating as unique work", branch)
        return 1, False


def _unique_files(git: GitRunner, trunk: str, branch: str) -> tuple[tuple[str, ...], bool]:
    """Files this branch changes relative to its merge-base with trunk.

    Empty means every change it carries already exists in trunk -- the only
    evidence strong enough to justify retiring a diverged branch. Returns
    (files, ok); ``ok=False`` means the diff could not be read.
    """
    try:
        raw = git(["diff", "--name-only", f"{trunk}...{branch}"])
    except (*_GIT_FAULTS, BranchCustodianError):
        log.warning("could not diff %s against %s; treating as unique work", branch, trunk)
        return (_UNREADABLE,), False
    return tuple(_lines(raw)), True


@dataclass
class ConsolidationResult:
    """What actually happened when a plan was applied."""

    deleted: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "deleted": list(self.deleted),
            "archived": list(self.archived),
            "flagged": list(self.flagged),
            "kept": list(self.kept),
            "errors": list(self.errors),
            "ok": self.ok,
        }


def consolidate(
    git: GitRunner,
    report: SprawlReport,
    *,
    apply: bool = False,
    archive_namespace: str = "refs/archive",
) -> ConsolidationResult:
    """Execute (or, by default, rehearse) the report's proposed actions.

    ``apply=False`` is a dry run: nothing is touched and the result describes
    what *would* happen. Branches carrying unique work are never deleted in
    either mode -- they are only flagged.
    """
    result = ConsolidationResult()

    for row in report.branches:
        action = row.action

        if action is Action.KEEP:
            result.kept.append(row.name)
            continue

        if action is Action.FLAG_FOR_CONSOLIDATION:
            result.flagged.append(row.name)
            continue

        if row.status in _NEVER_AUTO_DELETE:  # defence in depth
            result.kept.append(row.name)
            continue

        if not apply:
            if action is Action.ARCHIVE_AND_DELETE:
                result.archived.append(row.name)
            result.deleted.append(row.name)
            continue

        try:
            if action is Action.ARCHIVE_AND_DELETE:
                git(["update-ref", f"{archive_namespace}/{row.name}", row.sha])
                result.archived.append(row.name)
            git(["branch", "-D", row.name])
            result.deleted.append(row.name)
        except (*_GIT_FAULTS, BranchCustodianError) as exc:
            log.warning("could not retire %s: %s", row.name, exc)
            result.errors.append(f"{row.name}: {exc}")

    return result
