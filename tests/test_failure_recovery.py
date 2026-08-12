"""CAP-005 acceptance: failure recovery, alternate-strategy selection, loop-breaking.

Acceptance line: "Require an alternate strategy attempt followed by
contradiction-aware escalation and a failure summary."

Every test drives :class:`RecoveryController` deterministically with an injected
strategy list and a fake executor -- no live model, no network.
"""

from __future__ import annotations

import pytest

from thomas.agent.failure_recovery import (
    Attempt,
    AttemptOutcome,
    EscalationReason,
    FailureSummary,
    RecoveryController,
    Strategy,
)


def _fail(strategy: Strategy, action: str, detail: str = "") -> Attempt:
    return Attempt(strategy=strategy.name, action=action, outcome=AttemptOutcome.FAILURE, detail=detail)


def _ok(strategy: Strategy, action: str, detail: str = "") -> Attempt:
    return Attempt(strategy=strategy.name, action=action, outcome=AttemptOutcome.SUCCESS, detail=detail)


class ScriptedExecutor:
    """Maps a strategy name -> the Attempt to return, and records call order."""

    def __init__(self, script: dict[str, tuple[str, AttemptOutcome]]) -> None:
        self._script = script
        self.calls: list[str] = []

    def __call__(self, strategy: Strategy, context) -> Attempt:
        self.calls.append(strategy.name)
        action, outcome = self._script[strategy.name]
        return Attempt(strategy=strategy.name, action=action, outcome=outcome, detail=f"ran {strategy.name}")


# -- alternate strategy ------------------------------------------------------


def test_failed_attempt_triggers_a_different_alternate_strategy():
    ctrl = RecoveryController(["a", "b", "c"])
    first = ctrl.next_strategy(context=None, tried=[])
    assert first.name == "a"
    # After 'a' fails, the alternate must be a DIFFERENT strategy.
    alternate = ctrl.next_strategy(context=None, tried=["a"])
    assert alternate is not None
    assert alternate.name != "a"
    assert alternate.name == "b"


def test_same_strategy_is_never_retried_across_the_run():
    ctrl = RecoveryController(["a", "b", "c"])
    # Everything fails with a distinct action so no contradiction/cycle fires;
    # the run must walk each strategy exactly once and then exhaust.
    execu = ScriptedExecutor(
        {
            "a": ("act_a", AttemptOutcome.FAILURE),
            "b": ("act_b", AttemptOutcome.FAILURE),
            "c": ("act_c", AttemptOutcome.FAILURE),
        }
    )
    result = ctrl.run(execu)
    assert execu.calls == ["a", "b", "c"]
    assert len(execu.calls) == len(set(execu.calls))  # no repeats
    assert result.escalated is True


def test_next_strategy_returns_none_when_strategies_exhausted():
    ctrl = RecoveryController(["a", "b"])
    assert ctrl.next_strategy(tried=["a", "b"]) is None


# -- loop-breaking: contradiction & cycle ------------------------------------


def test_contradiction_across_attempts_escalates_with_contradiction():
    # 'on' -> action flag=on, 'off' -> flag=off, 'reon' -> flag=on again.
    # The action sequence on, off, on oscillates (thrash) -> contradiction.
    ctrl = RecoveryController(["on", "off", "reon"])
    execu = ScriptedExecutor(
        {
            "on": ("flag=on", AttemptOutcome.FAILURE),
            "off": ("flag=off", AttemptOutcome.FAILURE),
            "reon": ("flag=on", AttemptOutcome.FAILURE),
        }
    )
    result = ctrl.run(execu)
    assert result.escalated is True
    assert result.reason is EscalationReason.CONTRADICTION
    # It genuinely attempted alternates before escalating.
    assert execu.calls == ["on", "off", "reon"]
    assert result.summary.contradiction is not None


def test_repeated_signature_escalates_with_cycle_detected():
    # Two different strategies that converge on the SAME action+outcome:
    # a pure repeat with nothing different in between -> cycle, not contradiction.
    ctrl = RecoveryController(["first", "second", "third"])
    execu = ScriptedExecutor(
        {
            "first": ("retry_fetch", AttemptOutcome.FAILURE),
            "second": ("retry_fetch", AttemptOutcome.FAILURE),
            "third": ("retry_fetch", AttemptOutcome.FAILURE),
        }
    )
    result = ctrl.run(execu)
    assert result.escalated is True
    assert result.reason is EscalationReason.CYCLE_DETECTED
    # Escalated as soon as the second attempt reproduced the first's signature.
    assert execu.calls == ["first", "second"]


# -- strategies exhausted ----------------------------------------------------


def test_exhausting_distinct_strategies_escalates_with_strategies_exhausted():
    ctrl = RecoveryController(["a", "b"])
    execu = ScriptedExecutor(
        {
            "a": ("act_a", AttemptOutcome.FAILURE),
            "b": ("act_b", AttemptOutcome.FAILURE),
        }
    )
    result = ctrl.run(execu)
    assert result.escalated is True
    assert result.reason is EscalationReason.STRATEGIES_EXHAUSTED
    assert result.summary.reason is EscalationReason.STRATEGIES_EXHAUSTED


# -- failure summary ---------------------------------------------------------


def test_failure_summary_enumerates_attempts_outcomes_and_reason():
    ctrl = RecoveryController(["a", "b"], goal="deploy the service")
    execu = ScriptedExecutor(
        {
            "a": ("act_a", AttemptOutcome.FAILURE),
            "b": ("act_b", AttemptOutcome.FAILURE),
        }
    )
    result = ctrl.run(execu)
    summary = result.summary
    assert isinstance(summary, FailureSummary)
    assert summary.goal == "deploy the service"
    # Each strategy + its outcome is enumerated, in order.
    assert [s.strategy for s in summary.strategies_tried] == ["a", "b"]
    assert [s.action for s in summary.strategies_tried] == ["act_a", "act_b"]
    assert all(s.outcome == "failure" for s in summary.strategies_tried)
    # Why it is blocked is present and names the reason.
    assert summary.reason is EscalationReason.STRATEGIES_EXHAUSTED
    assert summary.blocked_because
    # Serializable for logging/telemetry.
    payload = summary.as_dict()
    assert payload["reason"] == "strategies_exhausted"
    assert len(payload["strategies_tried"]) == 2


def test_failure_summary_records_the_detected_contradiction():
    ctrl = RecoveryController(["on", "off", "reon"], goal="stabilize config")
    execu = ScriptedExecutor(
        {
            "on": ("flag=on", AttemptOutcome.FAILURE),
            "off": ("flag=off", AttemptOutcome.FAILURE),
            "reon": ("flag=on", AttemptOutcome.FAILURE),
        }
    )
    summary = ctrl.run(execu).summary
    assert summary.reason is EscalationReason.CONTRADICTION
    assert summary.contradiction is not None
    assert "flag=on" in summary.contradiction
    assert "flag=off" in summary.contradiction


# -- success on alternate does NOT escalate ----------------------------------


def test_success_on_alternate_strategy_does_not_escalate():
    ctrl = RecoveryController(["a", "b", "c"])
    execu = ScriptedExecutor(
        {
            "a": ("act_a", AttemptOutcome.FAILURE),
            "b": ("act_b", AttemptOutcome.SUCCESS),  # the alternate succeeds
            "c": ("act_c", AttemptOutcome.FAILURE),
        }
    )
    result = ctrl.run(execu)
    assert result.succeeded is True
    assert result.escalated is False
    assert result.winning_strategy == "b"
    assert result.summary is None
    # 'c' was never attempted because 'b' resolved the failure.
    assert execu.calls == ["a", "b"]


# -- guardrails --------------------------------------------------------------


def test_duplicate_strategy_names_are_rejected():
    with pytest.raises(ValueError):
        RecoveryController(["a", "a"])


def test_context_aware_selector_is_injectable():
    # A custom selector that prefers strategy 'c' first when the context asks.
    def selector(context, strategies, tried):
        ordered = sorted(strategies, key=lambda s: (s.name != context.get("prefer"), s.name))
        for strat in ordered:
            if strat.name not in tried:
                return strat
        return None

    ctrl = RecoveryController(["a", "b", "c"], selector=selector)
    chosen = ctrl.next_strategy(context={"prefer": "c"}, tried=[])
    assert chosen.name == "c"
