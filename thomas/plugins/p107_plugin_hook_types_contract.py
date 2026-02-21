from __future__ import annotations

import inspect
import importlib
import json
import os
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class HookTypesContractErrorCode(str, Enum):
    """Machine-readable error codes for hook contract generation."""

    INVALID_INPUT = "invalid_input"
    MISSING_CONFIG = "missing_config"
    EXTERNAL_FAILURE = "external_failure"
    NOT_FOUND = "not_found"


class HookTypesContractError(Exception):
    """Deterministic error raised by hook contract generation utilities."""

    def __init__(
        self,
        code: HookTypesContractErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": str(self), "details": self.details}


@dataclass
class HookTypesContractRequest:
    """Input contract for producing the plugin hook types contract."""

    plugin_base: str | None = None
    include_inherited: bool = True
    include_private: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "HookTypesContractRequest":
        allowed = {"plugin_base", "include_inherited", "include_private"}
        unknown = sorted(k for k in data.keys() if k not in allowed)
        if unknown:
            raise HookTypesContractError(
                HookTypesContractErrorCode.INVALID_INPUT,
                "Invalid request payload (unknown keys).",
                details={"unknown_keys": unknown},
            )

        plugin_base = data.get("plugin_base", None)
        if plugin_base is not None and not isinstance(plugin_base, str):
            raise HookTypesContractError(
                HookTypesContractErrorCode.INVALID_INPUT,
                "plugin_base must be a string or null.",
                details={"plugin_base_type": type(plugin_base).__name__},
            )

        include_inherited = data.get("include_inherited", True)
        if not isinstance(include_inherited, bool):
            raise HookTypesContractError(
                HookTypesContractErrorCode.INVALID_INPUT,
                "include_inherited must be a boolean.",
                details={"include_inherited_type": type(include_inherited).__name__},
            )

        include_private = data.get("include_private", False)
        if not isinstance(include_private, bool):
            raise HookTypesContractError(
                HookTypesContractErrorCode.INVALID_INPUT,
                "include_private must be a boolean.",
                details={"include_private_type": type(include_private).__name__},
            )

        return cls(
            plugin_base=plugin_base,
            include_inherited=include_inherited,
            include_private=include_private,
        )


@dataclass
class HookParameterContract:
    name: str
    annotation: str = "Any"
    kind: str = "positional_or_keyword"
    required: bool = True
    has_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "annotation": self.annotation,
            "kind": self.kind,
            "required": self.required,
            "has_default": self.has_default,
        }


@dataclass
class HookSignatureContract:
    name: str
    parameters: list[HookParameterContract] = field(default_factory=list)
    return_annotation: str = "Any"
    is_async: bool = False
    doc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": [p.to_dict() for p in self.parameters],
            "return_annotation": self.return_annotation,
            "is_async": self.is_async,
            "doc": self.doc,
        }


@dataclass
class HookTypesContractResponse:
    """Output contract describing the plugin hook surface area."""

    contract_version: str = "1"
    plugin_base: str = ""
    hooks: list[HookSignatureContract] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "plugin_base": self.plugin_base,
            "hooks": [h.to_dict() for h in self.hooks],
            "warnings": list(self.warnings),
        }


def contract_json_schema() -> dict[str, Any]:
    """Return a JSON Schema describing HookTypesContractResponse."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "HookTypesContractResponse",
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_version", "plugin_base", "hooks", "warnings"],
        "properties": {
            "contract_version": {"type": "string"},
            "plugin_base": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "hooks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "parameters", "return_annotation", "is_async", "doc"],
                    "properties": {
                        "name": {"type": "string"},
                        "return_annotation": {"type": "string"},
                        "is_async": {"type": "boolean"},
                        "doc": {"type": ["string", "null"]},
                        "parameters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "name",
                                    "annotation",
                                    "kind",
                                    "required",
                                    "has_default",
                                ],
                                "properties": {
                                    "name": {"type": "string"},
                                    "annotation": {"type": "string"},
                                    "kind": {"type": "string"},
                                    "required": {"type": "boolean"},
                                    "has_default": {"type": "boolean"},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def load_request_from_file(path: str) -> HookTypesContractRequest:
    """Load a request from a JSON or TOML config file.

    Supported schemas:
      - JSON: {"plugin_base": "...", "include_inherited": true, "include_private": false}
      - TOML: same keys at the document root.
    """
    if not isinstance(path, str) or not path.strip():
        raise HookTypesContractError(
            HookTypesContractErrorCode.INVALID_INPUT,
            "Config path must be a non-empty string.",
        )

    if not os.path.exists(path):
        raise HookTypesContractError(
            HookTypesContractErrorCode.MISSING_CONFIG,
            f"Config file not found: {path}",
            details={"path": path},
        )

    try:
        if path.lower().endswith(".toml"):
            try:
                import tomllib  # py311+
            except ModuleNotFoundError as e:
                raise HookTypesContractError(
                    HookTypesContractErrorCode.INVALID_INPUT,
                    "TOML config files require Python 3.11+ (tomllib).",
                    details={"path": path, "error": type(e).__name__},
                ) from e

            with open(path, "rb") as f:
                raw = tomllib.load(f)
        else:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
    except HookTypesContractError:
        raise
    except Exception as e:
        raise HookTypesContractError(
            HookTypesContractErrorCode.INVALID_INPUT,
            f"Failed to parse config file: {path}",
            details={"path": path, "error": type(e).__name__},
        ) from e

    if not isinstance(raw, dict):
        raise HookTypesContractError(
            HookTypesContractErrorCode.INVALID_INPUT,
            "Config file must contain an object at the document root.",
            details={"path": path, "root_type": type(raw).__name__},
        )

    return HookTypesContractRequest.from_mapping(raw)


def build_hook_types_contract(
    request: HookTypesContractRequest | Mapping[str, Any] | None = None,
) -> HookTypesContractResponse:
    """Generate the contract for Thomas plugin hooks."""
    req = _coerce_request(request)

    plugin_base_path, plugin_base_cls = _resolve_plugin_base(req.plugin_base)

    hooks_with_warnings = _collect_hooks(
        plugin_base_cls,
        include_inherited=req.include_inherited,
        include_private=req.include_private,
    )
    hooks, warnings = hooks_with_warnings

    hook_contracts: list[HookSignatureContract] = []
    for hook_name, fn in hooks:
        try:
            hook_contracts.append(_signature_to_contract(hook_name, fn))
        except Exception as e:
            warnings.append(f"Failed to fully introspect hook '{hook_name}': {type(e).__name__}")
            hook_contracts.append(_signature_to_contract(hook_name, fn, best_effort=True))

    hook_contracts.sort(key=lambda h: h.name)
    return HookTypesContractResponse(
        plugin_base=plugin_base_path,
        hooks=hook_contracts,
        warnings=warnings,
    )


def _coerce_request(request: HookTypesContractRequest | Mapping[str, Any] | None) -> HookTypesContractRequest:
    if request is None:
        return HookTypesContractRequest()
    if isinstance(request, HookTypesContractRequest):
        return request
    if isinstance(request, Mapping):
        return HookTypesContractRequest.from_mapping(request)
    raise HookTypesContractError(
        HookTypesContractErrorCode.INVALID_INPUT,
        "Request must be a HookTypesContractRequest, mapping, or None.",
        details={"type": type(request).__name__},
    )


def _resolve_plugin_base(explicit_path: str | None) -> tuple[str, type]:
    if explicit_path:
        obj = _import_object(explicit_path)
        if not isinstance(obj, type):
            raise HookTypesContractError(
                HookTypesContractErrorCode.INVALID_INPUT,
                "plugin_base must point to a class.",
                details={"plugin_base": explicit_path, "resolved_type": type(obj).__name__},
            )
        return explicit_path, obj

    module_name = "thomas.autonomy.plugin"
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        raise HookTypesContractError(
            HookTypesContractErrorCode.MISSING_CONFIG,
            f"Unable to import Thomas plugin interface module '{module_name}'.",
            details={"module": module_name, "error": type(e).__name__},
        ) from e

    preferred_names = (
        "Plugin",
        "BasePlugin",
        "AutonomyPlugin",
        "ThomasPlugin",
        "PluginBase",
    )
    for name in preferred_names:
        cls = getattr(mod, name, None)
        if isinstance(cls, type):
            return f"{module_name}.{name}", cls

    # Last resort: choose a class in the module with "Plugin" in its name.
    pluginish: list[tuple[str, type]] = []
    for name, cls in inspect.getmembers(mod, inspect.isclass):
        if cls.__module__ != mod.__name__:
            continue
        if "plugin" in name.lower():
            pluginish.append((name, cls))
    if pluginish:
        pluginish.sort(key=lambda t: (0 if t[0] == "Plugin" else 1, t[0]))
        picked_name, picked_cls = pluginish[0]
        return f"{module_name}.{picked_name}", picked_cls

    raise HookTypesContractError(
        HookTypesContractErrorCode.NOT_FOUND,
        "Could not locate a plugin base class in Thomas plugin interface module.",
        details={"module": module_name},
    )


def _import_object(dotted_path: str) -> Any:
    """Import an object from a dotted path.

    Supports:
      - module.attr
      - module:attr
      - module:attr.nested
    """
    if not isinstance(dotted_path, str) or not dotted_path.strip():
        raise HookTypesContractError(
            HookTypesContractErrorCode.INVALID_INPUT,
            "Import path must be a non-empty string.",
        )

    module_name: str
    attr_path: str
    if ":" in dotted_path:
        module_name, attr_path = dotted_path.split(":", 1)
    else:
        if "." not in dotted_path:
            raise HookTypesContractError(
                HookTypesContractErrorCode.INVALID_INPUT,
                "Import path must be of the form 'module.attr' or 'module:attr'.",
                details={"path": dotted_path},
            )
        module_name, attr_path = dotted_path.rsplit(".", 1)

    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        raise HookTypesContractError(
            HookTypesContractErrorCode.EXTERNAL_FAILURE,
            f"Failed to import module '{module_name}'.",
            details={"module": module_name, "error": type(e).__name__},
        ) from e

    obj: Any = mod
    for part in attr_path.split("."):
        if not hasattr(obj, part):
            raise HookTypesContractError(
                HookTypesContractErrorCode.NOT_FOUND,
                f"Attribute '{attr_path}' not found in module '{module_name}'.",
                details={"module": module_name, "attribute": attr_path},
            )
        obj = getattr(obj, part)

    return obj


def _collect_hooks(
    plugin_base: type,
    *,
    include_inherited: bool,
    include_private: bool,
) -> tuple[list[tuple[str, Any]], list[str]]:
    warnings: list[str] = []
    hooks: list[tuple[str, Any]] = []

    hook_names = _discover_hook_names(plugin_base)
    if hook_names:
        for name in hook_names:
            if not include_private and name.startswith("_"):
                continue
            if not hasattr(plugin_base, name):
                warnings.append(f"Hook '{name}' is declared but not present on {plugin_base.__name__}.")
                continue
            fn = getattr(plugin_base, name)
            if not callable(fn):
                warnings.append(f"Hook '{name}' exists but is not callable on {plugin_base.__name__}.")
                continue
            hooks.append((name, fn))
        return hooks, warnings

    # Fallback: treat (most) methods on the class as hooks.
    for name, fn in inspect.getmembers(plugin_base, predicate=inspect.isroutine):
        if name.startswith("__"):
            continue
        if not include_private and name.startswith("_"):
            continue
        if not include_inherited and name not in getattr(plugin_base, "__dict__", {}):
            continue
        # Skip obvious non-hook lifecycle helpers.
        if name in {"register", "setup", "teardown", "configure", "config_schema", "validate_config"}:
            continue
        hooks.append((name, fn))

    if not hooks:
        warnings.append(f"No hooks discovered on plugin base '{plugin_base.__name__}'.")
    return hooks, warnings


def _discover_hook_names(plugin_base: type) -> list[str]:
    """Best-effort discovery of hook names from the plugin interface.

    This tries a handful of conventional patterns, but never executes arbitrary user code.
    """

    def _names_from(raw: Any) -> list[str] | None:
        if raw is None:
            return None
        if isinstance(raw, dict) and all(isinstance(k, str) for k in raw.keys()):
            return list(raw.keys())
        if isinstance(raw, (list, tuple, set)) and all(isinstance(x, str) for x in raw):
            return list(raw)
        return None

    attrs = (
        "HOOKS",
        "HOOK_NAMES",
        "PLUGIN_HOOKS",
        "SUPPORTED_HOOKS",
        "SUPPORTED_HOOK_NAMES",
        "__hooks__",
    )

    # Class-level declarations.
    for attr in attrs:
        maybe = _names_from(getattr(plugin_base, attr, None))
        if maybe:
            return sorted(set(maybe))

    # Module-level declarations.
    mod = inspect.getmodule(plugin_base)
    if mod is not None:
        for attr in attrs:
            maybe = _names_from(getattr(mod, attr, None))
            if maybe:
                return sorted(set(maybe))

        # Enum-based hook declarations.
        for name, enum_cls in inspect.getmembers(mod, inspect.isclass):
            if "hook" not in name.lower():
                continue
            if not issubclass(enum_cls, Enum):
                continue
            names: list[str] = []
            for member in enum_cls:  # type: ignore[assignment]
                if isinstance(member.value, str):
                    names.append(member.value)
                else:
                    names.append(member.name)
            if names:
                return sorted(set(names))

    return []


def _signature_to_contract(name: str, fn: Any, *, best_effort: bool = False) -> HookSignatureContract:
    doc = inspect.getdoc(fn) or None
    if doc:
        doc = doc.strip().splitlines()[0].strip()

    is_async = inspect.iscoroutinefunction(fn)

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        if not best_effort:
            raise
        return HookSignatureContract(name=name, parameters=[], return_annotation="Any", is_async=is_async, doc=doc)

    hints: dict[str, Any] = {}
    if not best_effort:
        hints = _get_type_hints_safe(fn)
    else:
        hints = getattr(fn, "__annotations__", {}) or {}

    params: list[HookParameterContract] = []
    for p in sig.parameters.values():
        if p.name in {"self", "cls"}:
            continue
        kind = _param_kind_to_str(p.kind)
        required = p.default is inspect._empty and p.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
        has_default = p.default is not inspect._empty
        annotation = hints.get(p.name, p.annotation)
        params.append(
            HookParameterContract(
                name=p.name,
                annotation=_type_to_str(annotation),
                kind=kind,
                required=required,
                has_default=has_default,
            )
        )

    ret_ann = hints.get("return", sig.return_annotation)
    return HookSignatureContract(
        name=name,
        parameters=params,
        return_annotation=_type_to_str(ret_ann),
        is_async=is_async,
        doc=doc,
    )


def _get_type_hints_safe(fn: Any) -> dict[str, Any]:
    try:
        return typing.get_type_hints(fn)  # type: ignore[arg-type]
    except Exception:
        return getattr(fn, "__annotations__", {}) or {}


def _param_kind_to_str(kind: inspect._ParameterKind) -> str:
    mapping = {
        inspect.Parameter.POSITIONAL_ONLY: "positional_only",
        inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional_or_keyword",
        inspect.Parameter.VAR_POSITIONAL: "var_positional",
        inspect.Parameter.KEYWORD_ONLY: "keyword_only",
        inspect.Parameter.VAR_KEYWORD: "var_keyword",
    }
    return mapping.get(kind, str(kind))


def _type_to_str(tp: Any) -> str:
    if tp is inspect._empty:
        return "Any"
    if tp is None:
        return "None"
    if isinstance(tp, str):
        return tp
    if tp is type(None):  # noqa: E721 - explicit is fine here
        return "None"
    if isinstance(tp, type):
        return tp.__name__

    s = str(tp)
    # Normalize typing verbosity.
    return s.replace("typing.", "")
