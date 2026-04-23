"""WebChat marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class WebChatChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "webchat"
    recipient_config_keys = ("target", "recipient")


get_registry().register_adapter("webchat", WebChatChannelAdapter)
