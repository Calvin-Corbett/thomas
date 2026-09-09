from __future__ import annotations

from thomas.workflows.steps import ConditionExecutor


def test_condition_executor_evaluates_basic_comparisons() -> None:
    executor = ConditionExecutor()

    assert (
        executor._evaluate_condition("${status} == 'ready' and ${count} >= 2", {"status": "ready", "count": 3}) is True
    )


def test_condition_executor_rejects_unsafe_calls() -> None:
    executor = ConditionExecutor()

    assert executor._evaluate_condition("__import__('os').system('echo nope')", {}) is False
