"""Thomas plugin: plugin registry core model.

This module exposes a small, typed "core model" describing the plugins
available to Thomas at runtime.

Why this exists:
- Automation needs a deterministic JSON shape (CLI `--json`).
- Agents need a structured view of what tools exist and where they came from.

Design goals:
- Thomas-native naming (no OpenClaw naming reuse).
- Defensive introspection: works across a range of plugin styles.
- Deterministic error codes and stable output ordering.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict, cast
from collections.abc import Mapping, Sequence

try:  # Python 3.11+
    from typing import NotRequired
except ImportError:  # pragma: no cover
    NotRequired = Any  # type: ignore


SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Errors (deterministic + machine readable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryErrorInfo:
    code: str
    message: str
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = dict(self.details)
        return out


class PluginRegistryError(Exception):
    """Base error for plugin registry model failures."""

    code: str = "PLUGIN_REGISTRY_ERROR"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self._message = message
        self.details = dict(details) if details else None

    @property
    def message(self) -> str:
        return self._message

    def to_info(self) -> RegistryErrorInfo:
        return RegistryErrorInfo(code=self.code, message=self._message, details=self.details)

    def to_dict(self) -> dict[str, Any]:
        return self.to_info().to_dict()


class InvalidInputError(PluginRegistryError):
    code = "INVALID_INPUT"


class ConfigError(PluginRegistryError):
    code = "MISSING_CONFIG"


class ExternalFailureError(PluginRegistryError):
    code = "EXTERNAL_FAILURE"


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class BuildPluginRegistryRequestDict(TypedDict, total=False):
    """Untrusted request dict contract (e.g., from JSON)."""

    plugin_modules: list[str]
    include_tools: bool
    include_failed: bool
    on_error: Literal["collect", "raise"]


@dataclass(frozen=True)
class BuildPluginRegistryRequest:
    """Validated request contract."""

    plugin_modules: Sequence[str] | None = None
    include_tools: bool = True
    include_failed: bool = True
    on_error: Literal["collect", "raise"] = "collect"


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema) if self.input_schema else {},
            "output_schema": dict(self.output_schema) if self.output_schema else {},
        }


@dataclass(frozen=True)
class PluginDescriptor:
    name: str
    module: str
    version: str = ""
    description: str = ""
    tools: Sequence[ToolDescriptor] = field(default_factory=tuple)
    load_error: RegistryErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "module": self.module,
            "version": self.version,
            "description": self.description,
            "tools": [t.to_dict() for t in self.tools],
        }
        if self.load_error is not None:
            out["load_error"] = self.load_error.to_dict()
        return out


class PluginRegistryModelDict(TypedDict):
    schema_version: str
    plugins: list[dict[str, Any]]


@dataclass(frozen=True)
class PluginRegistryModel:
    schema_version: str
    plugins: Sequence[PluginDescriptor]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plugins": [p.to_dict() for p in self.plugins],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


_ALLOWED_REQUEST_KEYS = {"plugin_modules", "include_tools", "include_failed", "on_error"}


def parse_build_request(data: Mapping[str, Any] | None) -> BuildPluginRegistryRequest:
    """Validate and coerce an untrusted request dict into a BuildPluginRegistryRequest."""

    if data is None:
        return BuildPluginRegistryRequest()

    if not isinstance(data, Mapping):
        raise InvalidInputError(
            "Request must be an object.",
            details={"expected": "object", "got": type(data).__name__},
        )

    unknown = sorted(set(data.keys()) - _ALLOWED_REQUEST_KEYS)
    if unknown:
        raise InvalidInputError(
            "Unknown request field(s).",
            details={"unknown": unknown},
        )

    plugin_modules_raw = data.get("plugin_modules")
    plugin_modules: list[str] | None
    if plugin_modules_raw is None:
        plugin_modules = None
    else:
        if not isinstance(plugin_modules_raw, Sequence) or isinstance(plugin_modules_raw, (str, bytes)):
            raise InvalidInputError(
                "plugin_modules must be a list of strings.",
                details={"field": "plugin_modules", "got": type(plugin_modules_raw).__name__},
            )
        plugin_modules = []
        for idx, item in enumerate(plugin_modules_raw):
            if not isinstance(item, str) or not item.strip():
                raise InvalidInputError(
                    "plugin_modules must contain only non-empty strings.",
                    details={"field": "plugin_modules", "index": idx, "got": type(item).__name__},
                )
            plugin_modules.append(item)

    include_tools = data.get("include_tools", True)
    if not isinstance(include_tools, bool):
        raise InvalidInputError(
            "include_tools must be a boolean.",
            details={"field": "include_tools", "got": type(include_tools).__name__},
        )

    include_failed = data.get("include_failed", True)
    if not isinstance(include_failed, bool):
        raise InvalidInputError(
            "include_failed must be a boolean.",
            details={"field": "include_failed", "got": type(include_failed).__name__},
        )

    on_error = data.get("on_error", "collect")
    if on_error not in ("collect", "raise"):
        raise InvalidInputError(
            "on_error must be 'collect' or 'raise'.",
            details={"field": "on_error", "got": on_error},
        )

    return BuildPluginRegistryRequest(
        plugin_modules=plugin_modules,
        include_tools=include_tools,
        include_failed=include_failed,
        on_error=cast(Literal["collect", "raise"], on_error),
    )


def build_plugin_registry_core_model(
    request: BuildPluginRegistryRequest | Mapping[str, Any] | None = None,
) -> PluginRegistryModel:
    """Build the plugin registry core model."""

    if request is None:
        req = BuildPluginRegistryRequest()
    elif isinstance(request, BuildPluginRegistryRequest):
        req = request
    elif isinstance(request, Mapping):
        req = parse_build_request(request)
    else:
        raise InvalidInputError(
            "request must be a BuildPluginRegistryRequest or an object.",
            details={"got": type(request).__name__},
        )

    module_names = list(req.plugin_modules) if req.plugin_modules is not None else _discover_plugin_modules()

    plugins: list[PluginDescriptor] = []
    for mod_name in module_names:
        plugin = _load_plugin_descriptor(
            mod_name,
            include_tools=req.include_tools,
            include_failed=req.include_failed,
            on_error=req.on_error,
        )
        if plugin is not None:
            plugins.append(plugin)

    # Deterministic ordering
    plugins.sort(key=lambda p: p.module)

    return PluginRegistryModel(schema_version=SCHEMA_VERSION, plugins=plugins)


# ---------------------------------------------------------------------------
# Discovery / loading
# ---------------------------------------------------------------------------


def _discover_plugin_modules() -> list[str]:
    try:
        pkg = importlib.import_module("thomas.plugins")
    except Exception:
        raise ConfigError(
            "Thomas plugin package 'thomas.plugins' could not be imported.",
            details={"package": "thomas.plugins"},
        ) from None

    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        raise ConfigError(
            "Thomas plugin package 'thomas.plugins' does not expose a __path__ for discovery.",
            details={"package": "thomas.plugins"},
        )

    prefix = pkg.__name__ + "."
    module_names: list[str] = []
    for mod in pkgutil.iter_modules(pkg_path, prefix):
        if mod.ispkg:
            continue
        leaf = mod.name.split(".")[-1]
        if leaf.startswith("_"):
            continue
        module_names.append(mod.name)

    module_names.sort()
    return module_names


def _load_plugin_descriptor(
    module_name: str,
    *,
    include_tools: bool,
    include_failed: bool,
    on_error: Literal["collect", "raise"],
) -> PluginDescriptor | None:
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        err = RegistryErrorInfo(
            code="PLUGIN_IMPORT_FAILED",
            message=f"Failed to import plugin module '{module_name}'.",
            details={"module": module_name, "exception": type(exc).__name__},
        )
        if on_error == "raise":
            raise ExternalFailureError(err.message, details=err.details) from None
        if not include_failed:
            return None
        return PluginDescriptor(name=_fallback_plugin_name(module_name), module=module_name, load_error=err)

    try:
        name, version, description, tools = _extract_metadata_from_module(mod, include_tools=include_tools)
        tools_sorted = sorted(tools, key=lambda t: t.name)
        return PluginDescriptor(
            name=name,
            module=module_name,
            version=version,
            description=description,
            tools=tuple(tools_sorted),
        )
    except PluginRegistryError:
        raise
    except Exception as exc:
        err = RegistryErrorInfo(
            code="PLUGIN_METADATA_FAILED",
            message=f"Failed to extract plugin metadata from '{module_name}'.",
            details={"module": module_name, "exception": type(exc).__name__},
        )
        if on_error == "raise":
            raise ExternalFailureError(err.message, details=err.details) from None
        if not include_failed:
            return None
        return PluginDescriptor(name=_fallback_plugin_name(module_name), module=module_name, load_error=err)


def _fallback_plugin_name(module_name: str) -> str:
    return module_name.split(".")[-1]


def _extract_metadata_from_module(mod: Any, *, include_tools: bool) -> tuple[str, str, str, list[ToolDescriptor]]:
    plugin_obj = _find_plugin_object(mod)

    name = _coerce_str(_get_field(plugin_obj, mod, "name")) or getattr(mod, "__name__", "")
    version = _coerce_str(_get_field(plugin_obj, mod, "version")) or ""
    description = (
        _coerce_str(_get_field(plugin_obj, mod, "description"))
        or _coerce_str(getattr(mod, "__doc__", None))
        or ""
    )

    tools: list[ToolDescriptor] = []
    if include_tools:
        tools_raw = _get_field(plugin_obj, mod, "tools")
        if tools_raw is None:
            tools_raw = getattr(mod, "TOOLS", None)
        if tools_raw is not None:
            tools = _coerce_tools(tools_raw)

    return name, version, description, tools


def _find_plugin_object(mod: Any) -> Any:
    for attr in ("PLUGIN", "plugin", "PLUGIN_SPEC", "PLUGIN_INFO", "SPEC"):
        if hasattr(mod, attr):
            return getattr(mod, attr)
    return None


def _get_field(plugin_obj: Any, mod: Any, field: str) -> Any:
    if plugin_obj is None:
        return getattr(mod, field.upper(), None)
    if isinstance(plugin_obj, Mapping):
        return plugin_obj.get(field)
    return getattr(plugin_obj, field, None)


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return None


def _coerce_tools(value: Any) -> list[ToolDescriptor]:
    if value is None:
        return []

    # Mapping: name -> tool spec
    if isinstance(value, Mapping):
        return [_coerce_tool(v, fallback_name=str(k)) for k, v in value.items()]

    # Sequence of tool specs
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_coerce_tool(v) for v in value]

    raise InvalidInputError(
        "tools must be a list or mapping.",
        details={"field": "tools", "got": type(value).__name__},
    )


def _coerce_tool(value: Any, fallback_name: str = "") -> ToolDescriptor:
    # Minimal form: tool name as a string
    if isinstance(value, str):
        if not value.strip():
            raise InvalidInputError("tool name cannot be empty", details={"tool": value})
        return ToolDescriptor(name=value.strip())

    # Mapping form
    if isinstance(value, Mapping):
        name = _coerce_str(value.get("name")) or fallback_name
        if not name:
            raise InvalidInputError(
                "tool is missing required field 'name'.",
                details={"tool": dict(value)},
            )
        description = _coerce_str(value.get("description")) or ""
        input_schema = _coerce_schema(value.get("input_schema"))
        output_schema = _coerce_schema(value.get("output_schema"))
        return ToolDescriptor(name=name, description=description, input_schema=input_schema, output_schema=output_schema)

    # Object-like form
    name = _coerce_str(getattr(value, "name", None)) or fallback_name or value.__class__.__name__
    description = _coerce_str(getattr(value, "description", None)) or ""
    input_schema = _coerce_schema(getattr(value, "input_schema", None) or getattr(value, "schema", None) or {})
    output_schema = _coerce_schema(getattr(value, "output_schema", None) or {})
    return ToolDescriptor(name=name, description=description, input_schema=input_schema, output_schema=output_schema)


def _coerce_schema(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except Exception:
            return {}
        if isinstance(loaded, Mapping):
            return cast(Mapping[str, Any], loaded)
        return {}
    return {}


# ---------------------------------------------------------------------------
# Tool-callable wrapper (agent-friendly envelope)
# ---------------------------------------------------------------------------


class RegistryToolResponseDict(TypedDict):
    ok: bool
    result: NotRequired[PluginRegistryModelDict]
    error: NotRequired[Mapping[str, Any]]


def plugins_registry_model(payload: Mapping[str, Any] | None = None) -> RegistryToolResponseDict:
    """Tool entrypoint: return a machine-readable plugin registry model."""

    try:
        req = parse_build_request(payload)
        model = build_plugin_registry_core_model(req)
        return {"ok": True, "result": cast(PluginRegistryModelDict, model.to_dict())}
    except PluginRegistryError as exc:
        return {"ok": False, "error": exc.to_dict()}


# ---------------------------------------------------------------------------
# Plugin metadata (for loaders that inspect module-level declarations)
# ---------------------------------------------------------------------------


_TOOL_INPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "plugin_modules": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional module names to include. If omitted, Thomas will discover plugins.",
        },
        "include_tools": {"type": "boolean", "default": True},
        "include_failed": {"type": "boolean", "default": True},
        "on_error": {"type": "string", "enum": ["collect", "raise"], "default": "collect"},
    },
    "additionalProperties": False,
}

_TOOL_OUTPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "result": {"type": "object"},
        "error": {"type": "object"},
    },
    "required": ["ok"],
    "additionalProperties": True,
}


PLUGIN: Mapping[str, Any] = {
    "name": "plugin-registry-core-model",
    "version": "0.2.0",
    "description": "Expose a structured, machine-readable view of installed Thomas plugins.",
    "tools": [
        {
            "name": "plugins.registry_model",
            "description": "Return the plugin registry core model.",
            "input_schema": _TOOL_INPUT_SCHEMA,
            "output_schema": _TOOL_OUTPUT_SCHEMA,
        }
    ],
}

plugin = PLUGIN
TOOLS = PLUGIN["tools"]


__all__ = [
    "BuildPluginRegistryRequest",
    "ConfigError",
    "ExternalFailureError",
    "InvalidInputError",
    "PluginDescriptor",
    "PluginRegistryError",
    "PluginRegistryModel",
    "RegistryErrorInfo",
    "ToolDescriptor",
    "build_plugin_registry_core_model",
    "parse_build_request",
    "plugins_registry_model",
]
