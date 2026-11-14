"""The run ledger: the one thing that may advance a step.

There is no method here for declaring a step finished. ``attempt`` evaluates the
open step's gates and the ledger moves or does not. An agent at the far end of a
long context has nothing to call that would let it skip ahead, and nothing it
says is read as progress.

When a gate outlasts its retries the run does not hang. It resolves, and how it
resolves is read off the autonomy dial in :mod:`thomas.core.autonomy` rather than
from a second setting that would drift from it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .gates import GateContext, Verdict, evaluate_gate
from .model import Lane, Step

LOCKED = "locked"
OPEN = "open"
PASSED = "passed"
BLOCKED = "blocked"
WAIVED = "waived"

#: How a blocked step resolves.
PARK = "park"  # surface to the human and wait
WAIVE = "waive"  # record the skip and keep moving

DEFAULT_ATTEMPTS_PER_STEP = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class StepOutcome:
    advanced: bool
    step_id: str
    failures: list[str] = field(default_factory=list)
    blocked: bool = False


@dataclass(frozen=True)
class CompletionVerdict:
    passed: bool
    clean: bool
    reason: str


@dataclass
class RunLedger:
    """One job run against one lane."""

    lane: Lane
    autonomy_level: int
    run_id: str
    attempts_per_step: int = DEFAULT_ATTEMPTS_PER_STEP

    def __post_init__(self) -> None:
        self._states: dict[str, str] = {step.id: LOCKED for step in self.lane.steps}
        self._attempts: dict[str, int] = {step.id: 0 for step in self.lane.steps}
        self._last_failures: dict[str, list[str]] = {}
        self.waivers: list[dict[str, Any]] = []
        if self.lane.steps:
            self._states[self.lane.steps[0].id] = OPEN

    # ── where the run is ──────────────────────────────────────────────────────

    def open_step(self) -> Step | None:
        for step in self.lane.steps:
            if self._states[step.id] in (OPEN, BLOCKED):
                return step
        return None

    def state_of(self, step_id: str) -> str:
        return self._states.get(step_id, LOCKED)

    def is_blocked(self) -> bool:
        step = self.open_step()
        return bool(step and self._states[step.id] == BLOCKED)

    def current_brief(self) -> str:
        """The text re-presented to the agent every turn.

        Regenerated from the lane each call, so it cannot decay with context
        length -- the agent is told what is required rather than asked to recall
        it.
        """

        step = self.open_step()
        if step is None:
            return "Every step is resolved. Nothing is open."
        lines = [f"Open step: {step.name} ({step.id}). To advance it, all of these must hold:"]
        for gate in step.gates:
            mark = "" if gate.proven else "  [unproven: its pass will not count yet]"
            lines.append(f"  - {gate.description}{mark}")
        return "\n".join(lines)

    # ── the only way forward ──────────────────────────────────────────────────

    def attempt(
        self,
        ctx: GateContext,
        judge: Callable[[str, GateContext], Verdict] | None = None,
    ) -> StepOutcome:
        """Evaluate the open step's gates and advance only if every one counts."""

        step = self.open_step()
        if step is None:
            return StepOutcome(advanced=False, step_id="", failures=["nothing is open"])

        self._attempts[step.id] += 1
        failures: list[str] = []
        for gate in step.gates:
            verdict = evaluate_gate(gate, ctx, judge)
            gate.checked_count += 1
            if not verdict.passed:
                gate.fired_count += 1
            if not verdict.counts:
                failures.append(f"{gate.id}: {verdict.reason}")

        if failures:
            self._last_failures[step.id] = failures
            if self._attempts[step.id] >= self.attempts_per_step:
                self._states[step.id] = BLOCKED
                return StepOutcome(advanced=False, step_id=step.id, failures=failures, blocked=True)
            self._states[step.id] = OPEN
            return StepOutcome(advanced=False, step_id=step.id, failures=failures)

        self._states[step.id] = PASSED
        self._last_failures.pop(step.id, None)
        self._open_next_after(step)
        return StepOutcome(advanced=True, step_id=step.id)

    def _open_next_after(self, step: Step) -> None:
        index = self.lane.steps.index(step)
        for later in self.lane.steps[index + 1 :]:
            if self._states[later.id] == LOCKED:
                self._states[later.id] = OPEN
                return

    # ── what a block does ─────────────────────────────────────────────────────

    def block_policy(self, *, user_present: bool) -> str:
        """Read the resolution off the autonomy dial.

        L1 is read-only and L2/L3 stop when genuinely blocked. L4 keeps momentum
        -- but its own directive prefers native authentication to stopping, so
        when a human is actually there a two-second tap beats a waiver.
        """

        if self.autonomy_level >= 4 and not user_present:
            return WAIVE
        return PARK

    def resolve_block(self, *, user_present: bool = False, reason: str = "") -> str:
        step = self.open_step()
        if step is None or self._states[step.id] != BLOCKED:
            return PARK
        decision = self.block_policy(user_present=user_present)
        if decision == PARK:
            return PARK
        self._states[step.id] = WAIVED
        self.waivers.append(
            {
                "step_id": step.id,
                "step_name": step.name,
                "at": _now(),
                "autonomy_level": self.autonomy_level,
                "reason": reason or "; ".join(self._last_failures.get(step.id, [])) or "gate outlasted its retries",
            }
        )
        self._open_next_after(step)
        return WAIVE

    # ── how the run reports ───────────────────────────────────────────────────

    def completion_verdict(self) -> CompletionVerdict:
        unresolved = [s.id for s in self.lane.steps if self._states[s.id] not in (PASSED, WAIVED)]
        if unresolved:
            return CompletionVerdict(
                passed=False,
                clean=False,
                reason=f"unresolved step(s): {', '.join(unresolved)}",
            )
        if self.waivers:
            return CompletionVerdict(
                passed=True,
                clean=False,
                reason=f"finished with {len(self.waivers)} waived step(s)",
            )
        return CompletionVerdict(passed=True, clean=True, reason="every step passed its gates")

    def report_headline(self) -> str:
        """A waived step leads the report. Momentum must not become amnesia."""

        count = len(self.waivers)
        if count:
            names = ", ".join(w["step_name"] for w in self.waivers)
            plural = "step" if count == 1 else "steps"
            return f"{count} {plural} waived, not verified: {names}"
        verdict = self.completion_verdict()
        return "Every step passed its gates." if verdict.clean else verdict.reason
