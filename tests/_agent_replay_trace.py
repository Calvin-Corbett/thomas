from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

TRACE_SCHEMA = "thomas.worker_trace.v1"
ACTION_STATUSES = {"pending", "running", "succeeded", "failed", "blocked", "skipped"}
VERIFICATION_OUTCOMES = {"passed", "failed", "skipped", "unknown"}
REQUIRED_ACTION_FIELDS = (
    "task_id",
    "action_id",
    "action_type",
    "status",
    "timestamp",
    "order",
    "input_summary",
    "output_summary",
    "verification",
)
CANONICAL_ACTION_KEYS = (
    "order",
    "timestamp",
    "task_id",
    "action_id",
    "action_type",
    "status",
    "input_summary",
    "output_summary",
    "verification",
)


class TraceValidationError(ValueError):
    """Raised when a worker replay trace is missing required golden data."""


def normalize_worker_trace(actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a deterministic Thomas worker replay trace from action records."""

    normalized_actions = [_normalize_action(action, index) for index, action in enumerate(actions)]
    if not normalized_actions:
        raise TraceValidationError("trace must include at least one worker action")

    task_ids = {str(action["task_id"]) for action in normalized_actions}
    if len(task_ids) != 1:
        raise TraceValidationError("all worker actions in one trace must share task_id")

    normalized_actions.sort(
        key=lambda action: (
            int(action["order"]),
            str(action["timestamp"]),
            str(action["action_id"]),
        )
    )

    trace = {
        "schema": TRACE_SCHEMA,
        "task_id": normalized_actions[0]["task_id"],
        "actions": normalized_actions,
    }
    validate_worker_trace(trace)
    return trace


def validate_worker_trace(trace: Mapping[str, Any]) -> None:
    """Validate the minimal golden-fixture shape for a worker replay trace."""

    if trace.get("schema") != TRACE_SCHEMA:
        raise TraceValidationError(f"trace.schema must be {TRACE_SCHEMA!r}")
    task_id = _require_text(trace, "task_id", "trace")
    actions = trace.get("actions")
    if not isinstance(actions, list) or not actions:
        raise TraceValidationError("trace.actions must be a non-empty list")

    seen_action_ids: set[str] = set()
    previous_order: int | None = None
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping):
            raise TraceValidationError(f"actions[{index}] must be a mapping")
        for field in CANONICAL_ACTION_KEYS:
            if field not in action:
                raise TraceValidationError(f"actions[{index}].{field} is required")
        if action["task_id"] != task_id:
            raise TraceValidationError(f"actions[{index}].task_id does not match trace.task_id")

        action_id = _require_text(action, "action_id", f"actions[{index}]")
        if action_id in seen_action_ids:
            raise TraceValidationError(f"actions[{index}].action_id duplicates {action_id!r}")
        seen_action_ids.add(action_id)

        _require_text(action, "action_type", f"actions[{index}]")
        _require_text(action, "timestamp", f"actions[{index}]")
        _require_text(action, "input_summary", f"actions[{index}]")
        _require_text(action, "output_summary", f"actions[{index}]")
        status = _require_text(action, "status", f"actions[{index}]")
        if status not in ACTION_STATUSES:
            raise TraceValidationError(f"actions[{index}].status has unsupported value {status!r}")

        order = _coerce_order(action["order"], f"actions[{index}].order")
        if previous_order is not None and order < previous_order:
            raise TraceValidationError("trace actions must be sorted by non-decreasing order")
        previous_order = order

        verification = action["verification"]
        if not isinstance(verification, Mapping):
            raise TraceValidationError(f"actions[{index}].verification must be a mapping")
        outcome = _require_text(verification, "outcome", f"actions[{index}].verification")
        if outcome not in VERIFICATION_OUTCOMES:
            raise TraceValidationError(
                f"actions[{index}].verification.outcome has unsupported value {outcome!r}"
            )


def compare_worker_traces(
    actual: Mapping[str, Any],
    golden: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Compare two validated traces and return deterministic mismatch records."""

    validate_worker_trace(actual)
    validate_worker_trace(golden)
    mismatches: list[dict[str, Any]] = []
    _compare_values(actual, golden, "$", mismatches)
    return mismatches


def _normalize_action(action: Mapping[str, Any], index: int) -> dict[str, Any]:
    for field in REQUIRED_ACTION_FIELDS:
        if field not in action:
            raise TraceValidationError(f"actions[{index}].{field} is required")

    verification = action["verification"]
    if not isinstance(verification, Mapping):
        raise TraceValidationError(f"actions[{index}].verification must be a mapping")
    outcome = _require_text(verification, "outcome", f"actions[{index}].verification")
    normalized_verification = {"outcome": outcome}
    if "summary" in verification:
        normalized_verification["summary"] = str(verification["summary"])

    return {
        "order": _coerce_order(action["order"], f"actions[{index}].order"),
        "timestamp": _require_text(action, "timestamp", f"actions[{index}]"),
        "task_id": _require_text(action, "task_id", f"actions[{index}]"),
        "action_id": _require_text(action, "action_id", f"actions[{index}]"),
        "action_type": _require_text(action, "action_type", f"actions[{index}]"),
        "status": _require_text(action, "status", f"actions[{index}]"),
        "input_summary": _require_text(action, "input_summary", f"actions[{index}]"),
        "output_summary": _require_text(action, "output_summary", f"actions[{index}]"),
        "verification": normalized_verification,
    }


def _require_text(source: Mapping[str, Any], key: str, path: str) -> str:
    value = source.get(key)
    if value is None or str(value).strip() == "":
        raise TraceValidationError(f"{path}.{key} must be non-empty text")
    return str(value)


def _coerce_order(value: Any, path: str) -> int:
    if isinstance(value, bool):
        raise TraceValidationError(f"{path} must be an integer")
    try:
        order = int(value)
    except (TypeError, ValueError) as exc:
        raise TraceValidationError(f"{path} must be an integer") from exc
    if order < 0:
        raise TraceValidationError(f"{path} must be zero or greater")
    return order


def _compare_values(
    actual: Any,
    golden: Any,
    path: str,
    mismatches: list[dict[str, Any]],
) -> None:
    if isinstance(actual, Mapping) and isinstance(golden, Mapping):
        actual_keys = set(actual)
        golden_keys = set(golden)
        for key in sorted(golden_keys - actual_keys):
            mismatches.append({"path": f"{path}.{key}", "kind": "missing", "expected": golden[key], "actual": None})
        for key in sorted(actual_keys - golden_keys):
            mismatches.append({"path": f"{path}.{key}", "kind": "extra", "expected": None, "actual": actual[key]})
        for key in sorted(actual_keys & golden_keys):
            _compare_values(actual[key], golden[key], f"{path}.{key}", mismatches)
        return

    if isinstance(actual, list) and isinstance(golden, list):
        shared = min(len(actual), len(golden))
        for index in range(shared):
            _compare_values(actual[index], golden[index], f"{path}[{index}]", mismatches)
        for index in range(shared, len(golden)):
            mismatches.append({"path": f"{path}[{index}]", "kind": "missing", "expected": golden[index], "actual": None})
        for index in range(shared, len(actual)):
            mismatches.append({"path": f"{path}[{index}]", "kind": "extra", "expected": None, "actual": actual[index]})
        return

    if actual != golden:
        mismatches.append({"path": path, "kind": "value", "expected": golden, "actual": actual})
