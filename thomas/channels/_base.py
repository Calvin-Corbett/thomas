"""Base abstractions for channel adapters.

This is intentionally lightweight but import-safe when optional integrations are
missing. The full implementation is expected to be added by integration
modules, while these primitives keep the public API usable during launch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ChannelConfig:
    channel_id: str
    channel_type: str
    credentials: dict[str, Any] | None = None


@dataclass(frozen=True)
class UnifiedMessage:
    channel_id: str
    message_id: str
    content: str
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class DeliveryReceipt:
    message_id: str
    success: bool
    detail: str | None = None


@dataclass(frozen=True)
class ChannelHealth:
    ok: bool
    latency_ms: float | None = None
    status: str | None = None


class ChannelAdapterErrorCode:
    UNKNOWN = "unknown"
    CONNECT_FAILED = "connect_failed"
    SEND_FAILED = "send_failed"
    INVALID_CONFIG = "invalid_config"


class ChannelAdapterError(RuntimeError):
    """Base channel adapter error."""

    code: str = ChannelAdapterErrorCode.UNKNOWN

    def __init__(self, message: str, *, code: str = ChannelAdapterErrorCode.UNKNOWN) -> None:
        super().__init__(message)
        self.code = code


class ChannelAdapter(Protocol):
    """Minimal protocol used by adapters and registries."""

    def config(self) -> ChannelConfig: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send(self, message: UnifiedMessage) -> DeliveryReceipt: ...

    async def ping(self) -> ChannelHealth: ...
