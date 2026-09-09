"""Google Chat marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class GoogleChatChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "googlechat"
    recipient_config_keys = ("target", "thread_key", "space", "recipient")


get_registry().register_adapter("googlechat", GoogleChatChannelAdapter)
