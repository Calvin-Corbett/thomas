"""Model catalog scoring, aliases, and curated fallback rows."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from thomas.core.config import ModelConfig

CURATED_OPENAI_MODELS: tuple[str, ...] = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
)

OPENAI_CODEX_GPT56_MODELS: tuple[str, ...] = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
)

# Verified against the signed-in ChatGPT/Codex Responses endpoint on 2026-07-14.
# Keep this list aligned with live provider evidence so a temporary availability
# result does not leave a recovered GPT-5.6 variant disabled in the local UI.
OPENAI_CODEX_CHATGPT_VERIFIED_MODELS: tuple[str, ...] = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
)


def provider_family(cfg: ModelConfig) -> str:
    provider = str(getattr(cfg, "provider", "") or "").strip().lower()
    base_url = str(getattr(cfg, "base_url", "") or "").strip().lower()
    model = str(getattr(cfg, "model", "") or "").strip().lower()
    text = " ".join((provider, base_url, model))
    # Match the OpenAI API host on the parsed URL hostname (exact / suffix on a
    # dot boundary) instead of a bare substring, so look-alike hosts such as
    # "api.openai.com.evil.example" cannot spoof the openai family.
    host = urlparse(base_url if "://" in base_url else f"//{base_url}").hostname or ""
    is_openai_host = host == "api.openai.com" or host.endswith(".api.openai.com")
    if is_openai_host or model.startswith("gpt-"):
        return "openai"
    if provider == "anthropic" or "anthropic" in text or model.startswith("claude-"):
        return "anthropic"
    if "google" in text or "gemini" in text:
        return "google"
    if "deepseek" in text:
        return "deepseek"
    if "xai" in text or "grok" in text:
        return "xai"
    return provider or "unknown"


def entry(
    *,
    profile: str,
    provider: str,
    family: str,
    model_id: str,
    source: str,
    available: bool,
    display_name: str = "",
    is_default: bool = False,
) -> dict[str, Any]:
    return {
        "profile": str(profile or ""),
        "provider": str(provider or ""),
        "family": str(family or ""),
        "id": str(model_id or ""),
        "display_name": str(display_name or _display_name(model_id)),
        "source": str(source or ""),
        "available": bool(available),
        "is_default": bool(is_default),
        "capabilities": _infer_capabilities(model_id=model_id, provider=provider, family=family),
    }


def dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {"live": 0, "config": 1, "curated": 2}
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in entries:
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        owner = str(item.get("profile") or item.get("family") or item.get("provider") or "").strip().lower()
        key = (owner, model_id)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = dict(item)
            continue
        if priority.get(str(item.get("source")), 99) < priority.get(str(existing.get("source")), 99):
            merged = dict(existing)
            merged.update(item)
            by_key[key] = merged
        elif bool(item.get("available")) and not bool(existing.get("available")):
            existing["available"] = True
    # Newest version first, then (stable) the provider's own order within each
    # profile: a provider that lists GPT-6-Astra first is shown with it first.
    rows = sorted(by_key.values(), key=lambda row: _version_score(str(row.get("id") or "")), reverse=True)
    return sorted(
        rows,
        key=lambda row: (str(row.get("family") or ""), str(row.get("profile") or ""), int(row.get("order", 1000))),
    )


def build_aliases(entries: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    openai = [e for e in entries if str(e.get("family") or "") == "openai"]
    live_openai = [e for e in openai if bool(e.get("available"))]

    def best(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        return str(max(rows, key=lambda row: _version_score(str(row.get("id") or ""))).get("id") or "")

    frontier = best([e for e in openai if _is_frontier_candidate(str(e.get("id") or ""))])
    available_frontier = best([e for e in live_openai if _is_frontier_candidate(str(e.get("id") or ""))])
    codex = best([e for e in openai if "codex" in str(e.get("id") or "").lower()])
    available_codex = best([e for e in live_openai if "codex" in str(e.get("id") or "").lower()])
    tools = frontier or codex or best(openai)
    available_tools = available_frontier or available_codex or best(live_openai)

    if frontier:
        aliases["latest.openai.frontier"] = frontier
        aliases["best.reasoning"] = frontier
    if available_frontier:
        aliases["latest.openai.available"] = available_frontier
    if codex:
        aliases["latest.openai.codex"] = codex
    if available_codex:
        aliases["latest.openai.codex.available"] = available_codex
    if tools:
        aliases["best.tools"] = tools
    if available_tools:
        aliases["best.tools.available"] = available_tools
    return aliases


def _display_name(model_id: str) -> str:
    text = str(model_id or "").strip()
    if not text:
        return ""
    return text.replace("-", " ").replace("_", " ").title()


def _infer_capabilities(*, model_id: str, provider: str, family: str) -> dict[str, Any]:
    mid = str(model_id or "").lower()
    fam = str(family or "").lower()
    prov = str(provider or "").lower()
    reasoning = fam == "openai" and mid.startswith("gpt-5")
    return {
        "chat": writes_text(mid),
        "tools": fam in {"openai", "anthropic", "google", "xai", "deepseek"},
        "streaming": True,
        "reasoning_efforts": ["none", "low", "medium", "high", "xhigh", "max"] if reasoning else [],
        "frontier": _is_frontier_candidate(mid),
        "mini": _is_small_model(mid),
        "codex_optimized": "codex" in mid,
    }


# Providers such as DeepInfra list every model they host through one OpenAI-style list, with nothing saying which ones
# answer in words. These marks in a model's id name the ones that make pictures, video or sound, or turn text into
# numbers, so the catalog stops calling them chat models. A part of the id between dashes, slashes or dots must equal a
# word in the first set; anything in the second set may sit anywhere in the id.
_NOT_TEXT_PARTS = frozenset(
    {
        "tts",
        "asr",
        "stt",
        "flux",
        "veo",
        "sora",
        "kling",
        "wan2",
        "t2v",
        "i2v",
        "t2i",
        "bge",
        "e5",
        "gte",
        "rerank",
        "embedding",
        "embeddings",
        "embed",
        "mpnet",
        "minilm",
        "sdxl",
        "seedream",
        "seedance",
        "whisper",
        "musicgen",
    }
)
_NOT_TEXT_ANYWHERE = (
    "image",
    "banana",
    "dall-e",
    "stable-diffusion",
    "diffusion",
    "sentence-transformers",
    "fibo",
    "text-to-speech",
    "speech-to-text",
    "audio8",
    "kokoro",
    "orpheus",
    "hunyuanvideo",
)


def writes_text(model_id: str) -> bool:
    mid = str(model_id or "").lower()
    parts = {t for t in re.split(r"[^a-z0-9]+", mid) if t}
    return not (parts & _NOT_TEXT_PARTS or any(mark in mid for mark in _NOT_TEXT_ANYWHERE))


def _is_small_model(model_id: str) -> bool:
    tokens = {t for t in re.split(r"[^a-z0-9]+", str(model_id or "").lower()) if t}
    return bool(tokens.intersection({"mini", "small", "nano", "flash", "spark", "luna"}))


def _is_frontier_candidate(model_id: str) -> bool:
    mid = str(model_id or "").lower()
    return mid.startswith("gpt-") and not _is_small_model(mid)


def _version_score(model_id: str) -> tuple[int, int, int, int, int, str]:
    mid = str(model_id or "").lower()
    match = re.search(r"\bgpt[-_]?(\d+)(?:[.-](\d+))?", mid)
    major = int(match.group(1)) if match else 0
    minor = int(match.group(2)) if match and match.group(2) else 0
    codex_bonus = 1 if "codex" in mid else 0
    small_penalty = -1 if _is_small_model(mid) else 0
    variant_rank = 3 if "-sol" in mid else 2 if "-terra" in mid else 1 if "-luna" in mid else 0
    return (major, minor, variant_rank, codex_bonus, small_penalty, mid)
