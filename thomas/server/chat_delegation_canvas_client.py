"""Cached Canvas LLM client (idle keepalive retired — it cost real inference)."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CANVAS_LLM_LOCK = asyncio.Lock()
LLM_CACHE: dict[str, Any] = {}
_REPO_ROOT = Path(__file__).resolve().parents[2]
_keepalive_started = False


def canvas_diag(message: str) -> None:
    """Append Canvas diagnostics when explicitly enabled."""

    if not os.environ.get("THOMAS_CANVAS_DIAG"):
        return
    try:
        with open(_REPO_ROOT / "_canvas_diag.log", "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        return


def build_canvas_llm(root: Path, profile: str | None, model_id: str | None = None) -> Any | None:
    """Return a warm cached low-reasoning client for the selected profile."""

    key = f"{str(profile or '')}\0{str(model_id or '')}"
    cached = LLM_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from thomas.core.config import load_config
        from thomas.core.llm_client import LLMClient

        config = load_config(Path(root) / "thomas.toml")
        model_config = config.get_model(profile or None)
        overrides: dict[str, Any] = {"reasoning_effort": "low"}
        if str(model_id or "").strip():
            overrides["model"] = str(model_id).strip()
        try:
            model_config = replace(model_config, **overrides)
        except TypeError:
            pass
        canvas_diag(
            f"[build] profile={profile!r} provider={getattr(model_config, 'provider', None)!r} "
            f"model={getattr(model_config, 'model', None)!r} "
            f"has_api_key={bool(getattr(model_config, 'api_key', None))} "
            f"backend={getattr(model_config, 'backend', None)!r}"
        )
        client = LLMClient(model_config)
        LLM_CACHE[key] = client
        return client
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return None


def evict_canvas_llm(profile: str | None, model_id: str | None = None) -> None:
    LLM_CACHE.pop(f"{str(profile or '')}\0{str(model_id or '')}", None)


def start_canvas_keepalive(root: Path | None = None) -> None:
    """No-op (kept for callers). The old 'keepalive' ran REAL model inference
    ("Reply with the single word: ok") against the ChatGPT backend every 18
    seconds from boot, 24/7 — ~4,800 wasted subscription calls a day — while
    holding CANVAS_LLM_LOCK ahead of real canvas work. Warmth is not worth
    inference: the only cost of a cold client is one slightly slower first
    canvas request, and build_canvas_llm() already caches the client."""

    global _keepalive_started
    if _keepalive_started:
        return
    _keepalive_started = True
    log.info("Canvas keepalive disabled: no idle model calls (client is built and cached on first use).")
