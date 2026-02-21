from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence, runtime_checkable


class ChannelListEnrichedOutputError(Exception):
    """Deterministic error for enriched channel listing.

    The `code` field is stable and intended for automation.
    """

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = dict(details) if details else None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = _json_safe(self.details)
        return payload


@dataclass(frozen=True)
class ChannelListEnrichedRequest:
    """Input contract for enriched channel listing."""

    integration: Optional[str] = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class ChannelEnriched:
    """A single channel with enriched, JSON-safe metadata."""

    id: str
    name: str
    platform: str
    kind: Optional[str] = None
    username: Optional[str] = None
    member_count: Optional[int] = None
    is_private: Optional[bool] = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelListEnrichedResponse:
    """Output contract for enriched channel listing."""

    channels: tuple[ChannelEnriched, ...]
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "channels": [dataclasses.asdict(c) for c in self.channels],
        }


@runtime_checkable
class SupportsChannelListing(Protocol):
    def list_channels(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        ...


def channel_list_enriched_output(
    request: ChannelListEnrichedRequest,
    *,
    integration_client: Any = None,
    ctx: Any = None,
) -> ChannelListEnrichedResponse:
    """List channels and enrich the output with common metadata fields.

    This implementation is tolerant of different integration client shapes.
    It uses best-effort runtime introspection to locate a suitable method.

    Args:
        request: Input contract.
        integration_client: Optional explicit integration client.
        ctx: Optional CLI context object; used to resolve integration clients.

    Returns:
        ChannelListEnrichedResponse

    Raises:
        ChannelListEnrichedOutputError: deterministic, machine-friendly failures.
    """

    _validate_request(request)

    integration_name = (request.integration or _infer_integration_name(ctx) or "telegram").strip().lower()
    if not integration_name:
        raise ChannelListEnrichedOutputError("invalid_input", "integration name resolved to an empty string")

    client = integration_client if integration_client is not None else _resolve_integration_client(ctx, integration_name)
    if client is None:
        raise ChannelListEnrichedOutputError(
            "missing_config",
            f"No integration client available for '{integration_name}'.",
        )

    try:
        raw_channels = _call_list_channels(client, limit=request.limit, offset=request.offset)
    except ChannelListEnrichedOutputError:
        raise
    except Exception as exc:
        raise ChannelListEnrichedOutputError(
            "external_failure",
            f"Failed to list channels for '{integration_name}'.",
            details={"exc_type": type(exc).__name__, "exc_message": str(exc)},
        ) from exc

    enriched: list[ChannelEnriched] = []
    for i, item in enumerate(raw_channels):
        ch = _coerce_channel(item, platform=integration_name)
        # Provide deterministic fallbacks so automation never sees empty identifiers.
        if not ch.id.strip():
            ch = dataclasses.replace(ch, id=f"unknown:{i}")
        if not ch.name.strip():
            ch = dataclasses.replace(ch, name=ch.id)
        enriched.append(ch)

    # Deterministic ordering for stable output and automation diffs.
    enriched_sorted = tuple(sorted(enriched, key=lambda c: ((c.name or "").casefold(), c.id)))
    return ChannelListEnrichedResponse(channels=enriched_sorted, count=len(enriched_sorted))


# Compatibility alias: some dispatchers use a generic `run()` entrypoint.
run = channel_list_enriched_output


def response_to_json(response: ChannelListEnrichedResponse) -> str:
    """Convert response into deterministic JSON for automation."""

    return json.dumps(response.to_dict(), ensure_ascii=False, sort_keys=True)


def error_to_json(error: ChannelListEnrichedOutputError) -> str:
    return json.dumps({"error": error.to_dict()}, ensure_ascii=False, sort_keys=True)


def _validate_request(request: ChannelListEnrichedRequest) -> None:
    if request.limit < 0:
        raise ChannelListEnrichedOutputError("invalid_input", "limit must be >= 0", details={"limit": request.limit})
    if request.offset < 0:
        raise ChannelListEnrichedOutputError("invalid_input", "offset must be >= 0", details={"offset": request.offset})


def _infer_integration_name(ctx: Any) -> Optional[str]:
    if ctx is None:
        return None
    for key in ("integration", "platform", "channel_platform"):
        val = _maybe_get(ctx, key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _resolve_integration_client(ctx: Any, integration_name: str) -> Any:
    """Attempt to locate an integration client from an arbitrary context object."""

    if ctx is None:
        return None

    obj = getattr(ctx, "obj", None)
    for candidate in (ctx, obj):
        if candidate is None:
            continue

        if isinstance(candidate, Mapping):
            integrations = candidate.get("integrations")
            if isinstance(integrations, Mapping) and integration_name in integrations:
                return integrations[integration_name]
            clients = candidate.get("clients")
            if isinstance(clients, Mapping) and integration_name in clients:
                return clients[integration_name]
            if integration_name in candidate:
                return candidate[integration_name]

        for attr in ("integrations", "integration_clients", "clients"):
            integrations_obj = getattr(candidate, attr, None)
            if isinstance(integrations_obj, Mapping) and integration_name in integrations_obj:
                return integrations_obj[integration_name]

        direct = getattr(candidate, integration_name, None)
        if direct is not None:
            return direct

    return None


def _call_list_channels(client: Any, *, limit: int, offset: int) -> Sequence[Any]:
    """Call a "list channels" method on an integration client."""

    method_names = (
        "list_channels_enriched",
        "list_enriched_channels",
        "list_channels",
        "channels",
        "get_channels",
        "list_dialogs",
        "dialogs",
    )

    # Normalize no-limit behavior; callers can pass 0 from CLI to mean "all".
    norm_limit: Optional[int] = None if limit == 0 else limit

    for name in method_names:
        method = getattr(client, name, None)
        if not callable(method):
            continue

        try:
            result = _invoke_compat(method, limit=norm_limit, offset=offset)
        except TypeError:
            # Fallback for clients that use positional args only.
            try:
                result = method(norm_limit, offset)
            except TypeError:
                try:
                    result = method(norm_limit)
                except TypeError:
                    result = method()

        result = _maybe_await(result)
        return _normalize_sequence(result)

    raise ChannelListEnrichedOutputError(
        "missing_capability",
        "Integration client does not expose a channel listing method.",
        details={"client_type": type(client).__name__},
    )


def _invoke_compat(fn: Any, **kwargs: Any) -> Any:
    """Invoke `fn` passing only supported kwargs."""

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**{k: v for k, v in kwargs.items() if v is not None})

    accepted: dict[str, Any] = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        if k in sig.parameters:
            accepted[k] = v
    if accepted:
        return fn(**accepted)
    return fn()


def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(result)
        raise ChannelListEnrichedOutputError(
            "external_failure",
            "Channel listing returned an awaitable while an event loop is already running.",
            details={"awaitable_type": type(result).__name__},
        )
    return result


def _normalize_sequence(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return value
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return tuple(value)
    if isinstance(value, Mapping):
        return tuple(value.values())
    return (value,)


def _coerce_channel(item: Any, *, platform: str) -> ChannelEnriched:
    if isinstance(item, Mapping):
        return _coerce_from_mapping(item, platform=platform)

    channel_id = _stringify_first(_maybe_get(item, "id"), _maybe_get(item, "channel_id"), _maybe_get(item, "chat_id"))
    name = _stringify_first(_maybe_get(item, "name"), _maybe_get(item, "title"), _maybe_get(item, "display_name"))
    kind = _stringify_optional(_maybe_get(item, "kind"), _maybe_get(item, "type"), _maybe_get(item, "chat_type"))
    username = _stringify_optional(_maybe_get(item, "username"), _maybe_get(item, "handle"))
    member_count = _int_optional(
        _maybe_get(item, "member_count"),
        _maybe_get(item, "members_count"),
        _maybe_get(item, "participants_count"),
    )
    is_private = _bool_optional(_maybe_get(item, "is_private"), _maybe_get(item, "private"))

    meta: dict[str, Any] = {}
    for k in ("unread_count", "pinned", "archived"):
        v = _maybe_get(item, k)
        if v is not None:
            meta[k] = _json_safe(v)

    return ChannelEnriched(
        id=channel_id or "",
        name=name or "",
        platform=platform,
        kind=kind,
        username=username,
        member_count=member_count,
        is_private=is_private,
        meta=meta,
    )


def _coerce_from_mapping(data: Mapping[str, Any], *, platform: str) -> ChannelEnriched:
    channel_id = _stringify_first(data.get("id"), data.get("channel_id"), data.get("chat_id"), data.get("peer_id"))
    name = _stringify_first(data.get("name"), data.get("title"), data.get("display_name"))
    kind = _stringify_optional(data.get("kind"), data.get("type"), data.get("chat_type"))
    username = _stringify_optional(data.get("username"), data.get("handle"))
    member_count = _int_optional(data.get("member_count"), data.get("members_count"), data.get("participants_count"))
    is_private = _bool_optional(data.get("is_private"), data.get("private"))

    meta: dict[str, Any] = {}
    for k in ("unread_count", "pinned", "archived"):
        if k in data and data[k] is not None:
            meta[k] = _json_safe(data[k])

    known = {
        "id",
        "channel_id",
        "chat_id",
        "peer_id",
        "name",
        "title",
        "display_name",
        "kind",
        "type",
        "chat_type",
        "username",
        "handle",
        "member_count",
        "members_count",
        "participants_count",
        "is_private",
        "private",
        "unread_count",
        "pinned",
        "archived",
    }
    extra_keys = {k: v for k, v in data.items() if k not in known}
    if extra_keys:
        meta.setdefault("extra", _json_safe(extra_keys))

    return ChannelEnriched(
        id=channel_id or "",
        name=name or "",
        platform=platform,
        kind=kind,
        username=username,
        member_count=member_count,
        is_private=is_private,
        meta=meta,
    )


def _maybe_get(obj: Any, key: str) -> Any:
    try:
        if isinstance(obj, Mapping):
            return obj.get(key)
        return getattr(obj, key, None)
    except Exception:
        return None


def _stringify_first(*values: Any) -> Optional[str]:
    for v in values:
        if v is None:
            continue
        s = str(v)
        if s.strip():
            return s
    return None


def _stringify_optional(value: Any, *fallbacks: Any) -> Optional[str]:
    return _stringify_first(value, *fallbacks)


def _int_optional(value: Any, *fallbacks: Any) -> Optional[int]:
    for v in (value, *fallbacks):
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _bool_optional(value: Any, *fallbacks: Any) -> Optional[bool]:
    for v in (value, *fallbacks):
        if v is None:
            continue
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            s = v.strip().lower()
            if s in {"true", "yes", "1"}:
                return True
            if s in {"false", "no", "0"}:
                return False
        if isinstance(v, (int, float)):
            return bool(v)
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)
