"""P109: Before-model plugin hook.

This module defines a *before-model* hook that can synchronously transform a
model request immediately before it is sent to an LLM.

Design goals
- Thomas-native naming (no OpenClaw naming reuse)
- Clear input/output contracts (TypedDict + dataclasses)
- Deterministic errors for invalid input/config/external failures
- Automation-friendly JSON mode (schema + JSON in/out)

The hook contract is intentionally minimal and generic:
- messages: list of {role, content, ...}
- model: optional string
- metadata: optional mapping

A plugin wrapper is provided that supports common hook method names so it can be
loaded by different plugin registries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, TypedDict, Union, cast


class ChatMessage(TypedDict, total=False):
    """Minimal message contract.

    Only `role` and `content` are required by this prompt pack.
    Any extra keys are preserved and passed through.
    """

    role: str
    content: str


class BeforeModelError(RuntimeError):
    """Deterministic error raised by the before-model hook."""

    def __init__(self, *, code: str, message: str, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


@dataclass(frozen=True)
class BeforeModelHookConfig:
    """Configuration for the before-model hook.

    Attributes:
        inject_system:
            Text to inject as a *new leading* system message.
            If missing/empty, the hook raises a deterministic MISSING_CONFIG.
        simulate_external_failure:
            If True, raises EXTERNAL_FAILURE. (Test-only switch.)
        max_inject_chars:
            Guardrail to avoid accidental mega-prompts.
    """

    inject_system: Optional[str] = None
    simulate_external_failure: bool = False
    max_inject_chars: int = 4096

    @staticmethod
    def from_mapping(raw: Optional[Mapping[str, Any]]) -> "BeforeModelHookConfig":
        if raw is None:
            return BeforeModelHookConfig()

        inject_system = raw.get("inject_system")
        if inject_system is not None and not isinstance(inject_system, str):
            raise BeforeModelError(
                code="INVALID_CONFIG",
                message="Config field 'inject_system' must be a string when provided.",
                details={"field": "inject_system", "type": type(inject_system).__name__},
            )

        simulate_external_failure = raw.get("simulate_external_failure", False)
        if not isinstance(simulate_external_failure, bool):
            raise BeforeModelError(
                code="INVALID_CONFIG",
                message="Config field 'simulate_external_failure' must be a boolean.",
                details={"field": "simulate_external_failure", "type": type(simulate_external_failure).__name__},
            )

        max_inject_chars = raw.get("max_inject_chars", 4096)
        if not isinstance(max_inject_chars, int) or max_inject_chars <= 0:
            raise BeforeModelError(
                code="INVALID_CONFIG",
                message="Config field 'max_inject_chars' must be a positive integer.",
                details={"field": "max_inject_chars", "value": max_inject_chars},
            )

        return BeforeModelHookConfig(
            inject_system=cast(Optional[str], inject_system),
            simulate_external_failure=simulate_external_failure,
            max_inject_chars=max_inject_chars,
        )


@dataclass(frozen=True)
class BeforeModelHookInput:
    """Input contract for the before-model hook."""

    messages: List[ChatMessage]
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_mapping(raw: Mapping[str, Any]) -> "BeforeModelHookInput":
        if not isinstance(raw, Mapping):
            raise BeforeModelError(
                code="INVALID_INPUT",
                message="Hook input must be a JSON object/mapping.",
                details={"type": type(raw).__name__},
            )

        messages = raw.get("messages")
        if not isinstance(messages, list):
            raise BeforeModelError(
                code="INVALID_INPUT",
                message="Hook input must include a 'messages' list.",
                details={"field": "messages", "type": type(messages).__name__},
            )

        validated: List[ChatMessage] = []
        for idx, msg in enumerate(messages):
            if not isinstance(msg, Mapping):
                raise BeforeModelError(
                    code="INVALID_INPUT",
                    message="Each message must be an object/mapping.",
                    details={"index": idx, "type": type(msg).__name__},
                )

            role = msg.get("role")
            content = msg.get("content")

            if not isinstance(role, str) or not role:
                raise BeforeModelError(
                    code="INVALID_INPUT",
                    message="Each message must include a non-empty string 'role'.",
                    details={"index": idx, "field": "role", "value": role},
                )

            if not isinstance(content, str):
                raise BeforeModelError(
                    code="INVALID_INPUT",
                    message="Each message must include a string 'content'.",
                    details={"index": idx, "field": "content", "type": type(content).__name__},
                )

            validated.append(cast(ChatMessage, dict(msg)))

        model = raw.get("model")
        if model is not None and not isinstance(model, str):
            raise BeforeModelError(
                code="INVALID_INPUT",
                message="Hook input field 'model' must be a string when provided.",
                details={"field": "model", "type": type(model).__name__},
            )

        metadata = raw.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise BeforeModelError(
                code="INVALID_INPUT",
                message="Hook input field 'metadata' must be an object when provided.",
                details={"field": "metadata", "type": type(metadata).__name__},
            )

        return BeforeModelHookInput(
            messages=validated,
            model=cast(Optional[str], model),
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class BeforeModelHookOutput:
    """Output contract for the before-model hook."""

    messages: List[ChatMessage]
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    applied: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "result": {
                "messages": list(self.messages),
                "model": self.model,
                "metadata": dict(self.metadata),
                "applied": self.applied,
            },
        }


def apply_before_model_hook(
    hook_input: Union[BeforeModelHookInput, Mapping[str, Any]],
    *,
    config: Union[BeforeModelHookConfig, Mapping[str, Any], None] = None,
) -> BeforeModelHookOutput:
    """Apply the before-model hook.

    Raises :class:`BeforeModelError` with stable error codes:
    - INVALID_INPUT
    - INVALID_CONFIG
    - MISSING_CONFIG
    - EXTERNAL_FAILURE
    """

    parsed_input = (
        hook_input
        if isinstance(hook_input, BeforeModelHookInput)
        else BeforeModelHookInput.from_mapping(cast(Mapping[str, Any], hook_input))
    )

    parsed_config = (
        config
        if isinstance(config, BeforeModelHookConfig)
        else BeforeModelHookConfig.from_mapping(cast(Optional[Mapping[str, Any]], config))
    )

    if parsed_config.simulate_external_failure:
        raise BeforeModelError(code="EXTERNAL_FAILURE", message="Simulated external failure.")

    inject_text = (parsed_config.inject_system or "").strip()
    if not inject_text:
        raise BeforeModelError(
            code="MISSING_CONFIG",
            message="Missing required config: 'inject_system'.",
            details={"required": ["inject_system"]},
        )

    if len(inject_text) > parsed_config.max_inject_chars:
        raise BeforeModelError(
            code="INVALID_CONFIG",
            message="Config field 'inject_system' exceeds max_inject_chars.",
            details={"max_inject_chars": parsed_config.max_inject_chars, "length": len(inject_text)},
        )

    new_messages: List[ChatMessage] = [
        ChatMessage(role="system", content=inject_text),
        *parsed_input.messages,
    ]

    new_metadata = dict(parsed_input.metadata)
    before_meta = new_metadata.get("before_model")
    if isinstance(before_meta, Mapping):
        before_meta = dict(before_meta)
    else:
        before_meta = {}

    before_meta.setdefault("injected", True)
    before_meta.setdefault("inject_chars", len(inject_text))
    new_metadata["before_model"] = before_meta

    return BeforeModelHookOutput(
        messages=new_messages,
        model=parsed_input.model,
        metadata=new_metadata,
        applied=True,
    )


def hook_json_schema() -> Dict[str, Any]:
    """Return a JSON-schema-like contract for request/config/result.

    This is intentionally conservative: it documents the shape used by this
    plugin without implying any broader Thomas schemas.
    """

    message_schema: Dict[str, Any] = {
        "type": "object",
        "required": ["role", "content"],
        "properties": {
            "role": {"type": "string"},
            "content": {"type": "string"},
        },
        "additionalProperties": True,
    }

    request_schema: Dict[str, Any] = {
        "type": "object",
        "required": ["messages"],
        "properties": {
            "messages": {"type": "array", "items": message_schema},
            "model": {"type": ["string", "null"]},
            "metadata": {"type": "object", "additionalProperties": True},
        },
        "additionalProperties": True,
    }

    config_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "inject_system": {"type": "string"},
            "simulate_external_failure": {"type": "boolean"},
            "max_inject_chars": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": True,
    }

    result_schema: Dict[str, Any] = {
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "result": {
                "type": "object",
                "properties": {
                    "messages": {"type": "array", "items": message_schema},
                    "model": {"type": ["string", "null"]},
                    "metadata": {"type": "object", "additionalProperties": True},
                    "applied": {"type": "boolean"},
                },
                "required": ["messages", "model", "metadata", "applied"],
            },
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object", "additionalProperties": True},
                },
                "required": ["code", "message", "details"],
            },
        },
        "additionalProperties": False,
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "request": request_schema,
            "config": config_schema,
            "result": result_schema,
        },
        "required": ["request", "config", "result"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Plugin wrapper
# ---------------------------------------------------------------------------


@dataclass
class BeforeModelHookPlugin:
    """Plugin wrapper around :func:`apply_before_model_hook`.

    Different parts of the codebase might look for different hook method names.
    We provide a few aliases to increase compatibility without touching core.
    """

    plugin_id: str = "p109-before-model"

    def before_model(self, request: Mapping[str, Any], *, config: Optional[Mapping[str, Any]] = None, **_: Any) -> Any:
        out = apply_before_model_hook(request, config=config)
        out_request = dict(request)
        out_request["messages"] = out.messages
        if out.model is not None:
            out_request["model"] = out.model
        out_request["metadata"] = out.metadata
        return out_request

    # Compatibility aliases
    pre_model = before_model
    before_llm = before_model
    on_before_model = before_model


def get_plugin() -> BeforeModelHookPlugin:
    return BeforeModelHookPlugin()


PLUGIN = get_plugin()
plugin = PLUGIN


def run_json(hook_input_json: str, *, config_json: Optional[str] = None) -> str:
    """Automation helper: JSON in, JSON out."""

    try:
        hook_input = json.loads(hook_input_json)
    except Exception as e:
        return json.dumps(
            BeforeModelError(code="INVALID_INPUT", message="Input is not valid JSON.", details={"error": str(e)}).to_dict(),
            sort_keys=True,
        )

    cfg: Optional[Mapping[str, Any]] = None
    if config_json is not None:
        try:
            cfg = cast(Mapping[str, Any], json.loads(config_json))
        except Exception as e:
            return json.dumps(
                BeforeModelError(code="INVALID_CONFIG", message="Config is not valid JSON.", details={"error": str(e)}).to_dict(),
                sort_keys=True,
            )

    try:
        out = apply_before_model_hook(cast(Mapping[str, Any], hook_input), config=cfg)
        return json.dumps(out.to_dict(), sort_keys=True)
    except BeforeModelError as e:
        return json.dumps(e.to_dict(), sort_keys=True)
