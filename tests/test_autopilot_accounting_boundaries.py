"""Replayed receipts and restart wrappers cannot erase executed continuations."""

from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.autopilot_continuation_history import (
    executed_runs_since_instruction,
    ran_continuations,
)
from thomas.server.routes.autopilot_goal import STEER_LINE


def _ran(run_id: str) -> dict:
    return {
        "role": "agent",
        "run_id": run_id,
        "transcript": '{"fc":"tool","name":"check.run","input":{}}',
        "outcome": "failed",
        "reason": f"{run_id} ended",
    }


def test_replayed_steering_in_restart_keeps_executed_runs() -> None:
    steered = f"{ap.CONTINUATION_PREFIX}\n\n{STEER_LINE}make it blue"
    turns = [
        {"role": "user", "text": steered},
        _ran("before-restart"),
        {"role": "user", "text": f"{ap.RESTART_PREFIX} {ap.RESTART_MARK}{steered}"},
        _ran("after-restart"),
    ]
    assert [run["run_id"] for run in executed_runs_since_instruction(turns)] == [
        "before-restart",
        "after-restart",
    ]
    turns.extend(
        (
            {"role": "user", "text": f"{ap.RESTART_PREFIX}\n\n{STEER_LINE}make it red"},
            _ran("new-instruction"),
        )
    )
    assert [run["run_id"] for run in executed_runs_since_instruction(turns)] == ["new-instruction"]


def test_duplicate_receipt_does_not_consume_next_continuation() -> None:
    continuation = {"role": "user", "text": ap.CONTINUATION_PREFIX}
    turns = [continuation, _ran("first"), continuation, _ran("first"), _ran("second")]
    assert [run["run_id"] for run in ran_continuations(turns)] == ["first", "second"]


def test_nested_restart_preserves_replayed_steering_history() -> None:
    steered = f"{ap.CONTINUATION_PREFIX}\n\n{STEER_LINE}make it blue"
    restart = f"{ap.RESTART_PREFIX} {ap.RESTART_MARK}{steered}"
    turns = [
        {"role": "user", "text": steered},
        _ran("first"),
        {"role": "user", "text": restart},
        _ran("second"),
        {"role": "user", "text": f"{ap.RESTART_PREFIX} {ap.RESTART_MARK}{restart}"},
        _ran("third"),
    ]
    assert len(executed_runs_since_instruction(turns)) == 3
