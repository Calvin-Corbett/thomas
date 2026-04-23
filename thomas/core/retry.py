"""Unified retry and error handling policy for Thomas subsystems.

Provides a consistent RetryPolicy that all subsystems (tools, LLM, memory,
swarm) use for error recovery decisions. Eliminates the inconsistent
error handling where tools retry, LLM stops, and memory swallows errors.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class ErrorSeverity(str, Enum):
    """How bad is this error?"""

    TRANSIENT = "transient"  # Network blip, timeout — retry
    DEGRADED = "degraded"  # Feature unavailable — continue with fallback
    FATAL = "fatal"  # Cannot proceed — stop and report


class ErrorCategory(str, Enum):
    """What kind of subsystem errored?"""

    TOOL = "tool"
    LLM = "llm"
    MEMORY = "memory"
    SWARM = "swarm"
    NETWORK = "network"


@dataclass
class ErrorRecord:
    """A single error occurrence for tracking."""

    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    exception: Exception | None = None
    timestamp: float = field(default_factory=time.monotonic)
    attempt: int = 0
    resolved: bool = False


@dataclass
class RetryPolicy:
    """Unified retry configuration.

    Usage:
        policy = RetryPolicy(max_retries=3, backoff_base=1.0)

        result = await policy.execute(
            fn=some_async_function,
            category=ErrorCategory.TOOL,
            fallback="default value",
        )
    """

    max_retries: int = 2
    backoff_base: float = 1.0  # seconds — doubles each retry
    backoff_max: float = 10.0  # cap
    timeout: float | None = None  # per-attempt timeout in seconds
    on_retry: Callable[[ErrorRecord], None] | None = None
    on_failure: Callable[[ErrorRecord], None] | None = None

    def classify_error(self, exc: Exception) -> ErrorSeverity:
        """Classify an exception into a severity level."""
        name = type(exc).__name__.lower()
        msg = str(exc).lower()

        # Transient — worth retrying
        if any(k in name for k in ("timeout", "connect", "temporary", "throttl")):
            return ErrorSeverity.TRANSIENT
        if any(k in msg for k in ("timeout", "connection refused", "rate limit", "429", "503", "502")):
            return ErrorSeverity.TRANSIENT

        # Fatal — don't retry
        if any(k in name for k in ("auth", "permission", "notfound", "validation")):
            return ErrorSeverity.FATAL
        if any(k in msg for k in ("api key", "unauthorized", "forbidden", "not found", "invalid")):
            return ErrorSeverity.FATAL

        # Default: degraded — try once more then fallback
        return ErrorSeverity.DEGRADED

    async def execute(
        self,
        fn: Callable[..., Any],
        *args: Any,
        category: ErrorCategory = ErrorCategory.TOOL,
        fallback: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a function with retry logic.

        Returns the function result on success, or fallback on exhausted retries.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                if self.timeout is not None:
                    result = await asyncio.wait_for(
                        fn(*args, **kwargs),
                        timeout=self.timeout,
                    )
                else:
                    result = await fn(*args, **kwargs)
                return result

            except asyncio.CancelledError:
                raise  # Never retry cancellation

            except Exception as exc:
                last_error = exc
                severity = self.classify_error(exc)

                record = ErrorRecord(
                    category=category,
                    severity=severity,
                    message=str(exc),
                    exception=exc,
                    attempt=attempt,
                )

                if severity == ErrorSeverity.FATAL:
                    log.error(
                        "[%s] Fatal error (no retry): %s",
                        category.value,
                        exc,
                    )
                    if self.on_failure:
                        self.on_failure(record)
                    break

                if attempt < self.max_retries:
                    delay = min(
                        self.backoff_base * (2**attempt),
                        self.backoff_max,
                    )
                    log.warning(
                        "[%s] %s error (attempt %d/%d, retry in %.1fs): %s",
                        category.value,
                        severity.value,
                        attempt + 1,
                        self.max_retries + 1,
                        delay,
                        exc,
                    )
                    if self.on_retry:
                        self.on_retry(record)
                    await asyncio.sleep(delay)
                else:
                    log.error(
                        "[%s] All %d attempts exhausted: %s",
                        category.value,
                        self.max_retries + 1,
                        exc,
                    )
                    if self.on_failure:
                        record.resolved = False
                        self.on_failure(record)

        # All retries exhausted — return fallback
        if fallback is not None:
            log.warning(
                "[%s] Using fallback value after %d failed attempts",
                category.value,
                self.max_retries + 1,
            )
            return fallback

        # No fallback — re-raise
        if last_error is not None:
            raise last_error
        return None


# ── Pre-configured policies for each subsystem ──────────────

TOOL_RETRY = RetryPolicy(max_retries=2, backoff_base=0.5, timeout=120)
LLM_RETRY = RetryPolicy(max_retries=1, backoff_base=2.0, timeout=180)
MEMORY_RETRY = RetryPolicy(max_retries=1, backoff_base=0.5, timeout=10)
SWARM_RETRY = RetryPolicy(max_retries=2, backoff_base=1.0, timeout=300)
