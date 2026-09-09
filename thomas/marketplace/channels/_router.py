"""Simple channel router facade."""

from __future__ import annotations

from thomas.marketplace.channels._base import DeliveryReceipt, UnifiedMessage
from thomas.marketplace.channels._registry import get_registry


class ChannelRouter:
    """Resolve and dispatch messages through the registry."""

    def __init__(self) -> None:
        self._registry = get_registry()

    async def route_message(self, channel_type: str, message: UnifiedMessage) -> DeliveryReceipt:
        adapter_type = self._registry.get_adapter(channel_type)
        if adapter_type is None:
            return DeliveryReceipt(message_id=message.message_id, success=False, detail=f"no adapter: {channel_type}")

        adapter = adapter_type()
        try:
            import inspect

            if inspect.iscoroutinefunction(adapter.send):
                return await adapter.send(message)
            return DeliveryReceipt(message_id=message.message_id, success=True, detail="sync_adapter")
        except Exception as exc:
            return DeliveryReceipt(
                message_id=message.message_id, success=False, detail=f"adapter_error:{type(exc).__name__}"
            )
