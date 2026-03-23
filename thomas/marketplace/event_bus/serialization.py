"""
Event serialization with type registry and schema evolution support.

Provides JSON serialization for events with automatic type mapping and
support for event upcasting during deserialization.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ._types import Event


class TypeRegistry:
    """
    Registry mapping event type names to event classes.

    Supports event upcasting for schema evolution by allowing
    custom converters between versions.
    """

    def __init__(self) -> None:
        self._type_to_class: dict[str, type[Event]] = {}
        self._class_to_type: dict[type[Event], str] = {}
        self._upcasters: dict[str, list[Callable[[dict[str, Any]], dict[str, Any]]]] = {}

    def register(
        self,
        event_class: type[Event],
        type_name: str | None = None,
    ) -> None:
        """
        Register an event class with its type name.

        Args:
            event_class: The event class to register
            type_name: The string type name (defaults to class name)
        """
        name = type_name or event_class.__name__
        self._type_to_class[name] = event_class
        self._class_to_type[event_class] = name

    def register_upcaster(
        self,
        from_type: str,
        from_version: int,
        to_version: int,
        converter: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        """
        Register an upcaster to handle schema evolution.

        Args:
            from_type: Event type name
            from_version: Starting version
            to_version: Target version
            converter: Function to convert old schema to new
        """
        key = f"{from_type}@v{from_version}_v{to_version}"
        if key not in self._upcasters:
            self._upcasters[key] = []
        self._upcasters[key].append(converter)

    def get_class(self, type_name: str) -> type[Event]:
        """
        Get event class by type name.

        Args:
            type_name: The event type name

        Returns:
            The event class

        Raises:
            ValueError: If type is not registered
        """
        if type_name not in self._type_to_class:
            raise ValueError(f"Unknown event type: {type_name}")
        return self._type_to_class[type_name]

    def get_type_name(self, event_class: type[Event]) -> str:
        """
        Get type name for an event class.

        Args:
            event_class: The event class

        Returns:
            The type name

        Raises:
            ValueError: If class is not registered
        """
        if event_class not in self._class_to_type:
            raise ValueError(f"Unregistered event class: {event_class}")
        return self._class_to_type[event_class]

    def has_upcaster(self, type_name: str, from_version: int, to_version: int) -> bool:
        """Check if an upcaster exists for a version migration."""
        key = f"{type_name}@v{from_version}_v{to_version}"
        return key in self._upcasters

    def upcast(self, type_name: str, from_version: int, data: dict[str, Any]) -> dict[str, Any]:
        """
        Apply upcasters to upgrade event data.

        Args:
            type_name: Event type name
            from_version: Current version in data
            data: Event data to upgrade

        Returns:
            Upgraded event data
        """
        current_version = from_version
        result = data.copy()

        while True:
            key = f"{type_name}@v{current_version}_v{current_version + 1}"
            if key not in self._upcasters:
                break

            for converter in self._upcasters[key]:
                result = converter(result)
            current_version += 1

        return result


class EventSerializer:
    """
    Serializes and deserializes events to/from JSON.

    Uses a type registry for dynamic event creation and supports
    schema evolution through upcasting.
    """

    def __init__(self, registry: TypeRegistry | None = None) -> None:
        self.registry = registry or TypeRegistry()

    def serialize(self, event: Event) -> str:
        """
        Serialize an event to JSON.

        Args:
            event: The event to serialize

        Returns:
            JSON string representation

        Raises:
            ValueError: If event class is not registered
        """
        type_name = self.registry.get_type_name(event.__class__)
        data = {
            "id": event.id,
            "type": type_name,
            "timestamp": event.timestamp.isoformat(),
            "source": event.source,
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            "metadata": event.metadata,
            "data": self._serialize_event_data(event),
        }
        return json.dumps(data)

    def deserialize(self, json_str: str) -> Event:
        """
        Deserialize an event from JSON.

        Applies upcasters if schema version mismatches are detected.

        Args:
            json_str: JSON string to deserialize

        Returns:
            Reconstructed event instance

        Raises:
            ValueError: If event type is unknown
        """
        data = json.loads(json_str)

        type_name = data["type"]
        event_class = self.registry.get_class(type_name)

        timestamp = datetime.fromisoformat(data["timestamp"])

        event_data = data.get("data", {})
        event_version = event_data.pop("__version__", 1)

        if event_version > 1:
            event_data = self.registry.upcast(type_name, event_version, event_data)

        event = event_class(
            event_type=type_name,
            source=data["source"],
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            metadata=data.get("metadata", {}),
            timestamp=timestamp,
            event_id=data.get("id"),
        )

        for key, value in event_data.items():
            setattr(event, key, value)

        return event

    def serialize_to_dict(self, event: Event) -> dict[str, Any]:
        """
        Serialize event to a dictionary.

        Args:
            event: The event to serialize

        Returns:
            Dictionary representation
        """
        return json.loads(self.serialize(event))

    def _serialize_event_data(self, event: Event) -> dict[str, Any]:
        """Extract custom attributes from event for serialization."""
        excluded = {
            "id",
            "type",
            "timestamp",
            "source",
            "correlation_id",
            "causation_id",
            "metadata",
        }
        return {k: v for k, v in event.__dict__.items() if k not in excluded and not k.startswith("_")}


# Global default registry
_default_registry = TypeRegistry()
_default_serializer = EventSerializer(_default_registry)


def register_event_type(event_class: type[Event], type_name: str | None = None) -> None:
    """
    Register an event type globally.

    Args:
        event_class: The event class to register
        type_name: Optional custom type name (defaults to class name)
    """
    _default_registry.register(event_class, type_name)


def get_serializer() -> EventSerializer:
    """Get the global event serializer instance."""
    return _default_serializer


def get_registry() -> TypeRegistry:
    """Get the global type registry instance."""
    return _default_registry
