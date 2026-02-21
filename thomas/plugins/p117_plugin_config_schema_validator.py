"""Plugin configuration validation helpers.

Thomas-native utility for validating a plugin configuration payload (or config file)
against a JSON Schema.

The validator supports two modes:

1) Explicit schema mode: caller provides `schema` or `schema_path`.
2) Discovery mode: caller provides `plugin` and the schema is discovered via:
   - Thomas registries (best-effort, supports multiple internal shapes)
   - Importing the plugin module and reading common schema attributes

Design goals:
- Deterministic, automation-friendly errors (stable error codes and envelopes).
- Stable, machine-readable output for CI and gateway automation.
- Minimal assumptions about the rest of the Thomas codebase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


# ----------------------------- Public contracts -----------------------------


class PluginConfigSchemaValidatorError(Exception):
    """Deterministic exception type for plugin config schema validation."""

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
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class PluginConfigValidationIssue:
    """A single schema validation issue."""

    location: str
    message: str
    validator: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"location": self.location, "message": self.message}
        if self.validator is not None:
            out["validator"] = self.validator
        return out


@dataclass(frozen=True)
class PluginConfigValidationResult:
    """Output contract for validation results."""

    plugin: str | None
    valid: bool
    issues: list[PluginConfigValidationIssue] = field(default_factory=list)
    schema_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin,
            "valid": self.valid,
            "schema_source": self.schema_source,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass(frozen=True)
class PluginConfigValidationRequest:
    """Input contract for plugin configuration validation."""

    plugin: str | None = None
    config: Any | None = None
    config_path: Path | None = None
    schema: Mapping[str, Any] | None = None
    schema_path: Path | None = None


# JSON Schema describing the machine-readable output envelope used by the CLI.
OUTPUT_ENVELOPE_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PluginConfigSchemaValidatorOutput",
    "type": "object",
    "required": ["ok"],
    "properties": {
        "ok": {"type": "boolean"},
        "result": {
            "type": "object",
            "required": ["plugin", "valid", "schema_source", "issues"],
            "properties": {
                "plugin": {"type": ["string", "null"]},
                "valid": {"type": "boolean"},
                "schema_source": {"type": ["string", "null"]},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["location", "message"],
                        "properties": {
                            "location": {"type": "string"},
                            "message": {"type": "string"},
                            "validator": {"type": ["string", "null"]},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        "error": {
            "type": "object",
            "required": ["code", "message", "details"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"ok": {"const": True}}},
            "then": {"required": ["result"], "not": {"required": ["error"]}},
        },
        {
            "if": {"properties": {"ok": {"const": False}}},
            "then": {"required": ["error"], "not": {"required": ["result"]}},
        },
    ],
}


def get_output_envelope_schema() -> Mapping[str, Any]:
    """Return the JSON schema for the CLI JSON envelope."""
    return OUTPUT_ENVELOPE_JSON_SCHEMA


# ----------------------------- File reading --------------------------------


def _read_structured_file(path: Path, *, kind: str) -> Any:
    """Read a JSON/YAML/TOML file with deterministic errors."""
    if not path.exists():
        if kind == "schema":
            raise PluginConfigSchemaValidatorError(
                code="SCHEMA_FILE_NOT_FOUND",
                message="Schema file not found.",
                details={"path": str(path), "kind": kind},
            )
        raise PluginConfigSchemaValidatorError(
            code="CONFIG_NOT_FOUND",
            message="Config file not found.",
            details={"path": str(path), "kind": kind},
        )

    try:
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8")

        if suffix == ".json":
            return json.loads(text)

        if suffix in {".yml", ".yaml"}:
            try:
                import yaml  # type: ignore
            except Exception as e:  # pragma: no cover
                raise PluginConfigSchemaValidatorError(
                    code="YAML_UNAVAILABLE",
                    message="YAML support is not available.",
                    details={"path": str(path), "error": str(e), "kind": kind},
                ) from e
            return yaml.safe_load(text)

        if suffix == ".toml":
            try:
                import tomllib
            except ModuleNotFoundError:  # pragma: no cover
                import toml as tomllib  # type: ignore
            return tomllib.loads(text)

        raise PluginConfigSchemaValidatorError(
            code="UNSUPPORTED_FORMAT",
            message="Unsupported file format.",
            details={"path": str(path), "suffix": suffix, "kind": kind},
        )
    except PluginConfigSchemaValidatorError:
        raise
    except Exception as e:
        code = "SCHEMA_PARSE_ERROR" if kind == "schema" else "CONFIG_PARSE_ERROR"
        message = "Failed to parse schema file." if kind == "schema" else "Failed to parse config file."
        raise PluginConfigSchemaValidatorError(
            code=code,
            message=message,
            details={"path": str(path), "error": str(e), "kind": kind},
        ) from e


# ----------------------------- Schema discovery -----------------------------


def _json_pointer(parts: Iterable[Any]) -> str:
    """Convert an absolute_path iterable to an RFC6901-ish JSON pointer."""
    def esc(p: str) -> str:
        return p.replace("~", "~0").replace("/", "~1")

    out = ""
    for part in parts:
        out += "/" + esc(str(part))
    return out or "/"


def _coerce_schema(obj: Any, *, source: str) -> Mapping[str, Any]:
    if not isinstance(obj, Mapping):
        raise PluginConfigSchemaValidatorError(
            code="SCHEMA_INVALID",
            message="Schema must be a JSON object.",
            details={"schema_source": source, "type": type(obj).__name__},
        )
    return obj


def _extract_schema_from_module(mod: Any) -> tuple[Mapping[str, Any] | None, str | None]:
    """Extract a schema from a module using common, side-effect-free conventions."""
    # Simple constants or callables returning a mapping.
    for attr in ("CONFIG_SCHEMA", "config_schema", "SCHEMA", "schema"):
        if not hasattr(mod, attr):
            continue
        value = getattr(mod, attr)
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
        if isinstance(value, Mapping):
            return value, f"module:{mod.__name__}.{attr}"

    # Class or instance-based pattern.
    for attr in ("Plugin", "plugin", "PLUGIN"):
        if not hasattr(mod, attr):
            continue
        obj = getattr(mod, attr)

        # Avoid instantiating classes (constructors could have side effects).
        if isinstance(obj, type):
            for schema_attr in ("config_schema", "CONFIG_SCHEMA", "schema", "SCHEMA"):
                if hasattr(obj, schema_attr) and isinstance(getattr(obj, schema_attr), Mapping):
                    return getattr(obj, schema_attr), f"class:{mod.__name__}.{attr}.{schema_attr}"
            continue

        for schema_attr in ("config_schema", "CONFIG_SCHEMA", "schema", "SCHEMA"):
            if not hasattr(obj, schema_attr):
                continue
            value = getattr(obj, schema_attr)
            if callable(value):
                try:
                    value = value()
                except TypeError:
                    continue
            if isinstance(value, Mapping):
                return value, f"object:{mod.__name__}.{attr}.{schema_attr}"

    return None, None


def _extract_schema_from_object(obj: Any, *, label: str) -> tuple[Mapping[str, Any] | None, str | None]:
    """Extract schema from an object without knowing its exact type."""
    for attr in (
        "config_schema",
        "CONFIG_SCHEMA",
        "schema",
        "SCHEMA",
        "get_config_schema",
        "get_schema",
    ):
        if not hasattr(obj, attr):
            continue
        value = getattr(obj, attr)
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
        if isinstance(value, Mapping):
            return value, f"{label}.{attr}"
    return None, None


def _try_resolve_schema_via_registry(plugin: str) -> tuple[Mapping[str, Any] | None, str | None]:
    """Attempt schema discovery via Thomas's registry module.

    This is a best-effort adapter for multiple internal registry shapes. Any
    exceptions are swallowed so that module-based discovery can still run.
    """
    import importlib

    try:
        reg_mod = importlib.import_module("thomas.tools.registry")
    except Exception:
        return None, None

    candidates: list[Any] = []
    for name in ("registry", "REGISTRY", "tool_registry", "TOOL_REGISTRY"):
        value = getattr(reg_mod, name, None)
        if value is not None:
            candidates.append(value)

    for name in ("ToolRegistry", "ToolsRegistry", "Registry", "PluginRegistry"):
        value = getattr(reg_mod, name, None)
        if value is not None:
            candidates.append(value)

    def instance(candidate: Any) -> Any | None:
        if isinstance(candidate, type):
            for ctor_name in ("get_default", "default", "instance", "get"):
                ctor = getattr(candidate, ctor_name, None)
                if callable(ctor):
                    try:
                        return ctor()
                    except Exception:
                        pass
            try:
                return candidate()
            except Exception:
                return None
        return candidate

    for candidate in candidates:
        inst = instance(candidate)
        if inst is None:
            continue

        plugin_obj: Any | None = None

        # Common resolver methods
        for mname in ("get_plugin", "plugin", "resolve_plugin", "resolve", "get"):
            method = getattr(inst, mname, None)
            if not callable(method):
                continue
            try:
                plugin_obj = method(plugin)
            except Exception:
                continue
            if plugin_obj is not None:
                break

        # Mapping-like registries
        if plugin_obj is None:
            if isinstance(inst, Mapping):
                plugin_obj = inst.get(plugin)
            else:
                for attr in ("plugins", "_plugins", "registered_plugins", "available_plugins"):
                    mapping_obj = getattr(inst, attr, None)
                    if isinstance(mapping_obj, Mapping) and plugin in mapping_obj:
                        plugin_obj = mapping_obj[plugin]
                        break

        if plugin_obj is None:
            continue

        schema, source = _extract_schema_from_object(plugin_obj, label=f"registry:{inst.__class__.__name__}")
        if schema is not None and source is not None:
            return schema, source

    return None, None


def _import_plugin_module(plugin: str) -> Any:
    import importlib

    plugin = (plugin or "").strip()
    if not plugin:
        raise PluginConfigSchemaValidatorError(
            code="INVALID_REQUEST",
            message="Plugin identifier is empty.",
            details={},
        )

    candidates: list[str] = [plugin] if "." in plugin else [f"thomas.plugins.{plugin}", plugin]

    not_found: list[str] = []
    last_err: Exception | None = None

    for mod_name in candidates:
        try:
            return importlib.import_module(mod_name)
        except ModuleNotFoundError as e:
            last_err = e
            # Only treat as missing if the missing module *is* the candidate, not a dependency.
            if getattr(e, "name", None) == mod_name:
                not_found.append(mod_name)
                continue
            raise PluginConfigSchemaValidatorError(
                code="PLUGIN_IMPORT_FAILED",
                message="Plugin module import failed due to a missing dependency.",
                details={"plugin": plugin, "module": mod_name, "error": str(e)},
            ) from e
        except Exception as e:
            last_err = e
            raise PluginConfigSchemaValidatorError(
                code="PLUGIN_IMPORT_FAILED",
                message="Plugin module import failed.",
                details={"plugin": plugin, "module": mod_name, "error": str(e)},
            ) from e

    raise PluginConfigSchemaValidatorError(
        code="PLUGIN_NOT_FOUND",
        message="Plugin module could not be imported.",
        details={"plugin": plugin, "candidates": candidates, "error": str(last_err) if last_err else None},
    )


def resolve_schema(
    *,
    plugin: str | None = None,
    schema: Mapping[str, Any] | None = None,
    schema_path: Path | None = None,
) -> tuple[Mapping[str, Any], str]:
    """Resolve a JSON schema from explicit input or plugin discovery."""
    if schema is not None and schema_path is not None:
        raise PluginConfigSchemaValidatorError(
            code="INVALID_REQUEST",
            message="Provide either `schema` or `schema_path`, not both.",
            details={},
        )

    if schema is not None:
        return _coerce_schema(schema, source="inline"), "inline"

    if schema_path is not None:
        raw = _read_structured_file(schema_path, kind="schema")
        return _coerce_schema(raw, source=str(schema_path)), str(schema_path)

    if plugin is None:
        raise PluginConfigSchemaValidatorError(
            code="SCHEMA_NOT_PROVIDED",
            message="No schema provided and no plugin specified for discovery.",
            details={},
        )

    discovered, source = _try_resolve_schema_via_registry(plugin)
    if discovered is not None and source is not None:
        return _coerce_schema(discovered, source=source), source

    mod = _import_plugin_module(plugin)
    discovered, source = _extract_schema_from_module(mod)
    if discovered is None or source is None:
        raise PluginConfigSchemaValidatorError(
            code="SCHEMA_NOT_FOUND",
            message="No configuration schema found for plugin.",
            details={"plugin": plugin, "module": getattr(mod, "__name__", None)},
        )
    return _coerce_schema(discovered, source=source), source


# ----------------------------- Validation core ------------------------------


def validate_plugin_config(request: PluginConfigValidationRequest) -> PluginConfigValidationResult:
    """Validate a plugin configuration against its JSON Schema.

    Returns `PluginConfigValidationResult` with `valid=False` for schema mismatches.

    Raises `PluginConfigSchemaValidatorError` for fatal problems (missing input,
    missing schema, parse errors, import errors, unavailable dependencies, etc.).
    """
    if request.config is not None and request.config_path is not None:
        raise PluginConfigSchemaValidatorError(
            code="INVALID_REQUEST",
            message="Provide either `config` or `config_path`, not both.",
            details={},
        )

    if request.config is None and request.config_path is None:
        raise PluginConfigSchemaValidatorError(
            code="MISSING_CONFIG",
            message="No configuration provided.",
            details={},
        )

    config = request.config
    if request.config_path is not None:
        config = _read_structured_file(request.config_path, kind="config")

    schema, schema_source = resolve_schema(
        plugin=request.plugin,
        schema=request.schema,
        schema_path=request.schema_path,
    )

    try:
        from jsonschema import validators
    except Exception as e:  # pragma: no cover
        raise PluginConfigSchemaValidatorError(
            code="VALIDATOR_UNAVAILABLE",
            message="jsonschema is required for schema validation but is unavailable.",
            details={"error": str(e)},
        ) from e

    try:
        validator_cls = validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator = validator_cls(schema)
    except PluginConfigSchemaValidatorError:
        raise
    except Exception as e:
        raise PluginConfigSchemaValidatorError(
            code="SCHEMA_INVALID",
            message="Schema failed validator checks.",
            details={"schema_source": schema_source, "error": str(e)},
        ) from e

    issues: list[PluginConfigValidationIssue] = []
    try:
        for err in validator.iter_errors(config):
            issues.append(
                PluginConfigValidationIssue(
                    location=_json_pointer(getattr(err, "absolute_path", ())),
                    message=err.message,
                    validator=getattr(err, "validator", None),
                )
            )
    except Exception as e:
        raise PluginConfigSchemaValidatorError(
            code="VALIDATION_FAILED",
            message="Validator raised an unexpected error.",
            details={"schema_source": schema_source, "error": str(e)},
        ) from e

    issues.sort(key=lambda i: (i.location, i.message, i.validator or ""))
    return PluginConfigValidationResult(
        plugin=request.plugin,
        valid=len(issues) == 0,
        issues=issues,
        schema_source=schema_source,
    )


# ----------------------------- Rendering helpers ----------------------------


def format_result_human(result: PluginConfigValidationResult) -> str:
    """Human-friendly rendering suitable for CLI output."""
    plugin = result.plugin or "(unspecified plugin)"
    if result.valid:
        return f"Config for {plugin} is valid."
    lines = [f"Config for {plugin} is invalid:"]
    for issue in result.issues:
        lines.append(f"- {issue.location}: {issue.message}")
    return "\n".join(lines)


def json_envelope_ok(result: PluginConfigValidationResult) -> dict[str, Any]:
    return {"ok": True, "result": result.to_dict()}


def json_envelope_error(err: PluginConfigSchemaValidatorError) -> dict[str, Any]:
    return {"ok": False, "error": err.to_dict()}
