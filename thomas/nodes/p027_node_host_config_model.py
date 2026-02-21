"""Node host config model.

This module defines the configuration *model* for a node host (a headless node that
connects to a Thomas gateway). The model is exposed as JSON Schema + optional UI
hints and example snippets.

It is intentionally conservative:
- JSON-serializable output only
- A small schema surface, designed to be stable across releases
- Deterministic, machine-readable errors
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, TypedDict, Union
import json

try:
    import json5  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    json5 = None  # type: ignore


JsonDict = dict[str, Any]


class NodeHostConfigModelErrorDict(TypedDict, total=False):
    code: str
    message: str
    details: JsonDict


class NodeHostConfigModelOutputDict(TypedDict, total=False):
    schema: JsonDict
    example: JsonDict
    uiHints: JsonDict
    current: JsonDict


class NodeHostConfigModelError(Exception):
    """Base error for node-host config model operations."""

    code: str = "NODE_HOST_CONFIG_MODEL_ERROR"

    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: JsonDict = dict(details) if details else {}

    def to_dict(self) -> NodeHostConfigModelErrorDict:
        payload: NodeHostConfigModelErrorDict = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class NodeHostConfigModelInvalidInputError(NodeHostConfigModelError):
    code = "NODE_HOST_CONFIG_MODEL_INVALID_INPUT"


class NodeHostConfigModelMissingConfigError(NodeHostConfigModelError):
    code = "NODE_HOST_CONFIG_MODEL_MISSING_CONFIG"


class NodeHostConfigModelExternalFailure(NodeHostConfigModelError):
    code = "NODE_HOST_CONFIG_MODEL_EXTERNAL_FAILURE"


@dataclass(frozen=True)
class NodeHostConfigModelRequest:
    """Input contract for building the node-host config model."""

    # Optional config file path. When `include_current=True`, this must be provided.
    config_path: Optional[Union[str, Path]] = None

    # When true, attempt to load the current config from `config_path` and include it.
    include_current: bool = False

    # When true, include an example snippet.
    include_example: bool = True

    # When true, include UI hints.
    include_ui_hints: bool = True

    def resolved_config_path(self) -> Path:
        if self.config_path is None:
            raise NodeHostConfigModelMissingConfigError(
                "config_path is required when include_current=True"
            )
        return Path(self.config_path).expanduser()


@dataclass(frozen=True)
class NodeHostConfigModelResponse:
    """Output contract for the node-host config model."""

    schema: JsonDict
    example: Optional[JsonDict] = None
    ui_hints: Optional[JsonDict] = None
    current: Optional[JsonDict] = None

    def to_dict(self) -> NodeHostConfigModelOutputDict:
        payload: NodeHostConfigModelOutputDict = {"schema": self.schema}
        if self.example is not None:
            payload["example"] = self.example
        if self.ui_hints is not None:
            payload["uiHints"] = self.ui_hints
        if self.current is not None:
            payload["current"] = self.current
        return payload


def node_host_config_schema() -> JsonDict:
    """Return the JSON Schema for node-host configuration."""

    # Keep to a portable subset of JSON Schema to maximize client compatibility.
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "NodeHostConfig",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "browserProxy": {
                "type": "object",
                "additionalProperties": False,
                "description": "Browser proxy settings for a node host.",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "default": True,
                        "description": "Expose the local browser control server via a node proxy.",
                    },
                    "allowProfiles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional allowlist of browser profile names exposed via the node proxy.",
                    },
                },
                "required": [],
            }
        },
        "required": [],
    }


def node_host_config_ui_hints() -> JsonDict:
    """Return UI hints keyed by dotted config paths."""

    return {
        "browserProxy": {
            "label": "Browser proxy",
            "description": "Settings related to proxying browser control through a node host.",
        },
        "browserProxy.enabled": {
            "label": "Enable browser proxy",
            "help": "Expose the local browser control server via a node proxy.",
        },
        "browserProxy.allowProfiles": {
            "label": "Allowed profiles",
            "help": "Optional allowlist of browser profile names exposed via the node proxy.",
        },
    }


def node_host_config_example() -> JsonDict:
    """Return a minimal example node-host config."""

    return {"browserProxy": {"enabled": True}}


def node_host_config_model(
    request: Optional[NodeHostConfigModelRequest] = None,
) -> NodeHostConfigModelResponse:
    """Build the node-host config model."""

    req = request or NodeHostConfigModelRequest()

    if not isinstance(req, NodeHostConfigModelRequest):
        raise NodeHostConfigModelInvalidInputError(
            "request must be a NodeHostConfigModelRequest",
            details={"got": type(req).__name__},
        )

    schema = node_host_config_schema()
    example = node_host_config_example() if req.include_example else None
    ui_hints = node_host_config_ui_hints() if req.include_ui_hints else None

    current: Optional[JsonDict] = None
    if req.include_current:
        current = _load_node_host_config(req.resolved_config_path())

    return NodeHostConfigModelResponse(
        schema=schema,
        example=example,
        ui_hints=ui_hints,
        current=current,
    )


def get_node_host_config_model(
    request: Optional[NodeHostConfigModelRequest] = None,
) -> NodeHostConfigModelOutputDict:
    """Convenience wrapper returning a JSON-serializable dict."""

    return node_host_config_model(request).to_dict()


def _load_node_host_config(path: Path) -> JsonDict:
    """Load node-host configuration from a config file.

    The config file may contain either:
    - a full Thomas config object containing a top-level nodeHost section, or
    - a raw node-host config object (i.e., the nodeHost section itself).
    """

    if not path.exists():
        raise NodeHostConfigModelMissingConfigError(
            "config file not found",
            details={"path": str(path)},
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise NodeHostConfigModelExternalFailure(
            "failed to read config file",
            details={"path": str(path), "error": type(e).__name__},
        ) from e

    try:
        data = _loads_jsonish(raw)
    except Exception as e:
        raise NodeHostConfigModelInvalidInputError(
            "config file is not valid JSON/JSON5",
            details={"path": str(path), "error": type(e).__name__},
        ) from e

    # Accept either a full config containing nodeHost, or a direct node-host config object.
    node_host_section: Any
    if isinstance(data, Mapping):
        for key in ("nodeHost", "node_host", "node-host"):
            if key in data:
                node_host_section = data.get(key)
                break
        else:
            node_host_section = data
    else:
        node_host_section = data

    if not isinstance(node_host_section, Mapping):
        raise NodeHostConfigModelInvalidInputError(
            "node host config must be an object",
            details={"path": str(path), "type": type(node_host_section).__name__},
        )

    normalized = _normalize_json(node_host_section)

    if not isinstance(normalized, dict):
        normalized = dict(normalized)  # type: ignore[arg-type]

    _validate_node_host_config(normalized)

    return normalized


def _loads_jsonish(raw: str) -> Any:
    """Parse JSON5 if available, otherwise strict JSON."""

    if json5 is not None:
        try:
            return json5.loads(raw)
        except Exception:
            # Fall back to strict JSON for better error signaling on pure JSON.
            pass
    return json.loads(raw)


def _normalize_json(value: Any) -> Any:
    """Normalize mappings into plain dicts for stable JSON serialization."""

    if isinstance(value, Mapping):
        return {str(k): _normalize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_json(v) for v in value]
    return value


def _validate_node_host_config(cfg: JsonDict) -> None:
    """Validate node-host config.

    Validation is intentionally scoped to the keys described by this model so that:
    - errors are deterministic
    - future additions elsewhere in the main config do not break this model
    """

    allowed_top = {"browserProxy"}
    unknown_top = set(cfg.keys()) - allowed_top
    if unknown_top:
        raise NodeHostConfigModelInvalidInputError(
            "unknown node host config keys",
            details={"unknown": sorted(unknown_top)},
        )

    browser_proxy = cfg.get("browserProxy")
    if browser_proxy is None:
        return

    if not isinstance(browser_proxy, Mapping):
        raise NodeHostConfigModelInvalidInputError(
            "browserProxy must be an object",
            details={"type": type(browser_proxy).__name__},
        )

    allowed_bp = {"enabled", "allowProfiles"}
    unknown_bp = set(browser_proxy.keys()) - allowed_bp
    if unknown_bp:
        raise NodeHostConfigModelInvalidInputError(
            "unknown browserProxy keys",
            details={"unknown": sorted(unknown_bp)},
        )

    enabled = browser_proxy.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise NodeHostConfigModelInvalidInputError(
            "browserProxy.enabled must be a boolean",
            details={"type": type(enabled).__name__},
        )

    allow_profiles = browser_proxy.get("allowProfiles")
    if allow_profiles is not None:
        if not isinstance(allow_profiles, list) or not all(
            isinstance(p, str) for p in allow_profiles
        ):
            raise NodeHostConfigModelInvalidInputError(
                "browserProxy.allowProfiles must be an array of strings",
                details={"type": type(allow_profiles).__name__},
            )
