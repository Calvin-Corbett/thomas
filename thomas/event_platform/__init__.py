"""Event platform module for event-driven architecture."""

from thomas.event_platform.core import (
    ConsumerGroup,
    Event,
    EventBroker,
    Partition,
    Topic,
)
from thomas.event_platform.tools import register_event_platform_tools

__all__ = [
    "Event",
    "Partition",
    "Topic",
    "ConsumerGroup",
    "EventBroker",
    "register_event_platform_tools",
]
