"""Every connection other than the ChatGPT sign-in answers ``GET <base>/models``.

Anthropic, OpenAI, Gemini's OpenAI-compatible endpoint, OpenRouter, Groq,
Mistral, xAI and local servers (with Ollama's ``/api/tags`` as the fallback) all
go through ``handshake_models_async``, which already sends each one's headers.
"""

from __future__ import annotations

import json
import re

from thomas.core.config import ModelConfig
from thomas.models.catalog_rules import provider_family
from thomas.models.discovery import handshake_models_async
from thomas.models.sources import ListedModel, SourceAnswer

# OpenAI lists embeddings, speech and image models beside chat models. These are
# words the ids use for themselves, matched as whole words inside the id, so a
# new chat family appears without a change here.
_NOT_CHAT = re.compile(r"(?:^|[-_./:])(?:embedding|whisper|tts|dall-e|moderation|image|transcribe)(?:$|[-_./:])", re.I)

_ERROR_MAX_CHARS = 160


def _connection_error(cfg: ModelConfig, raw_error: str) -> str:
    """Name the connection, and never let a raw JSON error body through."""
    profile = str(getattr(cfg, "name", "") or "").strip() or "connection"
    message = str(raw_error or "").strip()
    try:
        parsed = json.loads(message)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict) and str(err.get("message") or "").strip():
            message = str(err["message"]).strip()
        elif str(parsed.get("message") or "").strip():
            message = str(parsed["message"]).strip()
    return f"{profile}: {message}"[:_ERROR_MAX_CHARS]


async def list_generic_models(cfg: ModelConfig, *, timeout_s: float = 10.0) -> SourceAnswer:
    handshake = await handshake_models_async(cfg, timeout_s=timeout_s)
    if not handshake.ok:
        error = _connection_error(cfg, str(handshake.error or handshake.status))
        return SourceAnswer(ok=False, source="provider", error=error)
    ids = [str(m) for m in handshake.models or [] if str(m).strip()]
    if provider_family(cfg) == "openai":
        ids = [m for m in ids if not _NOT_CHAT.search(m)]
    return SourceAnswer(ok=True, source="provider", models=tuple(ListedModel(id=m, order=i) for i, m in enumerate(ids)))
