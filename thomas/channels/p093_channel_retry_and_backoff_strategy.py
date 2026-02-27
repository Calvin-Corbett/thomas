"""Channel retry + backoff strategy.

This module is intentionally channel-agnostic: it contains no Telegram/Slack/etc code.

It provides:
- A validated :class:`RetryPolicy`
- Deterministic backoff schedule generation
- Helpers to execute callables with retry/backoff semantics

Design goals:
- Predictability and testability
- Strict, deterministic validation errors
- Optional jitter that is deterministic when a seed is provided

"""

from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable, Mapping, MutableSequence
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ChannelRetryError(Exception):
    """Base error for retry/backoff strategy."""

    code: str

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ChannelRetryConfigError(ChannelRetryError):
    """Raised when a retry/backoff policy is invalid or missing."""


class ChannelRetryExecutionError(ChannelRetryError):
    """Raised when an operation fails and cannot be (or is no longer) retried."""

    attempts: int
    last_error_type: str
    last_failure_kind: str

    def __init__(
        self,
        *,
        code: str,
        message: str,
        attempts: int,
        last_error_type: str,
        last_failure_kind: str,
    ) -> None:
        super().__init__(code, message)
        self.attempts = attempts
        self.last_error_type = last_error_type
        self.last_failure_kind = last_failure_kind


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configuration for retries.

    Args:
        max_attempts: Total attempts including the initial try. Must be >= 1.
        base_delay_s: Delay (seconds) before the *first* retry.
        max_delay_s: Upper bound for any computed delay.
        backoff_factor: Exponential growth factor. 2.0 is common.
        jitter: Fractional jitter applied to the computed delay. 0.1 means ±10%.
        jitter_seed: Required when jitter > 0 to keep delays deterministic.
        retry_on_status_codes: HTTP-like status codes considered transient.

    Note: Exception-type filtering is intentionally not part of the policy to
    keep it JSON-friendly.
    """

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0
    jitter: float = 0.0
    jitter_seed: int | None = None
    retry_on_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)

    def __post_init__(self) -> None:
        _validate_policy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "base_delay_s": float(self.base_delay_s),
            "max_delay_s": float(self.max_delay_s),
            "backoff_factor": float(self.backoff_factor),
            "jitter": float(self.jitter),
            "jitter_seed": self.jitter_seed,
            "retry_on_status_codes": list(self.retry_on_status_codes),
        }


@dataclass(frozen=True, slots=True)
class BackoffStep:
    """One delay step between attempts."""

    retry_index: int
    delay_s: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "retry_index": self.retry_index,
            "delay_s": float(self.delay_s),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RetryPlan:
    """A fully materialized retry schedule for a policy."""

    policy: RetryPolicy
    steps: tuple[BackoffStep, ...]
    total_delay_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "total_delay_s": float(self.total_delay_s),
        }


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """Record of a failed attempt."""

    attempt: int
    failure_kind: str
    error_type: str
    delay_s: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "failure_kind": self.failure_kind,
            "error_type": self.error_type,
            "delay_s": None if self.delay_s is None else float(self.delay_s),
        }


@dataclass(frozen=True, slots=True)
class RetryOutcome:
    """Outcome of :func:`call_with_retry`.

    When ok is False, value is None and errors contains all recorded failures.
    """

    ok: bool
    attempts: int
    value: Any | None
    errors: tuple[AttemptRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "attempts": self.attempts,
            "value": self.value,
            "errors": [e.to_dict() for e in self.errors],
        }


# ---------------------------------------------------------------------------
# Policy parsing + schema
# ---------------------------------------------------------------------------


def policy_from_mapping(data: Mapping[str, Any] | None) -> RetryPolicy:
    """Create a :class:`RetryPolicy` from a mapping.

    This function is strict on the presence of the mapping itself to provide a
    deterministic "missing config" failure mode.
    """

    if data is None:
        raise ChannelRetryConfigError(
            "missing_config",
            "Retry policy config is required but was not provided.",
        )

    # Allow a few synonyms to be forgiving across config sources.
    def _get(*keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in data:
                return data[k]
        return default

    return RetryPolicy(
        max_attempts=int(_get("max_attempts", "attempts", default=3)),
        base_delay_s=float(_get("base_delay_s", "base_delay", default=0.5)),
        max_delay_s=float(_get("max_delay_s", "max_delay", default=30.0)),
        backoff_factor=float(_get("backoff_factor", "factor", default=2.0)),
        jitter=float(_get("jitter", default=0.0)),
        jitter_seed=(None if _get("jitter_seed", "seed", default=None) is None else int(_get("jitter_seed", "seed"))),
        retry_on_status_codes=tuple(
            int(x)
            for x in _get(
                "retry_on_status_codes",
                "status_codes",
                default=(429, 500, 502, 503, 504),
            )
        ),
    )


def retry_plan_json_schema() -> dict[str, Any]:
    """Return a JSON Schema for a RetryPlan payload."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["policy", "steps", "total_delay_s"],
        "properties": {
            "policy": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "max_attempts",
                    "base_delay_s",
                    "max_delay_s",
                    "backoff_factor",
                    "jitter",
                    "jitter_seed",
                    "retry_on_status_codes",
                ],
                "properties": {
                    "max_attempts": {"type": "integer", "minimum": 1},
                    "base_delay_s": {"type": "number", "minimum": 0},
                    "max_delay_s": {"type": "number", "exclusiveMinimum": 0},
                    "backoff_factor": {"type": "number", "minimum": 1},
                    "jitter": {"type": "number", "minimum": 0, "maximum": 1},
                    "jitter_seed": {"type": ["integer", "null"]},
                    "retry_on_status_codes": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["retry_index", "delay_s", "reason"],
                    "properties": {
                        "retry_index": {"type": "integer", "minimum": 1},
                        "delay_s": {"type": "number", "minimum": 0},
                        "reason": {"type": "string"},
                    },
                },
            },
            "total_delay_s": {"type": "number", "minimum": 0},
        },
    }


# ---------------------------------------------------------------------------
# Backoff computation
# ---------------------------------------------------------------------------


def build_retry_plan(policy: RetryPolicy) -> RetryPlan:
    """Materialize all backoff steps for a policy."""

    steps: list[BackoffStep] = []
    total = 0.0

    # We generate delays between attempts, so there are max_attempts-1 waits.
    for retry_index in range(1, policy.max_attempts):
        delay = compute_exponential_backoff_s(policy, retry_index)
        steps.append(BackoffStep(retry_index=retry_index, delay_s=delay, reason="exponential"))
        total += delay

    return RetryPlan(policy=policy, steps=tuple(steps), total_delay_s=total)


def compute_exponential_backoff_s(policy: RetryPolicy, retry_index: int) -> float:
    """Compute the backoff delay for a given retry index (1 for first retry)."""

    if retry_index < 1:
        raise ChannelRetryConfigError("invalid_retry_index", "retry_index must be >= 1")

    delay = policy.base_delay_s * (policy.backoff_factor ** (retry_index - 1))
    delay = min(delay, policy.max_delay_s)

    if policy.jitter <= 0:
        return float(delay)

    # Jitter is deterministic per retry_index.
    assert policy.jitter_seed is not None  # validated in policy
    rng = random.Random(policy.jitter_seed + retry_index)
    jitter_multiplier = 1.0 + rng.uniform(-policy.jitter, policy.jitter)
    jittered = delay * jitter_multiplier

    # Never go below 0; keep max bound too.
    return float(max(0.0, min(jittered, policy.max_delay_s)))


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------


def classify_failure(exc: BaseException, policy: RetryPolicy) -> tuple[str, float | None]:
    """Classify an exception into a retry kind.

    Returns:
        (kind, suggested_delay_s)

    kind is one of: "rate_limit", "server", "network", "unknown".

    suggested_delay_s is used when the error provides a server-directed wait
    time (e.g. Telegram RetryAfter) and will be clamped by max_delay_s.
    """

    # Rate limit style: has retry_after attribute.
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        try:
            ra = float(retry_after)
        except (TypeError, ValueError):
            ra = None
        if ra is not None and ra > 0:
            return "rate_limit", float(min(ra, policy.max_delay_s))
        return "rate_limit", None

    # HTTP-ish style: has status_code.
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        if status_code in policy.retry_on_status_codes:
            if status_code == 429:
                return "rate_limit", None
            return "server", None
        return "unknown", None

    # Common transient built-ins.
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "network", None

    # Optional third-party clients.
    try:
        import requests  # type: ignore

        if isinstance(exc, requests.exceptions.RequestException):
            return "network", None
    except (ImportError, AttributeError, RuntimeError):
        pass

    try:
        import httpx  # type: ignore

        if isinstance(exc, httpx.TransportError):
            return "network", None
    except (ImportError, AttributeError, RuntimeError):
        pass

    try:
        import aiohttp  # type: ignore

        if isinstance(exc, aiohttp.ClientError):
            return "network", None
    except (ImportError, AttributeError, RuntimeError):
        pass

    return "unknown", None


def is_retryable_exception(exc: BaseException, policy: RetryPolicy) -> bool:
    kind, _status_delay = classify_failure(exc, policy)
    if kind in {"rate_limit", "server", "network"}:
        return True

    # Some libraries surface status code on the exception.
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and status_code in policy.retry_on_status_codes


def compute_retry_delay_s(policy: RetryPolicy, retry_index: int, exc: BaseException) -> tuple[float, str]:
    """Compute the delay for the *next* retry after a failure."""

    kind, suggested = classify_failure(exc, policy)
    if kind == "rate_limit" and suggested is not None:
        return float(min(suggested, policy.max_delay_s)), "retry_after"

    return compute_exponential_backoff_s(policy, retry_index), "exponential"


# ---------------------------------------------------------------------------
# Execution helper
# ---------------------------------------------------------------------------


def call_with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryOutcome:
    """Call operation with retry/backoff.

    Returns a :class:`RetryOutcome`. This function *never* raises the original
    exception; use :func:`call_with_retry_or_raise` when you want typed errors.

    The provided sleep function is injected for testability.
    """

    errors: MutableSequence[AttemptRecord] = []

    for attempt in range(1, policy.max_attempts + 1):
        try:
            value = operation()
            return RetryOutcome(ok=True, attempts=attempt, value=value, errors=tuple(errors))
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as exc:
            kind, _ = classify_failure(exc, policy)
            retryable = is_retryable_exception(exc, policy)

            if attempt >= policy.max_attempts or not retryable:
                errors.append(
                    AttemptRecord(
                        attempt=attempt,
                        failure_kind=kind,
                        error_type=exc.__class__.__name__,
                        delay_s=None,
                    )
                )
                return RetryOutcome(ok=False, attempts=attempt, value=None, errors=tuple(errors))

            retry_index = attempt  # after attempt 1 fails, this is retry #1
            delay_s, _reason = compute_retry_delay_s(policy, retry_index, exc)

            errors.append(
                AttemptRecord(
                    attempt=attempt,
                    failure_kind=kind,
                    error_type=exc.__class__.__name__,
                    delay_s=delay_s,
                )
            )

            sleep(delay_s)

    # Unreachable, but keeps type checkers happy.
    return RetryOutcome(ok=False, attempts=policy.max_attempts, value=None, errors=tuple(errors))


def call_with_retry_or_raise(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call operation with retry/backoff.

    Returns the operation result on success.

    Raises:
        ChannelRetryExecutionError: when the operation cannot be retried or
            retries are exhausted.
    """

    outcome = call_with_retry(operation, policy=policy, sleep=sleep)
    if outcome.ok:
        return outcome.value  # type: ignore[return-value]

    last = outcome.errors[-1]
    if outcome.attempts >= policy.max_attempts:
        code = "retry_exhausted"
        msg = f"Operation failed after {outcome.attempts} attempts."
    else:
        code = "non_retryable_failure"
        msg = "Operation failed with a non-retryable error."

    raise ChannelRetryExecutionError(
        code=code,
        message=msg,
        attempts=outcome.attempts,
        last_error_type=last.error_type,
        last_failure_kind=last.failure_kind,
    )


# ---------------------------------------------------------------------------
# Internal validation
# ---------------------------------------------------------------------------


def _validate_policy(policy: RetryPolicy) -> None:
    if not isinstance(policy.max_attempts, int) or policy.max_attempts < 1:
        raise ChannelRetryConfigError("invalid_max_attempts", "max_attempts must be an integer >= 1")

    for name in ("base_delay_s", "max_delay_s", "backoff_factor", "jitter"):
        value = getattr(policy, name)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ChannelRetryConfigError(f"invalid_{name}", f"{name} must be a finite number")

    if policy.base_delay_s < 0:
        raise ChannelRetryConfigError("invalid_base_delay", "base_delay_s must be >= 0")

    if policy.max_delay_s <= 0:
        raise ChannelRetryConfigError("invalid_max_delay", "max_delay_s must be > 0")

    if policy.backoff_factor < 1:
        raise ChannelRetryConfigError("invalid_backoff_factor", "backoff_factor must be >= 1")

    if not (0.0 <= policy.jitter <= 1.0):
        raise ChannelRetryConfigError("invalid_jitter", "jitter must be between 0 and 1")

    if policy.jitter > 0 and policy.jitter_seed is None:
        raise ChannelRetryConfigError(
            "missing_jitter_seed",
            "jitter_seed is required when jitter > 0 to keep delays deterministic",
        )

    for code in policy.retry_on_status_codes:
        if not isinstance(code, int) or code < 100 or code > 599:
            raise ChannelRetryConfigError(
                "invalid_status_code",
                "retry_on_status_codes must contain valid HTTP status codes",
            )


# ---------------------------------------------------------------------------
# Convenience for callers who want JSON
# ---------------------------------------------------------------------------


def dumps_retry_plan(plan: RetryPlan, *, indent: int | None = 2) -> str:
    """Serialize a RetryPlan as JSON."""

    return json.dumps(plan.to_dict(), indent=indent, sort_keys=True)


# ---------------------------------------------------------------------------
# Compatibility aliases
# ---------------------------------------------------------------------------


def compute_retry_plan(policy: RetryPolicy) -> RetryPlan:
    """Alias for :func:`build_retry_plan`."""

    return build_retry_plan(policy)


def retry_and_backoff(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Alias for :func:`call_with_retry_or_raise`."""

    return call_with_retry_or_raise(operation, policy=policy, sleep=sleep)
