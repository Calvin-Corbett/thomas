"""Telegram marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class TelegramChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "telegram"
    recipient_config_keys = ("target", "chat_id", "recipient")


get_registry().register_adapter("telegram", TelegramChannelAdapter)
