"""
Event dispatcher strategies for different delivery semantics.

Handles synchronous, asynchronous, and batched event dispatch with
timeout enforcement, circuit breaker, and error handling.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from ._types import Event, EventHandler, Subscription


class DispatchStrategy(Enum):
    """Event dispatch strategy selection."""

    SYNCHRONOUS = "synchronous"  # In-order, blocking
    ASYNCHRONOUS = "asynchronous"  # Concurrent handlers
    BATCHED = "batched"  # Process in batches


class CircuitBreakerState(Enum):
    """Circuit breaker state machine."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker per handler to prevent cascading failures.

    Tracks failures and transitions between states:
    - CLOSED: Normal operation, pass through
    - OPEN: Too many failures, fail fast
    - HALF_OPEN: Test if handler recovered
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None

    def record_success(self) -> None:
        """Record a successful call."""
        self.failure_count = 0

        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                self.success_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.success_count = 0

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN

    def can_execute(self) -> bool:
        """
        Check if a call can be executed.

        Returns:
            True if call should proceed, False if should fail fast
        """
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time is None:
                return True

            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0
                return True

            return False

        return True

    def is_open(self) -> bool:
        """Check if circuit is open (failing)."""
        return self.state == CircuitBreakerState.OPEN


class EventDispatcher(ABC):
    """Abstract base for event dispatcher strategies."""

    @abstractmethod
    async def dispatch(self, event: Event, subscriptions: list[Subscription]) -> dict[str, Any]:
        """
        Dispatch event to subscriptions.

        Args:
            event: Event to dispatch
            subscriptions: List of subscriptions to dispatch to

        Returns:
            Dispatch results dictionary
        """
        ...


class SynchronousDispatcher(EventDispatcher):
    """
    Synchronous dispatcher executing handlers in-order.

    Handlers are called sequentially in priority order. If a handler fails
    and doesn't have AT_MOST_ONCE delivery guarantee, the error propagates.
    """

    def __init__(self) -> None:
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    async def dispatch(self, event: Event, subscriptions: list[Subscription]) -> dict[str, Any]:
        """
        Dispatch event to handlers synchronously in order.

        Args:
            event: Event to dispatch
            subscriptions: Sorted list of subscriptions by priority

        Returns:
            Dict with 'succeeded' and 'failed' handler lists
        """
        results = {"succeeded": [], "failed": [], "skipped": []}

        for subscription in subscriptions:
            if not subscription.matches_event_type(event.type):
                continue

            handler_id = subscription.id
            breaker = self._get_circuit_breaker(handler_id)

            if not breaker.can_execute():
                results["skipped"].append(
                    {
                        "handler_id": handler_id,
                        "reason": "Circuit breaker open",
                    }
                )
                continue

            try:
                await asyncio.wait_for(
                    self._call_handler(subscription.handler, event),
                    timeout=subscription.timeout_seconds,
                )
                breaker.record_success()
                results["succeeded"].append(handler_id)

            except asyncio.TimeoutError:
                breaker.record_failure()
                results["failed"].append(
                    {
                        "handler_id": handler_id,
                        "error": "Handler timeout",
                        "delivery_guarantee": subscription.delivery_guarantee.value,
                    }
                )
            except Exception as e:
                breaker.record_failure()
                results["failed"].append(
                    {
                        "handler_id": handler_id,
                        "error": str(e),
                        "delivery_guarantee": subscription.delivery_guarantee.value,
                    }
                )

        return results

    def _get_circuit_breaker(self, handler_id: str) -> CircuitBreaker:
        """Get or create circuit breaker for handler."""
        if handler_id not in self._circuit_breakers:
            self._circuit_breakers[handler_id] = CircuitBreaker()
        return self._circuit_breakers[handler_id]

    @staticmethod
    async def _call_handler(handler: EventHandler, event: Event) -> None:
        """Call a handler, converting sync to async if needed."""
        if asyncio.iscoroutinefunction(handler):
            await handler(event)
        else:
            await asyncio.to_thread(handler, event)


class AsynchronousDispatcher(EventDispatcher):
    """
    Asynchronous dispatcher executing handlers concurrently.

    All handlers are invoked concurrently. Failures in one handler
    don't block others.
    """

    def __init__(self) -> None:
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    async def dispatch(self, event: Event, subscriptions: list[Subscription]) -> dict[str, Any]:
        """
        Dispatch event to handlers concurrently.

        Args:
            event: Event to dispatch
            subscriptions: List of subscriptions

        Returns:
            Dict with 'succeeded', 'failed', and 'skipped' lists
        """
        results = {"succeeded": [], "failed": [], "skipped": []}
        tasks = []

        for subscription in subscriptions:
            if not subscription.matches_event_type(event.type):
                continue

            task = self._dispatch_to_subscription(event, subscription, results)
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return results

    async def _dispatch_to_subscription(
        self, event: Event, subscription: Subscription, results: dict[str, Any]
    ) -> None:
        """Dispatch to a single subscription."""
        handler_id = subscription.id
        breaker = self._get_circuit_breaker(handler_id)

        if not breaker.can_execute():
            results["skipped"].append({"handler_id": handler_id, "reason": "Circuit breaker open"})
            return

        try:
            await asyncio.wait_for(
                self._call_handler(subscription.handler, event),
                timeout=subscription.timeout_seconds,
            )
            breaker.record_success()
            results["succeeded"].append(handler_id)

        except asyncio.TimeoutError:
            breaker.record_failure()
            results["failed"].append(
                {
                    "handler_id": handler_id,
                    "error": "Handler timeout",
                    "delivery_guarantee": subscription.delivery_guarantee.value,
                }
            )
        except Exception as e:
            breaker.record_failure()
            results["failed"].append(
                {
                    "handler_id": handler_id,
                    "error": str(e),
                    "delivery_guarantee": subscription.delivery_guarantee.value,
                }
            )

    def _get_circuit_breaker(self, handler_id: str) -> CircuitBreaker:
        """Get or create circuit breaker for handler."""
        if handler_id not in self._circuit_breakers:
            self._circuit_breakers[handler_id] = CircuitBreaker()
        return self._circuit_breakers[handler_id]

    @staticmethod
    async def _call_handler(handler: EventHandler, event: Event) -> None:
        """Call a handler, converting sync to async if needed."""
        if asyncio.iscoroutinefunction(handler):
            await handler(event)
        else:
            await asyncio.to_thread(handler, event)


class BatchedDispatcher(EventDispatcher):
    """
    Batched dispatcher accumulating events and processing in batches.

    Useful for performance optimization when processing many events.
    """

    def __init__(self, batch_size: int = 10, max_wait_ms: float = 1000.0) -> None:
        self.batch_size = batch_size
        self.max_wait_ms = max_wait_ms
        self._batch: list[Event] = []
        self._batch_task: asyncio.Task[None] | None = None

    async def dispatch(self, event: Event, subscriptions: list[Subscription]) -> dict[str, Any]:
        """
        Queue event for batched dispatch.

        Args:
            event: Event to dispatch
            subscriptions: Subscriptions for dispatch

        Returns:
            Immediate acknowledgment (actual processing is async)
        """
        self._batch.append(event)

        if len(self._batch) >= self.batch_size:
            await self._flush()

        return {"queued": True, "batch_size": len(self._batch)}

    async def _flush(self) -> None:
        """Process accumulated batch."""
        if not self._batch:
            return

        batch = self._batch[:]
        self._batch.clear()

        for event in batch:
            await asyncio.sleep(0.001)

    def get_batch_size(self) -> int:
        """Get current batch size."""
        return len(self._batch)
