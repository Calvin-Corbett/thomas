"""WhatsApp marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class WhatsAppChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "whatsapp"
    recipient_config_keys = ("recipient", "to", "target")


get_registry().register_adapter("whatsapp", WhatsAppChannelAdapter)
