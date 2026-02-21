"""Browser JSON output contract.

This module defines a stable machine-readable envelope for browser-related
outputs so that automation can reliably parse results.

The contract is intentionally minimal:

* Success: { ok: true, data: { stdout, stderr, result, ... }, meta: {...} }
* Failure: { ok: false, error: { code, message, details }, meta: {...} }

In JSON output mode, higher layers (typically the CLI) should ensure exactly one
JSON object is emitted.

This implementation avoids reusing any external project naming.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
from typing import Any, Literal, Mapping, MutableMapping, Optional, TypedDict, Union, cast


CONTRACT_NAME = "thomas.browser.json_output"
CONTRACT_VERSION = "1.0"


ErrorCode = Literal[
    "invalid_input",
    "missing_config",
    "external_failure",
    "internal_error",
]


class BrowserJsonContractError(Exception):
    """Contract-specific exception with deterministic error codes."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.details: dict[str, Any] = dict(details or {})


@dataclass(frozen=True)
class BrowserJsonError:
    code: ErrorCode
    message: str
    details: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class BrowserJsonMeta:
    contract: str = CONTRACT_NAME
    contract_version: str = CONTRACT_VERSION
    request_id: Optional[str] = None
    command: Optional[str] = None


class BrowserJsonData(TypedDict, total=False):
    """Common success payload fields.

    * stdout/stderr: captured human-oriented output
    * result: returned value from the underlying operation

    Commands may attach additional machine-friendly fields.
    """

    stdout: str
    stderr: str
    result: Any


class BrowserJsonSuccess(TypedDict):
    ok: Literal[True]
    data: Mapping[str, Any]
    meta: Mapping[str, Any]


class BrowserJsonFailure(TypedDict):
    ok: Literal[False]
    error: Mapping[str, Any]
    meta: Mapping[str, Any]


BrowserJsonEnvelope = Union[BrowserJsonSuccess, BrowserJsonFailure]


class BrowserJsonInput(TypedDict, total=False):
    """Lightweight input contract for browser operations.

    This is intentionally generic: different browser commands accept different
    flags/arguments.
    """

    command: str
    url: str
    request_id: str


def validate_input(inp: Mapping[str, Any]) -> None:
    """Validate minimal input invariants.

    This does *not* attempt to fully validate command-specific options; it only
    ensures that commonly present fields are well-formed.
    """

    if not isinstance(inp, Mapping):
        raise BrowserJsonContractError(
            "invalid_input",
            "Input must be a mapping.",
            details={"type": type(inp).__name__},
        )

    if "command" in inp and inp["command"] is not None:
        cmd = inp["command"]
        if not isinstance(cmd, str) or not cmd.strip():
            raise BrowserJsonContractError(
                "invalid_input",
                "Invalid command.",
                details={"command": cmd},
            )

    if "url" in inp and inp["url"] is not None:
        url = inp["url"]
        if not isinstance(url, str) or not url.strip() or any(ch.isspace() for ch in url):
            raise BrowserJsonContractError(
                "invalid_input",
                "Invalid URL.",
                details={"url": url},
            )


def _coerce_json_default(value: Any) -> Any:  # noqa: ANN401
    """Best-effort JSON coercion for unknown objects."""

    if is_dataclass(value):
        return asdict(value)

    for attr in ("model_dump", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                break

    return repr(value)


def render_json(envelope: BrowserJsonEnvelope) -> str:
    """Render an envelope as compact JSON."""

    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=_coerce_json_default)


def success(
    data: Any,
    *,
    command: Optional[str] = None,
    request_id: Optional[str] = None,
) -> BrowserJsonSuccess:
    """Create a success envelope."""

    meta = asdict(BrowserJsonMeta(command=command, request_id=request_id))

    payload: MutableMapping[str, Any]
    if isinstance(data, Mapping) and {"stdout", "stderr", "result"}.issubset(data.keys()):
        payload = dict(cast(Mapping[str, Any], data))
    else:
        payload = {"stdout": "", "stderr": "", "result": data}

    return {"ok": True, "data": payload, "meta": meta}


def failure(
    code: ErrorCode,
    message: str,
    *,
    details: Optional[Mapping[str, Any]] = None,
    command: Optional[str] = None,
    request_id: Optional[str] = None,
) -> BrowserJsonFailure:
    """Create a failure envelope."""

    meta = asdict(BrowserJsonMeta(command=command, request_id=request_id))
    err = asdict(BrowserJsonError(code=code, message=message, details=dict(details or {}) or None))
    return {"ok": False, "error": err, "meta": meta}


def failure_from_exception(
    exc: BaseException,
    *,
    command: Optional[str] = None,
    request_id: Optional[str] = None,
) -> BrowserJsonFailure:
    """Map an exception to a deterministic failure envelope."""

    if isinstance(exc, BrowserJsonContractError):
        details = dict(exc.details)
        details.setdefault("exception_type", exc.__class__.__name__)
        details.setdefault("exception_module", exc.__class__.__module__)
        return failure(
            exc.code,
            str(exc),
            details=details,
            command=command,
            request_id=request_id,
        )

    details: dict[str, Any] = {
        "exception_type": exc.__class__.__name__,
        "exception_module": exc.__class__.__module__,
    }

    # Deterministic category mapping.
    if isinstance(exc, ValueError):
        code: ErrorCode = "invalid_input"
    elif isinstance(exc, (KeyError, FileNotFoundError, ImportError, ModuleNotFoundError)):
        code = "missing_config"
    elif isinstance(exc, (TimeoutError, ConnectionError, OSError, RuntimeError)):
        code = "external_failure"
    elif isinstance(exc, (TypeError, AttributeError, AssertionError)):
        code = "internal_error"
    else:
        # Default to external failure: in browser tooling, most unexpected
        # exceptions are due to external systems (browser engine, network, etc.).
        code = "external_failure"

    message = str(exc) or exc.__class__.__name__
    return failure(code, message, details=details, command=command, request_id=request_id)


def attach_meta(envelope: BrowserJsonEnvelope, *, command: Optional[str] = None) -> BrowserJsonEnvelope:
    """Attach/override meta.command on an existing envelope."""

    updated: MutableMapping[str, Any] = dict(envelope)
    meta: MutableMapping[str, Any] = dict(cast(Mapping[str, Any], envelope.get("meta", {})))
    if command is not None:
        meta["command"] = command
    updated["meta"] = meta
    return cast(BrowserJsonEnvelope, updated)


def browser_json_schema() -> Mapping[str, Any]:
    """Return a JSON Schema describing :class:`BrowserJsonEnvelope`."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{CONTRACT_NAME}:{CONTRACT_VERSION}",
        "title": "Thomas Browser JSON Output",
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "ok": {"const": True},
                    "data": {
                        "type": "object",
                        "properties": {
                            "stdout": {"type": "string"},
                            "stderr": {"type": "string"},
                            "result": {},
                        },
                        "required": ["stdout", "stderr", "result"],
                        # Commands may attach additional keys.
                        "additionalProperties": True,
                    },
                    "meta": {"$ref": "#/$defs/meta"},
                },
                "required": ["ok", "data", "meta"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "ok": {"const": False},
                    "error": {"$ref": "#/$defs/error"},
                    "meta": {"$ref": "#/$defs/meta"},
                },
                "required": ["ok", "error", "meta"],
                "additionalProperties": False,
            },
        ],
        "$defs": {
            "meta": {
                "type": "object",
                "properties": {
                    "contract": {"type": "string"},
                    "contract_version": {"type": "string"},
                    "request_id": {"type": ["string", "null"]},
                    "command": {"type": ["string", "null"]},
                },
                "required": ["contract", "contract_version", "request_id", "command"],
                # Forward-compatible: allow extra metadata keys.
                "additionalProperties": True,
            },
            "error": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "enum": [
                            "invalid_input",
                            "missing_config",
                            "external_failure",
                            "internal_error",
                        ],
                    },
                    "message": {"type": "string"},
                    "details": {"type": ["object", "null"]},
                },
                "required": ["code", "message", "details"],
                "additionalProperties": True,
            },
        },
    }
