"""
Channel resolution helpers.

This module implements Thomas-native channel resolution logic for the `channels resolve`
CLI operation.

The core idea:
- Accept a user-supplied channel reference (e.g. "@mychannel", "t.me/mychannel",
  "telegram:@mychannel", or an alias defined in configuration).
- Resolve it into a canonical, machine-readable channel identity that other parts of
  the system can use.

This file intentionally has *no* hard dependency on the CLI framework (Typer/Click/argparse).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

_SUPPORTED_INTEGRATIONS = {"telegram"}


class ChannelResolveError(Exception):
    """Deterministic error for channel resolution failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: int = 1,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class InvalidChannelReference(ChannelResolveError):
    def __init__(
        self, message: str = "Invalid channel reference.", *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__("INVALID_INPUT", message, exit_code=2, details=details)


class MissingChannelConfig(ChannelResolveError):
    def __init__(
        self,
        message: str = "Missing configuration for channel resolution.",
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("MISSING_CONFIG", message, exit_code=3, details=details)


class ExternalChannelResolutionFailed(ChannelResolveError):
    def __init__(
        self,
        integration: str,
        message: str = "External channel resolution failed.",
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        d = dict(details or {})
        d.setdefault("integration", integration)
        super().__init__("EXTERNAL_FAILURE", message, exit_code=4, details=d)


@dataclass(frozen=True)
class ChannelResolveRequest:
    """Input contract for channel resolution."""

    reference: str
    config: Mapping[str, Any] | None = None
    timeout_s: float = 10.0


@dataclass(frozen=True)
class ChannelResolveResult:
    """Output contract for channel resolution."""

    integration: str
    channel_id: str
    raw_reference: str
    normalized_reference: str
    resolved_via: str  # "input" | "config" | "external"
    title: str | None = None
    username: str | None = None
    kind: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "integration": self.integration,
            "channel_id": self.channel_id,
            "raw_reference": self.raw_reference,
            "normalized_reference": self.normalized_reference,
            "resolved_via": self.resolved_via,
            "title": self.title,
            "username": self.username,
            "kind": self.kind,
            "metadata": dict(self.metadata),
        }


class TelegramResolver(Protocol):
    """Protocol for the subset of behavior we need from a Telegram integration."""

    def get_chat(self, reference: str) -> Any:  # pragma: no cover - protocol definition
        ...


_TELEGRAM_LINK_RE = re.compile(r"^(?:https?://)?t\.me/(?P<name>[A-Za-z0-9_]{4,})/?$")


def resolve_channel(
    request: ChannelResolveRequest,
    *,
    telegram_resolver: Any | None = None,
) -> ChannelResolveResult:
    """
    Resolve a user-supplied reference to a canonical channel identity.

    Args:
        request: ChannelResolveRequest
        telegram_resolver: Optional Telegram resolver instance/function (dependency injection).

    Returns:
        ChannelResolveResult

    Raises:
        InvalidChannelReference
        MissingChannelConfig
        ExternalChannelResolutionFailed
    """
    raw = (request.reference or "").strip()
    if not raw:
        raise InvalidChannelReference(details={"field": "reference"})

    # 1) Expand aliases from config (if provided).
    expanded, via = _expand_alias(raw, request.config)
    ref = expanded

    # 2) Parse integration + identifier.
    integration, identifier = _parse_integration_and_identifier(ref)
    if not integration:
        # Try to infer integration from the identifier itself.
        integration = _infer_integration_from_identifier(identifier)

    if not integration:
        raise InvalidChannelReference(
            "Unable to determine integration for channel reference.",
            details={"reference": raw},
        )

    if integration not in _SUPPORTED_INTEGRATIONS:
        raise InvalidChannelReference(
            "Unsupported integration for channel reference.",
            details={"integration": integration, "reference": raw},
        )

    if integration == "telegram":
        normalized_identifier, username_hint = _normalize_telegram_identifier(identifier)
        chat = _resolve_telegram(normalized_identifier, telegram_resolver, timeout_s=request.timeout_s)

        chat_id = _get_any(chat, ("id", "chat_id", "chatId"))
        if chat_id is None:
            raise ExternalChannelResolutionFailed(
                "telegram",
                "Telegram resolver returned no chat id.",
                details={"reference": raw},
            )

        title = _get_any(chat, ("title", "name"))
        username = _get_any(chat, ("username", "user_name", "handle")) or username_hint
        kind = _get_any(chat, ("type", "kind"))

        meta = _extract_json_safe_metadata(chat)
        return ChannelResolveResult(
            integration="telegram",
            channel_id=str(chat_id),
            raw_reference=raw,
            normalized_reference=_format_normalized_reference("telegram", normalized_identifier),
            resolved_via=via if via != "input" else "external",
            title=str(title) if title is not None else None,
            username=str(username) if username is not None else None,
            kind=str(kind) if kind is not None else None,
            metadata=meta,
        )

    # Defensive: should be unreachable due to _SUPPORTED_INTEGRATIONS
    raise InvalidChannelReference("Unsupported integration.", details={"integration": integration})


def result_json_schema() -> dict[str, Any]:
    """
    A minimal JSON schema for machine-readable output in `--json` mode.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ChannelResolveResult",
        "type": "object",
        "required": [
            "integration",
            "channel_id",
            "raw_reference",
            "normalized_reference",
            "resolved_via",
            "title",
            "username",
            "kind",
            "metadata",
        ],
        "properties": {
            "integration": {"type": "string", "enum": sorted(_SUPPORTED_INTEGRATIONS)},
            "channel_id": {"type": "string"},
            "raw_reference": {"type": "string"},
            "normalized_reference": {"type": "string"},
            "resolved_via": {"type": "string"},
            "title": {"type": ["string", "null"]},
            "username": {"type": ["string", "null"]},
            "kind": {"type": ["string", "null"]},
            "metadata": {"type": "object"},
        },
        "additionalProperties": False,
    }


def _expand_alias(reference: str, config: Mapping[str, Any] | None) -> tuple[str, str]:
    """
    Expand a reference via configuration if it matches a named alias.

    Returns: (expanded_reference, via) where via is "config" or "input".
    """
    if not config:
        return reference, "input"

    # Attempt a few likely config layouts without taking a hard dependency
    # on any specific config shape.
    channels = None
    if isinstance(config, Mapping):
        channels = config.get("channels")
        if channels is None:
            messaging = config.get("messaging")
            if isinstance(messaging, Mapping):
                channels = messaging.get("channels")
        if channels is None:
            channel_aliases = config.get("channel_aliases")
            if channel_aliases is not None:
                channels = channel_aliases

    if not isinstance(channels, Mapping):
        return reference, "input"

    if reference not in channels:
        return reference, "input"

    spec = channels[reference]

    # Accept simple string values.
    if isinstance(spec, str):
        return spec.strip(), "config"

    if isinstance(spec, Mapping):
        # Most explicit: {"reference": "..."} or {"target": "..."}
        for key in ("reference", "target", "ref"):
            v = spec.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip(), "config"

        # Common shorthand: {"telegram": "@name"} or {"integration": "telegram", "id": "@name"}
        if isinstance(spec.get("telegram"), str):
            return f"telegram:{spec['telegram']}".strip(), "config"
        if isinstance(spec.get("integration"), str) and ("id" in spec or "channel" in spec):
            ident = spec.get("id") or spec.get("channel")
            if isinstance(ident, (str, int)):
                return f"{spec['integration']}:{ident}".strip(), "config"

    # Unknown shape => keep original input.
    return reference, "input"


def _parse_integration_and_identifier(reference: str) -> tuple[str | None, str]:
    """
    Parse "integration:identifier" forms.

    Returns: (integration | None, identifier)
    """
    ref = reference.strip()

    # Handle scheme-like variants.
    if "://" in ref:
        scheme, rest = ref.split("://", 1)
        if scheme and rest:
            return scheme.lower(), rest.strip()

    if ":" in ref:
        prefix, rest = ref.split(":", 1)
        prefix_l = prefix.strip().lower()
        rest_s = rest.strip()

        # Normalize a few common shorthand aliases.
        if prefix_l in ("tg", "telegram"):
            return "telegram", rest_s

        return prefix_l or None, rest_s

    return None, ref


def _infer_integration_from_identifier(identifier: str) -> str | None:
    ident = identifier.strip()

    if ident.startswith("@"):
        return "telegram"

    if _TELEGRAM_LINK_RE.match(ident):
        return "telegram"

    if re.fullmatch(r"-?\d{5,}", ident):
        # Telegram chat IDs are typically large ints (and can be negative for groups)
        return "telegram"

    return None


def _normalize_telegram_identifier(identifier: str) -> tuple[str, str | None]:
    """
    Normalize the identifier portion for Telegram.

    Returns: (normalized_identifier, username_hint)
    """
    ident = identifier.strip()
    if not ident:
        raise InvalidChannelReference("Missing Telegram channel identifier.", details={"integration": "telegram"})

    m = _TELEGRAM_LINK_RE.match(ident)
    if m:
        name = m.group("name")
        return f"@{name}", f"@{name}"

    # Ensure usernames are "@name"
    if re.fullmatch(r"[A-Za-z0-9_]{4,}", ident):
        return f"@{ident}", f"@{ident}"

    if ident.startswith("@"):
        return ident, ident

    # Chat id numeric
    if re.fullmatch(r"-?\d{5,}", ident):
        return ident, None

    # As a last resort, pass through (Telegram API accepts some forms like "@name")
    return ident, ident if ident.startswith("@") else None


def _resolve_telegram(identifier: str, resolver: Any | None, *, timeout_s: float) -> Any:
    if resolver is None:
        raise MissingChannelConfig(
            "Telegram integration is not configured.",
            details={"integration": "telegram"},
        )

    # Support a variety of resolver shapes without binding to one.
    # - object with .get_chat(reference)
    # - object with .resolve(reference, timeout_s=...)
    # - callable(reference)
    try:
        if hasattr(resolver, "get_chat") and callable(resolver.get_chat):
            return resolver.get_chat(identifier)

        if hasattr(resolver, "resolve") and callable(resolver.resolve):
            try:
                return resolver.resolve(identifier, timeout_s=timeout_s)
            except TypeError:
                return resolver.resolve(identifier)

        if callable(resolver):
            try:
                return resolver(identifier, timeout_s=timeout_s)
            except TypeError:
                return resolver(identifier)
    except ChannelResolveError:
        raise
    except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as exc:
        raise ExternalChannelResolutionFailed(
            "telegram",
            details={"reason": _safe_reason(exc), "reference": identifier},
        ) from exc

    raise MissingChannelConfig(
        "Telegram integration is not configured.",
        details={"integration": "telegram"},
    )


def _get_any(obj: Any, keys: tuple[str, ...]) -> Any:
    if obj is None:
        return None

    # dict-like
    if isinstance(obj, Mapping):
        for k in keys:
            if k in obj:
                return obj.get(k)
        return None

    # attribute-like
    for k in keys:
        if hasattr(obj, k):
            return getattr(obj, k)
    return None


def _extract_json_safe_metadata(chat: Any) -> dict[str, Any]:
    """
    Extract a small JSON-serializable metadata dict from a resolver result.

    We intentionally avoid including the whole raw object since it may not be JSON-serializable.
    """
    meta: dict[str, Any] = {}
    for key in ("id", "chat_id", "title", "name", "username", "type"):
        v = _get_any(chat, (key,))
        if v is None:
            continue
        # Make it JSON-friendly.
        if isinstance(v, (str, int, float, bool)) or v is None:
            meta[key] = v
        else:
            meta[key] = str(v)

    # If the chat is a mapping, try to include any obvious primitive extras.
    if isinstance(chat, Mapping):
        for k, v in chat.items():
            if k in meta:
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                meta[k] = v

    # Ensure round-trippable JSON for deterministic CLI output.
    try:
        json.dumps(meta, sort_keys=True)
    except TypeError:
        # Last-ditch: stringify everything.
        meta = {str(k): str(v) for k, v in meta.items()}

    return meta


def _format_normalized_reference(integration: str, identifier: str) -> str:
    return f"{integration}:{identifier}"


def _safe_reason(exc: Exception) -> str:
    # Deterministic-ish: exception type + message (truncated).
    msg = str(exc).strip()
    if len(msg) > 200:
        msg = msg[:200] + "…"
    return f"{exc.__class__.__name__}: {msg}" if msg else exc.__class__.__name__
