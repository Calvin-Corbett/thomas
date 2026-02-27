"""Browser command registry scaffold.

This module provides a Thomas-native registry for browser-adjacent commands.

Design goals
- Small, dependency-free core.
- Clear input/output contracts.
- Deterministic, machine-readable errors.
- A registry description surface suitable for automation.

This is a *scaffold*: it purposely supports only a small subset of JSON Schema and
performs best-effort discovery from :mod:`thomas.tools.browser` when available.
"""

from __future__ import annotations

import inspect
import json
import types
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, get_args, get_origin

JsonValue = Any
JsonDict = dict[str, JsonValue]


class BrowserRegistryErrorCode(str, Enum):
    """Stable error codes for registry operations."""

    INVALID_INPUT = "invalid_input"
    COMMAND_NOT_FOUND = "command_not_found"
    MISSING_CONFIG = "missing_config"
    EXTERNAL_FAILURE = "external_failure"


@dataclass(frozen=True, slots=True)
class BrowserRegistryErrorPayload:
    """A deterministic, machine-readable error payload."""

    code: BrowserRegistryErrorCode
    message: str
    details: JsonDict | None = None

    def to_dict(self) -> JsonDict:
        out: JsonDict = {"code": self.code.value, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


class BrowserRegistryError(Exception):
    """Base class for deterministic registry exceptions."""

    def __init__(
        self,
        code: BrowserRegistryErrorCode,
        message: str,
        *,
        details: JsonDict | None = None,
    ) -> None:
        super().__init__(message)
        self._payload = BrowserRegistryErrorPayload(code=code, message=message, details=details)

    @property
    def payload(self) -> BrowserRegistryErrorPayload:
        return self._payload


class InvalidInputError(BrowserRegistryError):
    def __init__(self, message: str, *, details: JsonDict | None = None) -> None:
        super().__init__(BrowserRegistryErrorCode.INVALID_INPUT, message, details=details)


class CommandNotFoundError(BrowserRegistryError):
    def __init__(self, command_name: str) -> None:
        super().__init__(
            BrowserRegistryErrorCode.COMMAND_NOT_FOUND,
            f"Unknown browser command: {command_name}",
            details={"command": command_name},
        )


class MissingConfigError(BrowserRegistryError):
    def __init__(
        self, message: str = "Missing required browser configuration", *, details: JsonDict | None = None
    ) -> None:
        super().__init__(BrowserRegistryErrorCode.MISSING_CONFIG, message, details=details)


class ExternalFailureError(BrowserRegistryError):
    def __init__(self, message: str = "External browser failure", *, details: JsonDict | None = None) -> None:
        super().__init__(BrowserRegistryErrorCode.EXTERNAL_FAILURE, message, details=details)


@dataclass(frozen=True, slots=True)
class BrowserCommandDefinition:
    """Command metadata plus input/output contracts."""

    name: str
    description: str
    input_schema: JsonDict
    output_schema: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True, slots=True)
class BrowserCommandRequest:
    """Execution request contract."""

    name: str
    arguments: JsonDict


@dataclass(frozen=True, slots=True)
class BrowserCommandContext:
    """Execution context for a command.

    This is intentionally generic so it can wrap whatever browser implementation
    Thomas uses (Playwright, Selenium, a remote driver, etc.).
    """

    browser: Any | None = None
    config: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BrowserCommandResult:
    """Execution result contract."""

    ok: bool
    name: str
    data: JsonDict | None = None
    error: BrowserRegistryErrorPayload | None = None

    def to_dict(self) -> JsonDict:
        out: JsonDict = {"ok": self.ok, "name": self.name}
        if self.ok:
            out["data"] = self.data or {}
        else:
            out["error"] = (
                self.error
                or BrowserRegistryErrorPayload(
                    code=BrowserRegistryErrorCode.EXTERNAL_FAILURE,
                    message="Unknown error",
                )
            ).to_dict()
        return out


BrowserCommandHandler = Callable[[BrowserCommandRequest, BrowserCommandContext], BrowserCommandResult | JsonDict]


@dataclass(frozen=True, slots=True)
class BrowserCommandSpec:
    """A definition + handler pair (useful for discovery)."""

    definition: BrowserCommandDefinition
    handler: BrowserCommandHandler


def _ensure_object(value: Any, *, field: str) -> JsonDict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise InvalidInputError(
        f"{field} must be an object",
        details={"field": field, "actual_type": type(value).__name__},
    )


def _validate_schema(schema: Mapping[str, Any], data: Mapping[str, Any]) -> None:
    """Minimal validation against a small subset of JSON Schema.

    Supported:
    - type: "object"
    - properties: {k: {type: ...}}
    - required: [k]
    """

    if not schema:
        return

    schema_type = schema.get("type")
    if schema_type and schema_type != "object":
        raise InvalidInputError(
            "Only object schemas are supported by the scaffold",
            details={"schema_type": schema_type},
        )

    required = schema.get("required") or []
    if not isinstance(required, list):
        raise InvalidInputError("Schema 'required' must be a list")

    missing = [k for k in required if k not in data]
    if missing:
        raise InvalidInputError("Missing required fields", details={"missing": missing})

    props = schema.get("properties") or {}
    if props and not isinstance(props, dict):
        raise InvalidInputError("Schema 'properties' must be an object")

    for key, prop_schema in props.items():
        if key not in data:
            continue
        if not isinstance(prop_schema, dict):
            continue
        expected = prop_schema.get("type")
        if expected is None:
            continue

        value = data[key]
        if expected == "string" and not isinstance(value, str):
            raise InvalidInputError(
                f"Field '{key}' must be a string",
                details={"field": key, "expected": expected, "actual": type(value).__name__},
            )
        if expected == "boolean" and not isinstance(value, bool):
            raise InvalidInputError(
                f"Field '{key}' must be a boolean",
                details={"field": key, "expected": expected, "actual": type(value).__name__},
            )
        if (
            expected == "number"
            and not isinstance(value, (int, float))
            or (expected == "number" and isinstance(value, bool))
        ):
            raise InvalidInputError(
                f"Field '{key}' must be a number",
                details={"field": key, "expected": expected, "actual": type(value).__name__},
            )
        if expected == "integer" and not isinstance(value, int) or (expected == "integer" and isinstance(value, bool)):
            raise InvalidInputError(
                f"Field '{key}' must be an integer",
                details={"field": key, "expected": expected, "actual": type(value).__name__},
            )
        if expected == "object" and not isinstance(value, dict):
            raise InvalidInputError(
                f"Field '{key}' must be an object",
                details={"field": key, "expected": expected, "actual": type(value).__name__},
            )
        if expected == "array" and not isinstance(value, list):
            raise InvalidInputError(
                f"Field '{key}' must be an array",
                details={"field": key, "expected": expected, "actual": type(value).__name__},
            )


class BrowserCommandRegistry:
    """A small registry for describing and executing browser commands."""

    def __init__(self, *, name: str = "thomas.browser", version: int = 1) -> None:
        self._registry_name = name
        self._version = version
        self._definitions: dict[str, BrowserCommandDefinition] = {}
        self._handlers: dict[str, BrowserCommandHandler] = {}

    @property
    def name(self) -> str:
        return self._registry_name

    @property
    def version(self) -> int:
        return self._version

    def register(self, definition: BrowserCommandDefinition, handler: BrowserCommandHandler) -> None:
        if not isinstance(definition, BrowserCommandDefinition):
            raise InvalidInputError("definition must be a BrowserCommandDefinition")
        if not definition.name or not isinstance(definition.name, str):
            raise InvalidInputError("Command name must be a non-empty string")
        if definition.name in self._definitions:
            raise InvalidInputError(
                f"Command already registered: {definition.name}",
                details={"command": definition.name},
            )
        if not callable(handler):
            raise InvalidInputError("handler must be callable")

        self._definitions[definition.name] = BrowserCommandDefinition(
            name=definition.name,
            description=definition.description,
            input_schema=dict(definition.input_schema),
            output_schema=dict(definition.output_schema),
        )
        self._handlers[definition.name] = handler

    def get_definition(self, command_name: str) -> BrowserCommandDefinition:
        try:
            return self._definitions[command_name]
        except KeyError as exc:
            raise CommandNotFoundError(command_name) from exc

    def list_definitions(self) -> list[BrowserCommandDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions.keys())]

    def to_registry_dict(self) -> JsonDict:
        return {
            "name": self._registry_name,
            "version": self._version,
            "commands": [d.to_dict() for d in self.list_definitions()],
        }

    def to_json(self, *, indent: int | None = 2, sort_keys: bool = True) -> str:
        return json.dumps(self.to_registry_dict(), indent=indent, sort_keys=sort_keys)

    def output_schema(self) -> JsonDict:
        """JSON schema describing the registry output itself."""

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name", "version", "commands"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "integer"},
                "commands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "description", "input_schema", "output_schema"],
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "input_schema": {"type": "object"},
                            "output_schema": {"type": "object"},
                        },
                    },
                },
            },
        }

    def execute(
        self,
        request: BrowserCommandRequest | Mapping[str, Any],
        *,
        context: BrowserCommandContext | None = None,
    ) -> BrowserCommandResult:
        """Execute a registered command and return a deterministic result.

        This method never raises :class:`BrowserRegistryError`; failures are
        returned as ``BrowserCommandResult(ok=False, error=...)``.
        """
        name = "<invalid>"
        try:
            if isinstance(request, BrowserCommandRequest):
                name = request.name
            elif isinstance(request, Mapping):
                maybe_name = request.get("name")
                if isinstance(maybe_name, str) and maybe_name:
                    name = maybe_name

            return self._execute_strict(request, context=context)
        except BrowserRegistryError as exc:
            return BrowserCommandResult(ok=False, name=name, error=exc.payload)
        except Exception as exc:  # pragma: no cover
            return BrowserCommandResult(
                ok=False,
                name=name,
                error=BrowserRegistryErrorPayload(
                    code=BrowserRegistryErrorCode.EXTERNAL_FAILURE,
                    message="Unexpected failure",
                    details={"exception": type(exc).__name__},
                ),
            )

    def execute_strict(
        self,
        request: BrowserCommandRequest | Mapping[str, Any],
        *,
        context: BrowserCommandContext | None = None,
    ) -> BrowserCommandResult:
        """Execute and raise deterministic exceptions on failure."""
        return self._execute_strict(request, context=context)

    def _execute_strict(
        self,
        request: BrowserCommandRequest | Mapping[str, Any],
        *,
        context: BrowserCommandContext | None = None,
    ) -> BrowserCommandResult:
        ctx = context or BrowserCommandContext()

        if isinstance(request, BrowserCommandRequest):
            req = request
        elif isinstance(request, Mapping):
            name = request.get("name")
            if not isinstance(name, str) or not name:
                raise InvalidInputError("request.name must be a non-empty string")
            args = _ensure_object(request.get("arguments"), field="request.arguments")
            req = BrowserCommandRequest(name=name, arguments=args)
        else:
            raise InvalidInputError("request must be a BrowserCommandRequest or mapping")

        if req.name not in self._handlers:
            raise CommandNotFoundError(req.name)

        definition = self._definitions[req.name]
        _validate_schema(definition.input_schema, req.arguments)

        handler = self._handlers[req.name]
        try:
            raw = handler(req, ctx)
        except BrowserRegistryError:
            raise
        except Exception as exc:
            raise ExternalFailureError(
                "Command handler raised an exception",
                details={"command": req.name, "exception": type(exc).__name__},
            ) from exc

        if isinstance(raw, BrowserCommandResult):
            if raw.ok is False and raw.error is None:
                return BrowserCommandResult(
                    ok=False,
                    name=req.name,
                    data=raw.data,
                    error=BrowserRegistryErrorPayload(
                        code=BrowserRegistryErrorCode.EXTERNAL_FAILURE,
                        message="Command returned ok=false without an error payload",
                    ),
                )
            return raw

        if isinstance(raw, dict):
            return BrowserCommandResult(ok=True, name=req.name, data=raw)

        raise InvalidInputError(
            "Handler must return BrowserCommandResult or dict",
            details={"command": req.name, "return_type": type(raw).__name__},
        )


def build_browser_command_registry_scaffold() -> BrowserCommandRegistry:
    """Create a scaffold registry with a small set of safe, internal commands."""
    registry = BrowserCommandRegistry(name="thomas.browser", version=1)

    registry.register(
        BrowserCommandDefinition(
            name="registry.list",
            description="List available browser commands.",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={
                "type": "object",
                "required": ["commands"],
                "properties": {"commands": {"type": "array", "items": {"type": "string"}}},
            },
        ),
        handler=lambda req, ctx: {"commands": [d.name for d in registry.list_definitions()]},
    )

    registry.register(
        BrowserCommandDefinition(
            name="registry.describe",
            description="Return a machine-readable description of the browser command registry.",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema=registry.output_schema(),
        ),
        handler=lambda req, ctx: registry.to_registry_dict(),
    )

    registry.register(
        BrowserCommandDefinition(
            name="session.ping",
            description="Lightweight health check for the browser command layer.",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}},
        ),
        handler=lambda req, ctx: {"status": "ok"},
    )

    for spec in discover_browser_command_specs():
        try:
            registry.register(spec.definition, spec.handler)
        except InvalidInputError:
            # Duplicate or invalid discovered command; skip so the scaffold remains stable.
            continue

    return registry


def _python_type_to_json_schema(py_type: Any) -> JsonDict:
    """Best-effort conversion of a Python type annotation into a JSON schema."""
    if py_type is Any:
        return {}

    origin = get_origin(py_type)
    args = get_args(py_type)

    # PEP604 (T | None) produces types.UnionType.
    if origin in (types.UnionType, getattr(__import__("typing"), "Union", object())) or str(origin) == "typing.Union":
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        # Optional[T]
        if len(non_none) == 1:
            return _python_type_to_json_schema(non_none[0])
        return {}

    if py_type is type(None):  # noqa: E721
        return {"type": "null"}

    if py_type is str:
        return {"type": "string"}
    if py_type is bool:
        return {"type": "boolean"}
    if py_type is int:
        return {"type": "integer"}
    if py_type is float:
        return {"type": "number"}
    if py_type in (dict, Mapping, MutableMapping):
        return {"type": "object"}
    if py_type in (list, Sequence):
        return {"type": "array"}

    if origin in (list, Sequence, tuple):
        item_schema = _python_type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}

    if origin in (dict, Mapping, MutableMapping):
        return {"type": "object"}

    # Unknown / custom classes -> treat as object.
    if origin is None and isinstance(py_type, type):
        return {"type": "object"}

    return {}


def _schema_from_callable(fn: Callable[..., Any]) -> JsonDict:
    sig = inspect.signature(fn)
    properties: JsonDict = {}
    required: list[str] = []

    # These names are conventionally provided by the execution environment rather
    # than by the user payload. They should not appear as required input fields.
    injected_param_names = {
        "ctx",
        "context",
        "request",
        "req",
        "arguments",
        "args",
        "payload",
        "browser",
        "driver",
        "page",
        "session",
        "config",
    }

    for param in sig.parameters.values():
        if param.name in {"self", "cls"}:
            continue
        if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        if param.name in injected_param_names:
            continue

        ann = param.annotation if param.annotation is not inspect._empty else Any
        properties[param.name] = _python_type_to_json_schema(ann)
        if param.default is inspect._empty:
            required.append(param.name)

    return {"type": "object", "properties": properties, "required": required}


def _callable_description(fn: Callable[..., Any]) -> str:
    doc = (inspect.getdoc(fn) or "").strip()
    return doc


def _make_callable_handler(fn: Callable[..., Any], *, command_name: str) -> BrowserCommandHandler:
    """Wrap a discovered callable with context injection and deterministic errors."""
    sig = inspect.signature(fn)

    def _handler(req: BrowserCommandRequest, ctx: BrowserCommandContext) -> BrowserCommandResult | JsonDict:
        kwargs: dict[str, Any] = {}
        for param in sig.parameters.values():
            if param.name in {"self", "cls"}:
                continue
            if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
                continue

            if param.name in req.arguments:
                kwargs[param.name] = req.arguments[param.name]
                continue

            # Context injection by conventional names.
            if param.name in {"ctx", "context"}:
                kwargs[param.name] = ctx
                continue
            if param.name in {"request", "req"}:
                kwargs[param.name] = req
                continue
            if param.name in {"arguments", "args", "payload"}:
                kwargs[param.name] = req.arguments
                continue

            if param.name in {"browser", "driver", "page", "session"}:
                if ctx.browser is None and param.default is inspect._empty:
                    raise MissingConfigError(
                        "No browser instance provided in command context",
                        details={"command": command_name, "param": param.name},
                    )
                if ctx.browser is not None:
                    kwargs[param.name] = ctx.browser
                continue

            if param.name == "config":
                if ctx.config is None and param.default is inspect._empty:
                    raise MissingConfigError(
                        "No config provided in command context",
                        details={"command": command_name, "param": param.name},
                    )
                if ctx.config is not None:
                    kwargs[param.name] = ctx.config
                continue

            if param.default is not inspect._empty:
                # Let Python fill defaults.
                continue

            raise InvalidInputError(
                "Missing required argument",
                details={"command": command_name, "arg": param.name},
            )

        try:
            result = fn(**kwargs)
        except TypeError:
            # Some APIs accept a single positional payload.
            result = fn(req.arguments)
        except BrowserRegistryError:
            raise
        except Exception as exc:
            raise ExternalFailureError(
                "Browser command execution failed",
                details={"command": command_name, "exception": type(exc).__name__},
            ) from exc

        if isinstance(result, BrowserCommandResult):
            return result
        if isinstance(result, dict):
            return result
        if result is None:
            return {}
        return {"result": result}

    return _handler


def _coerce_command_definition_from_object(
    *,
    name: str,
    obj: Any,
    fallback_callable: Callable[..., Any] | None = None,
) -> BrowserCommandDefinition:
    # Prefer explicit schema attributes if they exist.
    description = ""
    if hasattr(obj, "description"):
        try:
            description = str(obj.description or "")
        except (AttributeError, TypeError):
            description = ""
    if not description and hasattr(obj, "help"):
        try:
            description = str(obj.help or "")
        except (AttributeError, TypeError):
            description = ""
    if not description and callable(fallback_callable):
        description = _callable_description(fallback_callable)

    input_schema: JsonDict = {}
    for key in ("input_schema", "args_schema", "request_schema", "schema"):
        if hasattr(obj, key):
            maybe = getattr(obj, key)
            if isinstance(maybe, Mapping):
                input_schema = dict(maybe)
                break
    if not input_schema and callable(fallback_callable):
        input_schema = _schema_from_callable(fallback_callable)

    output_schema: JsonDict = {}
    for key in ("output_schema", "response_schema", "result_schema"):
        if hasattr(obj, key):
            maybe = getattr(obj, key)
            if isinstance(maybe, Mapping):
                output_schema = dict(maybe)
                break
    if not output_schema:
        output_schema = {"type": "object"}

    return BrowserCommandDefinition(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
    )


def _coerce_command_spec(name_hint: str | None, obj: Any) -> BrowserCommandSpec | None:
    # Already a spec
    if isinstance(obj, BrowserCommandSpec):
        return obj

    # (definition, handler) pair
    if (
        isinstance(obj, (tuple, list))
        and len(obj) == 2
        and isinstance(obj[0], BrowserCommandDefinition)
        and callable(obj[1])
    ):
        return BrowserCommandSpec(definition=obj[0], handler=obj[1])

    # dict-shaped spec
    if isinstance(obj, Mapping):
        if (
            "definition" in obj
            and "handler" in obj
            and isinstance(obj["definition"], BrowserCommandDefinition)
            and callable(obj["handler"])
        ):
            return BrowserCommandSpec(definition=obj["definition"], handler=obj["handler"])  # type: ignore[index]
        name = obj.get("name") if isinstance(obj.get("name"), str) else name_hint
        handler = obj.get("handler") or obj.get("func") or obj.get("callable")
        if isinstance(name, str) and name and callable(handler):
            definition = _coerce_command_definition_from_object(name=name, obj=obj, fallback_callable=handler)
            return BrowserCommandSpec(definition=definition, handler=_make_callable_handler(handler, command_name=name))  # type: ignore[arg-type]

    # object with attributes
    if hasattr(obj, "definition") and hasattr(obj, "handler"):
        try:
            definition = obj.definition
            handler = obj.handler
            if isinstance(definition, BrowserCommandDefinition) and callable(handler):
                return BrowserCommandSpec(definition=definition, handler=handler)
        except (AttributeError, TypeError):
            pass

    # route-like object: name + handler/func
    name = None
    if hasattr(obj, "name"):
        try:
            name = obj.name
        except (AttributeError, TypeError):
            name = None
    if not isinstance(name, str) or not name:
        name = name_hint

    handler = None
    for key in ("handler", "func", "callable", "run", "execute"):
        if hasattr(obj, key):
            try:
                handler = getattr(obj, key)
            except (AttributeError, TypeError):
                handler = None
            if callable(handler):
                break
            handler = None

    if isinstance(name, str) and name and callable(handler):
        definition = _coerce_command_definition_from_object(name=name, obj=obj, fallback_callable=handler)
        return BrowserCommandSpec(definition=definition, handler=_make_callable_handler(handler, command_name=name))

    # plain callable
    if callable(obj):
        name = name_hint or getattr(obj, "__name__", None)
        if not isinstance(name, str) or not name:
            return None
        definition = BrowserCommandDefinition(
            name=name,
            description=_callable_description(obj),
            input_schema=_schema_from_callable(obj),
            output_schema={"type": "object"},
        )
        return BrowserCommandSpec(definition=definition, handler=_make_callable_handler(obj, command_name=name))

    return None


def _extract_specs(container: Any) -> list[BrowserCommandSpec]:
    specs: list[BrowserCommandSpec] = []

    if isinstance(container, Mapping):
        for name, value in container.items():
            if not isinstance(name, str) or not name:
                continue
            spec = _coerce_command_spec(name, value)
            if spec is not None:
                specs.append(spec)
        return specs

    if isinstance(container, Sequence) and not isinstance(container, (str, bytes, bytearray)):
        for item in container:
            spec = _coerce_command_spec(None, item)
            if spec is not None:
                specs.append(spec)
        return specs

    return specs


def discover_browser_command_specs() -> list[BrowserCommandSpec]:
    """Discover command specs from :mod:`thomas.tools.browser`.

    Discovery is *best-effort* and must never crash Thomas when optional browser
    dependencies are missing.
    """
    try:
        from thomas.tools import browser as browser_tool_mod  # type: ignore
    except (ImportError, ModuleNotFoundError):
        return []

    candidate_attr_names = [
        "BROWSER_COMMANDS",
        "BROWSER_COMMAND_DEFINITIONS",
        "COMMANDS",
        "COMMAND_DEFINITIONS",
        "ROUTES",
        "ACTIONS",
        "COMMAND_REGISTRY",
    ]

    found: list[BrowserCommandSpec] = []
    for attr_name in candidate_attr_names:
        if not hasattr(browser_tool_mod, attr_name):
            continue
        try:
            extracted = _extract_specs(getattr(browser_tool_mod, attr_name))
        except (AttributeError, TypeError, ValueError):
            continue
        found.extend(extracted)

    # If nothing explicit was found, fall back to module-level callables defined in that module.
    if not found:
        for name, value in vars(browser_tool_mod).items():
            if name.startswith("_"):
                continue
            if not callable(value):
                continue
            if getattr(value, "__module__", None) != getattr(browser_tool_mod, "__name__", None):
                continue
            spec = _coerce_command_spec(name, value)
            if spec is not None:
                found.append(spec)

    # Deduplicate by command name, keeping first occurrence for determinism.
    out: list[BrowserCommandSpec] = []
    seen: set[str] = set()
    for spec in found:
        if spec.definition.name in seen:
            continue
        seen.add(spec.definition.name)
        out.append(spec)

    # Stable ordering by name.
    out.sort(key=lambda s: s.definition.name)
    return out


def discover_browser_command_definitions() -> list[BrowserCommandDefinition]:
    """Compatibility helper: return only definitions."""
    return [s.definition for s in discover_browser_command_specs()]
