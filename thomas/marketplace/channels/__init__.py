"""
Thomas Channel Adapter Framework

A universal messaging channel system that allows Thomas to connect to any
messaging platform through a unified interface. Provides centralized
management of channel adapters, message routing, and delivery queuing.

This module exports the main public API:
- ChannelAdapter: Abstract base class for implementing channel integrations
- ChannelConfig: Configuration for a channel instance
- UnifiedMessage: Standard message format across all channels
- DeliveryReceipt: Confirmation of message delivery
- ChannelHealth: Health status of a channel
- ChannelRegistry: Central registry and lifecycle management
- DeliveryQueue: Reliable message queue with retry logic
- DeliveryPolicy: Delivery retry configuration
- DeadLetterEntry: Failed message record
- ChannelRouter: Message routing between Thomas and channels
- ChannelAdapterError: Base exception for channel operations
- ChannelAdapterErrorCode: Standard error codes

Example:
    >>> from thomas.marketplace.channels import ChannelRegistry, ChannelRouter
    >>> registry = ChannelRegistry()
    >>> router = ChannelRouter()
    >>> # Register custom adapters
    >>> registry.register_adapter('slack', SlackChannelAdapter)
    >>> config = ChannelConfig(
    ...     channel_id='slack-prod',
    ...     channel_type='slack',
    ...     credentials={'token': '...'}
    ... )
    >>> adapter = await registry.connect_channel(config)
"""

from ._base import (
    ChannelAdapter,
    ChannelAdapterError,
    ChannelAdapterErrorCode,
    ChannelConfig,
    ChannelHealth,
    DeliveryReceipt,
    UnifiedMessage,
)
from ._delivery import DeadLetterEntry, DeliveryPolicy, DeliveryQueue
from ._registry import ChannelRegistry, get_registry
from ._router import ChannelRouter
from .discord import DiscordChannelAdapter
from .google_chat import GoogleChatChannelAdapter
from .imessage import IMessageChannelAdapter
from .matrix_adapter import MatrixChannelAdapter
from .signal_adapter import SignalChannelAdapter
from .slack import SlackChannelAdapter
from .teams import MSTeamsChannelAdapter
from .telegram import TelegramChannelAdapter
from .webchat import WebChatChannelAdapter
from .whatsapp import WhatsAppChannelAdapter

__all__ = [
    # Base classes and data structures
    "ChannelAdapter",
    "ChannelConfig",
    "ChannelHealth",
    "UnifiedMessage",
    "DeliveryReceipt",
    # Exceptions and error codes
    "ChannelAdapterError",
    "ChannelAdapterErrorCode",
    # Registry
    "ChannelRegistry",
    "get_registry",
    "DiscordChannelAdapter",
    "GoogleChatChannelAdapter",
    "IMessageChannelAdapter",
    "MatrixChannelAdapter",
    "MSTeamsChannelAdapter",
    "SignalChannelAdapter",
    "SlackChannelAdapter",
    "TelegramChannelAdapter",
    "WebChatChannelAdapter",
    "WhatsAppChannelAdapter",
    # Delivery
    "DeliveryQueue",
    "DeliveryPolicy",
    "DeadLetterEntry",
    # Router
    "ChannelRouter",
]

__version__ = "1.0.0"
__author__ = "Thomas Framework"
__license__ = "MIT"
