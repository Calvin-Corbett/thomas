"""Stateless request/config helpers for the ChatGPT/Codex OAuth routes.

These helpers are factored out of ``openai_codex_aiohttp`` to keep that module
under the repo's per-file line cap. They hold no module state and are imported
back by the routes module.
"""

from __future__ import annotations

import json
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
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        # A body that will not decode is treated as no body at all.
        return {}
    return payload if isinstance(payload, dict) else {}


def configured_codex_models(
    config: AppConfig, profile: str, catalog: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    cfg = config.models.get(profile)
    model_id = str(getattr(cfg, "model", "") or "").strip() if cfg is not None else ""
    live = [
        r
        for r in (catalog or {}).get("models") or []
        if r.get("profile") == profile and r.get("source") == "live" and not r.get("hidden")
    ]
    if live:
        # The sign-in's own list (thomas/models/catalog.py). The hand list below
        # stands in only until that list has been read once.
        return [
            {
                "id": r["id"],
                "display_name": r.get("display_name") or r["id"],
                "description": r.get("description", ""),
                "is_default": r["id"] == model_id,
                "available": True,
                "is_new": bool(r.get("is_new")),
                "retires_at": r.get("retires_at", ""),
                "replacement": r.get("replacement", ""),
                "connection": "chatgpt_oauth",
            }
            for r in live
        ]
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
