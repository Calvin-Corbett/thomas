from __future__ import annotations

"""
P077 — Channel provider config schema.

Goal:
- Given a provider name (e.g. "telegram"), return a deterministic JSON Schema
  describing the configuration that provider expects.

Design:
- Provider module resolution uses the Thomas convention:
    thomas.integrations.<provider>
  (with a small normalization for import safety: lowercased, '-' -> '_').

- Schema discovery order (deterministic):
  1) explicit schema dict constant:
        PROVIDER_CONFIG_JSON_SCHEMA / PROVIDER_CONFIG_SCHEMA /
        CHANNEL_PROVIDER_CONFIG_SCHEMA / CONFIG_JSON_SCHEMA / CONFIG_SCHEMA
  2) explicit function returning a dict:
        get_config_schema() / config_schema() / get_provider_config_schema()
  3) inferred from a "config model" type:
        dataclass, TypedDict, Pydantic BaseModel, or annotated class

- Output is JSON-serializable and safe for automation.
"""

import enum
import importlib
import inspect
import json
import re
import types
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields, is_dataclass
from types import ModuleType
from typing import (
    Annotated,
    Any,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

_PROVIDER_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def _provider_to_module_fragment(provider: str) -> str:
    # Python module fragments cannot contain '-'. Accept it in provider names but
    # normalize for imports.
    return provider.strip().lower().replace("-", "_")


def _camel_case(s: str) -> str:
    parts = re.split(r"[_\-]+", s.strip())
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


class ChannelProviderConfigSchemaError(Exception):
    code: str
    provider: str | None
    details: dict[str, Any]

    def __init__(
        self,
        message: str,
        *,
        code: str,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.provider is not None:
            base["provider"] = self.provider
        if self.details:
            # Make best effort to keep this JSON-able.
            try:
                json.dumps(self.details)
                base["details"] = self.details
            except TypeError:
                base["details"] = {"repr": repr(self.details)}
        return base


class InvalidProviderNameError(ChannelProviderConfigSchemaError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            "Provider name must match pattern /^[a-zA-Z][a-zA-Z0-9_-]*$/",
            code="INVALID_PROVIDER_NAME",
            provider=provider,
        )


class ChannelProviderNotFoundError(ChannelProviderConfigSchemaError):
    def __init__(self, provider: str, *, attempted_modules: Sequence[str]) -> None:
        super().__init__(
            "Channel provider module not found",
            code="PROVIDER_NOT_FOUND",
            provider=provider,
            details={"attempted_modules": list(attempted_modules)},
        )


class ChannelProviderImportError(ChannelProviderConfigSchemaError):
    def __init__(self, provider: str, *, module: str, exc: BaseException) -> None:
        super().__init__(
            "Failed to import channel provider module",
            code="PROVIDER_IMPORT_FAILED",
            provider=provider,
            details={
                "module": module,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        )


class ProviderConfigNotDeclaredError(ChannelProviderConfigSchemaError):
    def __init__(self, provider: str, *, module: str) -> None:
        super().__init__(
            "Provider does not declare a config model or schema",
            code="PROVIDER_CONFIG_NOT_DECLARED",
            provider=provider,
            details={"module": module},
        )


class ProviderSchemaInvalidError(ChannelProviderConfigSchemaError):
    def __init__(self, provider: str, *, reason: str, module: str) -> None:
        super().__init__(
            "Provider config schema is invalid",
            code="PROVIDER_SCHEMA_INVALID",
            provider=provider,
            details={"module": module, "reason": reason},
        )


@dataclass(frozen=True)
class ChannelProviderConfigSchema:
    provider: str
    schema: dict[str, Any]
    source_module: str

    def to_json(self) -> dict[str, Any]:
        return {"provider": self.provider, "schema": self.schema, "source_module": self.source_module}


def get_channel_provider_config_schema(provider: str) -> ChannelProviderConfigSchema:
    provider = (provider or "").strip()
    if not provider or not _PROVIDER_RE.match(provider):
        raise InvalidProviderNameError(provider)

    module_fragment = _provider_to_module_fragment(provider)
    attempted = [f"thomas.integrations.{module_fragment}"]

    module: ModuleType | None = None
    imported_from: str | None = None

    for mod_name in attempted:
        try:
            module = importlib.import_module(mod_name)
            imported_from = mod_name
            break
        except ModuleNotFoundError as e:
            # If the missing module is the module we're trying to import, treat as not-found.
            # Otherwise, dependency error inside the provider module.
            if e.name == mod_name:
                continue
            raise ChannelProviderImportError(provider, module=mod_name, exc=e) from e
        except (ImportError, RuntimeError, AttributeError, SyntaxError) as e:  # noqa: BLE001
            raise ChannelProviderImportError(provider, module=mod_name, exc=e) from e

    if module is None or imported_from is None:
        raise ChannelProviderNotFoundError(provider, attempted_modules=attempted)

    try:
        schema = _extract_schema_from_module(module, provider=provider)
    except ChannelProviderConfigSchemaError:
        raise
    except (AttributeError, ValueError, KeyError, TypeError) as e:  # noqa: BLE001
        raise ProviderSchemaInvalidError(provider, module=imported_from, reason=str(e)) from e

    _validate_json_schema(schema, provider=provider, module=imported_from)
    return ChannelProviderConfigSchema(provider=provider.lower(), schema=schema, source_module=imported_from)


def _extract_schema_from_module(module: ModuleType, *, provider: str) -> dict[str, Any]:
    # 1) Explicit schema constant (highest priority).
    for attr in (
        "PROVIDER_CONFIG_JSON_SCHEMA",
        "PROVIDER_CONFIG_SCHEMA",
        "CHANNEL_PROVIDER_CONFIG_SCHEMA",
        "CONFIG_JSON_SCHEMA",
        "CONFIG_SCHEMA",
    ):
        value = getattr(module, attr, None)
        if isinstance(value, dict):
            return _normalize_schema_meta(value, title=f"{_camel_case(provider)}Config")

    # 2) Explicit function that returns a dict schema.
    for attr in ("get_config_schema", "config_schema", "get_provider_config_schema"):
        fn = getattr(module, attr, None)
        if callable(fn):
            try:
                value = fn()
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001
                raise ProviderSchemaInvalidError(
                    provider, module=module.__name__, reason=f"{attr}() raised: {e}"
                ) from e
            if isinstance(value, dict):
                return _normalize_schema_meta(value, title=f"{_camel_case(provider)}Config")
            raise ProviderSchemaInvalidError(provider, module=module.__name__, reason=f"{attr}() did not return a dict")

    # 3) Infer from config model type.
    config_type = _find_config_model_type(module, provider=provider)
    if config_type is None:
        raise ProviderConfigNotDeclaredError(provider, module=module.__name__)

    schema = json_schema_from_type(config_type)
    return _normalize_schema_meta(schema, title=f"{_camel_case(provider)}Config")


def _find_config_model_type(module: ModuleType, *, provider: str) -> type | None:
    provider_cc = _camel_case(provider)

    preferred_names = [
        f"{provider_cc}Config",
        f"{provider_cc}Settings",
        "ProviderConfig",
        "ChannelProviderConfig",
        "Config",
        "Settings",
    ]

    explicit = getattr(module, "CONFIG", None)
    if inspect.isclass(explicit):
        return explicit

    def _looks_like_config_model(cls: type) -> bool:
        if is_dataclass(cls):
            return True
        if _is_typed_dict(cls):
            return True
        if _is_pydantic_model(cls):
            return True
        anns = getattr(cls, "__annotations__", None)
        return isinstance(anns, dict) and len(anns) > 0

    for name in preferred_names:
        obj = getattr(module, name, None)
        if inspect.isclass(obj) and _looks_like_config_model(obj):
            return obj

    # Otherwise, scan for local classes that look like config containers.
    candidates: list[type] = []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ != module.__name__:
            continue
        if cls.__name__.endswith(("Config", "Settings")) and _looks_like_config_model(cls):
            candidates.append(cls)

    if not candidates:
        return None

    # Deterministic selection: alphabetical.
    candidates.sort(key=lambda c: c.__name__)
    return candidates[0]


def _is_typed_dict(cls: type) -> bool:
    return hasattr(cls, "__total__") and isinstance(getattr(cls, "__annotations__", None), dict)


def _is_pydantic_model(cls: type) -> bool:
    try:
        import pydantic  # type: ignore
    except ImportError:
        return False
    BaseModel = getattr(pydantic, "BaseModel", None)
    if BaseModel is None:
        return False
    try:
        return inspect.isclass(cls) and issubclass(cls, BaseModel)
    except (TypeError, AttributeError):
        return False


def json_schema_from_type(config_type: type) -> dict[str, Any]:
    """
    Convert a config *type* into a JSON Schema object.

    Supported:
    - dataclasses.dataclass
    - TypedDict
    - Pydantic BaseModel (v1 or v2)
    - annotated classes (class with __annotations__)
    """
    if is_dataclass(config_type):
        return _json_schema_from_dataclass(config_type)

    if _is_typed_dict(config_type):
        return _json_schema_from_typed_dict(config_type)

    pyd = _try_pydantic_schema(config_type)
    if pyd is not None:
        return pyd

    annotations = get_type_hints(config_type, include_extras=True)
    if not annotations:
        raise ValueError(f"{config_type.__name__} has no usable type annotations")

    defaults = _extract_class_defaults(config_type)
    required = set(annotations.keys())
    return _json_schema_from_annotations(
        annotations, required_keys=required, title=config_type.__name__, defaults=defaults
    )


def _try_pydantic_schema(config_type: type) -> dict[str, Any] | None:
    if not _is_pydantic_model(config_type):
        return None
    # Pydantic v2: model_json_schema. v1: schema()
    if hasattr(config_type, "model_json_schema"):
        return config_type.model_json_schema()  # type: ignore[no-any-return]
    if hasattr(config_type, "schema"):
        return config_type.schema()  # type: ignore[no-any-return]
    return None


def _extract_class_defaults(cls: type) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for name, value in vars(cls).items():
        if name.startswith("_"):
            continue
        # Skip descriptors, callables, classes.
        if inspect.isclass(value) or callable(value):
            continue
        if isinstance(value, (staticmethod, classmethod, property)):
            continue
        defaults[name] = value
    return defaults


def _json_schema_from_dataclass(cls: type) -> dict[str, Any]:
    type_hints = get_type_hints(cls, include_extras=True)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for f in fields(cls):
        name = f.name
        t = type_hints.get(name, Any)
        prop_schema = _type_to_schema(t)

        default_provided = f.default is not MISSING or f.default_factory is not MISSING  # type: ignore[attr-defined]
        if default_provided:
            # Avoid executing arbitrary default factories.
            if f.default is not MISSING:
                dv = f.default
                prop_schema = _with_default(prop_schema, dv)
            else:
                prop_schema = _with_default(prop_schema, "<factory>")
        else:
            if not _is_optional_type(t):
                required.append(name)

        properties[name] = prop_schema

    schema: dict[str, Any] = {
        "type": "object",
        "title": cls.__name__,
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if cls.__doc__:
        schema["description"] = cls.__doc__.strip()
    return schema


def _json_schema_from_typed_dict(td_cls: type) -> dict[str, Any]:
    hints = get_type_hints(td_cls, include_extras=True)
    properties: dict[str, Any] = {k: _type_to_schema(v) for k, v in hints.items()}

    required_keys: set[str] = set()
    optional_keys: set[str] = set()

    req = getattr(td_cls, "__required_keys__", None)
    opt = getattr(td_cls, "__optional_keys__", None)
    if isinstance(req, set):
        required_keys = set(req)
    if isinstance(opt, set):
        optional_keys = set(opt)

    if not required_keys and not optional_keys:
        total = bool(getattr(td_cls, "__total__", True))
        if total:
            required_keys = set(hints.keys())
        else:
            required_keys = set()

    schema: dict[str, Any] = {
        "type": "object",
        "title": td_cls.__name__,
        "properties": properties,
        "additionalProperties": False,
    }
    if required_keys:
        schema["required"] = [k for k in hints.keys() if k in required_keys]
    if td_cls.__doc__:
        schema["description"] = td_cls.__doc__.strip()
    return schema


def _json_schema_from_annotations(
    annotations: Mapping[str, Any],
    *,
    required_keys: set[str],
    title: str,
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = defaults or {}
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, t in annotations.items():
        prop_schema = _type_to_schema(t)
        if name in defaults:
            prop_schema = _with_default(prop_schema, defaults[name])
        else:
            if name in required_keys and not _is_optional_type(t):
                required.append(name)
        properties[name] = prop_schema

    schema: dict[str, Any] = {
        "type": "object",
        "title": title,
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _with_default(prop_schema: dict[str, Any], default_value: Any) -> dict[str, Any]:
    if _is_jsonable(default_value):
        return {**prop_schema, "default": default_value}
    return {**prop_schema, "default": repr(default_value)}


def _type_to_schema(t: Any) -> dict[str, Any]:
    origin = get_origin(t)
    args = get_args(t)

    # typing.Annotated[T, ...] -> unwrap T
    if origin is Annotated:
        inner = args[0] if args else Any
        return _type_to_schema(inner)

    if origin in (Union, types.UnionType):
        # Optional / Union
        has_null = any(a is type(None) for a in args)  # noqa: E721
        non_null = [a for a in args if a is not type(None)]  # noqa: E721
        schemas = [_type_to_schema(a) for a in non_null]
        if has_null:
            schemas.append({"type": "null"})
        if len(schemas) == 1:
            return schemas[0]
        return {"anyOf": schemas}

    if origin is Literal:
        return {"enum": list(args)}

    if t is Any:
        return {}

    if t is str:
        return {"type": "string"}
    if t is int:
        return {"type": "integer"}
    if t is float:
        return {"type": "number"}
    if t is bool:
        return {"type": "boolean"}
    if t is type(None):  # noqa: E721
        return {"type": "null"}

    if origin in (list, set, tuple, Sequence):
        item_t = args[0] if args else Any
        schema: dict[str, Any] = {"type": "array", "items": _type_to_schema(item_t)}
        if origin is set:
            schema["uniqueItems"] = True
        return schema

    if origin in (dict, Mapping):
        # JSON object keys are strings; ignore key type and map values.
        val_t = args[1] if len(args) == 2 else Any
        return {"type": "object", "additionalProperties": _type_to_schema(val_t)}

    if inspect.isclass(t) and issubclass(t, enum.Enum):
        values = []
        for m in t:  # type: ignore[operator]
            values.append(m.value)
        return {"enum": values}

    # Best-effort for other classes: represent as string.
    return {"type": "string"}


def _is_optional_type(t: Any) -> bool:
    origin = get_origin(t)
    if origin in (Union, types.UnionType):
        return any(a is type(None) for a in get_args(t))  # noqa: E721
    return False


def _is_jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except TypeError:
        return False


def _normalize_schema_meta(schema: dict[str, Any], *, title: str) -> dict[str, Any]:
    # Don't clobber provider-defined metadata; only fill gaps.
    out = dict(schema)
    out.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    out.setdefault("title", title)
    return out


def _validate_json_schema(schema: Mapping[str, Any], *, provider: str, module: str) -> None:
    if not isinstance(schema, Mapping):
        raise ProviderSchemaInvalidError(provider, module=module, reason="schema is not a mapping")
    if schema.get("type") != "object":
        raise ProviderSchemaInvalidError(provider, module=module, reason="schema.type must be 'object'")
    props = schema.get("properties")
    if props is None or not isinstance(props, Mapping):
        raise ProviderSchemaInvalidError(provider, module=module, reason="schema.properties must be a mapping")
