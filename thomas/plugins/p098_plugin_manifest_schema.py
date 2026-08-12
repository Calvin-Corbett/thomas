"""Plugin manifest JSON Schema for Thomas.

This module provides a deterministic JSON Schema document describing the
**Thomas plugin manifest** format.

It also includes a small, explicit input/output contract around schema
generation and a registry-friendly ``register(...)`` helper so the schema can be
exposed as a Thomas tool.

Design goals
------------
- Thomas-native naming (no Reference CLI naming reuse).
- Deterministic errors for invalid input and registration failures.
- Low coupling to the rest of the codebase (registry API discovered at runtime).

The schema itself is intentionally pragmatic: it validates a stable, minimal set
of fields that are useful for discovery and tooling.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker

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
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
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
    schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
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
            message=("Unsupported schema_version. Supported values: " + ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))),
            details={"schema_version": req.schema_version},
        )

    meta_schema = _DRAFT_TO_META_SCHEMA.get(req.draft)
    if meta_schema is None:
        raise PluginManifestSchemaError(
            code="invalid_draft",
            message=("Invalid JSON Schema draft. Supported values: " + ", ".join(sorted(_DRAFT_TO_META_SCHEMA.keys()))),
            details={"draft": req.draft},
        )

    defs_key = _defs_key(req.draft)

    # Reusable fragments.
    json_schema_fragment: dict[str, Any] = {
        "type": "object",
        "description": "A JSON Schema fragment (object form).",
    }

    plugin_block: dict[str, Any] = {
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

    runtime_block: dict[str, Any] = {
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

    tool_block: dict[str, Any] = {
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

    assistant_block: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["instructions", "conversation_starters", "knowledge_files"],
        "properties": {
            "instructions": {
                "type": "string",
                "minLength": 1,
                "maxLength": 20000,
                "description": "Tailored operating instructions for the assistant-backed plugin.",
            },
            "conversation_starters": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "knowledge_files": {
                "type": "array",
                "maxItems": 50,
                "items": {"type": "string", "minLength": 1, "maxLength": 260},
                "description": "Package-relative knowledge files available to this assistant only.",
            },
        },
    }

    permissions_block: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["tools", "apps", "apis"],
        "properties": {
            key: {
                "type": "array",
                "maxItems": 100,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": r"^[A-Za-z][A-Za-z0-9_.:-]*$",
                },
            }
            for key in ("tools", "apps", "apis")
        },
    }

    schema: dict[str, Any] = {
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
                "items": {"$ref": f"#/{defs_key}/tool"},
                "description": "Tools exposed by the plugin.",
            },
            "assistant": {
                "$ref": f"#/{defs_key}/assistant",
                "description": "Optional custom-assistant instructions, starters, and isolated knowledge.",
            },
            "permissions": {
                "$ref": f"#/{defs_key}/permissions",
                "description": "Explicit external tools, apps, and APIs selected for the plugin.",
            },
        },
        defs_key: {
            "json_schema": json_schema_fragment,
            "plugin": plugin_block,
            "runtime": runtime_block,
            "tool": tool_block,
            "assistant": assistant_block,
            "permissions": permissions_block,
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
                "assistant": {
                    "instructions": "Answer from the attached product handbook.",
                    "conversation_starters": ["Summarize the launch checklist."],
                    "knowledge_files": ["knowledge/handbook.md"],
                },
                "permissions": {"tools": ["files.read"], "apps": [], "apis": []},
            }
        ]

    return PluginManifestSchemaResult(
        schema_version=req.schema_version,
        draft=req.draft,
        schema=schema,
    )


def _validate_relative_manifest_path(value: str) -> bool:
    normalized = str(value or "").replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or ":" in normalized:
        return False
    parts = PurePosixPath(normalized).parts
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def validate_plugin_manifest(
    manifest: Mapping[str, Any],
    request: PluginManifestSchemaRequest | None = None,
) -> dict[str, Any]:
    """Validate one rich Thomas plugin manifest and return a plain copy.

    JSON Schema handles the structural contract. The semantic pass additionally
    rejects knowledge paths that could escape a plugin package and wildcard
    permission requests that would silently broaden authority.
    """

    if not isinstance(manifest, Mapping):
        raise PluginManifestSchemaError(
            code="invalid_manifest",
            message="Plugin manifest must be a JSON object.",
            details={"errors": ["manifest: expected object"]},
        )

    req = request or PluginManifestSchemaRequest()
    result = build_plugin_manifest_schema(req)
    validator_cls = Draft7Validator if req.draft == "7" else Draft202012Validator
    validator = validator_cls(result.schema, format_checker=FormatChecker())
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or 'manifest'}: {error.message}"
        for error in sorted(validator.iter_errors(dict(manifest)), key=lambda item: list(item.absolute_path))
    ]

    assistant = manifest.get("assistant")
    if isinstance(assistant, Mapping):
        knowledge_files = assistant.get("knowledge_files")
        if isinstance(knowledge_files, list):
            for index, raw_path in enumerate(knowledge_files):
                if isinstance(raw_path, str) and not _validate_relative_manifest_path(raw_path):
                    errors.append(f"assistant/knowledge_files/{index}: unsafe package-relative path")

    permissions = manifest.get("permissions")
    if isinstance(permissions, Mapping):
        for kind in ("tools", "apps", "apis"):
            values = permissions.get(kind)
            if not isinstance(values, list):
                continue
            for index, value in enumerate(values):
                if isinstance(value, str) and ("*" in value or value.lower() in {"all", "any", "root", "system"}):
                    errors.append(f"permissions/{kind}/{index}: wildcard or unrestricted authority is not allowed")

    if errors:
        raise PluginManifestSchemaError(
            code="invalid_manifest",
            message="Plugin manifest failed validation.",
            details={"errors": errors},
        )
    return dict(manifest)


def tool_plugin_manifest_schema(
    *,
    schema_version: str = "v1",
    draft: SchemaDraft = "2020-12",
    include_examples: bool = False,
) -> dict[str, Any]:
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

TOOL_INPUT_SCHEMA: dict[str, Any] = {
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

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "A JSON Schema document.",
}

TOOL_SPEC: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "Return the JSON Schema for the Thomas plugin manifest.",
    "input_schema": TOOL_INPUT_SCHEMA,
    "output_schema": TOOL_OUTPUT_SCHEMA,
}

# Include common callable keys to maximize compatibility with registry loaders.
TOOL_RUNTIME_SPEC: dict[str, Any] = {
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
        register_tool = registry.register_tool

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
        reg = registry.register

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
    "validate_plugin_manifest",
    "tool_plugin_manifest_schema",
    "register",
]
