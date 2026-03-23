"""
Event middleware for cross-cutting concerns.

Provides logging, metrics, correlation ID propagation, event enrichment,
deduplication, and causation chain tracking.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ._types import Event


class Middleware(ABC):
    """Abstract base for event middleware."""

    @abstractmethod
    async def before_publish(self, event: Event) -> Event:
        """
        Process event before publishing.

        Args:
            event: The event to process

        Returns:
            Modified event
        """
        ...

    @abstractmethod
    async def after_publish(self, event: Event, success: bool) -> None:
        """
        Process event after publishing.

        Args:
            event: The published event
            success: Whether publish succeeded
        """
        ...


class LoggingMiddleware(Middleware):
    """
    Logs all events published and their results.

    Useful for debugging and audit trails.
    """

    def __init__(self, log_func: Any | None = None) -> None:
        self.log_func = log_func or print

    async def before_publish(self, event: Event) -> Event:
        """Log event before publishing."""
        self.log_func(f"Publishing event: type={event.type}, " f"source={event.source}, id={event.id}")
        return event

    async def after_publish(self, event: Event, success: bool) -> None:
        """Log publication result."""
        status = "succeeded" if success else "failed"
        self.log_func(f"Event {event.id} publication {status}")


class MetricsMiddleware(Middleware):
    """
    Tracks metrics for published events.

    Collects counts by event type and handler latency statistics.
    """

    def __init__(self) -> None:
        self.event_counts: dict[str, int] = {}
        self.event_timings: dict[str, list[float]] = {}
        self.error_counts: dict[str, int] = {}
        self._event_times: dict[str, float] = {}

    async def before_publish(self, event: Event) -> Event:
        """Record start time for event."""
        self._event_times[event.id] = time.time()
        self.event_counts[event.type] = self.event_counts.get(event.type, 0) + 1
        return event

    async def after_publish(self, event: Event, success: bool) -> None:
        """Record latency and errors."""
        if event.id in self._event_times:
            latency = time.time() - self._event_times.pop(event.id)
            if event.type not in self.event_timings:
                self.event_timings[event.type] = []
            self.event_timings[event.type].append(latency)

        if not success:
            self.error_counts[event.type] = self.error_counts.get(event.type, 0) + 1

    def get_stats(self, event_type: str | None = None) -> dict[str, Any]:
        """
        Get collected metrics.

        Args:
            event_type: Specific type to get stats for (None = all)

        Returns:
            Dictionary of metric statistics
        """
        if event_type:
            timings = self.event_timings.get(event_type, [])
            if not timings:
                return {"count": 0, "errors": 0}

            return {
                "count": self.event_counts.get(event_type, 0),
                "errors": self.error_counts.get(event_type, 0),
                "avg_latency_ms": sum(timings) / len(timings) * 1000,
                "max_latency_ms": max(timings) * 1000,
                "min_latency_ms": min(timings) * 1000,
            }

        return {
            "total_events": sum(self.event_counts.values()),
            "total_errors": sum(self.error_counts.values()),
            "by_type": {event_type: self.get_stats(event_type) for event_type in self.event_counts.keys()},
        }


class CorrelationIdMiddleware(Middleware):
    """
    Ensures every event has a correlation ID for tracing related events.

    If an event lacks a correlation ID, one is generated. Propagates
    the correlation ID through causation chains.
    """

    async def before_publish(self, event: Event) -> Event:
        """Ensure event has correlation ID."""
        if not event.correlation_id or event.correlation_id == "":
            event.correlation_id = str(uuid.uuid4())
        return event

    async def after_publish(self, event: Event, success: bool) -> None:
        """No-op for correlation ID middleware."""
        pass


class CausationTrackingMiddleware(Middleware):
    """
    Tracks causation chains linking events together.

    Records which event caused which other events for tracing
    business processes across multiple events.
    """

    def __init__(self) -> None:
        self.causation_chains: dict[str, list[str]] = {}
        self._current_cause: str | None = None

    async def before_publish(self, event: Event) -> Event:
        """Record causation relationship."""
        if self._current_cause and not event.causation_id:
            event.causation_id = self._current_cause

        if event.causation_id:
            if event.causation_id not in self.causation_chains:
                self.causation_chains[event.causation_id] = []
            self.causation_chains[event.causation_id].append(event.id)

        return event

    async def after_publish(self, event: Event, success: bool) -> None:
        """Clear current cause after publish."""
        if success:
            self._current_cause = event.id

    def set_cause(self, event_id: str) -> None:
        """Set the current cause for subsequent publishes."""
        self._current_cause = event_id

    def get_chain(self, event_id: str) -> list[str]:
        """Get all events caused by a given event."""
        return self.causation_chains.get(event_id, [])


class EventEnrichmentMiddleware(Middleware):
    """
    Enriches events with additional context before publishing.

    Can add user context, environment info, timestamps, etc.
    """

    def __init__(self, enrichment_fn: callable | None = None) -> None:
        self.enrichment_fn = enrichment_fn

    async def before_publish(self, event: Event) -> Event:
        """Enrich event metadata."""
        if self.enrichment_fn:
            enrichment = self.enrichment_fn(event)
            if enrichment:
                event.metadata.update(enrichment)

        event.metadata.setdefault("published_at", datetime.utcnow().isoformat())

        return event

    async def after_publish(self, event: Event, success: bool) -> None:
        """No-op."""
        pass


class DeduplicationMiddleware(Middleware):
    """
    Prevents duplicate event processing through idempotency key tracking.

    Events with the same idempotency key within a time window are skipped.
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        self.window_seconds = window_seconds
        self._seen_keys: dict[str, float] = {}

    async def before_publish(self, event: Event) -> Event:
        """Check and record idempotency key."""
        idempotency_key = event.metadata.get("idempotency_key")

        if idempotency_key:
            now = time.time()

            if idempotency_key in self._seen_keys:
                age = now - self._seen_keys[idempotency_key]
                if age < self.window_seconds:
                    event.metadata["deduplicated"] = True
                    return event

            self._seen_keys[idempotency_key] = now

        self._cleanup_expired_keys()
        return event

    async def after_publish(self, event: Event, success: bool) -> None:
        """No-op."""
        pass

    def _cleanup_expired_keys(self) -> None:
        """Remove expired idempotency keys."""
        now = time.time()
        expired = [key for key, timestamp in self._seen_keys.items() if now - timestamp > self.window_seconds]
        for key in expired:
            del self._seen_keys[key]


class MiddlewareChain:
    """
    Manages a chain of middleware for event processing.

    Middleware are applied in registration order before publishing
    and in reverse order after publishing.
    """

    def __init__(self) -> None:
        self._middleware: list[Middleware] = []

    def register(self, middleware: Middleware) -> None:
        """Register middleware in the chain."""
        self._middleware.append(middleware)

    def unregister(self, middleware: Middleware) -> None:
        """Remove middleware from chain."""
        self._middleware.remove(middleware)

    async def before_publish(self, event: Event) -> Event:
        """Apply all middleware before publishing."""
        for middleware in self._middleware:
            event = await middleware.before_publish(event)
        return event

    async def after_publish(self, event: Event, success: bool) -> None:
        """Apply all middleware after publishing (reverse order)."""
        for middleware in reversed(self._middleware):
            await middleware.after_publish(event, success)

    def get_middleware(self, middleware_type: type) -> Middleware | None:
        """Get first middleware of given type."""
        for m in self._middleware:
            if isinstance(m, middleware_type):
                return m
        return None

    def clear(self) -> None:
        """Clear all middleware."""
        self._middleware.clear()
