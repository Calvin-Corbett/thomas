"""Matrix marketplace channel adapter."""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class MatrixChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "matrix"
    recipient_config_keys = ("target", "room_id", "recipient")


get_registry().register_adapter("matrix", MatrixChannelAdapter)
