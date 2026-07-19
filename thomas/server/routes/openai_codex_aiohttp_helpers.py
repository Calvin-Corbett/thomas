"""Stateless request/config helpers for the ChatGPT/Codex OAuth routes.

These helpers are factored out of ``openai_codex_aiohttp`` to keep that module
under the repo's per-file line cap. They hold no module state and are imported
back by the routes module.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.models.catalog_rules import (
    OPENAI_CODEX_CHATGPT_VERIFIED_MODELS,
    OPENAI_CODEX_GPT56_MODELS,
)
from thomas.server.openai_codex_oauth import normalize_openai_codex_profile


def profile_from_request(request: web.Request, payload: dict[str, Any] | None = None) -> str:
    payload = payload if isinstance(payload, dict) else {}
    value = request.query.get("profile") or payload.get("profile") or "openai_codex"
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
    ids = [model_id or "gpt-5.6-sol", *OPENAI_CODEX_GPT56_MODELS, "gpt-5.5"]
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    labels = {
        "gpt-5.6-sol": "GPT-5.6 Sol",
        "gpt-5.6-terra": "GPT-5.6 Terra",
        "gpt-5.6-luna": "GPT-5.6 Luna",
    }
    for model in ids:
        if model in seen:
            continue
        seen.add(model)
        available = model in OPENAI_CODEX_CHATGPT_VERIFIED_MODELS or model not in OPENAI_CODEX_GPT56_MODELS
        row: dict[str, Any] = {
            "id": model,
            "display_name": labels.get(model, model),
            "is_default": model == (model_id or "gpt-5.6-sol"),
            "available": available,
            "connection": "chatgpt_oauth",
        }
        if model == "gpt-5.6-luna" and not available:
            row["unavailable_reason"] = (
                "This signed-in ChatGPT/Codex connection currently returns Model not found for GPT-5.6 Luna."
            )
        rows.append(row)
    return rows
