from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Optional, Any
import asyncio


@dataclass(frozen=True)
class STTResult:
    text: str
    is_final: bool
    confidence: float = 0.0
    seq: int = 0
    src: str = "unknown"


class STTAdapter(Protocol):
    async def transcribe_chunk(self, audio: bytes, *, mime: str, seq: int, meta: dict[str, Any] | None = None) -> Optional[STTResult]:
        """Return an STTResult or None if not enough audio yet."""
        ...


class DisabledSTTAdapter:
    async def transcribe_chunk(self, audio: bytes, *, mime: str, seq: int, meta: dict[str, Any] | None = None) -> Optional[STTResult]:
        await asyncio.sleep(0)  # keep it awaitable
        return None
