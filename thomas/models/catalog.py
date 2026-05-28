"""Refreshable model catalog for configured Thomas providers.

The catalog is intentionally runtime-first: configured profiles are always
included, live provider discovery is merged when refresh is requested, and a
small curated frontier fallback keeps new model ids usable before every local
Codex install has learned to list them.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.models.catalog_rules import CURATED_OPENAI_MODELS, build_aliases, dedupe_entries, entry, provider_family
from thomas.models.discovery import handshake_models_async

CATALOG_SCHEMA_VERSION = 1
CATALOG_TTL_SECONDS = 12 * 60 * 60


def model_catalog_path(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "model_catalog" / "catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


async def build_model_catalog_async(
    config: AppConfig,
    *,
    refresh: bool = False,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    handshakes: dict[str, Any] = {}

    for profile, cfg in config.models.items():
        provider = str(getattr(cfg, "provider", "") or "").strip().lower()
        family = provider_family(cfg)
        configured_model = str(getattr(cfg, "model", "") or "").strip()
        profiles.append(
            {
                "name": profile,
                "provider": provider,
                "family": family,
                "configured_model": configured_model,
                "default": profile == config.default_model,
            }
        )
        if configured_model:
            entries.append(
                entry(
                    profile=profile,
                    provider=provider,
                    family=family,
                    model_id=configured_model,
                    source="config",
                    available=True,
                    is_default=profile == config.default_model,
                )
            )
        if refresh:
            try:
                handshake = await handshake_models_async(cfg, timeout_s=max(0.5, float(timeout_s)))
                handshakes[profile] = handshake.to_dict()
                for model_id in list(handshake.models or []):
                    entries.append(
                        entry(
                            profile=profile,
                            provider=provider,
                            family=family,
                            model_id=model_id,
                            source="live",
                            available=bool(handshake.ok),
                        )
                    )
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                handshakes[profile] = {
                    "ok": False,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "models": [],
                }

    for model_id in CURATED_OPENAI_MODELS:
        entries.append(
            entry(
                profile="",
                provider="codex",
                family="openai",
                model_id=model_id,
                source="curated",
                available=False,
            )
        )

    entries = dedupe_entries(entries)
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "updated_at": _now_utc(),
        "refresh": bool(refresh),
        "cache_ttl_seconds": CATALOG_TTL_SECONDS,
        "profiles": profiles,
        "models": entries,
        "aliases": build_aliases(entries),
        "handshakes": handshakes,
        "cache_path": str(model_catalog_path(config)),
    }
    if refresh:
        save_model_catalog(config, payload)
    return payload


def build_model_catalog(
    config: AppConfig,
    *,
    refresh: bool = False,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    return asyncio.run(build_model_catalog_async(config, refresh=refresh, timeout_s=timeout_s))


def save_model_catalog(config: AppConfig, payload: dict[str, Any]) -> Path:
    path = model_catalog_path(config)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_cached_model_catalog(config: AppConfig) -> dict[str, Any] | None:
    path = model_catalog_path(config)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("schema_version") or 0) != CATALOG_SCHEMA_VERSION:
        return None
    payload.setdefault("cache_path", str(path))
    return payload


def model_catalog_is_stale(payload: dict[str, Any] | None, *, ttl_seconds: int = CATALOG_TTL_SECONDS) -> bool:
    if not payload:
        return True
    updated = _parse_utc(str(payload.get("updated_at") or ""))
    if updated is None:
        return True
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    return age > max(1, int(ttl_seconds))


async def get_model_catalog_async(
    config: AppConfig,
    *,
    refresh: bool | None = None,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    cached = load_cached_model_catalog(config)
    should_refresh = bool(refresh) if refresh is not None else model_catalog_is_stale(cached)
    if should_refresh:
        return await build_model_catalog_async(config, refresh=True, timeout_s=timeout_s)
    if cached is not None:
        return cached
    return await build_model_catalog_async(config, refresh=False, timeout_s=timeout_s)


def get_model_catalog(
    config: AppConfig,
    *,
    refresh: bool | None = None,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    return asyncio.run(get_model_catalog_async(config, refresh=refresh, timeout_s=timeout_s))
