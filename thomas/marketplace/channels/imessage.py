"""iMessage marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class IMessageChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "imessage"
    recipient_config_keys = ("target", "handle", "chat_id", "recipient")


get_registry().register_adapter("imessage", IMessageChannelAdapter)
