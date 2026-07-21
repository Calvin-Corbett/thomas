"""Cost-tiered internal routing.

An *auditable* classifier that decides, for a single unit of internal work,
which cost tier (and therefore which model profile) should handle it. Cheap
low-risk work — status summaries, formatting, classification, short
extraction — is routed to a cheap profile; risky or complex work — code
changes, destructive/irreversible actions, long reasoning — is routed to a
more capable (and more expensive) profile.

Design goals
------------
1. **Rule-based and documented.** Classification uses an ordered list of
   named rules (see ``DEFAULT_RULES``). The first rule whose predicate matches
   decides the tier. Rules are ordered *risk-first*: destructive and
   code-changing work is checked before any cheap category, so risky work can
   never fall into the cheap tier by accident.

2. **Auditable.** Every decision produces a :class:`RoutingDecision` that
   records *why*: the matched rule, the concrete signal that fired, the risk
   level, and the chosen tier/profile. Decisions are plain, JSON-serializable
   records. The router keeps an append-only audit trail so routing is
   reviewable after the fact.

3. **Configurable profile mapping.** The tier → model-profile-id mapping has
   safe defaults but can be overridden per router instance.

The module is deterministic: :meth:`CostTierRouter.classify` is a pure
function of its input. No live model, no network, no wall-clock dependency in
the decision itself (an optional injected clock only timestamps audit
entries).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

__all__ = [
    "CostTier",
    "RiskLevel",
    "WorkItem",
    "ClassificationRule",
    "RoutingDecision",
    "CostTierRouter",
    "DEFAULT_PROFILE_MAP",
    "DEFAULT_RULES",
]


class CostTier(str, Enum):
    """Cost tier a unit of work is routed to.

    Ordered cheapest → most expensive. ``str`` mixin keeps values
    JSON-serializable as their plain string names.
    """

    CHEAP = "cheap"
    STANDARD = "standard"
    PREMIUM = "premium"


class RiskLevel(str, Enum):
    """Risk assessment recorded alongside every routing decision."""

    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Work item — the unit being classified
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkItem:
    """A single unit of internal work presented to the router.

    Callers may describe the work either structurally (via ``kind`` and the
    boolean signal flags) or in free text (``summary`` / ``detail``). The
    classifier inspects all of them. Structural flags always take precedence
    over free-text keyword matching, so a caller that *knows* an action is
    destructive can assert it directly rather than relying on wording.
    """

    kind: str = ""
    """Caller-declared category, e.g. ``"status_summary"`` or ``"code_edit"``.

    Matched case-insensitively against known low-risk / elevated categories.
    """

    summary: str = ""
    """Short human description of the work."""

    detail: str = ""
    """Optional longer description or the work payload itself."""

    modifies_code: bool = False
    """Caller-asserted: this work edits source code."""

    destructive: bool = False
    """Caller-asserted: this work performs an irreversible/destructive action."""

    est_reasoning_tokens: int = 0
    """Estimated reasoning budget; large values imply a complex task."""

    def searchable_text(self) -> str:
        """Lower-cased concatenation of the free-text fields for keyword rules."""

        return " ".join(part for part in (self.kind, self.summary, self.detail) if part).lower()

    def normalized_kind(self) -> str:
        """Lower-cased, trimmed ``kind`` for category matching."""

        return self.kind.strip().lower()


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

# Threshold above which a task is considered "long reasoning" and therefore
# not eligible for the cheap tier. Documented and fixed for determinism.
LONG_REASONING_TOKEN_THRESHOLD = 4000

# Free-text keyword signals. Compiled once at import for determinism/speed.
_DESTRUCTIVE_KEYWORDS: tuple[str, ...] = (
    "delete",
    "drop table",
    "drop database",
    "rm -rf",
    "force push",
    "force-push",
    "git push --force",
    "deploy to production",
    "production deploy",
    "migrate database",
    "database migration",
    "truncate",
    "wipe",
    "destroy",
    "revoke",
    "purge",
    "hard reset",
)

_CODE_CHANGE_KEYWORDS: tuple[str, ...] = (
    "code change",
    "modify code",
    "edit source",
    "refactor",
    "implement",
    "write a function",
    "write code",
    "patch the",
    "bug fix",
    "bugfix",
    "fix the bug",
    "add a feature",
    "code review",
)

_LOW_RISK_KEYWORDS: tuple[str, ...] = (
    "status summary",
    "status update",
    "summarize status",
    "summary",
    "summarize",
    "format",
    "formatting",
    "reformat",
    "classify",
    "classification",
    "categorize",
    "label this",
    "short extraction",
    "extract the",
    "tl;dr",
    "tldr",
)

# Known caller-declared categories that map directly to a risk posture.
_LOW_RISK_KINDS: frozenset[str] = frozenset(
    {
        "status",
        "status_summary",
        "status_update",
        "summary",
        "summarize",
        "formatting",
        "format",
        "classification",
        "classify",
        "extraction",
        "short_extraction",
        "labeling",
    }
)

_ELEVATED_KINDS: frozenset[str] = frozenset(
    {
        "code",
        "code_edit",
        "code_change",
        "refactor",
        "implementation",
        "reasoning",
        "analysis",
    }
)

_DESTRUCTIVE_KINDS: frozenset[str] = frozenset(
    {
        "destructive",
        "deletion",
        "delete",
        "deploy",
        "deployment",
        "migration",
    }
)


def _compile_keyword_matcher(keywords: Sequence[str]) -> Callable[[str], str | None]:
    """Return a matcher that reports the first keyword found in a text.

    Whole-token-ish matching via a regex alternation. Returns the matched
    keyword (the concrete signal) or ``None``.
    """

    # Sort longest-first so more specific phrases win the citation.
    ordered = sorted(set(keywords), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(kw) for kw in ordered))

    def _match(text: str) -> str | None:
        found = pattern.search(text)
        return found.group(0) if found else None

    return _match


_match_destructive = _compile_keyword_matcher(_DESTRUCTIVE_KEYWORDS)
_match_code_change = _compile_keyword_matcher(_CODE_CHANGE_KEYWORDS)
_match_low_risk = _compile_keyword_matcher(_LOW_RISK_KEYWORDS)


@dataclass(frozen=True)
class ClassificationRule:
    """One named, documented classification rule.

    ``evaluate`` inspects a :class:`WorkItem` and returns the concrete signal
    string that fired (used verbatim in the audit record) or ``None`` if the
    rule does not apply. The first applicable rule in the router's ordered
    list decides the outcome.
    """

    name: str
    tier: CostTier
    risk: RiskLevel
    rationale: str
    evaluate: Callable[[WorkItem], str | None]


def _rule_destructive_flag(work: WorkItem) -> str | None:
    return "flag:destructive=True" if work.destructive else None


def _rule_destructive_keyword(work: WorkItem) -> str | None:
    kind = work.normalized_kind()
    if kind in _DESTRUCTIVE_KINDS:
        return f"kind:{kind}"
    hit = _match_destructive(work.searchable_text())
    return f"keyword:{hit}" if hit else None


def _rule_code_flag(work: WorkItem) -> str | None:
    return "flag:modifies_code=True" if work.modifies_code else None


def _rule_code_keyword(work: WorkItem) -> str | None:
    kind = work.normalized_kind()
    if kind in _ELEVATED_KINDS:
        return f"kind:{kind}"
    hit = _match_code_change(work.searchable_text())
    return f"keyword:{hit}" if hit else None


def _rule_long_reasoning(work: WorkItem) -> str | None:
    if work.est_reasoning_tokens >= LONG_REASONING_TOKEN_THRESHOLD:
        return f"est_reasoning_tokens>={LONG_REASONING_TOKEN_THRESHOLD} (got {work.est_reasoning_tokens})"
    return None


def _rule_low_risk(work: WorkItem) -> str | None:
    kind = work.normalized_kind()
    if kind in _LOW_RISK_KINDS:
        return f"kind:{kind}"
    hit = _match_low_risk(work.searchable_text())
    return f"keyword:{hit}" if hit else None


# Ordered, risk-first. The first matching rule wins. Destructive and
# code-changing checks precede the low-risk check so risky work can never be
# routed to the cheap tier by accident.
DEFAULT_RULES: tuple[ClassificationRule, ...] = (
    ClassificationRule(
        name="destructive_flag",
        tier=CostTier.PREMIUM,
        risk=RiskLevel.HIGH,
        rationale="Caller asserted a destructive/irreversible action; route to the most capable profile.",
        evaluate=_rule_destructive_flag,
    ),
    ClassificationRule(
        name="destructive_signal",
        tier=CostTier.PREMIUM,
        risk=RiskLevel.HIGH,
        rationale="Destructive/irreversible category or keyword detected; route to the most capable profile.",
        evaluate=_rule_destructive_keyword,
    ),
    ClassificationRule(
        name="code_change_flag",
        tier=CostTier.STANDARD,
        risk=RiskLevel.ELEVATED,
        rationale="Caller asserted a code modification; route to a standard (non-cheap) profile.",
        evaluate=_rule_code_flag,
    ),
    ClassificationRule(
        name="code_change_signal",
        tier=CostTier.STANDARD,
        risk=RiskLevel.ELEVATED,
        rationale="Code-change category or keyword detected; route to a standard (non-cheap) profile.",
        evaluate=_rule_code_keyword,
    ),
    ClassificationRule(
        name="long_reasoning",
        tier=CostTier.STANDARD,
        risk=RiskLevel.ELEVATED,
        rationale="Large reasoning budget implies a complex task; route to a standard (non-cheap) profile.",
        evaluate=_rule_long_reasoning,
    ),
    ClassificationRule(
        name="low_risk_summary",
        tier=CostTier.CHEAP,
        risk=RiskLevel.LOW,
        rationale="Low-risk status/summary/formatting/classification/extraction work; route to the cheap profile.",
        evaluate=_rule_low_risk,
    ),
)

# Rule applied when no other rule matches. Deliberately routes to STANDARD (a
# documented safe default) rather than CHEAP, so unclassified work is never
# assumed low-risk.
FALLBACK_RULE = ClassificationRule(
    name="ambiguous_default",
    tier=CostTier.STANDARD,
    risk=RiskLevel.UNKNOWN,
    rationale=(
        "No classifying signal matched; applied documented safe default (standard, not cheap) "
        "so ambiguous work is never assumed low-risk."
    ),
    evaluate=lambda _work: "no_signal_matched",
)


# ---------------------------------------------------------------------------
# Decision record
# ---------------------------------------------------------------------------

DEFAULT_PROFILE_MAP: Mapping[CostTier, str] = MappingProxyType(
    {
        CostTier.CHEAP: "cheap-fast",
        CostTier.STANDARD: "standard-balanced",
        CostTier.PREMIUM: "premium-deep",
    }
)


@dataclass(frozen=True)
class RoutingDecision:
    """The auditable result of classifying one :class:`WorkItem`.

    Fully serializable via :meth:`to_dict`. Deterministic: a given work item
    always yields an equal decision (no timestamps or counters embedded).
    """

    tier: CostTier
    profile_id: str
    rule: str
    risk: RiskLevel
    signal: str
    rationale: str
    work_summary: str

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-serializable representation of the decision."""

        return {
            "tier": self.tier.value,
            "profile_id": self.profile_id,
            "rule": self.rule,
            "risk": self.risk.value,
            "signal": self.signal,
            "rationale": self.rationale,
            "work_summary": self.work_summary,
        }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@dataclass
class _AuditEntry:
    sequence: int
    decision: RoutingDecision
    decided_at: float | None

    def to_dict(self) -> dict[str, Any]:
        record = {"sequence": self.sequence, **self.decision.to_dict()}
        if self.decided_at is not None:
            record["decided_at"] = self.decided_at
        return record


class CostTierRouter:
    """Classify units of work into cost tiers and record an audit trail.

    Parameters
    ----------
    profile_map:
        Optional override of the tier → model-profile-id mapping. Missing tiers
        fall back to :data:`DEFAULT_PROFILE_MAP`.
    rules:
        Optional override of the ordered classification rules. Defaults to
        :data:`DEFAULT_RULES`. The fallback rule is always appended last.
    clock:
        Optional zero-arg callable returning a float timestamp, used only to
        stamp audit entries. Omitted by default to keep routing deterministic.
    """

    def __init__(
        self,
        profile_map: Mapping[CostTier, str] | None = None,
        *,
        rules: Sequence[ClassificationRule] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        merged: dict[CostTier, str] = dict(DEFAULT_PROFILE_MAP)
        if profile_map:
            for tier, profile in profile_map.items():
                merged[CostTier(tier)] = str(profile)
        self._profile_map: dict[CostTier, str] = merged
        self._rules: tuple[ClassificationRule, ...] = tuple(rules) if rules is not None else DEFAULT_RULES
        self._clock = clock
        self._audit: list[_AuditEntry] = []

    # -- configuration --------------------------------------------------

    def profile_for(self, tier: CostTier) -> str:
        """Return the configured model-profile id for ``tier``."""

        return self._profile_map[CostTier(tier)]

    @property
    def profile_map(self) -> Mapping[CostTier, str]:
        """Read-only view of the active tier → profile mapping."""

        return MappingProxyType(dict(self._profile_map))

    # -- classification -------------------------------------------------

    def classify(self, work: WorkItem) -> RoutingDecision:
        """Classify ``work`` into a cost tier and record the decision.

        Pure with respect to the returned decision (deterministic), but has the
        side effect of appending to the audit trail. Use :meth:`preview` for a
        non-recording classification.
        """

        decision = self.preview(work)
        decided_at = self._clock() if self._clock is not None else None
        self._audit.append(_AuditEntry(sequence=len(self._audit), decision=decision, decided_at=decided_at))
        return decision

    def preview(self, work: WorkItem) -> RoutingDecision:
        """Classify ``work`` without recording an audit entry."""

        for rule in self._rules:
            signal = rule.evaluate(work)
            if signal is not None:
                return self._decision(rule, signal, work)
        return self._decision(FALLBACK_RULE, FALLBACK_RULE.evaluate(work) or "no_signal_matched", work)

    def route(self, work: WorkItem) -> str:
        """Classify ``work`` and return just the chosen model-profile id."""

        return self.classify(work).profile_id

    def _decision(self, rule: ClassificationRule, signal: str, work: WorkItem) -> RoutingDecision:
        summary = work.summary or work.kind or (work.detail[:80] if work.detail else "")
        return RoutingDecision(
            tier=rule.tier,
            profile_id=self.profile_for(rule.tier),
            rule=rule.name,
            risk=rule.risk,
            signal=signal,
            rationale=rule.rationale,
            work_summary=summary,
        )

    # -- audit ----------------------------------------------------------

    @property
    def audit_trail(self) -> tuple[RoutingDecision, ...]:
        """Immutable ordered tuple of every recorded decision."""

        return tuple(entry.decision for entry in self._audit)

    def audit_log(self) -> list[dict[str, Any]]:
        """Serializable audit trail: one dict per recorded decision."""

        return [entry.to_dict() for entry in self._audit]

    def clear_audit(self) -> None:
        """Drop all recorded audit entries."""

        self._audit.clear()
