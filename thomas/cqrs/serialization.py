"""
Event serialization and schema evolution.

Provides event serialization with type registry, upcasting for schema
evolution, and versioned event support.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ._exceptions import (
    DeserializationException,
    InvalidEventTypeException,
    UpcastingException,
)
from ._types import AggregateId, Event, EventEnvelope, Metadata


class EventUpCaster(ABC):
    """
    Base class for event upcasters.

    Upcasters handle schema evolution by transforming old event
    versions to new versions.
    """

    @abstractmethod
    async def upcast(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """
        Transform old event version to new version.

        Args:
            event_data: Event data in old format

        Returns:
            Event data in new format
        """
        pass


class SimpleEventUpCaster(EventUpCaster):
    """
    Simple upcast function wrapper.

    Wraps a transformation function as an upcast strategy.
    """

    def __init__(self, transform: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """
        Initialize upcast function.

        Args:
            transform: Transformation function
        """
        self.transform = transform

    async def upcast(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Apply transformation."""
        return self.transform(event_data)


class EventTypeRegistry:
    """
    Registry for event types and serialization rules.

    Maps event class names to types and handles version tracking.
    """

    def __init__(self) -> None:
        """Initialize registry."""
        self._types: dict[str, type[Event]] = {}
        self._versions: dict[str, int] = {}
        self._upcasters: dict[tuple[str, int], list[EventUpCaster]] = {}

    def register(self, event_type: type[Event], version: int = 1) -> None:
        """
        Register event type.

        Args:
            event_type: Event class
            version: Current version of event
        """
        name = event_type.__name__
        self._types[name] = event_type
        self._versions[name] = version

    def get_type(self, name: str) -> type[Event] | None:
        """
        Get event type by name.

        Args:
            name: Event type name

        Returns:
            Event class or None
        """
        return self._types.get(name)

    def get_version(self, name: str) -> int:
        """
        Get current version of event type.

        Args:
            name: Event type name

        Returns:
            Version number
        """
        return self._versions.get(name, 1)

    def register_upcast(
        self,
        event_type: str,
        from_version: int,
        upcast_step: EventUpCaster,
    ) -> None:
        """
        Register upcast step.

        Args:
            event_type: Event type name
            from_version: Version this upcast transforms from
            upcast_step: Upcast strategy
        """
        key = (event_type, from_version)
        if key not in self._upcasters:
            self._upcasters[key] = []
        self._upcasters[key].append(upcast_step)

    async def upcast_event(
        self,
        event_type: str,
        from_version: int,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Upcast event through all applicable steps.

        Args:
            event_type: Event type name
            from_version: Starting version
            event_data: Event data to upcast

        Returns:
            Upcasted event data

        Raises:
            UpcastingException: If upcast fails
        """
        current_data = event_data.copy()
        current_version = from_version
        target_version = self.get_version(event_type)

        while current_version < target_version:
            key = (event_type, current_version)
            upcasters = self._upcasters.get(key, [])

            if not upcasters:
                raise UpcastingException(f"No upcast available for {event_type} from version {current_version}")

            try:
                for upcast_step in upcasters:
                    current_data = await upcast_step.upcast(current_data)
                current_version += 1
            except Exception as e:
                raise UpcastingException(f"Upcast failed for {event_type}: {str(e)}")

        return current_data


class EventSerializer:
    """
    Serializes and deserializes events.

    Handles converting between Event objects and JSON-serializable data.
    """

    def __init__(self, registry: EventTypeRegistry | None = None) -> None:
        """
        Initialize serializer.

        Args:
            registry: Event type registry
        """
        self.registry = registry or EventTypeRegistry()

    def serialize(self, event: Event, event_type: str) -> dict[str, Any]:
        """
        Serialize event to dictionary.

        Args:
            event: Event to serialize
            event_type: Event type name

        Returns:
            Serialized event data
        """
        version = self.registry.get_version(event_type)
        return {
            "event_type": event_type,
            "version": version,
            "event_id": event.event_id,
            "timestamp": event.timestamp.isoformat(),
            "data": self._serialize_data(vars(event)),
        }

    def _serialize_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively serialize event data."""
        result = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = self._serialize_data(value)
            elif isinstance(value, list):
                result[key] = [self._serialize_data(v) if isinstance(v, dict) else v for v in value]
            else:
                result[key] = value
        return result

    async def deserialize(
        self,
        data: dict[str, Any],
        aggregate_id: AggregateId,
        version: int,
        metadata: Metadata,
    ) -> EventEnvelope:
        """
        Deserialize event from dictionary.

        Args:
            data: Serialized event data
            aggregate_id: Aggregate this event applies to
            version: Aggregate version
            metadata: Event metadata

        Returns:
            Deserialized event envelope

        Raises:
            InvalidEventTypeException: If type not registered
            DeserializationException: If deserialization fails
        """
        try:
            event_type = data.get("event_type")
            event_version = data.get("version", 1)

            if not event_type:
                raise DeserializationException("Missing event_type in data")

            # Upcast if needed
            event_data = data.get("data", {})
            current_version = self.registry.get_version(event_type)
            if event_version < current_version:
                event_data = await self.registry.upcast_event(
                    event_type,
                    event_version,
                    event_data,
                )

            # Get event type
            event_cls = self.registry.get_type(event_type)
            if not event_cls:
                raise InvalidEventTypeException(event_type)

            # Create event instance
            event = event_cls()
            for key, value in event_data.items():
                if key not in ["timestamp", "event_id"]:
                    setattr(event, key, value)

            return EventEnvelope(
                event=event,
                aggregate_id=aggregate_id,
                aggregate_version=version,
                global_position=0,
                metadata=metadata,
                event_type=event_type,
            )

        except (InvalidEventTypeException, UpcastingException):
            raise
        except Exception as e:
            raise DeserializationException(f"Failed to deserialize {data.get('event_type')}: {str(e)}")

    def serialize_envelope(
        self,
        envelope: EventEnvelope,
    ) -> dict[str, Any]:
        """
        Serialize event envelope.

        Args:
            envelope: Event envelope to serialize

        Returns:
            Serialized envelope
        """
        event_data = self.serialize(envelope.event, envelope.event_type)

        return {
            **event_data,
            "aggregate_id": envelope.aggregate_id.value,
            "aggregate_type": envelope.aggregate_id.aggregate_type,
            "aggregate_version": envelope.aggregate_version,
            "global_position": envelope.global_position,
            "metadata": {
                "user_id": envelope.metadata.user_id,
                "correlation_id": envelope.metadata.correlation_id,
                "causation_id": envelope.metadata.causation_id,
                "timestamp": envelope.metadata.timestamp.isoformat(),
                "source": envelope.metadata.source,
                "custom_data": envelope.metadata.custom_data,
            },
        }

    async def deserialize_envelope(
        self,
        data: dict[str, Any],
    ) -> EventEnvelope:
        """
        Deserialize event envelope.

        Args:
            data: Serialized envelope data

        Returns:
            Deserialized envelope
        """
        aggregate_id = AggregateId(
            value=data["aggregate_id"],
            aggregate_type=data["aggregate_type"],
        )

        metadata_data = data.get("metadata", {})
        metadata = Metadata(
            user_id=metadata_data.get("user_id"),
            correlation_id=metadata_data.get("correlation_id", ""),
            causation_id=metadata_data.get("causation_id"),
            source=metadata_data.get("source"),
            custom_data=metadata_data.get("custom_data", {}),
        )

        return await self.deserialize(
            data,
            aggregate_id,
            data["aggregate_version"],
            metadata,
        )
