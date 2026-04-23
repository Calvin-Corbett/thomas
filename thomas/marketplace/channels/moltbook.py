"""Moltbook marketplace channel adapter.

Routes messages through Thomas's unified channel system to the Moltbook
AI agent social network. Posts are sent as submolt entries; the 'recipient'
field maps to the target submolt community name.
"""

from __future__ import annotations

from thomas.marketplace.channels._adapter_support import ProviderBackedChannelAdapter
from thomas.marketplace.channels._registry import get_registry


class MoltbookChannelAdapter(ProviderBackedChannelAdapter):
    provider_id = "moltbook"
    recipient_config_keys = ("submolt", "target", "recipient")


get_registry().register_adapter("moltbook", MoltbookChannelAdapter)
