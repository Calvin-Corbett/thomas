"""Channel registry primitives."""

from __future__ import annotations

from typing import Any

from thomas.marketplace.channels._base import ChannelAdapter

_BUILTIN_ADAPTER_MODULES = (
    "thomas.marketplace.channels.discord",
    "thomas.marketplace.channels.google_chat",
    "thomas.marketplace.channels.imessage",
    "thomas.marketplace.channels.matrix_adapter",
    "thomas.marketplace.channels.signal_adapter",
    "thomas.marketplace.channels.slack",
    "thomas.marketplace.channels.telegram",
    "thomas.marketplace.channels.teams",
    "thomas.marketplace.channels.webchat",
    "thomas.marketplace.channels.whatsapp",
)
_BUILTINS_LOADED = False
_BUILTINS_LOADING = False


class ChannelRegistry:
    """Runtime registry for channel adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, type[ChannelAdapter]] = {}

    def register_adapter(self, channel_type: str, adapter_type: type[ChannelAdapter]) -> None:
        self._adapters[str(channel_type)] = adapter_type

    def get_adapter(self, channel_type: str) -> type[ChannelAdapter] | None:
        _ensure_builtin_adapters_loaded()
        return self._adapters.get(str(channel_type))

    def list_channels(self) -> list[str]:
        _ensure_builtin_adapters_loaded()
        return sorted(self._adapters.keys())

    def create(self, channel_type: str, **kwargs: Any) -> ChannelAdapter:
        _ensure_builtin_adapters_loaded()
        adapter_type = self.get_adapter(channel_type)
        if adapter_type is None:
            raise KeyError(channel_type)
        return adapter_type(**kwargs)


_GLOBAL_REGISTRY = ChannelRegistry()


def get_registry() -> ChannelRegistry:
    _ensure_builtin_adapters_loaded()
    return _GLOBAL_REGISTRY


def _ensure_builtin_adapters_loaded() -> None:
    global _BUILTINS_LOADED, _BUILTINS_LOADING
    if _BUILTINS_LOADED or _BUILTINS_LOADING:
        return
    import importlib

    _BUILTINS_LOADING = True
    try:
        for module_name in _BUILTIN_ADAPTER_MODULES:
            importlib.import_module(module_name)
    finally:
        _BUILTINS_LOADING = False
    _BUILTINS_LOADED = True
