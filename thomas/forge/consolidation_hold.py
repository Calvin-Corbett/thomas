"""Consolidation holds -- the circuit breaker for branch sprawl.

Detecting sprawl is not enough. The failure this prevents is behavioural: an
agent arrives with no context, sees nothing wrong, and creates branch 82. By the
time anyone notices, work is stacked three generations deep on branches nobody
is tracking.

A *hold* is a durable, machine-readable "this repository is under consolidation"
marker. While one is active:

* :func:`guard_new_branch` refuses new branch creation and names the remedy --
  *if something calls it*.
* the trunk and an explicit allowlist stay usable, so consolidation work itself
  is never blocked by the hold it is trying to clear.

Holds are placed and lifted automatically by :func:`audit`, which is the piece
meant to run in the background on a schedule (wired into the live server via
``thomas/server/consolidation_maintenance.py``, every
``THOMAS_CONSOLIDATION_AUDIT_INTERVAL_S`` seconds). Nobody has to remember to
run the audit itself.

**THE GAP AN ADVERSARIAL REVIEW FOUND (branch-equilibrium plan, phase 2 Task 3
fix round 1, 2026-08-27):** the audit runs, and this repository's own
``runtime/logs/server_stderr.log`` proves it correctly detected 63 branches
over a ceiling of 10 and held for two straight days. But :func:`guard_new_branch`
-- the only function in this module that can actually refuse a branch -- has
**zero callers anywhere in this codebase, and never had one in this
repository's history** (``git log --all -S guard_new_branch``). The hold gets
placed, gets logged, gets released -- and never once stands between anyone and
a new branch, because nothing at the point a branch is actually created ever
asks it. This is this program's own documented "finished code with no caller"
shape, discovered in its own detection-and-consolidation mechanism.

The real, currently-enforcing mechanism is
``scripts/forge/gates/branch_claim_gate.py`` (branch-equilibrium plan, Task 2):
it sits in the pre-push hook path, which git itself invokes on every push --
no voluntary caller is needed the way this module's circuit breaker needs one.
That structural difference -- a hook git calls unconditionally, versus a
function that a human has to remember to wire into an enforcement point -- is
why Task 2's gate is built to stop sprawl and this module's hold, as shipped, did not.

Design rule: a hold must never be able to wedge the repository. It is advisory
state in one JSON file, it always names how to clear it (see
:meth:`Hold.message`, which now says plainly that this hold is not currently
consulted at branch creation), and :func:`release_hold` is unconditional.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from thomas.forge.branch_custodian import (
    DEFAULT_BRANCH_CEILING,
    DEFAULT_TRUNK,
    GitRunner,
    SprawlReport,
    survey,
)

log = logging.getLogger(__name__)

HOLD_ENV = "THOMAS_CONSOLIDATION_HOLD_FILE"
_DEFAULT_HOLD_REL = Path("runtime") / "consolidation_hold.json"
_REMEDY = "run `thomas consolidate` to retire what is safe, then decide on the rest"

_STORE_FAULTS = (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError)


@dataclass(frozen=True)
class Hold:
    """An active consolidation hold."""

    reason: str
    branch_count: int
    ceiling: int
    needs_decision: int
    placed_at: str
    allow: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "branch_count": self.branch_count,
            "ceiling": self.ceiling,
            "needs_decision": self.needs_decision,
            "placed_at": self.placed_at,
            "allow": list(self.allow),
            "remedy": _REMEDY,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Hold:
        return cls(
            reason=str(raw.get("reason", "")),
            branch_count=int(raw.get("branch_count", 0)),
            ceiling=int(raw.get("ceiling", 0)),
            needs_decision=int(raw.get("needs_decision", 0)),
            placed_at=str(raw.get("placed_at", "")),
            allow=tuple(str(a) for a in raw.get("allow", ())),
        )

    def message(self) -> str:
        """The hold's human-readable status line.

        FIX ROUND 1 (2026-08-27, adversarial review IMP-2): this used to say
        "To proceed, {remedy}" -- worded as if a new branch push was actually
        blocked pending that remedy. It never was: ``guard_new_branch`` (the
        only function that reads this hold to refuse a branch) has zero
        callers in this codebase. The message now states what is true --
        this hold is recorded and visible, not enforced at branch creation --
        and names the mechanism that actually is: ``branch_claim_gate.py``.
        """
        return (
            f"Repository is under consolidation: {self.reason} "
            f"({self.branch_count} branches, ceiling {self.ceiling}; "
            f"{self.needs_decision} need a decision). This hold is recorded, "
            f"but nothing in this codebase currently consults it at branch "
            f"creation -- it does not, by itself, block a new branch. "
            f"Push-time enforcement is scripts/forge/gates/branch_claim_gate.py "
            f"(CI today; local pre-push wiring rides the prepared tap, "
            f"PRAXIS-PHASE14-BREAKGLASS batch.md section (k)). "
            f"To retire what is already safe, {_REMEDY}."
        )


@dataclass(frozen=True)
class Decision:
    """The circuit breaker's verdict on an action."""

    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # lets callers write `if guard_new_branch(...)`
        return self.allowed


def hold_path(repo_root: Path | str = ".") -> Path:
    override = str(os.environ.get(HOLD_ENV, "") or "").strip()
    if override:
        return Path(override)
    return Path(repo_root) / _DEFAULT_HOLD_REL


def active_hold(repo_root: Path | str = ".") -> Hold | None:
    """Return the active hold, or ``None``. Never raises."""
    path = hold_path(repo_root)
    try:
        if not path.exists():
            return None
        return Hold.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except _STORE_FAULTS as exc:
        log.warning("unreadable consolidation hold at %s: %s", path, exc)
        return None


def place_hold(
    repo_root: Path | str = ".",
    *,
    reason: str,
    branch_count: int,
    ceiling: int,
    needs_decision: int = 0,
    allow: Sequence[str] = (),
    now: str = "",
) -> Hold:
    """Place (or refresh) the hold. Idempotent."""
    held = Hold(
        reason=reason,
        branch_count=branch_count,
        ceiling=ceiling,
        needs_decision=needs_decision,
        placed_at=now,
        allow=tuple(allow),
    )
    path = hold_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(held.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    log.info("consolidation hold placed: %s", reason)
    return held


def release_hold(repo_root: Path | str = ".") -> bool:
    """Lift the hold. Unconditional -- a hold can never wedge the repo."""
    path = hold_path(repo_root)
    try:
        if path.exists():
            path.unlink()
            log.info("consolidation hold released")
            return True
    except _STORE_FAULTS as exc:
        log.warning("could not release consolidation hold: %s", exc)
    return False


def guard_new_branch(
    name: str,
    repo_root: Path | str = ".",
    *,
    trunk: str = DEFAULT_TRUNK,
) -> Decision:
    """The circuit breaker: may a new branch called ``name`` be created?

    Trunk and the hold's allowlist always pass, so the work of clearing a hold
    is never blocked by that hold.
    """
    held = active_hold(repo_root)
    if held is None:
        return Decision(True)
    if name == trunk or name in held.allow:
        return Decision(True, "exempt from the active consolidation hold")
    return Decision(False, held.message())


@dataclass
class AuditResult:
    """What a background audit observed and did."""

    report: SprawlReport
    hold_placed: bool = False
    hold_released: bool = False
    hold: Hold | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def action(self) -> str:
        if self.hold_placed:
            return "placed"
        if self.hold_released:
            return "released"
        return "none"

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "hold": self.hold.as_dict() if self.hold else None,
            "summary": self.report.summary(),
            "over_ceiling": self.report.over_ceiling,
            "notes": list(self.notes),
        }


def audit(
    git: GitRunner,
    repo_root: Path | str = ".",
    *,
    trunk: str = DEFAULT_TRUNK,
    ceiling: int = DEFAULT_BRANCH_CEILING,
    now: Callable[[], str] | None = None,
    namespace: str = "refs/heads",
) -> AuditResult:
    """Survey, then place or lift the hold automatically.

    This is the background job. It is deliberately the *only* thing that needs
    scheduling: it decides on its own whether the repository should be under
    consolidation, so sprawl is caught without anyone remembering to look.
    """
    stamp = now() if now is not None else ""
    report = survey(git, trunk=trunk, ceiling=ceiling, namespace=namespace)
    existing = active_hold(repo_root)
    result = AuditResult(report=report, hold=existing)

    if report.over_ceiling:
        held = place_hold(
            repo_root,
            reason=f"{report.total} branches over a ceiling of {ceiling}",
            branch_count=report.total,
            ceiling=ceiling,
            needs_decision=len(report.needs_decision),
            allow=(trunk,),
            now=stamp,
        )
        result.hold = held
        result.hold_placed = True
        result.notes.append(held.message())
        return result

    if existing is not None:
        release_hold(repo_root)
        result.hold = None
        result.hold_released = True
        result.notes.append("Sprawl is back under the ceiling; consolidation hold lifted.")
        return result

    result.notes.append(report.summary())
    return result
