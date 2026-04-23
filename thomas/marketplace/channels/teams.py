"""Microsoft Teams marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class MSTeamsChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "msteams"
    recipient_config_keys = ("target", "conversation_id", "channel_id", "recipient")


get_registry().register_adapter("msteams", MSTeamsChannelAdapter)
