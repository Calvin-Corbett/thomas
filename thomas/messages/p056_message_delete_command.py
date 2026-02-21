from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, TypedDict, cast


class MessageDeleteError(Exception):
    """Deterministic error raised by the message delete command.

    This error is intentionally simple and stable for automation:
    - `code` is a machine-readable identifier
    - `message` is a human-readable summary
    - `details` is an optional JSON-serializable mapping
    """

    __slots__ = ("code", "message", "details")

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class _MessageDeleter(Protocol):
    """Backend interface expected by this command."""

    def delete_message(
        self,
        *,
        channel: Optional[str],
        account: Optional[str],
        target: str,
        message_id: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class MessageDeleteRequest:
    """Input contract for message deletion."""

    target: str
    message_id: str
    channel: Optional[str] = None
    account: Optional[str] = None
    dry_run: bool = False

    def validate(self) -> None:
        if not isinstance(self.target, str) or not self.target.strip():
            raise MessageDeleteError("invalid_input", "target is required", details={"field": "target"})
        if not isinstance(self.message_id, str) or not self.message_id.strip():
            raise MessageDeleteError(
                "invalid_input", "message_id is required", details={"field": "message_id"}
            )
        if self.channel is not None and not isinstance(self.channel, str):
            raise MessageDeleteError("invalid_input", "channel must be a string", details={"field": "channel"})
        if self.account is not None and not isinstance(self.account, str):
            raise MessageDeleteError("invalid_input", "account must be a string", details={"field": "account"})


@dataclass(frozen=True, slots=True)
class MessageDeleteResponse:
    """Output contract for message deletion."""

    target: str
    message_id: str
    deleted: bool
    channel: Optional[str] = None
    account: Optional[str] = None
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        # Stable JSON-facing contract.
        return {
            "channel": self.channel,
            "account": self.account,
            "to": self.target,
            "messageId": self.message_id,
            "deleted": bool(self.deleted),
            "dryRun": bool(self.dry_run),
        }


class MessageDeleteRequestJson(TypedDict, total=False):
    # Accept both snake_case and camelCase inputs.
    channel: Optional[str]
    account: Optional[str]
    target: str
    to: str
    messageId: str
    message_id: str
    dryRun: bool
    dry_run: bool


class MessageDeleteResponseJson(TypedDict):
    channel: Optional[str]
    account: Optional[str]
    to: str
    messageId: str
    deleted: bool
    dryRun: bool


MESSAGE_DELETE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "channel": {"type": ["string", "null"]},
        "account": {"type": ["string", "null"]},
        "target": {"type": "string", "minLength": 1},
        "to": {"type": "string", "minLength": 1},
        "messageId": {"type": "string", "minLength": 1},
        "dryRun": {"type": "boolean", "default": False},
    },
    "required": ["messageId"],
    "oneOf": [{"required": ["target"]}, {"required": ["to"]}],
}

MESSAGE_DELETE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "channel": {"type": ["string", "null"]},
        "account": {"type": ["string", "null"]},
        "to": {"type": "string", "minLength": 1},
        "messageId": {"type": "string", "minLength": 1},
        "deleted": {"type": "boolean"},
        "dryRun": {"type": "boolean"},
    },
    "required": ["to", "messageId", "deleted", "dryRun"],
}

# Common schema aliases expected by webhook/CLI glue.
REQUEST_SCHEMA = MESSAGE_DELETE_REQUEST_SCHEMA
RESPONSE_SCHEMA = MESSAGE_DELETE_RESPONSE_SCHEMA


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "y", "on"}:
            return True
        if v in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def parse_request(payload: Mapping[str, Any]) -> MessageDeleteRequest:
    """Parse a JSON-like payload into a validated request object."""

    data = cast(MessageDeleteRequestJson, dict(payload))

    target = data.get("target") or data.get("to")
    message_id = data.get("messageId") or data.get("message_id")
    dry_run = data.get("dryRun") if "dryRun" in data else data.get("dry_run")

    return MessageDeleteRequest(
        channel=cast(Optional[str], data.get("channel")),
        account=cast(Optional[str], data.get("account")),
        target=_coerce_str(target),
        message_id=_coerce_str(message_id),
        dry_run=_coerce_bool(dry_run),
    )


def build_default_deleter() -> _MessageDeleter:
    """Create the default backend deleter.

    The Thomas codebase can run in multiple modes (CLI-only, server-backed, etc).
    This function uses conservative discovery:
    - attempt to import likely backend modules
    - attempt to locate a factory or singleton that exposes `delete_message`

    If no backend is configured, a deterministic `config_missing` error is raised.
    """

    import importlib

    module_candidates: list[str] = [
        "thomas.messages.backend",
        "thomas.messages.service",
        "thomas.messages.client",
        "thomas.messages.providers",
        "thomas.messages",
    ]

    attr_candidates: list[str] = [
        "get_message_deleter",
        "get_messages_deleter",
        "get_message_backend",
        "get_messages_backend",
        "get_message_client",
        "get_messages_client",
        "message_deleter",
        "messages_deleter",
        "backend",
        "client",
        "service",
    ]

    for mod_name in module_candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue

        for attr in attr_candidates:
            obj = getattr(mod, attr, None)
            if obj is None:
                continue

            # Factory function
            if callable(obj):
                try:
                    candidate = obj()
                except Exception:
                    continue
            else:
                candidate = obj

            if candidate is not None and hasattr(candidate, "delete_message"):
                return cast(_MessageDeleter, candidate)

    raise MessageDeleteError(
        "config_missing",
        "no messaging backend is configured for message deletion",
        details={
            "hint": "Configure a messaging provider/channel backend or run the Thomas service that owns message deletion.",
        },
    )


def _adapt_external_error(exc: Exception) -> MessageDeleteError:
    """Convert arbitrary provider exceptions into deterministic errors."""

    # Preserve an existing structured error if it looks compatible.
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.strip():
        details = getattr(exc, "details", None)
        if isinstance(details, Mapping):
            return MessageDeleteError(code, str(exc), details=cast(Mapping[str, Any], details))
        return MessageDeleteError(code, str(exc))

    return MessageDeleteError(
        "external_failure",
        "message deletion failed",
        details={"exception": exc.__class__.__name__},
    )


def delete_message(
    request: MessageDeleteRequest,
    *,
    deleter: Optional[_MessageDeleter] = None,
) -> MessageDeleteResponse:
    """Delete a message via the configured messaging backend."""

    request.validate()

    if request.dry_run:
        # No backend I/O in dry-run mode.
        return MessageDeleteResponse(
            channel=request.channel,
            account=request.account,
            target=request.target,
            message_id=request.message_id,
            deleted=False,
            dry_run=True,
        )

    deleter = deleter or build_default_deleter()

    try:
        deleted = bool(
            deleter.delete_message(
                channel=request.channel,
                account=request.account,
                target=request.target,
                message_id=request.message_id,
            )
        )
    except MessageDeleteError:
        raise
    except Exception as exc:  # pragma: no cover
        raise _adapt_external_error(exc) from exc

    return MessageDeleteResponse(
        channel=request.channel,
        account=request.account,
        target=request.target,
        message_id=request.message_id,
        deleted=deleted,
        dry_run=False,
    )


def handle_webhook(payload: Mapping[str, Any], **context: Any) -> MessageDeleteResponseJson:
    """Server/webhook entrypoint.

    The surrounding router may pass additional context. If it provides an object that
    has a `delete_message` method, it will be used as the backend.
    """

    request = parse_request(payload)

    possible = (
        context.get("deleter"),
        context.get("message_deleter"),
        context.get("messages"),
        context.get("backend"),
    )
    deleter = next((d for d in possible if d is not None and hasattr(d, "delete_message")), None)

    response = delete_message(request, deleter=cast(Optional[_MessageDeleter], deleter))
    return cast(MessageDeleteResponseJson, response.to_dict())


# Convenience aliases for dispatchers with different expectations.
handle = handle_webhook
execute = handle_webhook


__all__ = [
    "MessageDeleteError",
    "MessageDeleteRequest",
    "MessageDeleteResponse",
    "MessageDeleteRequestJson",
    "MessageDeleteResponseJson",
    "MESSAGE_DELETE_REQUEST_SCHEMA",
    "MESSAGE_DELETE_RESPONSE_SCHEMA",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "parse_request",
    "delete_message",
    "handle_webhook",
    "handle",
    "execute",
]
