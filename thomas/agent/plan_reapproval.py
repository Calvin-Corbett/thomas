"""Deterministic plan re-approval triggers for the Thomas agent (CAP-050).

Plan-approval mode lets a human approve a bounded *scope* of work up front:
which tools/actions may run, how risky they may get, which paths may be
written, and any explicit constraints. Once approved, the agent should be able
to execute *in scope* without pestering the human again — but the moment
execution proposes something **materially surprising** (outside that approved
scope) it must stop and ask for re-approval.

This module makes that trigger **deterministic**: given the same
:class:`ApprovedPlan` and the same :class:`ProposedAction`,
:func:`evaluate_action` always returns the same :class:`ReapprovalDecision`.
There is no clock, randomness, or hidden state — the decision is a pure function
of its inputs.

An action is *materially surprising* (and forces re-approval) when any of these
hold. The checks run in this fixed, documented order and **every** matching
check contributes a trigger, so multiple surprises are all reported:

1. ``TOOL_OUT_OF_SCOPE`` — the action's tool is not in the approved allowlist.
2. ``RISK_ESCALATION`` — the action's risk tier is above the approved ceiling.
3. ``WRITE_OUTSIDE_SCOPE`` — the action writes a path matching none of the
   approved path globs.
4. ``NEWLY_DESTRUCTIVE`` — the action is destructive and the plan did not
   approve destructive operations.
5. ``CONSTRAINT_VIOLATION`` — the action matches an explicit forbidden-operation
   constraint the human attached to the plan.

Routine, in-scope actions produce a decision with ``requires_reapproval`` False
and no triggers.

Risk tiers reuse :class:`thomas.agent.tool_risk.ToolRiskLevel` (same package, not
a protected file). A caller may inject a risk level directly on the action; when
omitted, the level is derived offline via
:func:`thomas.agent.tool_risk.classify_tool_action` — no external services and
no protected-file imports.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from thomas.agent.tool_risk import ToolRiskLevel, classify_tool_action

__all__ = [
    "SurpriseKind",
    "ReapprovalTrigger",
    "ReapprovalDecision",
    "ProposedAction",
    "ApprovedPlan",
    "evaluate_action",
]

# Deterministic total order over risk tiers, mirroring tool_risk's ordering.
_RISK_RANK: dict[ToolRiskLevel, int] = {
    ToolRiskLevel.LOW: 1,
    ToolRiskLevel.MEDIUM: 2,
    ToolRiskLevel.HIGH: 3,
    ToolRiskLevel.CRITICAL: 4,
}


class SurpriseKind(str, Enum):
    """The fixed vocabulary of materially-surprising deviations.

    Values are stable strings so decisions can be logged and compared across
    processes without depending on enum member identity.
    """

    TOOL_OUT_OF_SCOPE = "tool_out_of_scope"
    RISK_ESCALATION = "risk_escalation"
    WRITE_OUTSIDE_SCOPE = "write_outside_scope"
    NEWLY_DESTRUCTIVE = "newly_destructive"
    CONSTRAINT_VIOLATION = "constraint_violation"


@dataclass(frozen=True)
class ReapprovalTrigger:
    """One specific reason an action requires re-approval."""

    kind: SurpriseKind
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "reason": self.reason}


@dataclass(frozen=True)
class ReapprovalDecision:
    """The deterministic outcome of evaluating a proposed action.

    ``triggers`` is ordered by the fixed check sequence documented on the module.
    ``requires_reapproval`` is simply ``bool(triggers)``.
    """

    requires_reapproval: bool
    triggers: tuple[ReapprovalTrigger, ...] = ()

    @property
    def reasons(self) -> tuple[str, ...]:
        """Human-readable reason strings, one per trigger, in check order."""

        return tuple(trigger.reason for trigger in self.triggers)

    @property
    def kinds(self) -> tuple[SurpriseKind, ...]:
        """The surprise kinds that fired, in check order."""

        return tuple(trigger.kind for trigger in self.triggers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requires_reapproval": self.requires_reapproval,
            "triggers": [trigger.to_dict() for trigger in self.triggers],
        }


def _normalize_path(path: str) -> str:
    """Normalize a path for glob comparison (``\\`` -> ``/``, strip whitespace)."""

    return str(path or "").strip().replace("\\", "/")


def _as_str_tuple(values: Iterable[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(str(value) for value in values)


@dataclass(frozen=True)
class ApprovedPlan:
    """The human-approved scope a run may execute without re-approval.

    Parameters
    ----------
    allowed_tools:
        Tool names or fnmatch-style patterns (e.g. ``"file.read"`` or
        ``"browser.*"``) the human approved. An action whose tool matches none
        of these is out of scope.
    risk_ceiling:
        The highest risk tier approved. An action whose (injected or derived)
        risk tier ranks above this ceiling is an escalation.
    write_globs:
        fnmatch-style path patterns the run may write to. An action that writes
        a path matching none of these is out of scope. Empty means *no writes
        were approved*, so any write is surprising.
    forbidden_operations:
        Explicit operation labels the human excluded (e.g. ``"force_push"``).
        A proposed action carrying a matching label always requires re-approval.
    allow_destructive:
        Whether destructive operations were approved. When False, any action
        flagged destructive is surprising.
    """

    allowed_tools: frozenset[str] = frozenset()
    risk_ceiling: ToolRiskLevel = ToolRiskLevel.LOW
    write_globs: tuple[str, ...] = ()
    forbidden_operations: frozenset[str] = frozenset()
    allow_destructive: bool = False

    @classmethod
    def build(
        cls,
        *,
        allowed_tools: Iterable[str] | None = None,
        risk_ceiling: ToolRiskLevel = ToolRiskLevel.LOW,
        write_globs: Iterable[str] | None = None,
        forbidden_operations: Iterable[str] | None = None,
        allow_destructive: bool = False,
    ) -> ApprovedPlan:
        """Construct a plan from loose iterables, freezing collections."""

        return cls(
            allowed_tools=frozenset(_as_str_tuple(allowed_tools)),
            risk_ceiling=risk_ceiling,
            write_globs=_as_str_tuple(write_globs),
            forbidden_operations=frozenset(_as_str_tuple(forbidden_operations)),
            allow_destructive=bool(allow_destructive),
        )

    def tool_in_scope(self, tool: str) -> bool:
        """True when ``tool`` exactly matches or fnmatches an approved entry."""

        name = str(tool or "")
        return any(name == entry or fnmatch.fnmatch(name, entry) for entry in sorted(self.allowed_tools))

    def write_in_scope(self, path: str) -> bool:
        """True when ``path`` matches at least one approved write glob."""

        normalized = _normalize_path(path)
        return any(fnmatch.fnmatch(normalized, _normalize_path(glob)) for glob in self.write_globs)


@dataclass(frozen=True)
class ProposedAction:
    """A single action execution proposes to take, checked against the plan.

    Parameters
    ----------
    tool:
        The tool name the action would invoke.
    risk_level:
        The risk tier for the action. When ``None`` it is derived offline from
        ``tool``/``args`` via :func:`classify_tool_action`.
    write_paths:
        Paths the action would write to (empty for read-only actions).
    destructive:
        Whether the action is a newly-destructive operation.
    operations:
        Explicit operation labels this action carries, matched against the
        plan's ``forbidden_operations``.
    args:
        Optional tool arguments, only used to derive a risk level when
        ``risk_level`` is not injected.
    """

    tool: str
    risk_level: ToolRiskLevel | None = None
    write_paths: tuple[str, ...] = ()
    destructive: bool = False
    operations: frozenset[str] = frozenset()
    args: Mapping[str, Any] = field(default_factory=dict)

    def effective_risk(self) -> ToolRiskLevel:
        """Return the injected risk tier, or derive one deterministically."""

        if self.risk_level is not None:
            return self.risk_level
        return classify_tool_action(self.tool, dict(self.args)).risk_level


def evaluate_action(plan: ApprovedPlan, proposed_action: ProposedAction) -> ReapprovalDecision:
    """Decide, deterministically, whether ``proposed_action`` needs re-approval.

    The five checks below run in a fixed order; each independently appends a
    :class:`ReapprovalTrigger` when it fires, so all concurrent surprises are
    reported. The result is a pure function of the inputs — identical inputs
    always yield an identical decision.
    """

    triggers: list[ReapprovalTrigger] = []

    # 1. Tool allowlist scope.
    if not plan.tool_in_scope(proposed_action.tool):
        triggers.append(
            ReapprovalTrigger(
                kind=SurpriseKind.TOOL_OUT_OF_SCOPE,
                reason=(
                    f"Tool '{proposed_action.tool}' is not in the approved allowlist "
                    f"{sorted(plan.allowed_tools)}; the approved scope did not cover it."
                ),
            )
        )

    # 2. Risk-tier escalation above the approved ceiling.
    effective_risk = proposed_action.effective_risk()
    if _RISK_RANK[effective_risk] > _RISK_RANK[plan.risk_ceiling]:
        triggers.append(
            ReapprovalTrigger(
                kind=SurpriseKind.RISK_ESCALATION,
                reason=(
                    f"Action risk tier '{effective_risk.value}' exceeds the approved "
                    f"ceiling '{plan.risk_ceiling.value}'."
                ),
            )
        )

    # 3. Writes outside the approved path globs (evaluated per path, in order).
    for path in proposed_action.write_paths:
        if not plan.write_in_scope(path):
            triggers.append(
                ReapprovalTrigger(
                    kind=SurpriseKind.WRITE_OUTSIDE_SCOPE,
                    reason=(f"Write to '{path}' matches none of the approved path globs {list(plan.write_globs)}."),
                )
            )

    # 4. Newly-destructive operation the plan did not approve.
    if proposed_action.destructive and not plan.allow_destructive:
        triggers.append(
            ReapprovalTrigger(
                kind=SurpriseKind.NEWLY_DESTRUCTIVE,
                reason=(
                    f"Action '{proposed_action.tool}' is destructive, but the approved "
                    "plan did not authorize destructive operations."
                ),
            )
        )

    # 5. Explicit forbidden-operation constraints (sorted for determinism).
    for operation in sorted(proposed_action.operations & plan.forbidden_operations):
        triggers.append(
            ReapprovalTrigger(
                kind=SurpriseKind.CONSTRAINT_VIOLATION,
                reason=(f"Operation '{operation}' is explicitly forbidden by the approved plan's constraints."),
            )
        )

    return ReapprovalDecision(requires_reapproval=bool(triggers), triggers=tuple(triggers))
