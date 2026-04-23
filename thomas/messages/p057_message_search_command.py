"""thomas.messages.p057_message_search_command

P057 - Message search command (core logic).

This module provides a small, testable implementation for searching messages.

Design goals
- Thomas-native naming and behavior (no OpenClaw naming reuse)
- Clear input/output contracts
- Deterministic, machine-readable errors
- Works in "automation" contexts via JSON serialization helpers
- Backend-agnostic with a practical default:
  - Prefer local message store search if configured
  - Otherwise fall back to Discord guild search if configured

Because the wider Thomas codebase isn't imported here, configuration is resolved
from a loosely-typed `runtime_or_config` object:
- A plain dict-like mapping
- An object with `.config` / `.settings` / `.cfg` dicts
- A Click/Typer context object with `.obj` pointing at a dict/runtime

Local store format (JSONL)
Each line is expected to be a JSON object with common fields such as:
- id / message_id
- content / text / body
- channel_id
- author.id / author_id
- timestamp
- url

Only the fields needed for search output are used.

Discord backend
If no local store path is configured, the implementation can call the Discord
"guild message search" endpoint. This requires Discord credentials in config.

Note: Discord's search endpoint is permission-sensitive; even with valid tokens,
it can return errors depending on token type and permissions.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

# -----------------------------
# Contracts
# -----------------------------


@dataclass(frozen=True)
class MessageSearchInput:
    """Validated message search request."""

    query: str
    guild_id: str | None = None
    channel_ids: tuple[str, ...] = ()
    author_ids: tuple[str, ...] = ()
    limit: int = 25


@dataclass(frozen=True)
class MessageSearchHit:
    message_id: str
    channel_id: str
    author_id: str
    content: str
    timestamp: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class MessageSearchOutput:
    total_results: int
    hits: tuple[MessageSearchHit, ...]


class MessageSearchJsonError(TypedDict):
    code: str
    message: str
    details: dict[str, Any]


class MessageSearchJsonSuccess(TypedDict):
    ok: bool
    total_results: int
    hits: list[dict[str, Any]]


class MessageSearchJsonFailure(TypedDict):
    ok: bool
    error: MessageSearchJsonError


class MessageSearchBackend(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    DISCORD = "discord"


# -----------------------------
# Deterministic errors
# -----------------------------


class MessageSearchError(RuntimeError):
    """Base error with a deterministic `code` and structured `details`."""

    code: str
    details: dict[str, Any]

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_json(self) -> MessageSearchJsonFailure:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
                "details": dict(self.details),
            },
        }


class MessageSearchInvalidInput(MessageSearchError):
    def __init__(self, *, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="invalid_input", message=message, details=details)


class MessageSearchMissingConfig(MessageSearchError):
    def __init__(self, *, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="missing_config", message=message, details=details)


class MessageSearchExternalFailure(MessageSearchError):
    def __init__(self, *, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="external_failure", message=message, details=details)


# -----------------------------
# Minimal HTTP abstraction
# -----------------------------


class HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(
        self, url: str, *, params: Sequence[tuple[str, str]] | None = None, headers: Mapping[str, str] | None = None
    ) -> HttpResponse: ...


class _UrllibResponse:
    def __init__(self, *, status_code: int, text: str):
        self.status_code = int(status_code)
        self.text = text

    def json(self) -> Any:
        return json.loads(self.text)


class _UrllibHttpClient:
    def __init__(self, *, timeout_s: float = 15.0):
        self._timeout_s = float(timeout_s)

    def get(
        self, url: str, *, params: Sequence[tuple[str, str]] | None = None, headers: Mapping[str, str] | None = None
    ) -> HttpResponse:
        if params:
            qs = urllib.parse.urlencode(list(params), doseq=True)
            joiner = "&" if ("?" in url) else "?"
            url = f"{url}{joiner}{qs}"

        req = urllib.request.Request(url=url, method="GET")
        for k, v in (headers or {}).items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
                return _UrllibResponse(status_code=getattr(resp, "status", 200), text=text)
        except urllib.error.HTTPError as e:
            raw = e.read() if hasattr(e, "read") else b""
            text = raw.decode("utf-8", errors="replace")
            return _UrllibResponse(status_code=int(getattr(e, "code", 500)), text=text)
        except (urllib.error.URLError, TimeoutError) as e:
            raise MessageSearchExternalFailure(
                message="message search request failed",
                details={"error": type(e).__name__},
            ) from e


# -----------------------------
# Helpers
# -----------------------------


_ID_WRAPPER_RE = re.compile(r"(\d+)")


def _unwrap_config(runtime_or_config: Any | None) -> Mapping[str, Any] | None:
    """Attempt to locate a dict-like config in a runtime/context object."""
    if runtime_or_config is None:
        return None

    # Direct mapping
    if isinstance(runtime_or_config, Mapping):
        return cast(Mapping[str, Any], runtime_or_config)

    # Click/Typer ctx: ctx.obj is often the runtime/config
    obj = getattr(runtime_or_config, "obj", None)
    if isinstance(obj, Mapping):
        return cast(Mapping[str, Any], obj)

    # Common patterns: runtime.config / runtime.settings
    for attr in ("config", "settings", "cfg"):
        maybe = getattr(runtime_or_config, attr, None)
        if isinstance(maybe, Mapping):
            return cast(Mapping[str, Any], maybe)

    return None


def _get_nested(mapping: Mapping[str, Any], path: Sequence[str]) -> Any | None:
    cur: Any = mapping
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        if key not in cur:
            return None
        cur = cur[key]
    return cur


def _normalize_optional_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    # If it's a Discord-style wrapper (<@123>, <#123>, etc) extract the digits.
    if raw.startswith("<") and raw.endswith(">"):
        m = _ID_WRAPPER_RE.search(raw)
        return m.group(1) if m else raw
    if raw.startswith("#") or raw.startswith("@"):
        m = _ID_WRAPPER_RE.search(raw)
        return m.group(1) if m else raw

    return raw


def _normalize_identifier_list(single: str | None, many: Sequence[str] | None) -> tuple[str, ...]:
    items: list[str] = []
    if single is not None:
        v = _normalize_optional_identifier(single)
        if v:
            items.append(v)
    if many:
        for m in many:
            v = _normalize_optional_identifier(m)
            if v:
                items.append(v)

    # stable de-dupe
    seen: set[str] = set()
    out: list[str] = []
    for v in items:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return tuple(out)


def _ensure_non_empty(value: str, *, field: str) -> str:
    v = (value or "").strip()
    if not v:
        raise MessageSearchInvalidInput(message=f"{field} must be a non-empty string", details={"field": field})
    return v


def _ensure_limit(limit: int | None) -> int:
    lim = 25 if limit is None else int(limit)
    if lim <= 0:
        raise MessageSearchInvalidInput(message="limit must be a positive integer", details={"field": "limit"})
    if lim > 100:
        raise MessageSearchInvalidInput(message="limit must be <= 100", details={"field": "limit", "limit": lim})
    return lim


def validate_message_search_input(
    *,
    query: str,
    guild_id: str | None = None,
    channel_id: str | None = None,
    channel_ids: Sequence[str] | None = None,
    author_id: str | None = None,
    author_ids: Sequence[str] | None = None,
    limit: int | None = None,
) -> MessageSearchInput:
    """Validate and normalize raw inputs into a MessageSearchInput."""
    q = _ensure_non_empty(query, field="query")
    lim = _ensure_limit(limit)

    gid = _normalize_optional_identifier(guild_id)
    cids = _normalize_identifier_list(channel_id, channel_ids)
    aids = _normalize_identifier_list(author_id, author_ids)

    return MessageSearchInput(query=q, guild_id=gid, channel_ids=cids, author_ids=aids, limit=lim)


def _resolve_message_store_path(cfg: Mapping[str, Any]) -> str | None:
    """Resolve a local JSONL store path from config/env.

    Supported config locations (best-effort):
    - messages.store_path
    - messages.log_path
    - messages.jsonl_path
    - storage.messages_path

    Environment fallback:
    - THOMAS_MESSAGE_STORE_PATH
    """
    env = os.getenv("THOMAS_MESSAGE_STORE_PATH")
    if env and env.strip():
        return env.strip()

    candidates: list[tuple[str, ...]] = [
        ("messages", "store_path"),
        ("messages", "log_path"),
        ("messages", "jsonl_path"),
        ("storage", "messages_path"),
        ("storage", "messages_log"),
    ]
    for p in candidates:
        v = _get_nested(cfg, p)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # If the app has a data_dir, accept messages.jsonl as an implicit default.
    data_dir = cfg.get("data_dir") if isinstance(cfg, Mapping) else None
    if isinstance(data_dir, str) and data_dir.strip():
        return str(Path(data_dir.strip()) / "messages.jsonl")

    return None


@dataclass(frozen=True)
class _DiscordAuth:
    token: str
    api_base: str
    authorization_header: str


def _resolve_discord_auth(cfg: Mapping[str, Any]) -> _DiscordAuth:
    """Resolve Discord auth from config/env.

    Supported config locations (best-effort):
    - channels.discord.token
    - channels.discord.authorization
    - discord.token
    - discord.authorization

    Environment fallback:
    - THOMAS_DISCORD_TOKEN
    """
    env = os.getenv("THOMAS_DISCORD_TOKEN")
    if env and env.strip():
        token_raw = env.strip()
    else:
        token_paths: list[tuple[str, ...]] = [
            ("channels", "discord", "authorization"),
            ("channels", "discord", "token"),
            ("discord", "authorization"),
            ("discord", "token"),
            ("discord_token",),
        ]
        token_raw = ""
        for p in token_paths:
            v = _get_nested(cfg, p)
            if isinstance(v, str) and v.strip():
                token_raw = v.strip()
                break

    if not token_raw:
        raise MessageSearchMissingConfig(
            message="Discord credentials are not configured",
            details={"expected_any_of": ["channels.discord.token", "discord.token", "THOMAS_DISCORD_TOKEN"]},
        )

    base_paths: list[tuple[str, ...]] = [
        ("channels", "discord", "api_base"),
        ("channels", "discord", "base_url"),
        ("discord", "api_base"),
        ("discord", "base_url"),
    ]
    api_base = "https://discord.com/api/v9"
    for p in base_paths:
        v = _get_nested(cfg, p)
        if isinstance(v, str) and v.strip():
            api_base = v.strip().rstrip("/")
            break

    # If token already looks like an authorization header, keep it.
    if token_raw.lower().startswith("bot ") or token_raw.lower().startswith("bearer "):
        auth_header = token_raw
    else:
        # Do not guess token type; pass as-is.
        auth_header = token_raw

    return _DiscordAuth(token=token_raw, api_base=api_base, authorization_header=auth_header)


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _search_local_jsonl(search_input: MessageSearchInput, *, store_path: str) -> MessageSearchOutput:
    path = Path(store_path)
    if not path.exists() or not path.is_file():
        raise MessageSearchExternalFailure(
            message="local message store is not readable",
            details={"path": str(path)},
        )

    query_cf = search_input.query.casefold()
    channel_filter = set(search_input.channel_ids)
    author_filter = set(search_input.author_ids)

    total = 0
    hits: list[MessageSearchHit] = []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                # Skip malformed lines deterministically.
                continue

            if not isinstance(rec, Mapping):
                continue

            content = _as_str(rec.get("content") or rec.get("text") or rec.get("body"))
            if query_cf not in content.casefold():
                continue

            channel_id = _as_str(rec.get("channel_id") or rec.get("channel") or rec.get("channelId"))
            if channel_filter and channel_id not in channel_filter:
                continue

            author_id = ""
            author = rec.get("author")
            if isinstance(author, Mapping):
                author_id = _as_str(author.get("id"))
            if not author_id:
                author_id = _as_str(rec.get("author_id") or rec.get("user_id") or rec.get("userId"))

            if author_filter and author_id not in author_filter:
                continue

            message_id = _as_str(rec.get("message_id") or rec.get("id"))
            if not message_id:
                # Skip entries without any stable identifier.
                continue

            timestamp = rec.get("timestamp") or rec.get("ts")
            url = rec.get("url")

            total += 1
            if len(hits) < search_input.limit:
                hits.append(
                    MessageSearchHit(
                        message_id=message_id,
                        channel_id=channel_id,
                        author_id=author_id,
                        content=content,
                        timestamp=_as_str(timestamp) if timestamp is not None else None,
                        url=_as_str(url) if url is not None else None,
                    )
                )

    return MessageSearchOutput(total_results=total, hits=tuple(hits))


def _validate_discord_ids(search_input: MessageSearchInput) -> MessageSearchInput:
    if not search_input.guild_id:
        raise MessageSearchInvalidInput(
            message="guild_id is required for Discord-backed search",
            details={"field": "guild_id"},
        )

    if not re.fullmatch(r"\d+", search_input.guild_id):
        raise MessageSearchInvalidInput(
            message="guild_id must be a numeric id for Discord-backed search",
            details={"field": "guild_id", "value": search_input.guild_id},
        )

    for cid in search_input.channel_ids:
        if not re.fullmatch(r"\d+", cid):
            raise MessageSearchInvalidInput(
                message="channel_id must be numeric for Discord-backed search",
                details={"field": "channel_id", "value": cid},
            )

    for aid in search_input.author_ids:
        if not re.fullmatch(r"\d+", aid):
            raise MessageSearchInvalidInput(
                message="author_id must be numeric for Discord-backed search",
                details={"field": "author_id", "value": aid},
            )

    return search_input


def _search_discord(
    search_input: MessageSearchInput,
    *,
    cfg: Mapping[str, Any],
    http_client: HttpClient | None,
) -> MessageSearchOutput:
    validated = _validate_discord_ids(search_input)
    auth = _resolve_discord_auth(cfg)

    params: list[tuple[str, str]] = [("content", validated.query), ("limit", str(validated.limit))]
    for cid in validated.channel_ids:
        params.append(("channel_id", cid))
    for aid in validated.author_ids:
        params.append(("author_id", aid))

    url = f"{auth.api_base}/guilds/{validated.guild_id}/messages/search"
    headers = {"Authorization": auth.authorization_header}

    client = http_client or _UrllibHttpClient(timeout_s=15.0)
    resp = client.get(url, params=params, headers=headers)

    if resp.status_code < 200 or resp.status_code >= 300:
        body_preview = resp.text
        if len(body_preview) > 500:
            body_preview = body_preview[:500] + "…"
        raise MessageSearchExternalFailure(
            message="message search request returned a non-success status",
            details={"status_code": int(resp.status_code), "body": body_preview},
        )

    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError, KeyError) as e:  # noqa: BLE001 - map any parse failure to deterministic error
        raise MessageSearchExternalFailure(
            message="message search response was not valid JSON",
            details={"status_code": int(resp.status_code)},
        ) from e

    total = int(payload.get("total_results") or payload.get("total") or 0)

    raw_messages = payload.get("messages", [])
    flattened: list[Mapping[str, Any]] = []
    if isinstance(raw_messages, list):
        for item in raw_messages:
            if isinstance(item, list):
                for inner in item:
                    if isinstance(inner, Mapping):
                        flattened.append(cast(Mapping[str, Any], inner))
            elif isinstance(item, Mapping):
                flattened.append(cast(Mapping[str, Any], item))

    hits: list[MessageSearchHit] = []
    for msg in flattened[: validated.limit]:
        msg_id = _as_str(msg.get("id"))
        ch_id = _as_str(msg.get("channel_id"))
        if not msg_id or not ch_id:
            continue

        author_id = ""
        author = msg.get("author")
        if isinstance(author, Mapping):
            author_id = _as_str(author.get("id"))
        if not author_id:
            author_id = _as_str(msg.get("author_id"))

        content = _as_str(msg.get("content"))
        ts = msg.get("timestamp")
        timestamp = _as_str(ts) if ts is not None else None
        url = f"https://discord.com/channels/{validated.guild_id}/{ch_id}/{msg_id}"

        hits.append(
            MessageSearchHit(
                message_id=msg_id,
                channel_id=ch_id,
                author_id=author_id,
                content=content,
                timestamp=timestamp,
                url=url,
            )
        )

    return MessageSearchOutput(total_results=total, hits=tuple(hits))


def search_messages(
    search_input: MessageSearchInput,
    *,
    runtime_or_config: Any | None = None,
    backend: MessageSearchBackend | str = MessageSearchBackend.AUTO,
    http_client: HttpClient | None = None,
) -> MessageSearchOutput:
    """Search messages using the selected backend.

    Backend selection:
    - auto: prefer local store if configured; else Discord if configured
    - local: require local store path
    - discord: require guild_id + Discord credentials
    """
    # Validate again defensively.
    validated = validate_message_search_input(
        query=search_input.query,
        guild_id=search_input.guild_id,
        channel_ids=search_input.channel_ids,
        author_ids=search_input.author_ids,
        limit=search_input.limit,
    )

    # Normalize backend.
    if isinstance(backend, str):
        try:
            backend = MessageSearchBackend(backend)
        except ValueError as e:
            raise MessageSearchInvalidInput(
                message="backend must be one of: auto, local, discord",
                details={"field": "backend", "value": backend},
            ) from e

    cfg = _unwrap_config(runtime_or_config) or {}
    store_path = _resolve_message_store_path(cfg)

    if backend in (MessageSearchBackend.AUTO, MessageSearchBackend.LOCAL):
        if store_path:
            return _search_local_jsonl(validated, store_path=store_path)
        if backend is MessageSearchBackend.LOCAL:
            raise MessageSearchMissingConfig(
                message="local message store path is not configured",
                details={"expected_any_of": ["messages.store_path", "THOMAS_MESSAGE_STORE_PATH"]},
            )

    # Discord fallback
    if backend in (MessageSearchBackend.AUTO, MessageSearchBackend.DISCORD):
        # If AUTO and local store is missing, Discord requires guild_id and token.
        if not validated.guild_id:
            raise MessageSearchMissingConfig(
                message="no message search backend is configured",
                details={
                    "hint": "Configure a local message store path or provide --guild-id with Discord credentials.",
                    "expected_any_of": [
                        "messages.store_path",
                        "THOMAS_MESSAGE_STORE_PATH",
                        "channels.discord.token",
                        "THOMAS_DISCORD_TOKEN",
                    ],
                },
            )

        return _search_discord(validated, cfg=cfg, http_client=http_client)

    # Should be unreachable.
    raise MessageSearchInvalidInput(message="unsupported backend", details={"backend": str(backend)})


def to_json_success(output: MessageSearchOutput) -> MessageSearchJsonSuccess:
    return {
        "ok": True,
        "total_results": int(output.total_results),
        "hits": [
            {
                "message_id": h.message_id,
                "channel_id": h.channel_id,
                "author_id": h.author_id,
                "content": h.content,
                "timestamp": h.timestamp,
                "url": h.url,
            }
            for h in output.hits
        ],
    }
