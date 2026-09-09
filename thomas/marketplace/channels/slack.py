"""Slack marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class SlackChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "slack"
    recipient_config_keys = ("target", "channel_id", "channel", "recipient")


get_registry().register_adapter("slack", SlackChannelAdapter)
