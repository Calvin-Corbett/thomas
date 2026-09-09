from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class STTResult:
    text: str
    is_final: bool
    confidence: float = 0.0
    seq: int = 0
    src: str = "unknown"


class STTAdapter(Protocol):
    async def transcribe_chunk(
        self, audio: bytes, *, mime: str, seq: int, meta: dict[str, Any] | None = None
    ) -> STTResult | None:
        """Return an STTResult or None if not enough audio yet."""
        ...


class DisabledSTTAdapter:
    async def transcribe_chunk(
        self, audio: bytes, *, mime: str, seq: int, meta: dict[str, Any] | None = None
    ) -> STTResult | None:
        await asyncio.sleep(0)  # keep it awaitable
        return None
