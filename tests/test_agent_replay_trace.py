from __future__ import annotations

import pytest

from tests._agent_replay_trace import (
    TraceValidationError,
    compare_worker_traces,
    normalize_worker_trace,
    validate_worker_trace,
)


def _raw_actions() -> list[dict[str, object]]:
    return [
        {
            "task_id": "task-123",
            "action_id": "verify",
            "action_type": "pytest",
            "status": "succeeded",
            "timestamp": "2026-06-27T22:10:02Z",
            "order": 2,
            "input_summary": "Run focused replay trace tests",
            "output_summary": "4 tests passed",
            "verification": {"outcome": "passed", "summary": "pytest green"},
        },
        {
            "task_id": "task-123",
            "action_id": "edit",
            "action_type": "apply_patch",
            "status": "succeeded",
            "timestamp": "2026-06-27T22:10:01Z",
            "order": 1,
            "input_summary": "Add worker trace helper",
            "output_summary": "Created replay trace fixture module",
            "verification": {"outcome": "passed"},
        },
    ]


def test_worker_trace_matches_golden_fixture() -> None:
    golden = normalize_worker_trace(_raw_actions())
    actual = normalize_worker_trace(list(reversed(_raw_actions())))

    validate_worker_trace(actual)

    assert compare_worker_traces(actual, golden) == []


def test_worker_trace_rejects_missing_required_field() -> None:
    actions = _raw_actions()
    del actions[0]["output_summary"]

    with pytest.raises(TraceValidationError, match="output_summary is required"):
        normalize_worker_trace(actions)


def test_worker_trace_reports_clear_mismatches() -> None:
    golden = normalize_worker_trace(_raw_actions())
    actual_actions = _raw_actions()
    actual_actions[0]["verification"] = {"outcome": "failed", "summary": "pytest failed"}
    actual = normalize_worker_trace(actual_actions)

    mismatches = compare_worker_traces(actual, golden)

    assert mismatches == [
        {
            "path": "$.actions[1].verification.outcome",
            "kind": "value",
            "expected": "passed",
            "actual": "failed",
        },
        {
            "path": "$.actions[1].verification.summary",
            "kind": "value",
            "expected": "pytest green",
            "actual": "pytest failed",
        },
    ]


def test_worker_trace_keeps_stable_ordering_and_key_order() -> None:
    trace = normalize_worker_trace(_raw_actions())

    assert [action["action_id"] for action in trace["actions"]] == ["edit", "verify"]
    assert list(trace) == ["schema", "task_id", "actions"]
    assert list(trace["actions"][0]) == [
        "order",
        "timestamp",
        "task_id",
        "action_id",
        "action_type",
        "status",
        "input_summary",
        "output_summary",
        "verification",
    ]
