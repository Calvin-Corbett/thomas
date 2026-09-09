"""Provider capability registry.

This module keeps a conservative, explicit capability map that Thomas can
surface to UI/CLI and use for routing decisions. It is intentionally static
and easy to audit; update when provider docs change.
"""

from __future__ import annotations

from thomas.core.config import ModelConfig

_BASE_FEATURES = (
    "chat",
    "tools",
    "streaming",
    "realtime",
    "batch",
    "embeddings",
    "fine_tuning",
    "image_gen",
    "audio",
    "video_gen",
    "stt",
    "tts",
)


def _cap(**kwargs: bool) -> dict[str, bool]:
    out = {k: False for k in _BASE_FEATURES}
    for k, v in kwargs.items():
        if k in out:
            out[k] = bool(v)
    return out


# Research-backed baseline (updated 2026-02-18).
_PROVIDER_CAPABILITIES: dict[str, dict[str, bool]] = {
    "openai_compat": _cap(
        chat=True,
        tools=True,
        streaming=True,
        batch=True,
        embeddings=True,
        image_gen=True,
        audio=True,
        video_gen=True,
        stt=True,
        tts=True,
    ),
    "anthropic": _cap(
        chat=True,
        tools=True,
        streaming=True,
        batch=True,
        embeddings=True,
        image_gen=False,
        audio=False,
        video_gen=False,
        stt=False,
        tts=False,
    ),
    "codex": _cap(
        chat=True,
        tools=True,
        streaming=True,
    ),
    "openai_codex": _cap(
        chat=True,
        tools=True,
        streaming=True,
    ),
}


def provider_capability_map(provider: str) -> dict[str, bool]:
    p = str(provider or "").strip().lower()
    base = _PROVIDER_CAPABILITIES.get(p)
    if base is None:
        # Unknown providers are treated as chat-only by default.
        return _cap(chat=True, tools=True, streaming=True)
    return dict(base)


def profile_capability_map(cfg: ModelConfig) -> dict[str, bool]:
    """Return a profile capability map, with model/profile heuristics layered in."""
    out = provider_capability_map(cfg.provider)

    profile_name = str(getattr(cfg, "name", "") or "").lower()
    model_id = str(getattr(cfg, "model", "") or "").lower()
    base_url = str(getattr(cfg, "base_url", "") or "").lower()

    text_hint = " ".join((profile_name, model_id, base_url))

    # Conservative provider-specific refinements for openai-compatible profiles.
    if str(getattr(cfg, "provider", "") or "").lower() == "openai_compat":
        if any(token in base_url for token in ("127.0.0.1", "localhost", "11434")):
            out["batch"] = False
        elif "groq" in text_hint:
            # Groq supports batch + speech APIs, but embeddings/fine-tuning
            # support is not broadly exposed as first-class today.
            out["embeddings"] = False
            out["fine_tuning"] = False
            out["video_gen"] = False
            out["image_gen"] = False
            out["audio"] = True
            out["stt"] = True
            out["tts"] = True
        elif "xai" in text_hint or "grok" in text_hint:
            out["chat"] = True
            out["tools"] = True
            out["streaming"] = True
            out["realtime"] = True
            out["batch"] = True
            out["image_gen"] = True
            out["audio"] = True
            out["video_gen"] = True
            out["stt"] = True
            out["tts"] = True
        elif "openrouter" in text_hint:
            # OpenRouter capabilities are provider-dependent, but routing supports
            # chat/tool/streaming broadly.
            out["batch"] = True
            out["video_gen"] = False
            out["image_gen"] = False
            out["audio"] = False
            out["stt"] = False
            out["tts"] = False
        elif "mistral" in text_hint:
            out["embeddings"] = True
            out["fine_tuning"] = True
            out["image_gen"] = False
            out["video_gen"] = False
            out["audio"] = True
            out["stt"] = True
            out["tts"] = False
        elif "cohere" in text_hint:
            out["embeddings"] = True
            out["fine_tuning"] = True
            out["image_gen"] = False
            out["video_gen"] = False
            out["audio"] = False
            out["stt"] = False
            out["tts"] = False

    # If the model id strongly signals speech-only, reflect that.
    if "tts" in model_id:
        out["chat"] = False
        out["tts"] = True
    if "stt" in model_id or "transcribe" in model_id:
        out["chat"] = False
        out["stt"] = True

    return out


def supports(cfg: ModelConfig, capability: str) -> bool:
    return bool(profile_capability_map(cfg).get(str(capability or "").strip(), False))
