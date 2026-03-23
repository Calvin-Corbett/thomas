"""Channel registry primitives."""

from __future__ import annotations

from typing import Any

from thomas.marketplace.channels._base import ChannelAdapter


class ChannelRegistry:
    """Runtime registry for channel adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, type[ChannelAdapter]] = {}

    def register_adapter(self, channel_type: str, adapter_type: type[ChannelAdapter]) -> None:
        self._adapters[str(channel_type)] = adapter_type

    def get_adapter(self, channel_type: str) -> type[ChannelAdapter] | None:
        return self._adapters.get(str(channel_type))

    def list_channels(self) -> list[str]:
        return sorted(self._adapters.keys())

    def create(self, channel_type: str, **kwargs: Any) -> ChannelAdapter:
        adapter_type = self.get_adapter(channel_type)
        if adapter_type is None:
            raise KeyError(channel_type)
        return adapter_type(**kwargs)


_GLOBAL_REGISTRY = ChannelRegistry()


def get_registry() -> ChannelRegistry:
    return _GLOBAL_REGISTRY
