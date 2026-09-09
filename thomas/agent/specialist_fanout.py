"""Standing specialist roles run in parallel, with a materiality proof.

Where :mod:`thomas.agent.fanout_synthesis` fans *one* prompt out to ``N``
interchangeable workers and reconciles their (possibly conflicting) answers,
this module fans a *task* out across a **panel of standing specialist roles**.
Each role is a distinct expert lens -- security, performance, correctness,
tests, ... -- with its own prompt framing and its own injectable worker. The
roles run **independently and in parallel**, each returning a *role-tagged*
contribution (a finding/recommendation plus supporting :class:`Evidence`).

The synthesizer merges the specialist contributions into a final result: a
decision plus the accumulated findings. The load-bearing property this module
adds on top of a plain fan-out is a **materiality proof** -- it computes the
result *with* the specialists against a baseline computed *without* them and
exposes exactly what the specialists added or changed:

* :attr:`MaterialityReport.added_findings` -- findings that exist only because a
  specialist raised them, each attributed to the role that raised it.
* :attr:`MaterialityReport.changed_decision` -- ``True`` when the specialists'
  contributions flipped the final decision relative to the baseline (e.g. a
  security specialist raised a *blocking* finding that turns an ``approve`` into
  a ``reject``).
* :attr:`MaterialityReport.per_role` -- a per-role breakdown recording whether
  that role was *material* (added a real finding / moved the decision) or a
  no-op that changed nothing.

Standing-ness matters: a :class:`SpecialistPanel` is configured once with its
roles and reused across many tasks -- the roles are a stable, named panel, not
an ad-hoc per-call list. Parallelism is real (a thread per role) but the
collected output is deterministic: contributions are always returned in role
order regardless of completion order, and there is no wall-clock or randomness
in the synthesis path. Workers are fully injectable, so the whole module is
hermetic and needs no live model, network, or clock.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from thomas.agent.fanout_synthesis import Evidence

__all__ = [
    "Severity",
    "SpecialistRequest",
    "SpecialistContribution",
    "SpecialistRole",
    "PanelResult",
    "RoleMateriality",
    "MaterialityReport",
    "PanelRun",
    "SpecialistPanel",
    "standard_panel_roles",
]


class Severity(enum.IntEnum):
    """Ordered severity of a specialist finding.

    Ordering is meaningful (``INFO < LOW < ... < BLOCKER``) so callers can rank
    or threshold findings. ``BLOCKER`` is the only level that, on its own,
    forces the merged decision to flip.
    """

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    BLOCKER = 4

    @classmethod
    def coerce(cls, value: Any) -> Severity:
        """Accept a :class:`Severity`, its name, or its int value."""

        if isinstance(value, Severity):
            return value
        if isinstance(value, str):
            try:
                return cls[value.strip().upper()]
            except KeyError:
                raise ValueError(f"unknown severity {value!r}") from None
        if isinstance(value, int):
            return cls(value)
        raise TypeError(f"cannot coerce {type(value).__name__} to Severity")


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

# The default decision a task carries before any specialist weighs in, and the
# decision the merge flips to when a blocking finding is present.
DEFAULT_BASELINE_DECISION = "approve"
BLOCKED_DECISION = "reject"


@dataclasses.dataclass(frozen=True)
class SpecialistRequest:
    """The isolated unit of work handed to one specialist role.

    Every role in a panel sees the same ``task`` but through its own ``role``
    name and ``lens`` (the expert framing). Nothing else is shared, which is
    what makes the roles independent.
    """

    task: str
    role: str
    lens: str


@dataclasses.dataclass(frozen=True)
class SpecialistContribution:
    """One role's role-tagged finding plus the evidence it stands on.

    ``role``/``lens``/``task`` are authoritative: the panel re-stamps them from
    the request so a contribution can always be traced back to the exact role
    and task that produced it, regardless of what the worker filled in.
    """

    role: str
    lens: str
    task: str
    finding: str
    severity: Severity
    blocking: bool
    evidence: Evidence

    @property
    def is_noop(self) -> bool:
        """True when this role contributed nothing that could move the result.

        A no-op has no finding text, ``INFO`` severity, is non-blocking, and
        carries no supporting evidence. Such a contribution is *non-material*.
        """

        return (
            not self.finding.strip()
            and self.severity is Severity.INFO
            and not self.blocking
            and not self.evidence.sources
            and not (self.evidence.summary or "").strip()
        )


@dataclasses.dataclass(frozen=True)
class SpecialistRole:
    """A standing expert lens with its own injectable worker.

    ``name`` is the stable role identity (e.g. ``"security"``); ``lens`` is the
    framing handed to the worker; ``worker`` is the callable that produces the
    contribution. Roles are configured once and reused across tasks.
    """

    name: str
    lens: str
    worker: Callable[[SpecialistRequest], Any]

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("role name must be non-empty")
        if not callable(self.worker):
            raise TypeError(f"role {self.name!r} worker must be callable")


@dataclasses.dataclass(frozen=True)
class PanelResult:
    """The merged outcome of a task: a decision plus accumulated findings.

    ``contributions`` are every role's raw contribution, in role order.
    ``findings`` are the *material* contributions only (no-ops filtered out),
    which is what actually feeds the decision.
    """

    task: str
    decision: str
    baseline_decision: str
    contributions: tuple[SpecialistContribution, ...]

    @property
    def findings(self) -> tuple[SpecialistContribution, ...]:
        """Material contributions (no-ops excluded), in role order."""

        return tuple(c for c in self.contributions if not c.is_noop)

    @property
    def blocking_findings(self) -> tuple[SpecialistContribution, ...]:
        """Findings that force the decision to flip, in role order."""

        return tuple(c for c in self.contributions if c.blocking)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(c.role for c in self.contributions)


@dataclasses.dataclass(frozen=True)
class RoleMateriality:
    """Per-role account of what that role changed relative to the baseline."""

    role: str
    material: bool
    added_finding: str | None
    severity: Severity
    flipped_decision: bool


@dataclasses.dataclass(frozen=True)
class MaterialityReport:
    """Proof of whether -- and how -- the specialists changed the result.

    Compares the result computed *with* the specialists against the baseline
    computed *without* them.
    """

    decision_with: str
    decision_without: str
    changed_decision: bool
    added_findings: tuple[SpecialistContribution, ...]
    per_role: tuple[RoleMateriality, ...]

    @property
    def material(self) -> bool:
        """True when the specialists changed anything at all."""

        return self.changed_decision or bool(self.added_findings)

    def role(self, name: str) -> RoleMateriality:
        """Look up one role's materiality record."""

        for record in self.per_role:
            if record.role == name:
                return record
        raise KeyError(name)

    @property
    def material_roles(self) -> tuple[str, ...]:
        """Roles that materially changed the result, in role order."""

        return tuple(r.role for r in self.per_role if r.material)

    def describe(self) -> str:
        """Deterministic human-readable materiality summary."""

        head = (
            f"decision {self.decision_without!r} -> {self.decision_with!r}"
            f" ({'CHANGED' if self.changed_decision else 'unchanged'});"
            f" {len(self.added_findings)} added finding(s)"
        )
        lines = [head]
        for record in self.per_role:
            tag = "material" if record.material else "non-material"
            flip = " [flipped decision]" if record.flipped_decision else ""
            note = record.added_finding if record.added_finding else "(no finding)"
            lines.append(f"  {record.role}: {tag}{flip} -> {note}")
        return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class PanelRun:
    """Everything one :meth:`SpecialistPanel.run_panel` produced."""

    task: str
    roles: tuple[str, ...]
    result_with: PanelResult
    result_without: PanelResult
    materiality: MaterialityReport
    contributions: tuple[SpecialistContribution, ...]

    @property
    def decision(self) -> str:
        """The final decision the panel arrived at (with specialists)."""

        return self.result_with.decision


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class SpecialistPanel:
    """A standing panel of specialist roles, reusable across many tasks.

    Construct once with the roles; call :meth:`run_panel` per task. Each role's
    worker receives a :class:`SpecialistRequest` and must return either a
    :class:`SpecialistContribution` or a mapping with a ``"finding"`` key and
    optional ``"severity"`` / ``"blocking"`` / ``"evidence"`` values. The panel
    re-stamps ``role``/``lens``/``task`` so role identity is authoritative.

    Worker exceptions are *not* swallowed: a role is expected to return a
    contribution, and letting failures propagate keeps the panel deterministic
    and free of broad exception handling.
    """

    def __init__(
        self,
        roles: Sequence[SpecialistRole],
        *,
        baseline_decision: str = DEFAULT_BASELINE_DECISION,
        blocked_decision: str = BLOCKED_DECISION,
    ) -> None:
        roles = tuple(roles)
        if not roles:
            raise ValueError("a panel needs at least one role")
        names = [r.name for r in roles]
        if len(set(names)) != len(names):
            raise ValueError("role names must be unique within a panel")
        self._roles = roles
        self._baseline_decision = baseline_decision
        self._blocked_decision = blocked_decision

    @property
    def roles(self) -> tuple[SpecialistRole, ...]:
        return self._roles

    @property
    def role_names(self) -> tuple[str, ...]:
        return tuple(r.name for r in self._roles)

    @property
    def baseline_decision(self) -> str:
        return self._baseline_decision

    # -- parallel fan-out ----------------------------------------------------

    def _dispatch(self, task: str, roles: tuple[SpecialistRole, ...]) -> tuple[SpecialistContribution, ...]:
        """Run every role's worker in parallel; collect in role order.

        A thread per role means the roles genuinely execute concurrently; the
        results are re-ordered back into role order before returning so the
        output is deterministic regardless of completion order.
        """

        def invoke(role: SpecialistRole) -> SpecialistContribution:
            request = SpecialistRequest(task=task, role=role.name, lens=role.lens)
            return self._coerce(request, role.worker(request))

        with ThreadPoolExecutor(max_workers=len(roles)) as pool:
            # executor.map preserves input order in its output, independent of
            # the order in which the worker threads actually finished.
            return tuple(pool.map(invoke, roles))

    def _coerce(self, request: SpecialistRequest, raw: Any) -> SpecialistContribution:
        """Normalize a worker return value into a stamped contribution."""

        if isinstance(raw, SpecialistContribution):
            finding = raw.finding
            severity = raw.severity
            blocking = raw.blocking
            evidence: Any = raw.evidence
        elif isinstance(raw, Mapping):
            if "finding" not in raw:
                raise ValueError(f"role {request.role!r} returned a mapping without a 'finding' key")
            finding = raw["finding"]
            severity = raw.get("severity", Severity.INFO)
            blocking = raw.get("blocking", False)
            evidence = raw.get("evidence")
        else:
            raise TypeError(
                f"role {request.role!r} returned unsupported type {type(raw).__name__};"
                " expected SpecialistContribution or mapping"
            )
        return SpecialistContribution(
            role=request.role,
            lens=request.lens,
            task=request.task,
            finding=str(finding),
            severity=Severity.coerce(severity),
            blocking=bool(blocking),
            evidence=self._coerce_evidence(request.role, evidence),
        )

    @staticmethod
    def _coerce_evidence(role: str, raw: Any) -> Evidence:
        """Build an :class:`Evidence` stamped with ``role`` as its worker id."""

        if isinstance(raw, Evidence):
            return dataclasses.replace(raw, worker_id=role)
        if isinstance(raw, Mapping):
            sources = raw.get("sources") or ()
            detail = raw.get("detail")
            return Evidence(
                worker_id=role,
                summary=str(raw.get("summary", "")),
                sources=tuple(str(s) for s in sources),
                detail=detail if isinstance(detail, Mapping) else None,
            )
        if raw is None:
            return Evidence(worker_id=role)
        return Evidence(worker_id=role, summary=str(raw))

    # -- synthesis -----------------------------------------------------------

    def _merge(
        self,
        task: str,
        contributions: tuple[SpecialistContribution, ...],
        baseline_decision: str,
    ) -> PanelResult:
        """Merge contributions into a decision.

        The baseline decision stands unless a *blocking* finding is present, in
        which case the decision flips to the panel's blocked decision.
        """

        blocked = any(c.blocking for c in contributions)
        decision = self._blocked_decision if blocked else baseline_decision
        return PanelResult(
            task=task,
            decision=decision,
            baseline_decision=baseline_decision,
            contributions=contributions,
        )

    def _materiality(self, result_with: PanelResult, result_without: PanelResult) -> MaterialityReport:
        """Diff the with/without results into a materiality proof."""

        changed_decision = result_with.decision != result_without.decision
        added = result_with.findings  # baseline has no specialist findings

        per_role: list[RoleMateriality] = []
        for contribution in result_with.contributions:
            material = not contribution.is_noop
            # A role flips the decision when the overall decision changed and
            # this role's contribution is a (blocking) cause of that flip.
            flipped = changed_decision and contribution.blocking
            per_role.append(
                RoleMateriality(
                    role=contribution.role,
                    material=material,
                    added_finding=contribution.finding if material else None,
                    severity=contribution.severity,
                    flipped_decision=flipped,
                )
            )

        return MaterialityReport(
            decision_with=result_with.decision,
            decision_without=result_without.decision,
            changed_decision=changed_decision,
            added_findings=added,
            per_role=tuple(per_role),
        )

    # -- entry point ---------------------------------------------------------

    def run_panel(
        self,
        task: str,
        roles: Sequence[SpecialistRole] | None = None,
        *,
        baseline_decision: str | None = None,
    ) -> PanelRun:
        """Run the panel on ``task`` and prove the specialists' materiality.

        Roles run in parallel (one thread each) and return role-tagged
        contributions in role order. The result *with* the specialists is
        compared against the baseline *without* them, and the difference is
        surfaced as a :class:`MaterialityReport`.

        Pass ``roles`` to run a subset/override for this call; omit it to use
        the panel's standing roles. ``baseline_decision`` overrides the panel
        default for this call only.
        """

        active = tuple(roles) if roles is not None else self._roles
        if not active:
            raise ValueError("cannot run a panel with no roles")
        base = self._baseline_decision if baseline_decision is None else baseline_decision

        contributions = self._dispatch(task, active)
        result_with = self._merge(task, contributions, base)
        # Baseline: the same task with no specialists weighing in.
        result_without = self._merge(task, (), base)
        report = self._materiality(result_with, result_without)

        return PanelRun(
            task=task,
            roles=tuple(r.name for r in active),
            result_with=result_with,
            result_without=result_without,
            materiality=report,
            contributions=contributions,
        )


def standard_panel_roles(
    workers: Mapping[str, Callable[[SpecialistRequest], Any]],
) -> tuple[SpecialistRole, ...]:
    """Build the four standing lenses (security/performance/correctness/tests).

    ``workers`` maps each role name to its injectable worker. This is a
    convenience for the common panel; callers may assemble any roles they like
    by constructing :class:`SpecialistRole` directly.
    """

    lenses = {
        "security": "audit for vulnerabilities, unsafe inputs, and secret exposure",
        "performance": "assess latency, allocation, and scaling hot paths",
        "correctness": "verify the logic satisfies the specified behavior",
        "tests": "check coverage of the changed behavior and edge cases",
    }
    missing = [name for name in lenses if name not in workers]
    if missing:
        raise ValueError(f"missing workers for roles: {', '.join(missing)}")
    return tuple(SpecialistRole(name=name, lens=lens, worker=workers[name]) for name, lens in lenses.items())
