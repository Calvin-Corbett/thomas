"""Completion gating for agent runs: no bare done on failed validation.

When rules-of-road validation fails, a run may not simply emit AGENT_DONE.
The only accepted terminal outcomes are:

- validation passes -> normal completion,
- an explicit structured give-up with a diagnosis -> completion surfaced as
  ``gave_up`` (distinct from success), or
- neither -> the gate demands a fix-or-give-up pass, and if that pass still
  produces a bare done, completion is blocked with AGENT_ERROR.

The give-up shape is precise: a line consisting of ``GIVE_UP`` followed by
three labeled fields, each with at least ``MIN_GIVE_UP_FIELD_CHARS``
characters of diagnosis text::

    GIVE_UP
    what_failed: <which required checks or validation failed>
    what_was_tried: <concrete remediation attempts made>
    why_blocked: <why the run cannot proceed further>
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from thomas.core.rules_of_road import required_failed_checks

GIVE_UP_MARKER = "GIVE_UP"
GIVE_UP_FIELDS: tuple[str, str, str] = ("what_failed", "what_was_tried", "why_blocked")
MIN_GIVE_UP_FIELD_CHARS = 20

GATE_ALLOW = "allow"
GATE_GIVE_UP = "give_up"
GATE_DEMAND_GIVE_UP = "demand_give_up"
GATE_BLOCK = "block"

_MARKER_RE = re.compile(r"^[ \t]*GIVE_UP[ \t]*:?[ \t]*$", re.MULTILINE)
_FIELD_RE = re.compile(
    r"^[ \t]*(what_failed|what_was_tried|why_blocked)[ \t]*:[ \t]*(.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GiveUpDiagnosis:
    """A structured, explicit give-up returned by the agent."""

    what_failed: str
    what_was_tried: str
    why_blocked: str

    def to_payload(self) -> dict[str, str]:
        return {
            "what_failed": self.what_failed,
            "what_was_tried": self.what_was_tried,
            "why_blocked": self.why_blocked,
        }


@dataclass(frozen=True)
class GateDecision:
    """Outcome of the completion gate for one post-loop evaluation."""

    outcome: str
    reason: str = ""
    diagnosis: GiveUpDiagnosis | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"outcome": self.outcome, "reason": self.reason}
        if self.diagnosis is not None:
            payload["diagnosis"] = self.diagnosis.to_payload()
        return payload


def parse_give_up(text: str) -> GiveUpDiagnosis | None:
    """Parse an explicit structured give-up from response text.

    Returns ``None`` unless the marker line is present and all three fields
    carry diagnosis text of meaningful length.
    """
    marker = _MARKER_RE.search(str(text or ""))
    if marker is None:
        return None
    body = str(text or "")[marker.end() :]

    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = _FIELD_RE.match(line)
        if match is not None:
            current = match.group(1).lower()
            fields.setdefault(current, [])
            if match.group(2).strip():
                fields[current].append(match.group(2).strip())
            continue
        if current is None:
            continue
        if not line.strip():
            current = None
            continue
        fields[current].append(line.strip())

    values: dict[str, str] = {}
    for name in GIVE_UP_FIELDS:
        value = " ".join(fields.get(name, [])).strip()
        if len(value) < MIN_GIVE_UP_FIELD_CHARS:
            return None
        values[name] = value
    return GiveUpDiagnosis(**values)


def evaluate_completion_gate(
    *,
    validation_passed: bool,
    response_text: str,
    gate_active: bool,
    attempt: int,
    max_retries: int,
) -> GateDecision:
    """Decide whether a run may complete given its validation outcome.

    - Validation passed (or the gate does not apply to this run): ``allow``.
    - Validation failed with a well-formed diagnosed give-up: ``give_up``.
    - Validation failed, no give-up, demand budget remains:
      ``demand_give_up`` (the loop re-runs with a fix-or-give-up prompt).
    - Validation failed, no give-up, budget exhausted: ``block``.
    """
    if validation_passed:
        return GateDecision(outcome=GATE_ALLOW, reason="validation_passed")
    if not gate_active:
        return GateDecision(outcome=GATE_ALLOW, reason="gate_not_enforced")

    diagnosis = parse_give_up(response_text)
    if diagnosis is not None:
        return GateDecision(
            outcome=GATE_GIVE_UP,
            reason="explicit_diagnosed_give_up",
            diagnosis=diagnosis,
        )

    if int(attempt) <= int(max_retries):
        return GateDecision(
            outcome=GATE_DEMAND_GIVE_UP,
            reason="failed_validation_without_give_up",
        )
    return GateDecision(
        outcome=GATE_BLOCK,
        reason=("Required validation failed and the run returned neither a fix nor an explicit diagnosed give-up."),
    )


def build_give_up_demand_prompt(report: dict[str, Any]) -> str:
    """Prompt for the final gate pass: fix the checks or give up explicitly."""
    lines = [
        "Completion gate: required validation is still failing, so a plain final answer is not accepted.",
        "You must do exactly one of the following:",
        "1. Fix the failing required checks below, then give the final answer.",
        "2. Give up explicitly with a diagnosis, using EXACTLY this structure:",
        "",
        GIVE_UP_MARKER,
        "what_failed: <which required checks or validation failed>",
        "what_was_tried: <concrete remediation attempts you made>",
        "why_blocked: <why you cannot proceed further>",
        "",
        f"Each field needs at least {MIN_GIVE_UP_FIELD_CHARS} characters of real diagnosis.",
        "Required failures:",
    ]
    for check in required_failed_checks(report):
        lines.append(f"- {check.get('title')}: {check.get('detail')}")
    return "\n".join(lines)
