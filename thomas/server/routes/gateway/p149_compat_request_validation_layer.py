from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict, Union, cast
from collections.abc import Mapping

from aiohttp import web

# ----------------------------------------------------------------------------
# Contracts
# ----------------------------------------------------------------------------

CompatKind = Literal["openai_chat_completions", "responses_create"]


class CompatValidationErrorDict(TypedDict, total=False):
    code: str
    message: str
    path: str
    hint: str


@dataclass(frozen=True)
class CompatValidationError(Exception):
    """Deterministic, machine-readable validation error."""

    code: str
    message: str
    path: str = ""
    hint: str = ""

    def to_dict(self) -> CompatValidationErrorDict:
        d: CompatValidationErrorDict = {"code": self.code, "message": self.message}
        if self.path:
            d["path"] = self.path
        if self.hint:
            d["hint"] = self.hint
        return d


class CompatValidationResultDict(TypedDict):
    ok: bool
    kind: str
    normalized: dict[str, Any]
    errors: list[CompatValidationErrorDict]


@dataclass(frozen=True)
class CompatValidationResult:
    ok: bool
    kind: str
    normalized: dict[str, Any]
    errors: tuple[CompatValidationError, ...]

    def to_dict(self) -> CompatValidationResultDict:
        return {
            "ok": self.ok,
            "kind": self.kind,
            "normalized": self.normalized,
            "errors": [e.to_dict() for e in self.errors],
        }


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _err(code: str, message: str, *, path: str = "", hint: str = "") -> CompatValidationError:
    return CompatValidationError(code=code, message=message, path=path, hint=hint)


def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _as_dict(payload: Any) -> dict[str, Any] | CompatValidationError:
    if not isinstance(payload, dict):
        return _err("invalid_type", "Payload must be a JSON object.", path="$")
    return cast(dict[str, Any], payload)


def _optional_number(payload: Mapping[str, Any], key: str, *, path: str) -> None | float | CompatValidationError:
    v = payload.get(key)
    if v is None:
        return None
    if isinstance(v, bool):
        return _err("invalid_type", f"'{key}' must be a number.", path=path)
    if not isinstance(v, (int, float)):
        return _err("invalid_type", f"'{key}' must be a number.", path=path)
    return float(v)


def _optional_bool(payload: Mapping[str, Any], key: str, *, path: str) -> None | bool | CompatValidationError:
    v = payload.get(key)
    if v is None:
        return None
    if not isinstance(v, bool):
        return _err("invalid_type", f"'{key}' must be a boolean.", path=path)
    return v


# ----------------------------------------------------------------------------
# Validators (conservative, deterministic)
# ----------------------------------------------------------------------------

def _validate_openai_chat_completions(payload: dict[str, Any]) -> CompatValidationResult:
    errors: list[CompatValidationError] = []
    normalized: dict[str, Any] = {}

    model = payload.get("model")
    if not _is_nonempty_str(model):
        errors.append(
            _err(
                "missing_field",
                "Missing or invalid 'model'.",
                path="$.model",
                hint="Provide a non-empty model string.",
            )
        )
    else:
        normalized["model"] = model

    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) == 0:
        errors.append(
            _err(
                "missing_field",
                "Missing or invalid 'messages'.",
                path="$.messages",
                hint="Provide a non-empty array of message objects.",
            )
        )
    else:
        norm_msgs: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                errors.append(_err("invalid_type", "Each message must be an object.", path=f"$.messages[{i}]"))
                continue
            role = m.get("role")
            if not _is_nonempty_str(role):
                errors.append(
                    _err(
                        "missing_field",
                        "Message missing 'role'.",
                        path=f"$.messages[{i}].role",
                        hint="Use roles like 'system', 'user', 'assistant', 'tool'.",
                    )
                )
            content = m.get("content")
            # Conservative content validation:
            # - allow string
            # - allow null (tool-call placeholder)
            if content is not None and not isinstance(content, str):
                errors.append(
                    _err(
                        "invalid_type",
                        "Message 'content' must be a string or null.",
                        path=f"$.messages[{i}].content",
                    )
                )
            norm_msgs.append(dict(m))
        normalized["messages"] = norm_msgs

    temp = _optional_number(payload, "temperature", path="$.temperature")
    if isinstance(temp, CompatValidationError):
        errors.append(temp)
    elif temp is not None:
        normalized["temperature"] = temp

    max_tokens = payload.get("max_tokens")
    if max_tokens is not None:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            errors.append(_err("invalid_type", "'max_tokens' must be an integer.", path="$.max_tokens"))
        elif max_tokens < 1:
            errors.append(_err("invalid_value", "'max_tokens' must be >= 1.", path="$.max_tokens"))
        else:
            normalized["max_tokens"] = max_tokens

    stream = _optional_bool(payload, "stream", path="$.stream")
    if isinstance(stream, CompatValidationError):
        errors.append(stream)
    elif stream is not None:
        normalized["stream"] = stream

    ok = len(errors) == 0
    return CompatValidationResult(ok=ok, kind="openai_chat_completions", normalized=normalized, errors=tuple(errors))


def _validate_responses_create(payload: dict[str, Any]) -> CompatValidationResult:
    errors: list[CompatValidationError] = []
    normalized: dict[str, Any] = {}

    model = payload.get("model")
    if not _is_nonempty_str(model):
        errors.append(
            _err(
                "missing_field",
                "Missing or invalid 'model'.",
                path="$.model",
                hint="Provide a non-empty model string.",
            )
        )
    else:
        normalized["model"] = model

    input_v = payload.get("input")
    messages = payload.get("messages")

    if input_v is None and messages is None:
        errors.append(
            _err(
                "missing_field",
                "Provide either 'input' or 'messages'.",
                path="$",
                hint="For simple text, set 'input' to a string.",
            )
        )
    else:
        if input_v is not None and not isinstance(input_v, (str, list)):
            errors.append(_err("invalid_type", "'input' must be a string or array.", path="$.input"))
        elif input_v is not None:
            normalized["input"] = input_v

        if messages is not None and not isinstance(messages, list):
            errors.append(_err("invalid_type", "'messages' must be an array.", path="$.messages"))
        elif messages is not None:
            normalized["messages"] = messages

    stream = _optional_bool(payload, "stream", path="$.stream")
    if isinstance(stream, CompatValidationError):
        errors.append(stream)
    elif stream is not None:
        normalized["stream"] = stream

    ok = len(errors) == 0
    return CompatValidationResult(ok=ok, kind="responses_create", normalized=normalized, errors=tuple(errors))


def validate_compat_request(kind: str, payload: Any) -> CompatValidationResult:
    """Deterministic, side-effect-free validation returning a structured result."""

    d_or_err = _as_dict(payload)
    if isinstance(d_or_err, CompatValidationError):
        return CompatValidationResult(ok=False, kind=str(kind), normalized={}, errors=(d_or_err,))
    d = d_or_err

    if kind == "openai_chat_completions":
        return _validate_openai_chat_completions(d)
    if kind == "responses_create":
        return _validate_responses_create(d)

    return CompatValidationResult(
        ok=False,
        kind=str(kind),
        normalized={},
        errors=(
            _err(
                "unsupported_kind",
                f"Unsupported kind '{kind}'.",
                path="$.kind",
                hint="Use 'openai_chat_completions' or 'responses_create'.",
            ),
        ),
    )


# ----------------------------------------------------------------------------
# Aiohttp route surface (machine-readable JSON)
# ----------------------------------------------------------------------------

ROUTE_PATH = "/gateway/compat/validate"


async def handle_compat_validate(request: web.Request) -> web.StreamResponse:
    """POST /gateway/compat/validate  Body: {"kind": "...", "payload": {...}}"""

    try:
        body = await request.json()
    except Exception:
        res = CompatValidationResult(
            ok=False,
            kind="",
            normalized={},
            errors=(_err("invalid_json", "Request body must be valid JSON.", path="$"),),
        )
        return web.json_response(res.to_dict(), status=400)

    if not isinstance(body, dict):
        res = CompatValidationResult(
            ok=False,
            kind="",
            normalized={},
            errors=(_err("invalid_type", "Request body must be a JSON object.", path="$"),),
        )
        return web.json_response(res.to_dict(), status=400)

    kind = body.get("kind")
    payload = body.get("payload")

    if not _is_nonempty_str(kind):
        res = CompatValidationResult(
            ok=False,
            kind="",
            normalized={},
            errors=(_err("missing_field", "Missing or invalid 'kind'.", path="$.kind"),),
        )
        return web.json_response(res.to_dict(), status=400)

    result = validate_compat_request(cast(str, kind), payload)
    return web.json_response(result.to_dict(), status=200 if result.ok else 400)


def bind_routes(app: web.Application) -> None:
    """Route binder for Thomas gateway route modules."""

    app.router.add_post(ROUTE_PATH, handle_compat_validate)


def json_schema() -> dict[str, Any]:
    """Stable JSON schema for the validation envelope expected by /gateway/compat/validate."""

    return {
        "title": "CompatValidateRequest",
        "type": "object",
        "required": ["kind", "payload"],
        "properties": {
            "kind": {"type": "string", "enum": ["openai_chat_completions", "responses_create"]},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
