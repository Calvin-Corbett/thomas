"""Plugin manifest JSON Schema for Thomas.

This module provides a deterministic JSON Schema document describing the
**Thomas plugin manifest** format.

It also includes a small, explicit input/output contract around schema
generation and a registry-friendly ``register(...)`` helper so the schema can be
exposed as a Thomas tool.

Design goals
------------
- Thomas-native naming (no OpenClaw naming reuse).
- Deterministic errors for invalid input and registration failures.
- Low coupling to the rest of the codebase (registry API discovered at runtime).

The schema itself is intentionally pragmatic: it validates a stable, minimal set
of fields that are useful for discovery and tooling.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping, Optional


SchemaDraft = Literal["2020-12", "7"]


_DRAFT_TO_META_SCHEMA: Mapping[SchemaDraft, str] = {
    "2020-12": "https://json-schema.org/draft/2020-12/schema",
    "7": "http://json-schema.org/draft-07/schema#",
}


SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"v1"})


class PluginManifestSchemaError(Exception):
    """Deterministic error for plugin manifest schema operations."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


@dataclass(frozen=True)
class PluginManifestSchemaRequest:
    """Input contract for building a plugin manifest schema."""

    schema_version: str = "v1"
    draft: SchemaDraft = "2020-12"
    include_examples: bool = False


@dataclass(frozen=True)
class PluginManifestSchemaResult:
    """Output contract for building a plugin manifest schema."""

    schema_version: str
    draft: SchemaDraft
    schema: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "draft": self.draft,
            "schema": self.schema,
        }


TOOL_NAME = "plugin_manifest_schema"


def _defs_key(draft: SchemaDraft) -> str:
    # Draft 7 uses "definitions"; 2020-12 uses "$defs".
    return "definitions" if draft == "7" else "$defs"


def build_plugin_manifest_schema(
    request: PluginManifestSchemaRequest | None = None,
) -> PluginManifestSchemaResult:
    """Build the JSON Schema describing the Thomas plugin manifest."""

    req = request or PluginManifestSchemaRequest()

    if req.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise PluginManifestSchemaError(
            code="unsupported_schema_version",
            message=(
                "Unsupported schema_version. Supported values: "
                + ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
            ),
            details={"schema_version": req.schema_version},
        )

    meta_schema = _DRAFT_TO_META_SCHEMA.get(req.draft)
    if meta_schema is None:
        raise PluginManifestSchemaError(
            code="invalid_draft",
            message=(
                "Invalid JSON Schema draft. Supported values: "
                + ", ".join(sorted(_DRAFT_TO_META_SCHEMA.keys()))
            ),
            details={"draft": req.draft},
        )

    defs_key = _defs_key(req.draft)

    # Reusable fragments.
    json_schema_fragment: Dict[str, Any] = {
        "type": "object",
        "description": "A JSON Schema fragment (object form).",
    }

    plugin_block: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "version", "description"],
        "properties": {
            "id": {
                "type": "string",
                "description": "Optional stable identifier for the plugin.",
                "pattern": r"^[a-z0-9][a-z0-9_.-]{0,63}$",
            },
            "name": {
                "type": "string",
                "minLength": 1,
                "description": "Human readable plugin name.",
            },
            "version": {
                "type": "string",
                "minLength": 1,
                "description": "Plugin version string (recommend SemVer).",
            },
            "description": {
                "type": "string",
                "minLength": 1,
                "description": "Human readable plugin description.",
            },
            "author": {
                "type": "string",
                "minLength": 1,
                "description": "Optional plugin author or organization.",
            },
            "homepage": {
                "type": "string",
                "format": "uri",
                "description": "Optional project homepage URL.",
            },
            "license": {
                "type": "string",
                "minLength": 1,
                "description": "Optional license identifier or text.",
            },
        },
    }

    runtime_block: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "entrypoint"],
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["python", "http"],
                "description": "Execution environment for the plugin.",
            },
            "entrypoint": {
                "type": "string",
                "minLength": 1,
                "description": "Module path or URL used to load the plugin.",
            },
        },
    }

    tool_block: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "description", "input_schema", "output_schema"],
        "properties": {
            "name": {
                "type": "string",
                "minLength": 1,
                "description": "Stable tool name.",
                "pattern": r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$",
            },
            "summary": {
                "type": "string",
                "description": "Optional short summary.",
            },
            "description": {
                "type": "string",
                "minLength": 1,
                "description": "Long-form tool description.",
            },
            "input_schema": {"$ref": f"#/{defs_key}/json_schema"},
            "output_schema": {"$ref": f"#/{defs_key}/json_schema"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for grouping or discovery.",
            },
        },
    }

    schema: Dict[str, Any] = {
        "$schema": meta_schema,
        "$id": f"https://thomas.local/schemas/plugin-manifest/{req.schema_version}.json",
        "title": "Thomas Plugin Manifest",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "plugin", "tools"],
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": [req.schema_version],
                "description": "Schema version for this manifest document.",
            },
            "plugin": {"$ref": f"#/{defs_key}/plugin"},
            "runtime": {
                "$ref": f"#/{defs_key}/runtime",
                "description": "Optional runtime/packaging metadata.",
            },
            "tools": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": f"#/{defs_key}/tool"},
                "description": "Tools exposed by the plugin.",
            },
        },
        defs_key: {
            "json_schema": json_schema_fragment,
            "plugin": plugin_block,
            "runtime": runtime_block,
            "tool": tool_block,
        },
    }

    if req.include_examples:
        schema["examples"] = [
            {
                "schema_version": req.schema_version,
                "plugin": {
                    "id": "example-plugin",
                    "name": "Example Plugin",
                    "version": "1.0.0",
                    "description": "An example Thomas plugin manifest.",
                },
                "tools": [
                    {
                        "name": "example.echo",
                        "description": "Echoes the provided text.",
                        "input_schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {"text": {"type": "string"}},
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {"text": {"type": "string"}},
                            "additionalProperties": False,
                        },
                    }
                ],
            }
        ]

    return PluginManifestSchemaResult(
        schema_version=req.schema_version,
        draft=req.draft,
        schema=schema,
    )


def tool_plugin_manifest_schema(
    *,
    schema_version: str = "v1",
    draft: SchemaDraft = "2020-12",
    include_examples: bool = False,
) -> Dict[str, Any]:
    """Tool wrapper: return the schema document as JSON-serializable data."""

    result = build_plugin_manifest_schema(
        PluginManifestSchemaRequest(
            schema_version=schema_version,
            draft=draft,
            include_examples=include_examples,
        )
    )
    # Return only the JSON Schema document for maximum interoperability.
    return result.schema


# --- Tool descriptor(s) ----------------------------------------------------

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {
            "type": "string",
            "default": "v1",
            "description": "Schema version to emit.",
        },
        "draft": {
            "type": "string",
            "default": "2020-12",
            "enum": ["2020-12", "7"],
            "description": "JSON Schema draft to target.",
        },
        "include_examples": {
            "type": "boolean",
            "default": False,
            "description": "Whether to include example manifests.",
        },
    },
}

TOOL_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "A JSON Schema document.",
}

TOOL_SPEC: Dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "Return the JSON Schema for the Thomas plugin manifest.",
    "input_schema": TOOL_INPUT_SCHEMA,
    "output_schema": TOOL_OUTPUT_SCHEMA,
}

# Include common callable keys to maximize compatibility with registry loaders.
TOOL_RUNTIME_SPEC: Dict[str, Any] = {
    **TOOL_SPEC,
    "func": tool_plugin_manifest_schema,
    "callable": tool_plugin_manifest_schema,
    "handler": tool_plugin_manifest_schema,
    "fn": tool_plugin_manifest_schema,
}

TOOLS = [TOOL_RUNTIME_SPEC]


def _call_with_supported_kwargs(callable_obj: Any, **kwargs: Any) -> Any:
    """Call *callable_obj* with only kwargs it appears to accept."""

    try:
        sig = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return callable_obj(**kwargs)

    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return callable_obj(**kwargs)

    supported = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return callable_obj(**supported)


def register(registry: Any) -> None:
    """Register this schema tool with a Thomas registry.

    The registry API is discovered at runtime to keep this module low-coupling.
    """

    payload = TOOL_RUNTIME_SPEC

    # 1) register_tool(...) is the most explicit.
    if hasattr(registry, "register_tool"):
        register_tool = getattr(registry, "register_tool")

        # Common patterns:
        #   register_tool(spec)
        #   register_tool(name, func)
        #   register_tool(**spec_fields)
        try:
            register_tool(payload)
            return
        except TypeError:
            pass

        try:
            register_tool(TOOL_NAME, tool_plugin_manifest_schema)
            return
        except TypeError:
            pass

        try:
            _call_with_supported_kwargs(register_tool, **payload)
            return
        except TypeError:
            pass

    # 2) register(...) is a common fallback.
    if hasattr(registry, "register"):
        reg = getattr(registry, "register")

        try:
            reg(payload)
            return
        except TypeError:
            pass

        try:
            reg(TOOL_NAME, tool_plugin_manifest_schema)
            return
        except TypeError:
            pass

        try:
            _call_with_supported_kwargs(reg, **payload)
            return
        except TypeError:
            pass

    # 3) Dict-like fallback.
    try:
        registry[TOOL_NAME] = tool_plugin_manifest_schema
    except Exception as exc:  # pragma: no cover
        raise PluginManifestSchemaError(
            code="registry_registration_failed",
            message="Failed to register plugin_manifest_schema tool.",
            details={"reason": str(exc)},
        )


__all__ = [
    "PluginManifestSchemaError",
    "PluginManifestSchemaRequest",
    "PluginManifestSchemaResult",
    "SUPPORTED_SCHEMA_VERSIONS",
    "SchemaDraft",
    "TOOL_NAME",
    "TOOL_INPUT_SCHEMA",
    "TOOL_OUTPUT_SCHEMA",
    "TOOL_SPEC",
    "TOOLS",
    "build_plugin_manifest_schema",
    "tool_plugin_manifest_schema",
    "register",
]
