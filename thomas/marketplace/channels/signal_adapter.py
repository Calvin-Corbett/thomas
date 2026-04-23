"""Signal marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class SignalChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "signal"
    recipient_config_keys = ("target", "recipient", "to")


get_registry().register_adapter("signal", SignalChannelAdapter)
