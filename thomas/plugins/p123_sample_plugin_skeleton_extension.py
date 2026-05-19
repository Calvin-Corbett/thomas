"""P123 - Sample plugin skeleton extension.

This module implements a small, deterministic plugin intended as an example of how
Thomas-native plugins can be structured.

Design goals:
- Clear input/output contracts (Pydantic models)
- Deterministic, structured error reporting
- Optional config loading with explicit error categories
- Optional registry registration helper (best-effort)
- Pydantic v1/v2 compatibility helpers (Thomas repos vary)

Behavior:
- Renders a message using a prefix (default: "Thomas")
- Optional config JSON provides a prefix
- Optional transformations: uppercase, repeat

It intentionally avoids OpenClaw naming conventions.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

PLUGIN_ID = "p123_sample_plugin_skeleton_extension"
TOOL_NAME = "sample_plugin_skeleton_extension"
DESCRIPTION = (
    "Render a message with an optional prefix loaded from config. "
    "This is a sample plugin used for prompt-pack scaffolding."
)

# Environment variable used to locate an optional config file.
CONFIG_PATH_ENV = "THOMAS_P123_SAMPLE_PLUGIN_CONFIG"


# -----------------------------
# Pydantic compatibility layer
# -----------------------------


def _model_validate(model_cls: Any, payload: Any) -> Any:
    """Validate payload into a Pydantic model (v1/v2 compatible)."""

    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)  # pydantic v2
    return model_cls.parse_obj(payload)  # pydantic v1


def _model_dump(model: Any) -> dict[str, Any]:
    """Dump a Pydantic model to dict (v1/v2 compatible)."""

    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_schema(model_cls: Any) -> dict[str, Any]:
    """Return JSON-schema-like dict (v1/v2 compatible)."""

    if hasattr(model_cls, "model_json_schema"):
        return model_cls.model_json_schema()
    return model_cls.schema()


# -----------------------------
# Errors (deterministic)
# -----------------------------


class SamplePluginError(RuntimeError):
    """Deterministic error type for this plugin."""

    code: str
    details: Mapping[str, Any]
    retryable: bool

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
            "retryable": self.retryable,
        }


class InvalidInputError(SamplePluginError):
    def __init__(
        self,
        *,
        message: str = "Invalid input",
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(code="invalid_input", message=message, details=details, retryable=False)


class MissingConfigError(SamplePluginError):
    def __init__(
        self,
        *,
        message: str = "Missing configuration",
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(code="missing_config", message=message, details=details, retryable=False)


class ExternalFailureError(SamplePluginError):
    def __init__(
        self,
        *,
        message: str = "External failure",
        details: Mapping[str, Any] | None = None,
        retryable: bool = True,
    ):
        super().__init__(code="external_failure", message=message, details=details, retryable=retryable)


# -----------------------------
# Contracts
# -----------------------------


class SamplePluginSkeletonExtensionInput(BaseModel):
    """Input contract for the sample plugin."""

    message: str = Field(..., min_length=1, description="Message to render")
    times: int = Field(1, ge=1, le=20, description="How many times to repeat the message")
    uppercase: bool = Field(False, description="Whether to uppercase the message")
    use_config: bool = Field(
        False,
        description=(
            "When true, the plugin will attempt to load a JSON config file "
            "from `config_path` or the environment variable."
        ),
    )


class SamplePluginSkeletonExtensionOutput(BaseModel):
    """Output contract for the sample plugin."""

    rendered: str = Field(..., description="Rendered message")
    prefix: str = Field(..., description="Prefix used for rendering")
    used_config: bool = Field(..., description="Whether config was used")


class _SamplePluginConfig(BaseModel):
    prefix: str = Field("Thomas", min_length=1)


@dataclass(frozen=True)
class SamplePluginRouteSchema:
    """A small bundle of request/response schemas."""

    request_schema: dict[str, Any]
    response_schema: dict[str, Any]


def get_route_schema() -> SamplePluginRouteSchema:
    """Return JSON Schemas suitable for an HTTP route."""

    return SamplePluginRouteSchema(
        request_schema=_model_schema(SamplePluginSkeletonExtensionInput),
        response_schema=_model_schema(SamplePluginSkeletonExtensionOutput),
    )


def manifest() -> dict[str, Any]:
    """Return a small, machine-readable plugin manifest."""

    schema = get_route_schema()
    return {
        "plugin_id": PLUGIN_ID,
        "tool_name": TOOL_NAME,
        "description": DESCRIPTION,
        "request_schema": schema.request_schema,
        "response_schema": schema.response_schema,
    }


# -----------------------------
# Config loading
# -----------------------------


def _load_config_file(path: Path) -> _SamplePluginConfig:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise MissingConfigError(message="Config file not found", details={"path": str(path)}) from e
    except OSError as e:
        raise ExternalFailureError(
            message="Failed to read config file",
            details={"path": str(path)},
            retryable=True,
        ) from e

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ExternalFailureError(
            message="Config file is not valid JSON",
            details={"path": str(path)},
            retryable=False,
        ) from e

    try:
        return _model_validate(_SamplePluginConfig, payload)
    except ValidationError as e:
        raise ExternalFailureError(
            message="Config file is invalid",
            details={"path": str(path), "errors": e.errors()},
            retryable=False,
        ) from e


def _resolve_prefix(
    *,
    use_config: bool,
    config_path: str | None,
    env: Mapping[str, str],
) -> tuple[str, bool]:
    if not use_config:
        return "Thomas", False

    path_value = config_path or env.get(CONFIG_PATH_ENV)
    if not path_value:
        raise MissingConfigError(
            message="Config path not provided",
            details={"expected_env": CONFIG_PATH_ENV},
        )

    cfg = _load_config_file(Path(path_value))
    return cfg.prefix, True


# -----------------------------
# Core execution
# -----------------------------


def run(
    request: SamplePluginSkeletonExtensionInput,
    *,
    config_path: str | None = None,
    env: Mapping[str, str] | None = None,
) -> SamplePluginSkeletonExtensionOutput:
    env_map = env or os.environ

    prefix, used_config = _resolve_prefix(use_config=request.use_config, config_path=config_path, env=env_map)

    msg = request.message
    if request.uppercase:
        msg = msg.upper()

    rendered = f"{prefix}: " + " ".join([msg] * request.times)

    return SamplePluginSkeletonExtensionOutput(rendered=rendered, prefix=prefix, used_config=used_config)


def invoke(
    payload: Mapping[str, Any],
    *,
    config_path: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Invoke the plugin from an untyped payload.

    Wrapper contract:

    - success: {"ok": true, "plugin_id": ..., "result": {...}}
    - failure: {"ok": false, "plugin_id": ..., "error": {...}}
    """

    try:
        request = _model_validate(SamplePluginSkeletonExtensionInput, payload)
    except ValidationError as e:
        err = InvalidInputError(details={"errors": e.errors()})
        return {"ok": False, "plugin_id": PLUGIN_ID, "error": err.to_dict()}

    try:
        result = run(request, config_path=config_path, env=env)
        return {"ok": True, "plugin_id": PLUGIN_ID, "result": _model_dump(result)}
    except SamplePluginError as e:
        return {"ok": False, "plugin_id": PLUGIN_ID, "error": e.to_dict()}


def tool_handler(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Registry-friendly handler returning the raw result dict or raising."""

    wrapper = invoke(payload)
    if not wrapper.get("ok"):
        error = wrapper.get("error") or {}
        raise SamplePluginError(
            code=str(error.get("code") or "error"),
            message=str(error.get("message") or "Tool execution failed"),
            details=error.get("details") or {},
            retryable=bool(error.get("retryable") or False),
        )
    return wrapper["result"]


def register(registry: Any) -> None:
    """Best-effort registration with Thomas' tool registry.

    Thomas' registry API may vary across versions. We try a small set of common
    method names/signatures.
    """

    schema = get_route_schema()

    candidates: list[tuple[str, dict[str, Any]]]
    candidates = [
        (
            "register_tool",
            {
                "name": TOOL_NAME,
                "func": tool_handler,
                "description": DESCRIPTION,
                "input_schema": schema.request_schema,
                "output_schema": schema.response_schema,
            },
        ),
        (
            "register",
            {
                "name": TOOL_NAME,
                "handler": tool_handler,
                "description": DESCRIPTION,
                "input_schema": schema.request_schema,
                "output_schema": schema.response_schema,
            },
        ),
        (
            "add_tool",
            {
                "name": TOOL_NAME,
                "func": tool_handler,
                "description": DESCRIPTION,
                "input_schema": schema.request_schema,
                "output_schema": schema.response_schema,
            },
        ),
    ]

    for method_name, kwargs in candidates:
        method = getattr(registry, method_name, None)
        if method is None:
            continue
        try:
            method(**kwargs)
            return
        except TypeError:
            # Signature mismatch; try the next candidate.
            continue

    raise ExternalFailureError(
        message="Unsupported registry interface",
        details={"expected_methods": [name for name, _ in candidates]},
        retryable=False,
    )
