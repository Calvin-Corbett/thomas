"""Refreshable model catalog for configured Thomas providers.

The catalog is intentionally runtime-first: configured profiles are always
included, live provider discovery is merged when refresh is requested, and a
small curated frontier fallback keeps new model ids usable before every local
Codex install has learned to list them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thomas.core import listed_models
from thomas.core.claude_alias_ids import CLAUDE_SIZE_ALIASES, alias_label
from thomas.core.config import AppConfig, ModelConfig
from thomas.models.catalog_rules import CURATED_OPENAI_MODELS, build_aliases, dedupe_entries, entry, provider_family
from thomas.models.sources import ListedModel, SourceAnswer, TokenFn, list_profile_models

log = logging.getLogger(__name__)

CATALOG_SCHEMA_VERSION = 2
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


NEW_FOR = timedelta(days=7)


def _live_row(profile: str, provider: str, family: str, model: ListedModel) -> dict[str, Any]:
    """One model a connection listed. ``source`` used to be an argument, to mark the
    Claude CLI's names ``build_only``: Chat could not run them, so the picker hid them
    outside Build. Chat runs them now (thomas/core/llm_streaming_claude_cli.py), so
    there is nothing left for the flag to hide and no row carries it."""
    row = entry(
        profile=profile,
        provider=provider,
        family=family,
        model_id=model.id,
        source="live",
        available=True,
        display_name=model.display_name,
    )
    row.update(
        description=model.description,
        order=model.order,
        hidden=model.hidden,
        retires_at=model.retires_at,
        replacement=model.replacement,
        context_window=model.context_window,
    )
    return row


def _is_codex(cfg: ModelConfig) -> bool:
    return str(getattr(cfg, "provider", "") or "").strip().lower().replace("-", "_") == "openai_codex"


async def build_model_catalog_async(
    config: AppConfig,
    *,
    refresh: bool = False,
    timeout_s: float = 10.0,
    cfg_with_secrets: Callable[[str], ModelConfig] | None = None,
    codex_token: TokenFn | None = None,
) -> dict[str, Any]:
    now = _now_utc()
    previous = load_cached_model_catalog(config) or {}
    previous_rows = [r for r in previous.get("models") or [] if isinstance(r, dict)]
    previous_state: dict[str, Any] = dict(previous.get("providers") or {})
    first_seen = {(r.get("profile"), r.get("id")): str(r.get("first_seen") or "") for r in previous_rows}
    entries: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    providers: dict[str, dict[str, Any]] = {}
    model_items = list(config.models.items())

    async def _answer_for(answer_profile: str, answer_cfg: ModelConfig) -> SourceAnswer:
        resolved = cfg_with_secrets(answer_profile) if cfg_with_secrets else answer_cfg
        prior_etag = str((previous_state.get(answer_profile) or {}).get("etag") or "")
        return await list_profile_models(
            answer_profile, resolved, codex_token=codex_token, previous_etag=prior_etag, timeout_s=timeout_s
        )

    answers: dict[str, SourceAnswer] = {}
    if refresh:
        # Ask every profile at once: sequential asking measured 13-15s for 16
        # profiles with 10s timeouts, and one reader raising used to lose the
        # whole refresh. gather() with return_exceptions turns a raise into a
        # failed answer for that profile only; everyone else's check still
        # lands. The merge loop below is unchanged -- only the asking moved.
        gathered = await asyncio.gather(
            *(_answer_for(profile, cfg) for profile, cfg in model_items), return_exceptions=True
        )
        for (profile, _cfg), result in zip(model_items, gathered, strict=True):
            if isinstance(result, BaseException):
                log.warning("model list refresh failed for %s: %s", profile, result, exc_info=result)
                answers[profile] = SourceAnswer(
                    ok=False, source="provider", error=f"{profile}: {type(result).__name__}"
                )
            else:
                answers[profile] = result

    for profile, cfg in model_items:
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
        state = dict(previous_state.get(profile) or {})
        had_answered = bool(state.get("checked_at"))
        live = [dict(r) for r in previous_rows if r.get("profile") == profile and r.get("source") == "live"]
        if refresh:
            answer = answers[profile]
            state["last_attempt_at"] = now
            if answer.ok:
                if not answer.not_modified:
                    live = [_live_row(profile, provider, family, m) for m in answer.models]
                state.update(
                    checked_at=now, error="", etag=answer.etag or str(state.get("etag") or ""), source=answer.source
                )
            else:
                state["error"] = answer.error
        for row in live:
            # A connection's first answer is the baseline, not news: nothing in
            # it is marked New. Later arrivals are dated when first seen.
            key = (profile, row["id"])
            row["first_seen"] = first_seen.get(key, now if had_answered else "")
        if state:
            providers[profile] = state
        entries.extend(live)

    signed_in = any(providers.get(name, {}).get("checked_at") for name, cfg in config.models.items() if _is_codex(cfg))
    if not signed_in:
        # The curated list is a hand-typed stand-in, never merged over a live
        # answer: skip any id a live or config row already listed for this family.
        live_openai_ids = {str(e.get("id") or "") for e in entries if str(e.get("family") or "") == "openai"}
        for model_id in CURATED_OPENAI_MODELS:
            if model_id in live_openai_ids:
                continue
            entries.append(
                entry(
                    profile="",
                    provider="openai_codex",
                    family="openai",
                    model_id=model_id,
                    source="curated",
                    available=False,
                )
            )

    entries = dedupe_entries(entries)
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "updated_at": now,
        "refresh": bool(refresh),
        "cache_ttl_seconds": CATALOG_TTL_SECONDS,
        "profiles": profiles,
        "providers": providers,
        "models": entries,
        "aliases": build_aliases(entries),
        "cache_path": str(model_catalog_path(config)),
    }
    if refresh:
        save_model_catalog(config, payload)
    publish_listed(payload)
    return payload


def publish_listed(payload: dict[str, Any]) -> None:
    """Tell Build which Claude ids Anthropic listed (thomas/core/listed_models.py)."""
    rows = payload.get("models") or []
    listed_models.publish(
        "anthropic",
        [str(r.get("id") or "") for r in rows if r.get("family") == "anthropic" and r.get("source") == "live"],
    )


def _current_alias_label(row: dict[str, Any]) -> dict[str, Any]:
    """A Claude alias row labelled with what is known NOW, not at the last refresh.

    The cached catalog froze the label from the day it was built, so a run that
    reported what ``opus`` starts changed nothing the picker showed until the
    next refresh -- up to half a day later.
    """
    if row.get("family") != "anthropic" or str(row.get("id") or "") not in CLAUDE_SIZE_ALIASES:
        return row
    display_name, description = alias_label(str(row["id"]))
    return {**row, "display_name": display_name, "description": description}


def catalog_view(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """The payload as the pickers get it: each row says whether it is new."""
    moment = now or datetime.now(timezone.utc)
    view = dict(payload)
    view["models"] = [
        {
            **_current_alias_label(row),
            "is_new": bool((seen := _parse_utc(str(row.get("first_seen") or ""))) and moment - seen < NEW_FOR),
        }
        for row in payload.get("models") or []
    ]
    return view


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
    publish_listed(payload)
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
