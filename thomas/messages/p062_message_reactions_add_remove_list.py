"""P062 - Message reactions add/remove/list.

Thomas-native functionality for managing reactions on a message.

What this *is*:
- Validated, deterministic core operations: add/remove/list
- Pluggable backend interface (Protocol)
- A simple in-memory backend for tests/local runs
- An optional HTTP backend for delegating to a running Thomas server

What this *isn't*:
- A promise about your server route layout. The HTTP backend is a thin client
  that expects a small route surface. Adjust paths as needed once the server
  implementation exists.

Environment variables (used when no config is supplied, or to fill missing config fields):
- THOMAS_MESSAGE_REACTIONS_BACKEND: "memory" | "http"
- THOMAS_API_BASE_URL: required if backend=http
- THOMAS_API_TOKEN: optional if backend=http
- THOMAS_API_TIMEOUT_SECONDS: optional float

All errors are returned as deterministic, machine-readable dicts via `to_dict()`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Protocol, Sequence, Tuple


def _resolve_error_base() -> type[Exception]:
    """Best-effort resolution of Thomas' base error type."""
    import importlib

    candidates = (
        ("thomas.errors", "ThomasError"),
        ("thomas.core.errors", "ThomasError"),
        ("thomas.exceptions", "ThomasError"),
    )
    for module_name, attr in candidates:
        try:
            module = importlib.import_module(module_name)
            base = getattr(module, attr)
            if isinstance(base, type) and issubclass(base, Exception):
                return base
        except Exception:
            continue
    return Exception


_ThomasErrorBase = _resolve_error_base()


class MessageReactionsError(_ThomasErrorBase):
    """Deterministic error for message reaction operations."""

    code: str
    details: Dict[str, Any]

    def __init__(self, code: str, message: str, *, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    @classmethod
    def invalid_input(cls, message: str, *, details: Optional[Dict[str, Any]] = None) -> "MessageReactionsError":
        return cls("invalid_input", message, details=details)

    @classmethod
    def missing_config(cls, message: str, *, details: Optional[Dict[str, Any]] = None) -> "MessageReactionsError":
        return cls("missing_config", message, details=details)

    @classmethod
    def external_failure(cls, message: str, *, details: Optional[Dict[str, Any]] = None) -> "MessageReactionsError":
        return cls("external_failure", message, details=details)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {"code": self.code, "message": str(self), "details": self.details},
        }


def _non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MessageReactionsError.invalid_input(
            f"{field_name} must be a string",
            details={"field": field_name, "value_type": type(value).__name__},
        )
    s = value.strip()
    if not s:
        raise MessageReactionsError.invalid_input(f"{field_name} must not be empty", details={"field": field_name})
    return s


def _optional_str(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MessageReactionsError.invalid_input(
            f"{field_name} must be a string if provided",
            details={"field": field_name, "value_type": type(value).__name__},
        )
    s = value.strip()
    return s or None


def _normalize_emoji(raw: Any) -> str:
    emoji = _non_empty_str(raw, "emoji")
    # Permissive: allow both unicode and :shortcode:
    if len(emoji) > 64:
        raise MessageReactionsError.invalid_input(
            "emoji is too long",
            details={"max_length": 64, "length": len(emoji)},
        )
    return emoji


@dataclass(frozen=True, slots=True)
class MessageReactionAddInput:
    message_id: str
    emoji: str
    channel_id: Optional[str] = None
    user_id: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MessageReactionAddInput":
        return cls(
            message_id=_non_empty_str(data.get("message_id"), "message_id"),
            emoji=_normalize_emoji(data.get("emoji")),
            channel_id=_optional_str(data.get("channel_id"), "channel_id"),
            user_id=_optional_str(data.get("user_id"), "user_id"),
        )


@dataclass(frozen=True, slots=True)
class MessageReactionRemoveInput:
    message_id: str
    emoji: str
    channel_id: Optional[str] = None
    user_id: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MessageReactionRemoveInput":
        return cls(
            message_id=_non_empty_str(data.get("message_id"), "message_id"),
            emoji=_normalize_emoji(data.get("emoji")),
            channel_id=_optional_str(data.get("channel_id"), "channel_id"),
            user_id=_optional_str(data.get("user_id"), "user_id"),
        )


@dataclass(frozen=True, slots=True)
class MessageReactionListInput:
    message_id: str
    channel_id: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MessageReactionListInput":
        return cls(
            message_id=_non_empty_str(data.get("message_id"), "message_id"),
            channel_id=_optional_str(data.get("channel_id"), "channel_id"),
        )


@dataclass(frozen=True, slots=True)
class ReactionSummary:
    emoji: str
    count: int
    user_ids: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {"emoji": self.emoji, "count": self.count, "user_ids": list(self.user_ids)}


@dataclass(frozen=True, slots=True)
class ReactionMutationResult:
    ok: bool
    action: str
    message_id: str
    channel_id: Optional[str]
    emoji: str
    applied: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "emoji": self.emoji,
            "applied": self.applied,
        }


@dataclass(frozen=True, slots=True)
class ReactionListResult:
    ok: bool
    action: str
    message_id: str
    channel_id: Optional[str]
    reactions: Tuple[ReactionSummary, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "reactions": [r.to_dict() for r in self.reactions],
        }


class ReactionBackend(Protocol):
    """Backend interface for reaction operations."""

    name: str

    def add_reaction(self, *, message_id: str, emoji: str, channel_id: Optional[str], user_id: Optional[str]) -> bool:
        """Return True if a state change was applied, False if no-op."""

    def remove_reaction(self, *, message_id: str, emoji: str, channel_id: Optional[str], user_id: Optional[str]) -> bool:
        """Return True if a state change was applied, False if no-op."""

    def list_reactions(self, *, message_id: str, channel_id: Optional[str]) -> Sequence[ReactionSummary]:
        """Return a list of reaction summaries."""


# Module-level store so "memory" backend works across multiple CLI invocations in same process.
_DEFAULT_MEMORY_STORE: MutableMapping[str, MutableMapping[str, set[str]]] = {}


class InMemoryReactionBackend:
    """Simple in-process backend for tests/local usage."""

    name = "memory"

    def __init__(self, store: Optional[MutableMapping[str, MutableMapping[str, set[str]]]] = None):
        self._store = store if store is not None else _DEFAULT_MEMORY_STORE

    @staticmethod
    def _key(message_id: str, channel_id: Optional[str]) -> str:
        return f"{channel_id or ''}:{message_id}"

    def add_reaction(self, *, message_id: str, emoji: str, channel_id: Optional[str], user_id: Optional[str]) -> bool:
        key = self._key(message_id, channel_id)
        emoji_map = self._store.setdefault(key, {})
        users = emoji_map.setdefault(emoji, set())
        uid = user_id or "bot"
        if uid in users:
            return False
        users.add(uid)
        return True

    def remove_reaction(self, *, message_id: str, emoji: str, channel_id: Optional[str], user_id: Optional[str]) -> bool:
        key = self._key(message_id, channel_id)
        emoji_map = self._store.get(key)
        if not emoji_map:
            return False
        users = emoji_map.get(emoji)
        if not users:
            return False
        uid = user_id or "bot"
        if uid not in users:
            return False
        users.remove(uid)
        if not users:
            emoji_map.pop(emoji, None)
        if not emoji_map:
            self._store.pop(key, None)
        return True

    def list_reactions(self, *, message_id: str, channel_id: Optional[str]) -> Sequence[ReactionSummary]:
        key = self._key(message_id, channel_id)
        emoji_map = self._store.get(key, {})
        out: List[ReactionSummary] = []
        for emoji in sorted(emoji_map.keys()):
            user_ids = tuple(sorted(emoji_map[emoji]))
            out.append(ReactionSummary(emoji=emoji, count=len(user_ids), user_ids=user_ids))
        return out

    @classmethod
    def reset_global_store(cls) -> None:
        _DEFAULT_MEMORY_STORE.clear()


@dataclass(frozen=True, slots=True)
class MessageReactionsConfig:
    backend: str
    api_base_url: Optional[str] = None
    api_token: Optional[str] = None
    timeout_seconds: float = 10.0


class HttpReactionBackend:
    """Generic HTTP backend.

    Expected endpoints (relative to base_url):
      - POST /messages/reactions/add
      - POST /messages/reactions/remove
      - GET  /messages/reactions/list?message_id=...&channel_id=...

    These paths are placeholders until the server-side routes exist.
    """

    name = "http"

    def __init__(self, *, base_url: str, token: Optional[str], timeout_seconds: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds

    def _request(self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json"}
        data_bytes: Optional[bytes] = None
        if json_body is not None:
            data_bytes = json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        req = urllib.request.Request(url=url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            raise MessageReactionsError.external_failure(
                "HTTP backend returned an error",
                details={
                    "backend": self.name,
                    "status": int(getattr(e, "code", 0) or 0),
                    "reason": getattr(e, "reason", ""),
                    "body": body,
                },
            ) from e
        except urllib.error.URLError as e:
            raise MessageReactionsError.external_failure(
                "HTTP backend request failed",
                details={"backend": self.name, "reason": str(getattr(e, "reason", e))},
            ) from e
        except json.JSONDecodeError as e:
            raise MessageReactionsError.external_failure(
                "HTTP backend returned invalid JSON",
                details={"backend": self.name, "error": str(e)},
            ) from e

    def add_reaction(self, *, message_id: str, emoji: str, channel_id: Optional[str], user_id: Optional[str]) -> bool:
        resp = self._request(
            "POST",
            "/messages/reactions/add",
            json_body={"message_id": message_id, "emoji": emoji, "channel_id": channel_id, "user_id": user_id},
        )
        applied = resp.get("applied")
        return bool(applied) if applied is not None else True

    def remove_reaction(self, *, message_id: str, emoji: str, channel_id: Optional[str], user_id: Optional[str]) -> bool:
        resp = self._request(
            "POST",
            "/messages/reactions/remove",
            json_body={"message_id": message_id, "emoji": emoji, "channel_id": channel_id, "user_id": user_id},
        )
        applied = resp.get("applied")
        return bool(applied) if applied is not None else True

    def list_reactions(self, *, message_id: str, channel_id: Optional[str]) -> Sequence[ReactionSummary]:
        query = urllib.parse.urlencode({"message_id": message_id, "channel_id": channel_id or ""})
        resp = self._request("GET", f"/messages/reactions/list?{query}")
        reactions = resp.get("reactions")
        if reactions is None:
            return []
        if not isinstance(reactions, list):
            raise MessageReactionsError.external_failure(
                "HTTP backend returned unexpected reactions payload",
                details={"backend": self.name, "value_type": type(reactions).__name__},
            )
        out: List[ReactionSummary] = []
        for item in reactions:
            if not isinstance(item, dict):
                continue
            emoji = item.get("emoji")
            count = item.get("count")
            if not isinstance(emoji, str) or not isinstance(count, int):
                continue
            user_ids = item.get("user_ids")
            ids_tuple = tuple(str(x) for x in user_ids) if isinstance(user_ids, list) else tuple()
            out.append(ReactionSummary(emoji=emoji, count=count, user_ids=ids_tuple))
        out.sort(key=lambda r: r.emoji)
        return out


def _coerce_config(config: Any) -> MessageReactionsConfig:
    if isinstance(config, MessageReactionsConfig):
        return config

    if isinstance(config, Mapping):
        backend = config.get("backend") or config.get("message_reactions_backend")
        if backend is None:
            raise MessageReactionsError.invalid_input(
                "Config is missing required field 'backend'",
                details={"known_keys": sorted(list(config.keys()))},
            )
        timeout = config.get("timeout_seconds") or config.get("timeoutSeconds") or 10.0
        return MessageReactionsConfig(
            backend=str(backend).strip(),
            api_base_url=config.get("api_base_url") or config.get("apiBaseUrl"),
            api_token=config.get("api_token") or config.get("apiToken"),
            timeout_seconds=float(timeout),
        )

    backend = getattr(config, "backend", None)
    if backend is None:
        raise MessageReactionsError.invalid_input(
            "Invalid message reactions config object",
            details={"value_type": type(config).__name__},
        )
    return MessageReactionsConfig(
        backend=str(backend).strip(),
        api_base_url=getattr(config, "api_base_url", None),
        api_token=getattr(config, "api_token", None),
        timeout_seconds=float(getattr(config, "timeout_seconds", 10.0)),
    )


def _env_fallback(cfg: MessageReactionsConfig) -> MessageReactionsConfig:
    """Merge env vars into a config *only* where fields are missing."""
    api_base_url = cfg.api_base_url or os.environ.get("THOMAS_API_BASE_URL")
    api_token = cfg.api_token or os.environ.get("THOMAS_API_TOKEN")
    timeout = cfg.timeout_seconds
    if (not cfg.timeout_seconds) or cfg.timeout_seconds == 10.0:
        env_timeout = os.environ.get("THOMAS_API_TIMEOUT_SECONDS")
        if env_timeout:
            try:
                timeout = float(env_timeout)
            except ValueError:
                raise MessageReactionsError.invalid_input(
                    "THOMAS_API_TIMEOUT_SECONDS must be a number",
                    details={"value": env_timeout},
                )
    return MessageReactionsConfig(
        backend=cfg.backend,
        api_base_url=api_base_url,
        api_token=api_token,
        timeout_seconds=timeout,
    )


def build_backend(config: Optional[Any] = None) -> ReactionBackend:
    """Create a backend from explicit config or environment."""
    if config is None:
        backend = os.environ.get("THOMAS_MESSAGE_REACTIONS_BACKEND")
        if not backend:
            raise MessageReactionsError.missing_config(
                "Message reactions backend is not configured",
                details={"expected_env": ["THOMAS_MESSAGE_REACTIONS_BACKEND"]},
            )
        cfg = MessageReactionsConfig(
            backend=backend,
            api_base_url=os.environ.get("THOMAS_API_BASE_URL"),
            api_token=os.environ.get("THOMAS_API_TOKEN"),
            timeout_seconds=float(os.environ.get("THOMAS_API_TIMEOUT_SECONDS") or 10.0),
        )
    else:
        cfg = _env_fallback(_coerce_config(config))

    backend_name = cfg.backend.strip().lower()
    if backend_name == "memory":
        return InMemoryReactionBackend()
    if backend_name == "http":
        base_url = (cfg.api_base_url or "").strip()
        if not base_url:
            raise MessageReactionsError.missing_config(
                "HTTP backend requires an API base URL",
                details={"expected_env": ["THOMAS_API_BASE_URL"], "expected_config_fields": ["api_base_url"]},
            )
        return HttpReactionBackend(base_url=base_url, token=cfg.api_token, timeout_seconds=cfg.timeout_seconds)

    raise MessageReactionsError.invalid_input(
        "Unknown message reactions backend",
        details={"backend": cfg.backend, "supported": ["memory", "http"]},
    )


def add_reaction(
    request: MessageReactionAddInput,
    *,
    backend: Optional[ReactionBackend] = None,
    config: Optional[MessageReactionsConfig] = None,
) -> ReactionMutationResult:
    be = backend or build_backend(config)
    try:
        applied = be.add_reaction(
            message_id=request.message_id,
            emoji=request.emoji,
            channel_id=request.channel_id,
            user_id=request.user_id,
        )
    except MessageReactionsError:
        raise
    except Exception as e:
        raise MessageReactionsError.external_failure(
            "Backend failed while adding reaction",
            details={"backend": getattr(be, "name", type(be).__name__), "error": str(e)},
        ) from e
    return ReactionMutationResult(
        ok=True,
        action="add",
        message_id=request.message_id,
        channel_id=request.channel_id,
        emoji=request.emoji,
        applied=bool(applied),
    )


def remove_reaction(
    request: MessageReactionRemoveInput,
    *,
    backend: Optional[ReactionBackend] = None,
    config: Optional[MessageReactionsConfig] = None,
) -> ReactionMutationResult:
    be = backend or build_backend(config)
    try:
        applied = be.remove_reaction(
            message_id=request.message_id,
            emoji=request.emoji,
            channel_id=request.channel_id,
            user_id=request.user_id,
        )
    except MessageReactionsError:
        raise
    except Exception as e:
        raise MessageReactionsError.external_failure(
            "Backend failed while removing reaction",
            details={"backend": getattr(be, "name", type(be).__name__), "error": str(e)},
        ) from e
    return ReactionMutationResult(
        ok=True,
        action="remove",
        message_id=request.message_id,
        channel_id=request.channel_id,
        emoji=request.emoji,
        applied=bool(applied),
    )


def list_reactions(
    request: MessageReactionListInput,
    *,
    backend: Optional[ReactionBackend] = None,
    config: Optional[MessageReactionsConfig] = None,
) -> ReactionListResult:
    be = backend or build_backend(config)
    try:
        reactions = be.list_reactions(message_id=request.message_id, channel_id=request.channel_id)
    except MessageReactionsError:
        raise
    except Exception as e:
        raise MessageReactionsError.external_failure(
            "Backend failed while listing reactions",
            details={"backend": getattr(be, "name", type(be).__name__), "error": str(e)},
        ) from e
    reactions_sorted = tuple(sorted(reactions, key=lambda r: r.emoji))
    return ReactionListResult(
        ok=True,
        action="list",
        message_id=request.message_id,
        channel_id=request.channel_id,
        reactions=reactions_sorted,
    )


def run(
    payload: Mapping[str, Any],
    *,
    backend: Optional[ReactionBackend] = None,
    config: Optional[MessageReactionsConfig] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Generic dispatcher for add/remove/list.

    Payload fields:
      - operation/action/op: "add" | "remove" | "list" (plus small alias set)
      - message_id
      - emoji (for add/remove)
      - channel_id (optional)
      - user_id (optional)
    """
    op_raw = payload.get("operation") or payload.get("action") or payload.get("op") or payload.get("verb") or payload.get("type")
    if not isinstance(op_raw, str) or not op_raw.strip():
        raise MessageReactionsError.invalid_input(
            "operation is required",
            details={"expected": ["add", "remove", "list"], "received": op_raw},
        )

    op = op_raw.strip().lower()
    add_ops = {"add", "reaction_add", "reaction_added", "added"}
    remove_ops = {"remove", "reaction_remove", "reaction_removed", "removed"}
    list_ops = {"list", "get", "reactions_list", "reactions"}

    if op in add_ops:
        req = MessageReactionAddInput.from_mapping(payload)
        return add_reaction(req, backend=backend, config=config).to_dict()
    if op in remove_ops:
        req = MessageReactionRemoveInput.from_mapping(payload)
        return remove_reaction(req, backend=backend, config=config).to_dict()
    if op in list_ops:
        req = MessageReactionListInput.from_mapping(payload)
        return list_reactions(req, backend=backend, config=config).to_dict()

    raise MessageReactionsError.invalid_input(
        "Unknown operation",
        details={"operation": op_raw, "supported": ["add", "remove", "list"]},
    )


def reset_memory_backend() -> None:
    """Clear the global in-memory store (primarily for tests)."""
    InMemoryReactionBackend.reset_global_store()


# Common alternate entrypoint names.
execute = run
handle = run
