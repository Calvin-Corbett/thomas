"""
Event projections for building read models from event streams.

Provides projection base class, catch-up and live projections,
checkpoint tracking, and rebuild capability.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import Any

from ._types import Event
from .store import EventStore


class ProjectionStatus(Enum):
    """Status of a projection."""

    IDLE = "idle"
    CATCHING_UP = "catching_up"
    LIVE = "live"
    FAILED = "failed"


class Projection(ABC):
    """
    Abstract base for event projections.

    Projections build read models by applying events to state.
    Can be rebuilt from the event store and track progress via checkpoints.
    """

    def __init__(self, projection_name: str) -> None:
        self.name = projection_name
        self.status = ProjectionStatus.IDLE
        self._state: dict[str, Any] = {}
        self._version = 0
        self._checkpoint = 0

    @abstractmethod
    async def apply(self, event: Event) -> None:
        """
        Apply an event to projection state.

        Args:
            event: Event to apply
        """
        ...

    def get_state(self) -> dict[str, Any]:
        """Get current projection state."""
        return self._state.copy()

    def get_version(self) -> int:
        """Get projection version (events processed)."""
        return self._version

    def get_checkpoint(self) -> int:
        """Get current checkpoint position."""
        return self._checkpoint

    def set_checkpoint(self, sequence: int) -> None:
        """Set checkpoint for resumption."""
        self._checkpoint = sequence

    async def reset(self) -> None:
        """Reset projection to initial state."""
        self._state.clear()
        self._version = 0
        self._checkpoint = 0


class InMemoryProjection(Projection):
    """
    Simple in-memory projection storing state as a dictionary.

    Useful for counters, aggregations, and simple read models.
    """

    def __init__(self, projection_name: str, initial_state: dict[str, Any] | None = None) -> None:
        super().__init__(projection_name)
        if initial_state:
            self._state = initial_state.copy()

    async def apply(self, event: Event) -> None:
        """
        Apply event by dispatching to typed handler.

        Looks for method _on_{event_type_snake_case}(event).
        """
        method_name = self._get_handler_name(event.type)

        if hasattr(self, method_name):
            handler = getattr(self, method_name)
            await self._call_handler(handler, event)
            self._version += 1

    @staticmethod
    def _get_handler_name(event_type: str) -> str:
        """Generate handler name from event type."""
        name = "".join(["_" + c.lower() if c.isupper() else c for c in event_type]).lstrip("_")
        return f"_on_{name}"

    @staticmethod
    async def _call_handler(handler: Callable, event: Event) -> None:
        """Call handler, converting sync to async."""
        if asyncio.iscoroutinefunction(handler):
            await handler(event)
        else:
            await asyncio.to_thread(handler, event)


class AggregateProjection(Projection):
    """
    Projection that models individual aggregates.

    Maintains separate state per aggregate ID.
    """

    def __init__(self, projection_name: str) -> None:
        super().__init__(projection_name)
        self._aggregates: dict[str, dict[str, Any]] = {}

    async def apply(self, event: Event) -> None:
        """Apply event to appropriate aggregate."""
        aggregate_id = event.source

        if aggregate_id not in self._aggregates:
            self._aggregates[aggregate_id] = {}

        method_name = self._get_handler_name(event.type)

        if hasattr(self, method_name):
            handler = getattr(self, method_name)
            await self._call_handler(handler, event, self._aggregates[aggregate_id])
            self._version += 1

    def get_aggregate(self, aggregate_id: str) -> dict[str, Any] | None:
        """Get state for a specific aggregate."""
        return self._aggregates.get(aggregate_id)

    def get_all_aggregates(self) -> dict[str, dict[str, Any]]:
        """Get all aggregates."""
        return {k: v.copy() for k, v in self._aggregates.items()}

    async def reset(self) -> None:
        """Reset projection."""
        await super().reset()
        self._aggregates.clear()

    @staticmethod
    def _get_handler_name(event_type: str) -> str:
        """Generate handler name from event type."""
        name = "".join(["_" + c.lower() if c.isupper() else c for c in event_type]).lstrip("_")
        return f"_on_{name}"

    @staticmethod
    async def _call_handler(handler: Callable, event: Event, aggregate_state: dict[str, Any]) -> None:
        """Call handler with aggregate state."""
        if asyncio.iscoroutinefunction(handler):
            await handler(event, aggregate_state)
        else:
            await asyncio.to_thread(handler, event, aggregate_state)


class CatchUpProjection:
    """
    Loads a projection by replaying events from the event store.

    Processes events in order with checkpoint tracking for resumption.
    """

    def __init__(self, store: EventStore) -> None:
        self.store = store

    async def catchup(
        self,
        projection: Projection,
        from_checkpoint: int | None = None,
        batch_size: int = 100,
    ) -> None:
        """
        Replay events to catch up projection.

        Args:
            projection: Projection to catchup
            from_checkpoint: Starting position (None = from beginning)
            batch_size: Process events in batches
        """
        projection.status = ProjectionStatus.CATCHING_UP

        try:
            checkpoint = from_checkpoint or projection.get_checkpoint()

            all_events = self.store.read_all_forward(checkpoint)

            for i, envelope in enumerate(all_events):
                await projection.apply(envelope.event)
                projection.set_checkpoint(envelope.sequence_number)

                if (i + 1) % batch_size == 0:
                    await asyncio.sleep(0)

            projection.status = ProjectionStatus.IDLE

        except Exception:
            projection.status = ProjectionStatus.FAILED
            raise

    async def rebuild(self, projection: Projection, batch_size: int = 100) -> None:
        """
        Rebuild projection from scratch.

        Args:
            projection: Projection to rebuild
            batch_size: Process events in batches
        """
        await projection.reset()
        await self.catchup(projection, 0, batch_size)


class LiveProjection:
    """
    Keeps projection in sync with new events from the event bus.

    Complements CatchUpProjection for a complete projection system.
    """

    def __init__(self, projection: Projection) -> None:
        self.projection = projection

    async def handle_event(self, event: Event) -> None:
        """
        Process an event for live projection updates.

        Args:
            event: Event to apply
        """
        try:
            await self.projection.apply(event)
            self.projection.status = ProjectionStatus.LIVE

        except Exception:
            self.projection.status = ProjectionStatus.FAILED
            raise


class ProjectionManager:
    """
    Manages multiple projections with catchup and live sync.

    Coordinates between event store catchup and live event streaming.
    """

    def __init__(self, store: EventStore) -> None:
        self.store = store
        self._projections: dict[str, Projection] = {}
        self._catchup = CatchUpProjection(store)

    def register_projection(self, projection: Projection) -> None:
        """Register a projection."""
        self._projections[projection.name] = projection

    def unregister_projection(self, name: str) -> None:
        """Unregister a projection."""
        self._projections.pop(name, None)

    def get_projection(self, name: str) -> Projection | None:
        """Get a projection by name."""
        return self._projections.get(name)

    async def catchup_all(self, batch_size: int = 100) -> None:
        """
        Catch up all registered projections.

        Args:
            batch_size: Events to process per batch
        """
        for projection in self._projections.values():
            await self._catchup.catchup(projection, batch_size=batch_size)

    async def catchup_projection(self, name: str, batch_size: int = 100) -> None:
        """
        Catch up a specific projection.

        Args:
            name: Projection name
            batch_size: Events to process per batch
        """
        projection = self.get_projection(name)
        if projection:
            await self._catchup.catchup(projection, batch_size=batch_size)

    async def rebuild_projection(self, name: str, batch_size: int = 100) -> None:
        """
        Rebuild a projection from scratch.

        Args:
            name: Projection name
            batch_size: Events to process per batch
        """
        projection = self.get_projection(name)
        if projection:
            await self._catchup.rebuild(projection, batch_size)

    async def rebuild_all(self, batch_size: int = 100) -> None:
        """Rebuild all projections from scratch."""
        for projection in self._projections.values():
            await self._catchup.rebuild(projection, batch_size)

    def get_all_projections(self) -> dict[str, Projection]:
        """Get all registered projections."""
        return self._projections.copy()

    async def handle_event(self, event: Event) -> None:
        """
        Broadcast event to all live projections.

        Args:
            event: Event to apply
        """
        for projection in self._projections.values():
            await projection.apply(event)
