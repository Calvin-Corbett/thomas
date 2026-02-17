from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, AsyncIterator, Optional, Any
import asyncio


@dataclass(frozen=True)
class TTSChunk:
    audio: bytes
    mime: str = "audio/ogg"
    is_last: bool = False


class TTSAdapter(Protocol):
    async def synth(self, text: str, *, voice: str | None = None, meta: dict[str, Any] | None = None) -> AsyncIterator[TTSChunk]:
        ...


class DisabledTTSAdapter:
    async def synth(self, text: str, *, voice: str | None = None, meta: dict[str, Any] | None = None):
        # No server-side TTS by default (client uses SpeechSynthesis).
        if False:
            yield  # pragma: no cover
        await asyncio.sleep(0)
        return
