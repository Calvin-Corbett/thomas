#!/usr/bin/env python3
"""The branch sweep: an expired or long-unclaimed local branch stops sitting
around forever -- it gets archived, recorded, and deleted.

WHY STANDALONE, NOT A ``thomas/forge/branch_custodian.py`` EXTENSION: the
plan (``docs/superpowers/plans/2026-08-27-branch-equilibrium.md``, Task 2)
asked for exactly this check first. ``thomas/forge/branch_custodian.py`` is
NOT a pinned/protected file -- it appears in neither
``agent_safety.toml[protected]`` nor ``[runtime_protection]`` nor
``enforcement_scripts``, and no hash for it is recorded in
``scripts/forge/gates/enforcement_manifest.json`` (checked directly against
the committed manifest and the toml, both grepped clean of the name). So
extending it was technically available. It was not the choice made here: the
custodian is wired into a LIVE path (``thomas/cli/consolidate_cmd.py``'s
``thomas consolidate`` command and ``thomas/server/consolidation_maintenance.py``'s
background maintenance loop) that already deletes branches under its own
existing rules. Bolting a second, unrelated deletion rule (claim-expiry, a
completely different question from "does this branch's content already
exist in trunk") onto that live surface widens its blast radius for a
mechanism this task needs to prove out with fixture-only tests first. A
standalone script has the same safety properties (dry-run default, archive-
before-delete, fail-closed on unreadable state) with zero risk to the
already-live consolidation path. The custodian can adopt this sweep's rule
later via a tap item once the claim registry has real data in it -- see
``plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/status.md``.

WHAT THIS DOES: for every LOCAL branch except ``dev``/``main`` (trunk -- see
``TRUNK_BRANCHES``), the branch is eligible for archive-and-delete when
EITHER:
  * it has a claim (``branch_claims.py``) and that claim is EXPIRED, or
  * it has NO claim at all, and more than ``GRACE_DAYS`` (7) days have
    passed since the branch was CREATED (not since it was last touched --
    branch creation time is read from the branch's own reflog, the oldest
    entry). A branch with an absent claim inside its 7-day grace window is
    left alone -- someone may still be about to claim it. A branch whose
    creation time cannot be determined at all (no reflog, e.g. created by a
    bare ``update-ref`` with reflogs disabled) is NEVER treated as beyond
    grace -- unknown creation time means the grace period has, by
    definition, not been proven to have elapsed. This is fail-closed for
    destruction: an unprovable "old enough" is treated as "not old enough",
    never the reverse.

ARCHIVE-THEN-DELETE, VERIFIED, CREATE-ONLY (fix round 1, CRIT-1): a branch
selected for deletion is never deleted un-archived, AND the archive write
itself can never silently clobber a prior archive. The sequence is: write
``refs/archive/branch/<name>`` with a CREATE-ONLY ``update-ref`` (the
three-argument form, ``update-ref <ref> <new-sha> <old-sha>`` with the
all-zeros old-sha -- git's documented "this ref must not already exist"
assertion; verified empirically: a second create-only write to the same ref
name exits 128 with "reference already exists" and leaves the first archive
untouched, never overwritten), VERIFY that ref actually resolves to that
exact sha (``git rev-parse``, not just a successful ``update-ref`` exit
code), record a graveyard branch-death (``scripts/forge/graveyard.py``, so
``dead_ref_gate.py`` refuses the name coming back on a push), and only THEN
delete the local branch (``git branch -D``). A COLLISION -- a prior archive
ref already sitting at that exact name, e.g. from an earlier sweep of a
branch that was later re-created with the same name -- is reported as a
per-branch error and that branch is left un-deleted; the sweep continues to
the remaining branches and exits 1. Before this fix, a plain (non-create-
only) ``update-ref`` silently overwrote a colliding archive, and the only
verify step checked the NEW sha resolved (which it always did) -- the
earlier archive's sole ref anchor was lost with no error and no signal,
making its objects GC-eligible. If the verify step does not match, or the
graveyard write raises, the branch is also left un-deleted -- the archive
ref may already exist in that case, which is a safe partial state (an extra
verified archive ref costs nothing); a deleted-but-unarchived branch would
not be.

FAIL-CLOSED ON UNREADABLE STATE (the destruction half of the plan's
asymmetry -- see ``branch_claim_gate.py``'s docstring for the surfacing
half): if the claims registry is UNREADABLE -- including simply ABSENT,
unlike the gate's leniency for that exact condition -- or the graveyard is
unreadable (malformed; an absent graveyard is legitimately empty and does
not block), this sweep refuses to delete or archive ANYTHING, in both
dry-run and ``--apply`` mode, and says so loudly. Destruction needs positive
proof a branch truly has no claim; "the registry was never set up on this
machine" is not that proof, so it is treated as evidence withheld, not
evidence of absence.

DRY-RUN BY DEFAULT: ``--apply`` is required to actually mutate anything.
Without it, this prints exactly what WOULD happen and touches nothing.

CLI: ``python scripts/forge/branch_sweep.py [--repo-root ...] [--apply] [--json]``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.forge import branch_claims, graveyard  # noqa: E402

ROOT = _REPO_ROOT

GRACE_DAYS = 7
TRUNK_BRANCHES = frozenset({"dev", "main"})
_GIT_TIMEOUT_SECONDS = 120
_ZERO_SHA = "0" * 40
# Matches the reflog-selector suffix `%gd` renders under `--date=unix`, e.g.
# `some-branch@{1787874642}` -- see `_branch_created_at`.
_REFLOG_ENTRY_TIME_RE = re.compile(r"@\{(\d+)\}\s*$")

# Faults a git invocation can realistically raise -- mirrors
# thomas/forge/branch_custodian.py's identical tuple, deliberately wide but
# concrete, never a bare `except Exception`.
_GIT_FAULTS = (
    OSError,
    ValueError,
    TypeError,
    LookupError,
    RuntimeError,
    UnicodeDecodeError,
    subprocess.SubprocessError,
)


@runtime_checkable
class GitRunner(Protocol):
    """The injectable git edge -- same shape as branch_custodian.py's."""

    def __call__(self, args: Sequence[str]) -> str:  # pragma: no cover - protocol
        """Run a git command and return stdout. Raise on failure."""


def subprocess_git_runner(repo_root: Path) -> GitRunner:
    """The real git edge: shells out to ``git`` in ``repo_root``. Tests
    inject a fake instead, so the planning rules are provable offline."""

    def _run(args: Sequence[str]) -> str:
        cmd = ["git", "-C", str(repo_root), *args]
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                cmd,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"git invocation failed: {' '.join(args)}: {exc}") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()}")
        return proc.stdout

    return _run


def _lines(raw: str) -> list[str]:
    return [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]


def _local_branches(git: GitRunner) -> list[tuple[str, str]]:
    """Every local branch as (name, tip sha), from ``for-each-ref``."""
    raw = git(["for-each-ref", "--format=%(refname:short)%09%(objectname)", "refs/heads"])
    out: list[tuple[str, str]] = []
    for line in _lines(raw):
        parts = line.split("\t")
        if len(parts) == 2:
            out.append((parts[0], parts[1]))
    return out


def _branch_created_at(git: GitRunner, branch: str) -> int | None:
    """The branch's creation time (unix seconds), from the OLDEST entry in
    its own reflog -- ``git log -g`` walks a ref's reflog newest-first, so
    the last line of its output is the branch's earliest recorded event.

    FIX ROUND 1 (CRIT-2): this must read the reflog ENTRY's own timestamp
    (when the ref was updated), never ``%ct`` (the committer date of the
    commit that entry happens to point at) -- those two dates are only the
    same when a branch is cut from its tip commit the instant that commit
    was made. Cutting a branch today from a commit made weeks ago (the
    common case) previously read as a weeks-old branch and skipped its grace
    window entirely. ``%gd`` is git's reflog-selector placeholder; under
    ``--date=unix`` it renders as ``<shortname>@{<unix-timestamp>}`` using
    the reflog entry's actual date instead of the ordinal ``@{0}`` form --
    verified empirically (a branch cut today from a 30-day-old commit:
    ``%ct`` on that entry reads the 30-day-old commit time; ``%gd`` under
    ``--date=unix`` reads today, matching ``date +%s`` at creation time to
    within the test's own execution window).

    Returns ``None`` if the reflog is empty or unreadable (no reflog, e.g.
    disabled, or a ref created without one), or if the oldest line's
    selector cannot be parsed -- callers must treat that as "creation time
    unknown", never as "recently created" or "long ago"."""
    try:
        raw = git(["log", "-g", "--date=unix", "--format=%gd", f"refs/heads/{branch}"])
    except _GIT_FAULTS:
        return None
    entries = _lines(raw)
    if not entries:
        return None
    match = _REFLOG_ENTRY_TIME_RE.search(entries[-1])
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


@dataclass(frozen=True)
class SweepDecision:
    """One local branch's verdict."""

    branch: str
    sha: str
    reason: str
    delete: bool

    def as_dict(self) -> dict[str, Any]:
        return {"branch": self.branch, "sha": self.sha, "reason": self.reason, "delete": self.delete}


def plan_sweep(
    git: GitRunner,
    claims: branch_claims.Claims,
    *,
    today: dt.date,
    grace_days: int = GRACE_DAYS,
) -> tuple[SweepDecision, ...]:
    """Pure planning: decide every local branch's fate. No side effects --
    the heart of the sweep, provable without touching a real repository."""
    decisions: list[SweepDecision] = []
    for name, sha in _local_branches(git):
        if name in TRUNK_BRANCHES:
            decisions.append(SweepDecision(name, sha, "trunk", False))
            continue

        expired = claims.is_expired(name, today)
        if expired is False:
            decisions.append(SweepDecision(name, sha, "live_claim", False))
            continue
        if expired is True:
            decisions.append(SweepDecision(name, sha, "expired_claim", True))
            continue

        # expired is None -> no claim was ever recorded for this branch.
        created_at = _branch_created_at(git, name)
        if created_at is None:
            decisions.append(SweepDecision(name, sha, "unclaimed_creation_time_unknown", False))
            continue
        created_date = dt.datetime.fromtimestamp(created_at, tz=dt.timezone.utc).date()
        age_days = (today - created_date).days
        if age_days > grace_days:
            decisions.append(SweepDecision(name, sha, "unclaimed_beyond_grace", True))
        else:
            decisions.append(SweepDecision(name, sha, "unclaimed_within_grace", False))

    return tuple(decisions)


@dataclass
class SweepReport:
    """What the sweep found, and -- in ``--apply`` mode -- what it did."""

    decisions: tuple[SweepDecision, ...]
    applied: bool
    archived: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    graveyard_records_written: int = 0
    errors: list[str] = field(default_factory=list)
    refused: bool = False
    refused_reason: str = ""

    @property
    def to_delete(self) -> tuple[SweepDecision, ...]:
        return tuple(d for d in self.decisions if d.delete)

    @property
    def ok(self) -> bool:
        return not self.refused and not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "refused": self.refused,
            "refused_reason": self.refused_reason,
            "total_branches": len(self.decisions),
            "planned_deletions": len(self.to_delete),
            "archived": list(self.archived),
            "deleted": list(self.deleted),
            "graveyard_records_written": self.graveyard_records_written,
            "errors": list(self.errors),
            "ok": self.ok,
            "decisions": [d.as_dict() for d in self.decisions],
        }


def _refused(decisions_applied: bool, reason: str) -> SweepReport:
    return SweepReport(decisions=(), applied=decisions_applied, refused=True, refused_reason=reason)


def run_sweep(
    repo_root: Path,
    git: GitRunner | None = None,
    *,
    apply: bool = False,
    now: Callable[[], float] | None = None,
    archive_namespace: str = "refs/archive/branch",
) -> SweepReport:
    """Plan (and, with ``apply=True``, execute) one sweep pass.

    Refuses to plan at all -- not just to apply -- when either registry is
    unreadable, so a dry-run report can never claim branches are "safe to
    delete" based on state the sweep could not actually verify. See the
    module docstring's "FAIL-CLOSED ON UNREADABLE STATE".
    """
    git = git or subprocess_git_runner(repo_root)
    now_unix = (now or time.time)()
    today = dt.datetime.fromtimestamp(now_unix, tz=dt.timezone.utc).date()

    claims_path = branch_claims.path(repo_root)
    if not claims_path.exists():
        return _refused(
            apply,
            f"branch claims registry {claims_path} does not exist -- refusing to delete or archive anything "
            "(unreadable registry, fail-closed for destruction)",
        )
    try:
        claims = branch_claims.load(repo_root)
    except SystemExit as exc:
        return _refused(
            apply,
            f"branch claims registry is unreadable ({exc}) -- refusing to delete or archive anything",
        )

    try:
        graveyard.load(repo_root)
    except SystemExit as exc:
        return _refused(
            apply,
            f"graveyard is unreadable ({exc}) -- refusing to delete or archive anything",
        )

    decisions = plan_sweep(git, claims, today=today)
    report = SweepReport(decisions=decisions, applied=apply)

    if not apply:
        return report

    for decision in decisions:
        if not decision.delete:
            continue
        archive_ref = f"{archive_namespace}/{decision.branch}"

        # CREATE-ONLY write (CRIT-1 fix): the all-zeros old-sha asserts the
        # ref does not already exist. A collision (a prior archive still
        # sitting at this exact name, e.g. this same branch name was swept,
        # deleted, re-created, and is now being swept again) raises here,
        # caught below and reported per-branch -- never silently overwritten.
        try:
            git(["update-ref", archive_ref, decision.sha, _ZERO_SHA])
        except _GIT_FAULTS as exc:
            report.errors.append(
                f"{decision.branch}: could not create archive ref {archive_ref} -- most likely a COLLISION "
                f"with an existing archive ref from a prior sweep -- refusing to overwrite it, branch left "
                f"un-deleted: {exc}"
            )
            continue

        try:
            resolved = git(["rev-parse", archive_ref]).strip()
            if resolved != decision.sha:
                report.errors.append(
                    f"{decision.branch}: archive ref {archive_ref} did not resolve to {decision.sha} "
                    f"(got {resolved!r}) -- refusing to delete un-verified"
                )
                continue
            report.archived.append(decision.branch)

            graveyard.record_death(
                repo_root,
                "branch",
                decision.branch,
                decision.sha,
                reason=f"branch-sweep: {decision.reason}",
                by="branch-sweep",
            )
            report.graveyard_records_written += 1

            git(["branch", "-D", decision.branch])
            report.deleted.append(decision.branch)
        except (*_GIT_FAULTS, SystemExit) as exc:
            report.errors.append(f"{decision.branch}: {exc}")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(report: SweepReport) -> str:
    lines = [f"Branch sweep ({'apply' if report.applied else 'dry-run'}):"]
    if report.refused:
        lines.append(f"REFUSED -- {report.refused_reason}")
        return "\n".join(lines)

    lines.append(f"  {len(report.decisions)} local branch(es) examined, {len(report.to_delete)} planned for removal.")
    for decision in report.to_delete:
        lines.append(f"  - {decision.branch} ({decision.reason})")
    if report.applied:
        lines.append(
            f"  archived={len(report.archived)} deleted={len(report.deleted)} "
            f"graveyard_records_written={report.graveyard_records_written} errors={len(report.errors)}"
        )
        for err in report.errors:
            lines.append(f"  ERROR: {err}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT), help="Repository root path.")
    parser.add_argument("--apply", action="store_true", help="Actually archive+delete. Default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report = run_sweep(repo_root, apply=args.apply)

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_text(report))

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
