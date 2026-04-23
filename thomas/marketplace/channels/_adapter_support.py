"""Shared helpers for provider-backed channel adapters."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from thomas.marketplace.channels._base import ChannelConfig, ChannelHealth, DeliveryReceipt, UnifiedMessage
from thomas.marketplace.channels.p075_channel_provider_interface_contract import (
    SendMessageRequest,
    load_provider,
)


class ProviderBackedChannelAdapter:
    """Small adapter that forwards to a provider-contract implementation."""

    provider_id: str = ""
    recipient_config_keys: tuple[str, ...] = ("target", "recipient", "channel_id", "chat_id")

    def __init__(
        self,
        *,
        config: ChannelConfig | None = None,
        channel_id: str | None = None,
        credentials: Mapping[str, Any] | None = None,
        channel_type: str | None = None,
    ) -> None:
        self._config = config or ChannelConfig(
            channel_id=str(channel_id or self.provider_id),
            channel_type=str(channel_type or self.provider_id),
            credentials=dict(credentials or {}),
        )
        self._connected = False

    def config(self) -> ChannelConfig:
        return self._config

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, message: UnifiedMessage) -> DeliveryReceipt:
        provider = load_provider(self.provider_id, config=self._provider_config())
        recipient = self._resolve_recipient(message)
        send_result = provider.send_message(
            SendMessageRequest(
                recipient=recipient,
                message=str(message.content or ""),
                metadata=self._message_metadata(message),
            )
        )
        send_result = await _maybe_await(send_result)
        delivered = bool(getattr(send_result, "delivered", False))
        message_id = str(getattr(send_result, "message_id", "") or message.message_id)
        detail = "delivered" if delivered else "provider_rejected"
        return DeliveryReceipt(message_id=message_id, success=delivered, detail=detail)

    async def ping(self) -> ChannelHealth:
        provider = load_provider(self.provider_id, config=self._provider_config())
        health_result = provider.health_check()
        health_result = await _maybe_await(health_result)
        if isinstance(health_result, Mapping):
            details = dict(health_result)
            return ChannelHealth(
                ok=bool(details.get("ok", False)),
                status=str(details.get("details") or details.get("status") or ""),
            )
        return ChannelHealth(ok=bool(getattr(health_result, "ok", False)), status=None)

    def _provider_config(self) -> dict[str, Any]:
        credentials = self._config.credentials
        if isinstance(credentials, Mapping):
            return {str(k): v for k, v in credentials.items()}
        return {}

    def _resolve_recipient(self, message: UnifiedMessage) -> str:
        metadata = self._message_metadata(message)
        for key in ("recipient", "target", "channel_id", "chat_id", "to"):
            value = metadata.get(key)
            if value not in (None, ""):
                return str(value)
        config = self._provider_config()
        for key in self.recipient_config_keys:
            value = config.get(key)
            if value not in (None, ""):
                return str(value)
        return self._config.channel_id

    def _message_metadata(self, message: UnifiedMessage) -> dict[str, Any]:
        if isinstance(message.metadata, Mapping):
            return {str(k): v for k, v in message.metadata.items()}
        return {}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
