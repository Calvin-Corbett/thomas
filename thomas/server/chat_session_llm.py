"""The model a background message is written with: the session's cached one, else the default. Light, so other plugins
can ask for it without Chat's routes."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_CONFIG
from thomas.server.chat_app_keys import APP_SESSION_LLM_CACHE

log = logging.getLogger(__name__)


def announce_llm(app: web.Application, sid: str) -> Any | None:
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    entry = cache.get(sid)
    if entry is not None and getattr(entry, "llm", None) is not None:
        return entry.llm
    cfg = app.get(APP_CONFIG)
    if cfg is None:
        return None
    try:
        from thomas.core.llm_client import LLMClient
        from thomas.core.llm_slot import models

        return models().open(cfg.get_model(getattr(cfg, "default_model", "") or None), default=LLMClient)
    except (AttributeError, ImportError, LookupError, RuntimeError, TypeError, ValueError) as exc:
        log.debug("announce LLM lookup failed for session %s: %s", sid, exc, exc_info=True)
        return None
