"""
Central event bus for pub/sub event handling.

Manages subscriptions, publishes events, executes handlers with priorities,
and provides error handling, dead letter queues, and metrics.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from ._exceptions import EventBusError
from ._types import (
    DeliveryGuarantee,
    Event,
    EventHandler,
    HandlerPriority,
    Subscription,
)
from .dispatcher import (
    AsynchronousDispatcher,
    DispatchStrategy,
    EventDispatcher,
    SynchronousDispatcher,
)
from .middleware import MiddlewareChain


class EventBus:
    """
    Central event bus for typed pub/sub event handling.

    Features:
    - Subscribe to specific event types or wildcards
    - Handler priority ordering
    - Error handling with dead letter queue and retries
    - Middleware pipeline for cross-cutting concerns
    - Metrics collection
    - Graceful shutdown
    - Multiple dispatch strategies (sync, async, batched)
    """

    def __init__(
        self,
        dispatch_strategy: DispatchStrategy = DispatchStrategy.ASYNCHRONOUS,
    ) -> None:
        self._subscriptions: dict[str, set[Subscription]] = defaultdict(set)
        self._all_subscriptions: set[Subscription] = set()
        self._dispatch_strategy = dispatch_strategy
        self._dispatcher = self._create_dispatcher(dispatch_strategy)
        self._middleware_chain = MiddlewareChain()
        self._dead_letters: list[tuple[Event, Exception]] = []
        self._metrics = {
            "events_published": 0,
            "events_failed": 0,
            "events_retried": 0,
            "by_type": defaultdict(lambda: {"count": 0, "errors": 0}),
        }
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._retry_queues: dict[str, list[tuple[Event, int]]] = defaultdict(list)

    def subscribe(
        self,
        handler: EventHandler,
        event_types: set[str] | None = None,
        priority: HandlerPriority = HandlerPriority.NORMAL,
        delivery_guarantee: DeliveryGuarantee = DeliveryGuarantee.AT_LEAST_ONCE,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ) -> str:
        """
        Subscribe a handler to events.

        Args:
            handler: Event handler function
            event_types: Event types to subscribe to (None/{"*"} = all types)
            priority: Handler execution priority
            delivery_guarantee: Delivery semantics
            max_retries: Max retry attempts on failure
            timeout_seconds: Handler timeout

        Returns:
            Subscription ID
        """
        sub_id = str(uuid.uuid4())

        if event_types is None:
            event_types = {"*"}

        subscription = Subscription(
            id=sub_id,
            handler=handler,
            event_types=event_types,
            priority=priority,
            delivery_guarantee=delivery_guarantee,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )

        self._all_subscriptions.add(subscription)

        for event_type in event_types:
            self._subscriptions[event_type].add(subscription)

        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe a handler.

        Args:
            subscription_id: ID returned from subscribe()

        Returns:
            True if found and removed
        """
        to_remove = None

        for sub in self._all_subscriptions:
            if sub.id == subscription_id:
                to_remove = sub
                break

        if not to_remove:
            return False

        self._all_subscriptions.remove(to_remove)

        for subs in self._subscriptions.values():
            subs.discard(to_remove)

        return True

    async def publish(self, event: Event) -> dict[str, Any]:
        """
        Publish an event to all subscribed handlers.

        Args:
            event: Event to publish

        Returns:
            Publish result with succeeded/failed handlers

        Raises:
            EventBusError: If publish fails critically
        """
        if not self._running:
            raise EventBusError("Event bus is not running")

        event = await self._middleware_chain.before_publish(event)

        subscriptions = self._get_subscriptions_for_event(event)

        sorted_subs = sorted(subscriptions, key=lambda s: s.priority.value, reverse=True)

        try:
            result = await self._dispatcher.dispatch(event, sorted_subs)

            self._metrics["events_published"] += 1
            self._metrics["by_type"][event.type]["count"] += 1

            await self._middleware_chain.after_publish(event, True)

            return result

        except Exception as e:
            self._metrics["events_failed"] += 1
            self._metrics["by_type"][event.type]["errors"] += 1
            self._dead_letters.append((event, e))

            await self._middleware_chain.after_publish(event, False)

            raise EventBusError(f"Publish failed for {event.type}: {e}") from e

    async def publish_batch(self, events: list[Event]) -> dict[str, Any]:
        """
        Publish multiple events.

        Args:
            events: Events to publish

        Returns:
            Aggregate result across all events
        """
        results = {"total": len(events), "succeeded": 0, "failed": 0}

        for event in events:
            try:
                await self.publish(event)
                results["succeeded"] += 1
            except Exception:
                results["failed"] += 1

        return results

    async def start(self) -> None:
        """Start the event bus."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()

    async def shutdown(self) -> None:
        """Gracefully shutdown the event bus."""
        self._running = False
        self._shutdown_event.set()

    def is_running(self) -> bool:
        """Check if bus is running."""
        return self._running

    def add_middleware(self, middleware: Any) -> None:
        """Add middleware to the pipeline."""
        self._middleware_chain.register(middleware)

    def remove_middleware(self, middleware: Any) -> None:
        """Remove middleware from pipeline."""
        self._middleware_chain.unregister(middleware)

    def get_metrics(self) -> dict[str, Any]:
        """Get collected metrics."""
        metrics = self._metrics.copy()
        metrics["by_type"] = dict(metrics["by_type"])
        return metrics

    def get_dead_letters(self) -> list[tuple[Event, Exception]]:
        """Get events that failed to publish."""
        return self._dead_letters[:]

    def clear_dead_letters(self) -> None:
        """Clear dead letter queue."""
        self._dead_letters.clear()

    def retry_dead_letters(self) -> int:
        """
        Retry publishing dead letters.

        Returns:
            Number of events retried
        """
        dead_letters = self._dead_letters[:]
        self._dead_letters.clear()

        count = 0
        for event, _ in dead_letters:
            try:
                asyncio.create_task(self.publish(event))
                count += 1
            except Exception:
                self._dead_letters.append((event, _))

        return count

    def get_subscription_count(self, event_type: str | None = None) -> int:
        """
        Get number of subscriptions.

        Args:
            event_type: Specific type (None = total)

        Returns:
            Subscription count
        """
        if event_type:
            wildcard_subs = len([s for s in self._subscriptions.get("*", set())])
            type_subs = len(self._subscriptions.get(event_type, set()))
            return wildcard_subs + type_subs

        return len(self._all_subscriptions)

    def set_dispatch_strategy(self, strategy: DispatchStrategy) -> None:
        """Change dispatch strategy."""
        self._dispatch_strategy = strategy
        self._dispatcher = self._create_dispatcher(strategy)

    def get_dispatch_strategy(self) -> DispatchStrategy:
        """Get current dispatch strategy."""
        return self._dispatch_strategy

    def clear_metrics(self) -> None:
        """Reset metrics."""
        self._metrics = {
            "events_published": 0,
            "events_failed": 0,
            "events_retried": 0,
            "by_type": defaultdict(lambda: {"count": 0, "errors": 0}),
        }

    def _get_subscriptions_for_event(self, event: Event) -> set[Subscription]:
        """Get all subscriptions that handle an event."""
        subs = set()

        subs.update(self._subscriptions.get(event.type, set()))

        subs.update(self._subscriptions.get("*", set()))

        return subs

    @staticmethod
    def _create_dispatcher(strategy: DispatchStrategy) -> EventDispatcher:
        """Create dispatcher for strategy."""
        if strategy == DispatchStrategy.SYNCHRONOUS:
            return SynchronousDispatcher()
        elif strategy == DispatchStrategy.ASYNCHRONOUS:
            return AsynchronousDispatcher()
        else:
            return AsynchronousDispatcher()


class EventBusContext:
    """
    Context manager for event bus lifecycle.

    Usage:
        async with EventBusContext() as bus:
            await bus.publish(event)
    """

    def __init__(self, dispatch_strategy: DispatchStrategy = DispatchStrategy.ASYNCHRONOUS) -> None:
        self.bus = EventBus(dispatch_strategy)

    async def __aenter__(self) -> EventBus:
        await self.bus.start()
        return self.bus

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.bus.shutdown()
