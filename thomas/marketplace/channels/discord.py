"""Discord marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class DiscordChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "discord"
    recipient_config_keys = ("target", "channel_id", "channel", "recipient")


get_registry().register_adapter("discord", DiscordChannelAdapter)
