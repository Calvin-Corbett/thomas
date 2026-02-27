"""P055 - Message edit command (Thomas-native).

This module implements the *core* behavior for editing an existing message in an
external messaging channel.

Design goals:
- **Thomas-native** naming and contracts (no OpenClaw naming reused).
- **Clear contracts**: dataclasses for input/output.
- **Deterministic failures**: stable error codes and messages.
- **Adapter flexibility**: support a variety of editor/client method shapes.

The CLI wrapper (argparse) lives in:
    thomas/cli/commands/messages/p055_message_edit_command.py
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MessageEditCommandInput:
    """Inputs required to edit an existing message."""

    message_id: str
    new_text: str
    channel_id: str | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MessageEditCommandOutput:
    """Successful edit result."""

    message_id: str
    new_text: str
    channel_id: str | None = None
    edited: bool = True
    provider_result: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Ensure provider_result is JSON-friendly and deterministic.
        if data.get("provider_result") is not None:
            data["provider_result"] = _json_safe(data["provider_result"])
        return data


# ---------------------------------------------------------------------------
# JSON schema helpers (optional, but useful for HTTP routes and automation)
# ---------------------------------------------------------------------------


MESSAGE_EDIT_INPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "message_id": {"type": "string", "minLength": 1},
        "new_text": {"type": "string", "minLength": 1},
        "channel_id": {"type": ["string", "null"]},
        "metadata": {"type": ["object", "null"]},
    },
    "required": ["message_id", "new_text"],
}

MESSAGE_EDIT_OUTPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "message_id": {"type": "string"},
        "new_text": {"type": "string"},
        "channel_id": {"type": ["string", "null"]},
        "edited": {"type": "boolean"},
        "provider_result": {"type": ["object", "null"]},
    },
    "required": ["message_id", "new_text", "edited"],
}

MESSAGE_EDIT_ERROR_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "details": {"type": ["object", "null"]},
    },
    "required": ["code", "message"],
}


# ---------------------------------------------------------------------------
# Deterministic errors
# ---------------------------------------------------------------------------


class MessageEditCommandError(Exception):
    """Deterministic error for message edit failures.

    Attributes:
        code: Stable, machine-readable error code.
        message: Stable, human-readable message.
        details: Optional structured details (must be deterministic).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details) if details else None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = _json_safe(self.details)
        return payload


# Error codes (strings are easiest to keep stable across refactors)
ERR_INVALID_INPUT = "invalid_input"
ERR_MISSING_CONFIG = "missing_config"
ERR_EXTERNAL_FAILURE = "external_failure"


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------


def execute_message_edit(
    request: MessageEditCommandInput,
    *,
    editor: Any = None,
) -> MessageEditCommandOutput:
    """Edit a message using the provided editor.

    Args:
        request: Required inputs.
        editor: An object capable of performing the edit.

    Raises:
        MessageEditCommandError: invalid input, missing config, or external failures.

    Returns:
        MessageEditCommandOutput
    """

    _validate_request(request)

    if editor is None:
        raise MessageEditCommandError(
            ERR_MISSING_CONFIG,
            "No message editor is configured for this command.",
            details={"hint": "Pass an editor/client (or configure the CLI compat layer)."},
        )

    try:
        provider_result_raw = _call_editor(editor, request)
        provider_result = _coerce_provider_result(provider_result_raw)
    except MessageEditCommandError:
        raise
    except (ConnectionError, TimeoutError, RuntimeError) as exc:  # pragma: no cover (defensive)
        # Deterministic wrapper: do not leak network/library messages.
        raise MessageEditCommandError(
            ERR_EXTERNAL_FAILURE,
            "Message edit failed due to an external error.",
            details={"cause": type(exc).__name__},
        )

    return MessageEditCommandOutput(
        message_id=request.message_id,
        new_text=request.new_text,
        channel_id=request.channel_id,
        edited=True,
        provider_result=provider_result,
    )


# Aliases used by some runners
execute = execute_message_edit
run = execute_message_edit


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _validate_request(request: MessageEditCommandInput) -> None:
    message_id = (request.message_id or "").strip()
    if not message_id:
        raise MessageEditCommandError(ERR_INVALID_INPUT, "message_id is required.")

    if request.new_text is None:
        raise MessageEditCommandError(ERR_INVALID_INPUT, "new_text is required.")

    if not str(request.new_text).strip():
        raise MessageEditCommandError(ERR_INVALID_INPUT, "new_text must not be empty.")


def _call_editor(editor: Any, request: MessageEditCommandInput) -> Any:
    """Call a compatible edit method on `editor`.

    Supported method names (checked in order):
      - editor.edit_message
      - editor.message_edit
      - editor.messages_edit
      - editor.update_message
      - editor.messages.edit_message
      - editor.messages.edit

    Each candidate is attempted with multiple calling conventions:
      - keyword args with common parameter aliases
      - positional: (message_id, new_text[, channel_id])
      - single request object positional
    """

    candidates: list[tuple[Any, str]] = []

    for attr in ("edit_message", "message_edit", "messages_edit", "update_message"):
        fn = getattr(editor, attr, None)
        if callable(fn):
            candidates.append((fn, f"editor.{attr}"))

    messages_obj = getattr(editor, "messages", None)
    if messages_obj is not None:
        for attr in ("edit_message", "edit", "update", "message_edit"):
            fn = getattr(messages_obj, attr, None)
            if callable(fn):
                candidates.append((fn, f"editor.messages.{attr}"))

    if not candidates:
        raise MessageEditCommandError(
            ERR_MISSING_CONFIG,
            "Provided editor does not support message editing.",
            details={"expected": "edit_message/message_edit/update_message"},
        )

    # Common kw arg alias sets.
    id_keys = ["message_id", "id"]
    text_keys = ["text", "new_text", "content", "body"]
    channel_keys = ["channel_id", "channel", "room_id", "conversation_id"]

    last_type_error: TypeError | None = None

    for fn, _label in candidates:
        # Try keyword conventions.
        for id_key in id_keys:
            for text_key in text_keys:
                base_kwargs: dict[str, Any] = {
                    id_key: request.message_id,
                    text_key: request.new_text,
                    "metadata": request.metadata,
                }
                for channel_key in channel_keys:
                    kwargs = dict(base_kwargs)
                    kwargs[channel_key] = request.channel_id
                    # First, try with None values (helps when param is required).
                    try:
                        return _call_with_filtered_kwargs(fn, kwargs)
                    except TypeError as te:
                        last_type_error = te
                    # Second, try again dropping explicit None values (helps strict clients).
                    kwargs_no_none = {k: v for k, v in kwargs.items() if v is not None}
                    try:
                        return _call_with_filtered_kwargs(fn, kwargs_no_none)
                    except TypeError as te:
                        last_type_error = te
                        continue

        # Try positional conventions.
        pos_attempts = [
            (request.message_id, request.new_text, request.channel_id),
            (request.message_id, request.new_text),
            (request,),
        ]
        for args in pos_attempts:
            try:
                return fn(*args)
            except TypeError as te:
                last_type_error = te
                continue

    # Editor had methods, but none matched expected signatures.
    raise MessageEditCommandError(
        ERR_EXTERNAL_FAILURE,
        "Message edit failed due to an external error.",
        details={
            "cause": "TypeError",
            "note": "editor_signature_mismatch",
        },
    )


def _call_with_filtered_kwargs(fn: Any, kwargs: MutableMapping[str, Any]) -> Any:
    """Call fn(**kwargs), filtering kwargs when possible."""

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # Builtins/callables without signatures.
        return fn(**kwargs)

    params = sig.parameters

    # If fn accepts **kwargs, no need to filter.
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**kwargs)

    filtered = {k: v for k, v in kwargs.items() if k in params}
    return fn(**filtered)


def _coerce_provider_result(result: Any) -> Mapping[str, Any] | None:
    """Coerce provider result to a JSON-friendly mapping (or None).

    Determinism matters: when we can't serialize something, we do **not** include
    repr() (which can include memory addresses). We only include the type name.
    """

    if result is None:
        return None

    if isinstance(result, Mapping):
        # Shallow copy to avoid retaining mutable references.
        return dict(result)

    if dataclasses.is_dataclass(result):
        return asdict(result)

    # Common conventions (pydantic, custom)
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        try:
            v = to_dict()
            if isinstance(v, Mapping):
                return dict(v)
        except (ImportError, AttributeError, RuntimeError):
            return {"type": type(result).__name__}

    dict_method = getattr(result, "dict", None)
    if callable(dict_method):
        try:
            v = dict_method()
            if isinstance(v, Mapping):
                return dict(v)
        except (ImportError, AttributeError, RuntimeError):
            return {"type": type(result).__name__}

    # Fallback: record only the type.
    return {"type": type(result).__name__}


def _json_safe(value: Any) -> Any:
    """Best-effort conversion to something JSON serializable and deterministic."""

    try:
        json.dumps(value)
        return value
    except TypeError:
        pass

    if dataclasses.is_dataclass(value):
        return _json_safe(asdict(value))

    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]

    # Deterministic fallback.
    return {"type": type(value).__name__}
