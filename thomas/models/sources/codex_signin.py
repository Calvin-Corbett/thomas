"""The ChatGPT sign-in's own model list, the one the Codex app shows.

``GET <OPENAI_CODEX_BASE_URL>/models?client_version=<v>`` with the sign-in token
names every model the account may use: the provider's order, display names,
which ones are hidden, and retirement notices. When that call fails, the Codex
app's own copy (``models_cache.json`` in ``$CODEX_HOME`` or ``~/.codex``)
stands in while it is under a week old.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from thomas.core.codex_provider import OPENAI_CODEX_BASE_URL
from thomas.models.sources import ListedModel, SourceAnswer, TokenFn

DEFAULT_CLIENT_VERSION = "0.155.0"
APP_COPY_MAX_AGE = timedelta(days=7)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _int_or(value: Any, default: int | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def parse_codex_models(payload: Any) -> tuple[ListedModel, ...]:
    rows = payload.get("models") if isinstance(payload, dict) else None
    out: list[ListedModel] = []
    for row in rows if isinstance(rows, list) else []:
        slug = str(row.get("slug") or "").strip() if isinstance(row, dict) else ""
        if not slug:
            continue
        upgrade = row.get("upgrade") if isinstance(row.get("upgrade"), dict) else {}
        out.append(
            ListedModel(
                id=slug,
                display_name=str(row.get("display_name") or ""),
                description=str(row.get("description") or ""),
                order=_int_or(row.get("priority"), 1000) or 0,
                hidden=str(row.get("visibility") or "list").strip().lower() != "list",
                retires_at=str(upgrade.get("retirement_at") or ""),
                replacement=str(upgrade.get("model") or ""),
                context_window=_int_or(row.get("context_window"), None),
            )
        )
    return tuple(sorted(out, key=lambda m: (m.order, m.id)))


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def app_client_version(home: Path | None = None) -> str:
    try:
        version = _read_json((home or codex_home()) / "models_cache.json").get("client_version")
    except (OSError, ValueError):
        return DEFAULT_CLIENT_VERSION
    return str(version or DEFAULT_CLIENT_VERSION)


def read_app_cache(home: Path | None = None, *, now: datetime | None = None) -> SourceAnswer:
    path = (home or codex_home()) / "models_cache.json"
    try:
        cached = _read_json(path)
        fetched = datetime.fromisoformat(str(cached["fetched_at"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError) as exc:
        return SourceAnswer(ok=False, source="codex-app", error=f"no readable Codex app list at {path}: {exc}")
    age = (now or datetime.now(timezone.utc)) - fetched
    if age > APP_COPY_MAX_AGE:
        return SourceAnswer(ok=False, source="codex-app", error=f"the Codex app's list is {age.days} days old")
    models = parse_codex_models(cached)
    if not models:
        return SourceAnswer(ok=False, source="codex-app", error="the Codex app's list is empty")
    return SourceAnswer(ok=True, source="codex-app", models=models)


async def _live(
    token: str, *, etag: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None, home: Path | None
) -> SourceAnswer:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    url = OPENAI_CODEX_BASE_URL.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:
            resp = await client.get(url, params={"client_version": app_client_version(home)}, headers=headers)
        if resp.status_code == 304:
            return SourceAnswer(ok=True, source="chatgpt", etag=etag, not_modified=True)
        if resp.status_code != 200:
            return SourceAnswer(
                ok=False, source="chatgpt", error=f"the ChatGPT sign-in answered HTTP {resp.status_code}"
            )
        models = parse_codex_models(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        return SourceAnswer(
            ok=False, source="chatgpt", error=f"the ChatGPT sign-in could not be reached: {type(exc).__name__}"
        )
    if not models:
        return SourceAnswer(ok=False, source="chatgpt", error="the ChatGPT sign-in answered with no models")
    return SourceAnswer(ok=True, source="chatgpt", models=models, etag=resp.headers.get("etag", ""))


async def list_codex_models(
    profile: str,
    *,
    codex_token: TokenFn | None,
    etag: str = "",
    timeout_s: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
    home: Path | None = None,
) -> SourceAnswer:
    live_error = "no ChatGPT sign-in token"
    token = ""
    if codex_token is not None:
        try:
            token = str(await codex_token(profile) or "").strip()
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            live_error = f"the ChatGPT sign-in could not be read: {type(exc).__name__}"
    if token:
        answer = await _live(token, etag=etag, timeout_s=timeout_s, transport=transport, home=home)
        if answer.ok:
            return answer
        live_error = answer.error
    fallback = read_app_cache(home)
    if fallback.ok:
        return fallback
    return SourceAnswer(ok=False, source="chatgpt", error=f"{live_error}; {fallback.error}")
