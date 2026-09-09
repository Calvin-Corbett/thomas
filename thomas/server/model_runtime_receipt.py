"""Secret-safe observed model receipts shared by chat and background workers."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_CONFIG_KEYS = ("profile", "provider", "model")
_ATTEMPT_KEYS = ("profile", "provider", "model", "status", "retryable", "cooldown_remaining_s")
_SAFE_TRACE_ERRORS = {
    "invalid_runtime_trace",
    "llm_unavailable",
    "runtime_trace_failed",
    "runtime_trace_unavailable",
}


def _public_row(value: Any, allowed: tuple[str, ...]) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        key: row[key] for key in allowed if key in row and isinstance(row[key], (str, int, float, bool, type(None)))
    }


def sanitize_model_runtime_trace(
    trace: Any,
    *,
    requested_profile: str = "",
    requested_model_id: str = "",
) -> dict[str, Any]:
    """Whitelist runtime attribution fields and discard URLs, secrets, and raw errors."""

    row = trace if isinstance(trace, dict) else {}
    requested = _public_row(row.get("requested"), _CONFIG_KEYS)
    if requested_profile:
        requested.setdefault("profile", str(requested_profile))
    if requested_model_id:
        requested.setdefault("model", str(requested_model_id))
    attempts = row.get("attempts")
    receipt: dict[str, Any] = {
        "requested": requested,
        "active": _public_row(row.get("active"), _CONFIG_KEYS),
        "failover_enabled": bool(row.get("failover_enabled")),
        "failover_used": bool(row.get("failover_used")),
        "attempts": [
            _public_row(attempt, _ATTEMPT_KEYS)
            for attempt in (attempts if isinstance(attempts, list) else [])
            if isinstance(attempt, dict)
        ],
    }
    trace_error = row.get("trace_error")
    if isinstance(trace_error, str) and trace_error:
        receipt["trace_error"] = trace_error if trace_error in _SAFE_TRACE_ERRORS else "runtime_trace_failed"
    return receipt


def validate_model_runtime_receipt(
    receipt: Any,
    *,
    requested_profile: str = "",
    requested_model_id: str = "",
    require_requested_active_match: bool = True,
) -> dict[str, Any] | None:
    """Return a secret-safe, internally consistent receipt or ``None``.

    Empty traces, stale/error-only traces, requested-model mismatches, and
    receipts without a successful attempt are not proof that a worker used a
    model. Validation is repeated at persistence boundaries so a compromised or
    regressed worker cannot smuggle raw provider fields into delegation state.
    """

    # Validate what the producer actually reported. Do not overwrite requested
    # fields with the caller's expectation before comparing them.
    safe = sanitize_model_runtime_trace(receipt)
    if safe.get("trace_error"):
        return None
    requested = safe.get("requested") if isinstance(safe.get("requested"), dict) else {}
    active = safe.get("active") if isinstance(safe.get("active"), dict) else {}
    expected_profile = str(requested_profile or requested.get("profile") or "")
    expected_model = str(requested_model_id or requested.get("model") or "")
    if not expected_profile or not expected_model:
        return None
    if str(requested.get("profile") or "") != expected_profile:
        return None
    if str(requested.get("model") or "") != expected_model:
        return None
    if not all(str(active.get(key) or "") for key in _CONFIG_KEYS):
        return None
    if require_requested_active_match and (
        str(active.get("profile") or "") != expected_profile or str(active.get("model") or "") != expected_model
    ):
        return None
    successful_attempt = any(
        str(attempt.get("status") or "") == "success"
        and all(str(attempt.get(key) or "") == str(active.get(key) or "") for key in _CONFIG_KEYS)
        for attempt in safe.get("attempts", [])
        if isinstance(attempt, dict)
    )
    return safe if successful_attempt else None


def model_runtime_receipt(
    llm: Any,
    *,
    requested_profile: str = "",
    requested_model_id: str = "",
) -> dict[str, Any]:
    """Read an LLM runtime trace without allowing telemetry to break the user turn."""

    if llm is None:
        return sanitize_model_runtime_trace(
            {"trace_error": "llm_unavailable"},
            requested_profile=requested_profile,
            requested_model_id=requested_model_id,
        )
    trace_fn = getattr(llm, "runtime_trace", None)
    if not callable(trace_fn):
        return sanitize_model_runtime_trace(
            {
                "failover_enabled": bool(getattr(llm, "_failover_enabled", False)),
                "trace_error": "runtime_trace_unavailable",
            },
            requested_profile=requested_profile,
            requested_model_id=requested_model_id,
        )
    try:
        trace = trace_fn()
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        log.warning("Model runtime trace failed at the telemetry boundary (%s)", type(exc).__name__)
        trace = {
            "failover_enabled": bool(getattr(llm, "_failover_enabled", False)),
            "trace_error": "runtime_trace_failed",
        }
    if not isinstance(trace, dict):
        trace = {"trace_error": "invalid_runtime_trace"}
    return sanitize_model_runtime_trace(
        trace,
        requested_profile=requested_profile,
        requested_model_id=requested_model_id,
    )
