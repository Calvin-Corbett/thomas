"""Stateless request/config helpers for the ChatGPT/Codex OAuth routes.

These helpers are factored out of ``openai_codex_aiohttp`` to keep that module
under the repo's per-file line cap. They hold no module state and are imported
back by the routes module.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.openai_codex_oauth import normalize_openai_codex_profile


def profile_from_request(request: web.Request, payload: dict[str, Any] | None = None) -> str:
    payload = payload if isinstance(payload, dict) else {}
    value = request.query.get("profile") or payload.get("profile") or "chatgpt"
    return normalize_openai_codex_profile(str(value or ""))


async def read_json_object(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def configured_codex_models(config: AppConfig, profile: str) -> list[dict[str, Any]]:
    cfg = config.models.get(profile)
    model_id = str(getattr(cfg, "model", "") or "").strip() if cfg is not None else ""
    ids = [model_id] if model_id else ["gpt-5.5"]
    seen: set[str] = set()
    return [
        {
            "id": model,
            "display_name": model,
            "is_default": idx == 0,
        }
        for idx, model in enumerate(ids)
        if not (model in seen or seen.add(model))
    ]
