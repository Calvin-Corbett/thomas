"""
Projection and denormalized view infrastructure.

Implements event-driven projections for building denormalized read models
and eventual consistency views.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from ._exceptions import ProjectionException
from ._types import EventEnvelope
from .events import EventStore


@dataclass
class ProjectionCheckpoint:
    """Tracks projection processing progress."""

    projection_name: str
    last_processed_position: int
    last_updated: datetime

    def __post_init__(self) -> None:
        """Initialize checkpoint."""
        if self.last_processed_position < 0:
            raise ValueError("Position cannot be negative")


class ProjectionEventHandler(Protocol):
    """
    Protocol for projection event handlers.

    Handles a specific event type in a projection.
    """

    async def __call__(self, event: EventEnvelope) -> None:
        """
        Handle an event.

        Args:
            event: Event envelope to process
        """
        ...


class Projection(ABC):
    """
    Base class for event projections.

    Projections listen to events and build denormalized read models.
    """

    def __init__(self, name: str) -> None:
        """
        Initialize projection.

        Args:
            name: Unique projection name
        """
        self.name = name
        self._handlers: dict[str, ProjectionEventHandler] = {}

    def register_handler(
        self,
        event_type: str,
        handler: ProjectionEventHandler,
    ) -> None:
        """
        Register handler for event type.

        Args:
            event_type: Event class name
            handler: Async handler function
        """
        self._handlers[event_type] = handler

    async def handle_event(self, event: EventEnvelope) -> None:
        """
        Process an event.

        Routes to registered handler if exists.

        Args:
            event: Event envelope to handle
        """
        handler = self._handlers.get(event.event_type)
        if handler:
            await handler(event)

    @abstractmethod
    async def reset(self) -> None:
        """
        Reset projection state.

        Used during rebuild operations.
        """
        pass

    @abstractmethod
    async def is_ready(self) -> bool:
        """
        Check if projection is ready to serve queries.

        Returns:
            True if ready
        """
        pass


class InMemoryProjection(Projection):
    """Simple in-memory projection for testing."""

    def __init__(self, name: str) -> None:
        """Initialize projection."""
        super().__init__(name)
        self._data: dict[str, Any] = {}
        self._ready = False

    async def reset(self) -> None:
        """Reset projection."""
        self._data.clear()
        self._ready = False

    async def is_ready(self) -> bool:
        """Check if ready."""
        return self._ready

    async def set_ready(self) -> None:
        """Mark as ready."""
        self._ready = True

    async def get_data(self) -> dict[str, Any]:
        """Get projection data."""
        return self._data.copy()

    async def update_data(self, updates: dict[str, Any]) -> None:
        """Update projection data."""
        self._data.update(updates)


class ProjectionManager:
    """
    Manages multiple projections and their lifecycle.

    Handles projection registration, event distribution,
    catch-up, and coordination.
    """

    def __init__(self, event_store: EventStore) -> None:
        """
        Initialize projection manager.

        Args:
            event_store: Event store for catch-up
        """
        self.event_store = event_store
        self._projections: dict[str, Projection] = {}
        self._checkpoints: dict[str, ProjectionCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def register_projection(self, projection: Projection) -> None:
        """
        Register a projection.

        Args:
            projection: Projection to register
        """
        async with self._lock:
            self._projections[projection.name] = projection
            self._checkpoints[projection.name] = ProjectionCheckpoint(
                projection_name=projection.name,
                last_processed_position=-1,
                last_updated=datetime.utcnow(),
            )

    async def handle_event(self, event: EventEnvelope) -> None:
        """
        Distribute event to all projections.

        Args:
            event: Event envelope
        """
        async with self._lock:
            for projection in self._projections.values():
                try:
                    await projection.handle_event(event)
                except Exception as e:
                    raise ProjectionException(f"Projection {projection.name} failed: {str(e)}")

    async def catch_up(self, projection_name: str) -> None:
        """
        Catch up projection from event store.

        Processes all events since last checkpoint.

        Args:
            projection_name: Projection to catch up
        """
        async with self._lock:
            projection = self._projections.get(projection_name)
            if not projection:
                raise ProjectionException(f"Projection not found: {projection_name}")

            checkpoint = self._checkpoints[projection_name]
            start_position = checkpoint.last_processed_position + 1

            # Get events from store
            events = await self.event_store.get_events_from_position(start_position)

            # Process events
            for event in events:
                await projection.handle_event(event)
                checkpoint.last_processed_position = event.global_position
                checkpoint.last_updated = datetime.utcnow()

    async def catch_up_all(self) -> None:
        """Catch up all projections."""
        for projection_name in self._projections.keys():
            await self.catch_up(projection_name)

    async def rebuild_projection(self, projection_name: str) -> None:
        """
        Rebuild projection from scratch.

        Resets projection and reprocesses all events.

        Args:
            projection_name: Projection to rebuild
        """
        async with self._lock:
            projection = self._projections.get(projection_name)
            if not projection:
                raise ProjectionException(f"Projection not found: {projection_name}")

            # Reset projection
            await projection.reset()

            # Get all events
            events = await self.event_store.get_events_from_position(0)

            # Reprocess all events
            for event in events:
                await projection.handle_event(event)

            # Update checkpoint
            if events:
                self._checkpoints[projection_name].last_processed_position = events[-1].global_position
            else:
                self._checkpoints[projection_name].last_processed_position = -1

            self._checkpoints[projection_name].last_updated = datetime.utcnow()

    async def get_checkpoint(self, projection_name: str) -> ProjectionCheckpoint | None:
        """
        Get checkpoint for projection.

        Args:
            projection_name: Projection name

        Returns:
            ProjectionCheckpoint or None
        """
        async with self._lock:
            return self._checkpoints.get(projection_name)

    async def update_checkpoint(
        self,
        projection_name: str,
        position: int,
    ) -> None:
        """
        Update checkpoint position.

        Args:
            projection_name: Projection name
            position: New position
        """
        async with self._lock:
            checkpoint = self._checkpoints.get(projection_name)
            if checkpoint:
                checkpoint.last_processed_position = position
                checkpoint.last_updated = datetime.utcnow()

    async def get_projection(self, name: str) -> Projection | None:
        """
        Get projection by name.

        Args:
            name: Projection name

        Returns:
            Projection or None
        """
        async with self._lock:
            return self._projections.get(name)

    async def is_projection_ready(self, name: str) -> bool:
        """
        Check if projection is ready.

        Args:
            name: Projection name

        Returns:
            True if ready
        """
        projection = await self.get_projection(name)
        if not projection:
            return False
        return await projection.is_ready()

    async def wait_for_projection(
        self,
        name: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        """
        Wait for projection to be ready.

        Args:
            name: Projection name
            timeout_seconds: Timeout limit

        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        start = asyncio.get_event_loop().time()
        while True:
            if await self.is_projection_ready(name):
                return
            if asyncio.get_event_loop().time() - start > timeout_seconds:
                raise asyncio.TimeoutError(f"Projection {name} not ready within {timeout_seconds}s")
            await asyncio.sleep(0.1)

    async def projections(self) -> dict[str, Projection]:
        """
        Get all projections.

        Returns:
            Dictionary of projections
        """
        async with self._lock:
            return self._projections.copy()
