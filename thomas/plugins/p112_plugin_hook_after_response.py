"""P112 - After-response hook (Thomas-native).

This module provides a deterministic "after-response" hook that can be invoked by
the agent loop, a plugin manager, or automation.

Goals:
- Clear input/output contracts (dataclasses)
- Deterministic, machine-readable errors (stable error codes)
- Optional side-effect sinks (currently: file append)
- JSON schema helpers for gateway/CLI automation
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from collections.abc import Mapping, MutableMapping

# -------------------------------
# Contracts
# -------------------------------

@dataclass(frozen=True, slots=True)
class AfterResponseHookRequest:
    """Input contract for the after-response hook."""

    response_text: str
    conversation_id: str | None = None
    response_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AfterResponseHookRequest:
        if not isinstance(raw, Mapping):
            raise AfterResponseHookInputError(
                "request must be an object", field="request", got=type(raw).__name__
            )

        if "response_text" not in raw:
            raise AfterResponseHookInputError("missing required field", field="response_text")

        response_text = raw.get("response_text")
        if not isinstance(response_text, str):
            raise AfterResponseHookInputError(
                "response_text must be a string",
                field="response_text",
                got=type(response_text).__name__,
            )

        conversation_id = raw.get("conversation_id")
        if conversation_id is not None and not isinstance(conversation_id, str):
            raise AfterResponseHookInputError(
                "conversation_id must be a string",
                field="conversation_id",
                got=type(conversation_id).__name__,
            )

        response_id = raw.get("response_id")
        if response_id is not None and not isinstance(response_id, str):
            raise AfterResponseHookInputError(
                "response_id must be a string",
                field="response_id",
                got=type(response_id).__name__,
            )

        metadata = raw.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise AfterResponseHookInputError(
                "metadata must be an object",
                field="metadata",
                got=type(metadata).__name__,
            )

        return cls(
            response_text=response_text,
            conversation_id=conversation_id,
            response_id=response_id,
            metadata=metadata,
        )

    @classmethod
    def from_any(cls, raw: Any) -> AfterResponseHookRequest:
        """A small convenience adapter.

        Accepts:
        - AfterResponseHookRequest
        - Mapping[str, Any]
        - str (treated as response_text)
        """
        if isinstance(raw, AfterResponseHookRequest):
            return raw
        if isinstance(raw, str):
            return cls(response_text=raw)
        if isinstance(raw, Mapping):
            return cls.from_mapping(raw)
        raise AfterResponseHookInputError(
            "request must be an object or string",
            field="request",
            got=type(raw).__name__,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SinkType = Literal["none", "file"]


@dataclass(frozen=True, slots=True)
class AfterResponseHookConfig:
    """Configuration contract for the after-response hook."""

    enabled: bool
    sink: SinkType = "none"
    file_path: str | None = None
    max_chars: int = 50_000

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> AfterResponseHookConfig:
        if raw is None:
            raise AfterResponseHookConfigError("missing config", code="missing_config")

        if not isinstance(raw, Mapping):
            raise AfterResponseHookConfigError(
                "config must be an object",
                code="invalid_config",
                details={"got": type(raw).__name__},
            )

        if "enabled" not in raw:
            raise AfterResponseHookConfigError(
                "missing required field",
                code="invalid_config",
                details={"field": "enabled"},
            )
        enabled = raw.get("enabled")
        if not isinstance(enabled, bool):
            raise AfterResponseHookConfigError(
                "enabled must be a boolean",
                code="invalid_config",
                details={"field": "enabled", "got": type(enabled).__name__},
            )

        sink = raw.get("sink", "none")
        if not isinstance(sink, str):
            raise AfterResponseHookConfigError(
                "sink must be a string",
                code="invalid_config",
                details={"field": "sink", "got": type(sink).__name__},
            )
        sink_norm = sink.strip().lower()
        if sink_norm == "none":
            sink_t: SinkType = "none"
        elif sink_norm == "file":
            sink_t = "file"
        else:
            raise AfterResponseHookConfigError(
                "unsupported sink",
                code="invalid_config",
                details={"field": "sink", "allowed": ["none", "file"], "got": sink},
            )

        file_path = raw.get("file_path")
        if file_path is not None and not isinstance(file_path, str):
            raise AfterResponseHookConfigError(
                "file_path must be a string",
                code="invalid_config",
                details={"field": "file_path", "got": type(file_path).__name__},
            )

        max_chars = raw.get("max_chars", 50_000)
        if not isinstance(max_chars, int) or max_chars <= 0:
            raise AfterResponseHookConfigError(
                "max_chars must be a positive integer",
                code="invalid_config",
                details={"field": "max_chars", "got": type(max_chars).__name__},
            )

        cfg = cls(enabled=enabled, sink=sink_t, file_path=file_path, max_chars=max_chars)
        cfg._validate_cross_fields()
        return cfg

    def _validate_cross_fields(self) -> None:
        if self.sink == "file" and not self.file_path:
            raise AfterResponseHookConfigError(
                "file sink requires file_path",
                code="invalid_config",
                details={"field": "file_path", "reason": "required when sink=file"},
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AfterResponseHookResult:
    """Output contract for the after-response hook."""

    response_text: str
    char_count: int
    word_count: int
    sha256: str
    written_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -------------------------------
# Deterministic errors
# -------------------------------

class AfterResponseHookError(RuntimeError):
    """Base error for this hook with a stable error code."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_error_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class AfterResponseHookInputError(AfterResponseHookError):
    def __init__(self, message: str, *, field: str, got: str | None = None) -> None:
        details: dict[str, Any] = {"field": field}
        if got is not None:
            details["got"] = got
        super().__init__(message, code="invalid_input", details=details)


class AfterResponseHookConfigError(AfterResponseHookError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_config",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class AfterResponseHookExternalError(AfterResponseHookError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, code="external_failure", details=details)


# -------------------------------
# Hook implementation
# -------------------------------

def run_after_response_hook(
    request: AfterResponseHookRequest | Mapping[str, Any] | str,
    config: AfterResponseHookConfig | Mapping[str, Any] | None,
) -> AfterResponseHookResult:
    """Execute the after-response hook.

    Raises:
        AfterResponseHookInputError
        AfterResponseHookConfigError
        AfterResponseHookExternalError
    """

    req_obj = AfterResponseHookRequest.from_any(request)
    cfg_obj = config if isinstance(config, AfterResponseHookConfig) else AfterResponseHookConfig.from_mapping(
        config  # type: ignore[arg-type]
    )

    # Deterministic inspection output even for disabled mode.
    if not cfg_obj.enabled:
        return _build_result(req_obj.response_text, written_to=None)

    if len(req_obj.response_text) > cfg_obj.max_chars:
        raise AfterResponseHookInputError(
            "response_text exceeds max_chars",
            field="response_text",
            got=str(
                {
                    "actual": len(req_obj.response_text),
                    "max_chars": cfg_obj.max_chars,
                }
            ),
        )

    written_to: str | None = None
    if cfg_obj.sink == "file":
        written_to = _append_to_file(cfg_obj.file_path, req_obj.response_text)

    return _build_result(req_obj.response_text, written_to=written_to)


def _build_result(response_text: str, *, written_to: str | None) -> AfterResponseHookResult:
    sha = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    return AfterResponseHookResult(
        response_text=response_text,
        char_count=len(response_text),
        word_count=len(response_text.split()),
        sha256=sha,
        written_to=written_to,
    )


def _append_to_file(file_path: str | None, content: str) -> str:
    if not file_path:
        raise AfterResponseHookConfigError(
            "file sink requires file_path",
            code="invalid_config",
            details={"field": "file_path"},
        )

    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
    except Exception as exc:  # noqa: BLE001
        raise AfterResponseHookExternalError(
            f"Failed to write response to '{path}' ({exc.__class__.__name__}).",
            details={"file_path": str(path), "exc_type": exc.__class__.__name__},
        ) from None

    return str(path)


# -------------------------------
# Optional helper: a callable hook object
# -------------------------------

@dataclass(slots=True)
class AfterResponseHook:
    """A small callable wrapper useful for agent-loop integration."""

    config: AfterResponseHookConfig

    def __call__(self, response_text: str, **metadata: Any) -> AfterResponseHookResult:
        req = AfterResponseHookRequest(response_text=response_text, metadata=dict(metadata))
        return run_after_response_hook(req, self.config)


# -------------------------------
# JSON helpers (automation)
# -------------------------------

def request_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AfterResponseHookRequest",
        "type": "object",
        "additionalProperties": False,
        "required": ["response_text"],
        "properties": {
            "response_text": {"type": "string"},
            "conversation_id": {"type": ["string", "null"]},
            "response_id": {"type": ["string", "null"]},
            "metadata": {"type": "object"},
        },
    }


def config_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AfterResponseHookConfig",
        "type": "object",
        "additionalProperties": False,
        "required": ["enabled"],
        "properties": {
            "enabled": {"type": "boolean"},
            "sink": {"type": "string", "enum": ["none", "file"]},
            "file_path": {"type": ["string", "null"]},
            "max_chars": {"type": "integer", "minimum": 1},
        },
    }


def result_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AfterResponseHookResult",
        "type": "object",
        "additionalProperties": False,
        "required": ["response_text", "char_count", "word_count", "sha256"],
        "properties": {
            "response_text": {"type": "string"},
            "char_count": {"type": "integer", "minimum": 0},
            "word_count": {"type": "integer", "minimum": 0},
            "sha256": {"type": "string"},
            "written_to": {"type": ["string", "null"]},
        },
    }


def error_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AfterResponseHookError",
        "type": "object",
        "additionalProperties": False,
        "required": ["code", "message", "details"],
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "details": {"type": "object"},
        },
    }


def response_envelope_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AfterResponseHookEnvelope",
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "result": result_json_schema(),
            "error": error_json_schema(),
        },
    }


def run_after_response_hook_enveloped(
    request: AfterResponseHookRequest | Mapping[str, Any] | str,
    config: AfterResponseHookConfig | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Run the hook and return a stable JSON-friendly envelope."""

    try:
        result = run_after_response_hook(request=request, config=config)
        return {"ok": True, "result": result.to_dict()}
    except AfterResponseHookError as exc:
        return {"ok": False, "error": exc.to_error_dict()}


def loads_json_object(text: str, *, what: str) -> MutableMapping[str, Any]:
    """Parse JSON and require a top-level object.

    This helper exists to keep error messages deterministic.
    """

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AfterResponseHookInputError(
            f"{what} is not valid JSON",
            field=what,
            got=f"JSONDecodeError:{exc.msg}",
        ) from None

    if not isinstance(parsed, dict):
        raise AfterResponseHookInputError(
            f"{what} must be a JSON object",
            field=what,
            got=type(parsed).__name__,
        )
    return parsed


def env_truthy(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}
