"""Thomas-native message unpin command.

This module intentionally avoids any OpenClaw naming. It provides a small,
deterministic contract for unpinning a message from a channel across supported
messaging backends.

The surrounding Thomas codebase typically provides a "messages client"/gateway
object via an execution context. For robustness (and to keep this command usable
in isolation), this implementation supports multiple client resolution paths and
multiple backend method shapes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MessageUnpinInput:
    """Input contract for unpinning a message.

    At least one of the following must be provided:
      - (channel_id AND message_id)
      - message_url (from which channel/message IDs can be parsed for common
        platforms like Slack and Discord)

    The command treats *message_id* as an opaque identifier. For Slack, this is
    expected to be the message timestamp ("ts"), e.g. "1712345678.000100".
    """

    channel_id: Optional[str] = None
    message_id: Optional[str] = None
    message_url: Optional[str] = None


@dataclass(frozen=True, slots=True)
class MessageUnpinOutput:
    """Output contract for unpinning a message."""

    unpinned: bool
    channel_id: str
    message_id: str


# ---------------------------------------------------------------------------
# Deterministic errors
# ---------------------------------------------------------------------------


class MessageUnpinError(RuntimeError):
    """Base error for this command.

    The Thomas codebase may provide its own rich error hierarchy. We keep this
    local base class small and deterministic, while still allowing upstream
    tooling to pattern-match on `.code`.
    """

    code: str = "message_unpin.error"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


class MessageUnpinInputError(MessageUnpinError):
    code = "message_unpin.invalid_input"


class MessageUnpinConfigError(MessageUnpinError):
    code = "message_unpin.missing_config"


class MessageUnpinExternalError(MessageUnpinError):
    code = "message_unpin.external_failure"


class MessageUnpinCommand:
    """Command-object wrapper.

    Some parts of the Thomas codebase (and parity tooling) prefer a simple
    object with a ``run``/``execute`` method. This wrapper keeps that ergonomic
    shape without constraining callers to a single interface.
    """

    def execute(
        self,
        request: MessageUnpinInput,
        *,
        ctx: Any | None = None,
        client: Any | None = None,
    ) -> MessageUnpinOutput:
        return execute(request, ctx=ctx, client=client)

    def run(
        self,
        request: MessageUnpinInput,
        *,
        ctx: Any | None = None,
        client: Any | None = None,
    ) -> MessageUnpinOutput:
        return execute(request, ctx=ctx, client=client)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute(
    request: MessageUnpinInput,
    *,
    ctx: Any | None = None,
    client: Any | None = None,
) -> MessageUnpinOutput:
    """Unpin a message.

    Args:
        request: MessageUnpinInput
        ctx: Optional Thomas execution context, if the codebase provides one.
        client: Optional explicit client/gateway override.

    Returns:
        MessageUnpinOutput

    Raises:
        MessageUnpinInputError: invalid or insufficient input
        MessageUnpinConfigError: cannot resolve a messaging client
        MessageUnpinExternalError: backend call failed
    """

    normalized = _normalize_input(request)
    resolved_client = client or _resolve_messages_client(ctx)
    _call_unpin_backend(
        resolved_client,
        channel_id=normalized.channel_id,  # type: ignore[arg-type]
        message_id=normalized.message_id,  # type: ignore[arg-type]
    )
    # normalized guarantees channel_id/message_id are not None.
    return MessageUnpinOutput(unpinned=True, channel_id=normalized.channel_id or "", message_id=normalized.message_id or "")


def to_machine_dict(result: MessageUnpinOutput) -> dict[str, Any]:
    """Convert output to a machine-readable dict."""

    return asdict(result)


def input_json_schema() -> dict[str, Any]:
    """A small JSON schema describing the input contract."""

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "channel_id": {"type": ["string", "null"]},
            "message_id": {"type": ["string", "null"]},
            "message_url": {"type": ["string", "null"]},
        },
        "anyOf": [
            {"required": ["channel_id", "message_id"]},
            {"required": ["message_url"]},
        ],
    }


def output_json_schema() -> dict[str, Any]:
    """A small JSON schema describing the output contract."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["unpinned", "channel_id", "message_id"],
        "properties": {
            "unpinned": {"type": "boolean"},
            "channel_id": {"type": "string"},
            "message_id": {"type": "string"},
        },
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_SLACK_ARCHIVE_RE = re.compile(r"/archives/(?P<channel>[A-Z0-9]+)/p(?P<ts>\d{10,})")
_DISCORD_CHANNELS_RE = re.compile(r"/channels/(?:@me|(?P<guild>\d+))/(?P<channel>\d+)/(?P<message>\d+)")


def _normalize_input(request: MessageUnpinInput) -> MessageUnpinInput:
    channel_id = (request.channel_id or "").strip() or None
    message_id = (request.message_id or "").strip() or None
    message_url = (request.message_url or "").strip() or None

    if message_url and (not channel_id or not message_id):
        parsed = _parse_message_url(message_url)
        channel_id = channel_id or parsed.get("channel_id")
        message_id = message_id or parsed.get("message_id")

    # Best-effort: accept Slack-style "p<digits>" timestamps passed directly,
    # but only when the channel_id looks Slack-ish (contains letters).
    if channel_id and message_id and message_id.isdigit() and "." not in message_id and len(message_id) > 6:
        if re.search(r"[A-Za-z]", channel_id):
            sec = message_id[:-6]
            micros = message_id[-6:]
            message_id = f"{sec}.{micros}"

    if not channel_id or not message_id:
        raise MessageUnpinInputError(
            "channel_id and message_id are required (or provide a message_url that can be parsed)"
        )

    return MessageUnpinInput(channel_id=channel_id, message_id=message_id, message_url=message_url)


def _parse_message_url(message_url: str) -> dict[str, str]:
    """Best-effort parsing for common message URL formats.

    Supported:
      - Slack permalinks: .../archives/<CHANNEL>/p<digits>
      - Discord message links: .../channels/<GUILD>/<CHANNEL>/<MESSAGE>
    """

    try:
        url = urlparse(message_url)
    except Exception as exc:  # pragma: no cover
        raise MessageUnpinInputError("message_url is not a valid URL") from exc

    # Slack
    m = _SLACK_ARCHIVE_RE.search(url.path)
    if m:
        channel = m.group("channel")
        ts_digits = m.group("ts")
        if len(ts_digits) > 6:
            sec = ts_digits[:-6]
            micros = ts_digits[-6:]
            ts = f"{sec}.{micros}"
        else:
            ts = ts_digits

        qs = parse_qs(url.query)
        for key in ("thread_ts", "message_ts"):
            if key in qs and qs[key]:
                ts = qs[key][0]
                break

        return {"channel_id": channel, "message_id": ts}

    # Discord
    m = _DISCORD_CHANNELS_RE.search(url.path)
    if m:
        return {"channel_id": m.group("channel"), "message_id": m.group("message")}

    raise MessageUnpinInputError("message_url format is not recognized")


def _resolve_messages_client(ctx: Any | None) -> Any:
    """Resolve a messaging client from context, config, or environment."""

    # 1) Dict context probing (common in lightweight runners).
    if isinstance(ctx, dict):
        for key in ("messages_client", "message_client", "messages", "messaging", "slack_client", "client"):
            candidate = ctx.get(key)
            if candidate is not None:
                return candidate

    # 2) Attribute probing.
    if ctx is not None:
        for attr in ("messages_client", "message_client", "messages", "messaging", "slack_client", "client"):
            candidate = getattr(ctx, attr, None)
            if candidate is not None:
                return candidate

    # 3) Known factory functions in the Thomas codebase (best-effort).
    for module_name, factory_names in (
        ("thomas.messages.client", ("get_client", "build_client", "default_client")),
        ("thomas.messages.gateway", ("get_gateway", "build_gateway", "default_gateway")),
        ("thomas.messages.service", ("get_service", "build_service", "default_service")),
    ):
        try:
            mod = __import__(module_name, fromlist=["*"])
        except Exception:
            continue
        for fn_name in factory_names:
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    return fn()  # type: ignore[misc]
                except TypeError:
                    continue
                except Exception:
                    continue

    # 4) Optional environment-based Slack client convenience.
    token = os.getenv("THOMAS_SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    if token:
        try:
            from slack_sdk import WebClient  # type: ignore

            return WebClient(token=token)
        except Exception:
            pass

    raise MessageUnpinConfigError(
        "No messaging client is configured for message unpin (provide a client or configure integration)"
    )


def _call_unpin_backend(client: Any, *, channel_id: str, message_id: str) -> None:
    """Call the unpin operation on a variety of client shapes."""

    # Common Thomas abstraction.
    for method_name, kwargs in (
        ("unpin_message", {"channel_id": channel_id, "message_id": message_id}),
        ("message_unpin", {"channel_id": channel_id, "message_id": message_id}),
        ("unpin", {"channel_id": channel_id, "message_id": message_id}),
    ):
        method = getattr(client, method_name, None)
        if callable(method):
            try:
                method(**kwargs)
                return
            except TypeError:
                # Try positional signature.
                try:
                    method(channel_id, message_id)  # type: ignore[misc]
                    return
                except TypeError:
                    pass
                except Exception as exc:
                    raise MessageUnpinExternalError(
                        f"Failed to unpin message via {method_name}: {exc.__class__.__name__}"
                    ) from exc
            except Exception as exc:
                raise MessageUnpinExternalError(
                    f"Failed to unpin message via {method_name}: {exc.__class__.__name__}"
                ) from exc

    # Slack WebClient shape.
    pins_remove = getattr(client, "pins_remove", None)
    if callable(pins_remove):
        try:
            pins_remove(channel=channel_id, timestamp=message_id)
            return
        except Exception as exc:
            raise MessageUnpinExternalError(
                f"Failed to unpin message via Slack pins.remove: {exc.__class__.__name__}"
            ) from exc

    # Slack legacy wrapper shape.
    pins = getattr(client, "pins", None)
    if pins is not None:
        remove = getattr(pins, "remove", None)
        if callable(remove):
            try:
                remove(channel=channel_id, timestamp=message_id)
                return
            except Exception as exc:
                raise MessageUnpinExternalError(
                    f"Failed to unpin message via Slack pins.remove: {exc.__class__.__name__}"
                ) from exc

    # Slack generic api_call.
    api_call = getattr(client, "api_call", None)
    if callable(api_call):
        try:
            api_call("pins.remove", json={"channel": channel_id, "timestamp": message_id})
            return
        except Exception as exc:
            raise MessageUnpinExternalError(
                f"Failed to unpin message via Slack pins.remove: {exc.__class__.__name__}"
            ) from exc

    raise MessageUnpinConfigError(
        "Messaging client does not support message unpin (missing unpin_message/unpin/pins_remove)"
    )


def format_success_json(result: MessageUnpinOutput) -> str:
    payload = {"ok": True, "result": to_machine_dict(result)}
    return json.dumps(payload, sort_keys=True)


def format_error_json(err: MessageUnpinError) -> str:
    payload = {"ok": False, "error": err.to_dict()}
    return json.dumps(payload, sort_keys=True)


# Common aliases used by different parts of the codebase.
run = execute
COMMAND = MessageUnpinCommand()


__all__ = [
    "MessageUnpinInput",
    "MessageUnpinOutput",
    "MessageUnpinError",
    "MessageUnpinInputError",
    "MessageUnpinConfigError",
    "MessageUnpinExternalError",
    "MessageUnpinCommand",
    "execute",
    "run",
    "COMMAND",
    "to_machine_dict",
    "input_json_schema",
    "output_json_schema",
    "format_success_json",
    "format_error_json",
]
