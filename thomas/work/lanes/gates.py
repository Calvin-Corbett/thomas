"""Gate evaluation: the only thing allowed to advance a step.

Three kinds, strongest first. **mechanical** runs a named check from a closed
registry -- closed so a lane definition can never become an execution vector.
**evidence** requires a named artifact that is actually there and not a stub.
**judged** asks a separate model call, and is the last resort rather than the
default.

Every verdict carries ``counts`` as well as ``passed``. They differ for an
unproven gate: the predicate may hold, but a gate whose failing branch has never
been observed does not get to advance anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .model import Gate


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str
    counts: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {"passed": self.passed, "counts": self.counts, "reason": self.reason}


@dataclass
class GateContext:
    """The facts a gate is allowed to look at.

    ``provenance`` records where a field's value came from -- ``"user"`` for a
    recorded user action, ``"model"`` for something the agent wrote about its
    own work. Gates that must not accept a self-report read this.
    """

    fields: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, int] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)


def _int_param(params: dict[str, Any], key: str, default: int) -> int:
    """Read an int param without letting a deliberate 0 fall back to the default.

    ``int(params.get(key) or default)`` silently rewrites a configured 0 into the
    default, so a gate weakened to a threshold of zero keeps behaving like a
    strict one and the weakening never shows up. Config must mean what it says.
    """

    value = params.get(key)
    if value is None or value == "":
        return default
    return int(value)


# ── the closed mechanical registry ────────────────────────────────────────────


def _nonempty_text(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    name = str(params.get("field") or "")
    minimum = _int_param(params, "min_chars", 1)
    value = str(ctx.fields.get(name) or "").strip()
    if len(value) < minimum:
        return Verdict(False, f"{name} is {len(value)} chars, needs at least {minimum}")
    return Verdict(True, f"{name} is {len(value)} chars")


def _count_between(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    name = str(params.get("field") or "")
    low = _int_param(params, "min", 0)
    high = _int_param(params, "max", 0)
    rows = ctx.fields.get(name)
    size = len(rows) if isinstance(rows, (list, tuple)) else 0
    if not low <= size <= high:
        return Verdict(False, f"{name} has {size} entries, needs {low}..{high}")
    return Verdict(True, f"{name} has {size} entries")


def _each_has(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    name = str(params.get("field") or "")
    keys = [str(k) for k in (params.get("keys") or [])]
    rows = ctx.fields.get(name)
    if not isinstance(rows, (list, tuple)) or not rows:
        return Verdict(False, f"{name} is empty")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return Verdict(False, f"{name}[{index}] is not an object")
        for key in keys:
            if not str(row.get(key) or "").strip():
                return Verdict(False, f"{name}[{index}] is missing {key}")
    return Verdict(True, f"every entry in {name} has {', '.join(keys)}")


def _subset_of(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    """Every id claimed under ``field`` must appear in ``allowed_field``."""

    name = str(params.get("field") or "")
    allowed_name = str(params.get("allowed_field") or "")
    claimed = ctx.fields.get(name)
    allowed = ctx.fields.get(allowed_name)
    claimed_ids = {str(v) for v in claimed} if isinstance(claimed, (list, tuple, set)) else set()
    allowed_ids = {str(v) for v in allowed} if isinstance(allowed, (list, tuple, set)) else set()
    unknown = sorted(claimed_ids - allowed_ids)
    if unknown:
        return Verdict(False, f"{name} names {', '.join(unknown)}, which {allowed_name} does not contain")
    return Verdict(True, f"every id in {name} is present in {allowed_name}")


def _user_originated(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    """The field must carry a real user action, not the agent's own report.

    This is the check for the shape where a model copies a value it wrote and a
    later reader treats the copy as confirmation.
    """

    name = str(params.get("field") or "")
    value = str(ctx.fields.get(name) or "").strip()
    source = str(ctx.provenance.get(name) or "").strip().lower()
    if not value:
        return Verdict(False, f"{name} is empty")
    if source != "user":
        return Verdict(False, f"{name} came from '{source or 'nowhere'}', not a recorded user action")
    return Verdict(True, f"{name} came from a recorded user action")


def _not_equals(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    """The field must not hold a named value -- e.g. a phase still in flight."""

    name = str(params.get("field") or "")
    forbidden = str(params.get("value") or "")
    value = str(ctx.fields.get(name) or "").strip()
    if value == forbidden:
        return Verdict(False, f"{name} is still {forbidden!r}")
    return Verdict(True, f"{name} is {value!r}, not {forbidden!r}")


def _min_counter(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    name = str(params.get("field") or "")
    minimum = _int_param(params, "min", 1)
    value = int(ctx.counters.get(name) or 0)
    if value < minimum:
        return Verdict(False, f"{name} is {value}, needs at least {minimum}")
    return Verdict(True, f"{name} is {value}")


def _one_of(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    """The field must hold one of a named set of values."""

    name = str(params.get("field") or "")
    allowed = [str(value) for value in (params.get("values") or [])]
    value = str(ctx.fields.get(name) or "").strip()
    if value not in allowed:
        return Verdict(False, f"{name} is {value!r}, not one of {', '.join(allowed)}")
    return Verdict(True, f"{name} is {value!r}")


def _marker_within_count(ctx: GateContext, params: dict[str, Any]) -> Verdict:
    """A recorded marker turn must be real, and must sit inside the turns that happened.

    This is the provenance question for a workflow selection: was it recorded at
    a turn the user actually took? A marker of zero or missing means no user
    action was ever recorded, and a marker beyond the conversation means a turn
    that never happened.

    It deliberately does NOT demand a further turn after the marker. Requiring one
    rejects a user who chooses and configures in the same message, which is a real
    two-turn onboarding, and demanding extra turns is what made a simple
    onboarding unfinishable before.

    ``bool`` is rejected explicitly -- it is an ``int`` in Python, so accepting it
    would make ``True`` a valid turn number and the gate trivially satisfiable.
    """

    name = str(params.get("field") or "")
    marker_name = str(params.get("marker_field") or "")
    min_marker = _int_param(params, "min_marker", 1)

    marker = ctx.counters.get(marker_name)
    if isinstance(marker, bool) or not isinstance(marker, int) or marker < min_marker:
        return Verdict(False, f"{marker_name} was never recorded as a real user turn (got {marker!r})")

    count = ctx.counters.get(name)
    if isinstance(count, bool) or not isinstance(count, int) or count < marker:
        return Verdict(False, f"{marker_name} ({marker}) names a turn beyond {name} ({count!r})")
    return Verdict(True, f"{marker_name} ({marker}) is a real turn within {name} ({count})")


CHECKS: dict[str, Callable[[GateContext, dict[str, Any]], Verdict]] = {
    "nonempty_text": _nonempty_text,
    "count_between": _count_between,
    "each_has": _each_has,
    "subset_of": _subset_of,
    "user_originated": _user_originated,
    "not_equals": _not_equals,
    "one_of": _one_of,
    "marker_within_count": _marker_within_count,
    "min_counter": _min_counter,
}


# ── the three kinds ───────────────────────────────────────────────────────────


def _evaluate_mechanical(gate: Gate, ctx: GateContext) -> Verdict:
    check = CHECKS.get(gate.check)
    if check is None:
        # Fail closed. An unknown check is a broken gate, and a broken gate that
        # waves work through is the defect this package exists to prevent.
        return Verdict(False, f"unknown mechanical check: {gate.check}")
    return check(ctx, gate.params or {})


def _evaluate_evidence(gate: Gate, ctx: GateContext) -> Verdict:
    name = str(gate.params.get("artifact") or gate.check or "")
    minimum = _int_param(gate.params, "min_bytes", 1)
    size = int(ctx.artifacts.get(name) or 0)
    if size < minimum:
        return Verdict(False, f"artifact {name!r} is {size} bytes, needs at least {minimum}")
    return Verdict(True, f"artifact {name!r} is {size} bytes")


def _evaluate_judged(gate: Gate, ctx: GateContext, judge: Callable[[str, GateContext], Verdict] | None) -> Verdict:
    if judge is None:
        return Verdict(False, "no judge available for a judged gate")
    return judge(gate.check, ctx)


def evaluate_gate(
    gate: Gate,
    ctx: GateContext,
    judge: Callable[[str, GateContext], Verdict] | None = None,
) -> Verdict:
    """Evaluate one gate. ``counts`` is false for an unproven gate that passes."""

    if gate.kind == "mechanical":
        verdict = _evaluate_mechanical(gate, ctx)
    elif gate.kind == "evidence":
        verdict = _evaluate_evidence(gate, ctx)
    elif gate.kind == "judged":
        verdict = _evaluate_judged(gate, ctx, judge)
    else:
        verdict = Verdict(False, f"unknown gate kind: {gate.kind}")

    if not verdict.passed:
        return Verdict(False, verdict.reason, counts=False)
    if not gate.proven:
        return Verdict(
            True,
            f"{verdict.reason} -- but this gate is unproven (never observed failing), so its pass does not count",
            counts=False,
        )
    return Verdict(True, verdict.reason, counts=True)
