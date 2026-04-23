"""Plugin hook runner core.

This module provides a Thomas-native mechanism for running *hooks* implemented
by plugins.

Design goals
- Minimal coupling: the runner can operate on an explicit list of plugin
  instances, on a "plugin manager" object, or from a JSON config file.
- Determinism: invalid input and config errors raise stable, code-based
  exceptions. Per-plugin failures are captured in structured results.
- Automation-friendly: request/response contracts are dataclasses and can be
  serialized to JSON.

"Hook" here simply means: a named callable that a plugin may implement.
The runner supports multiple common patterns:
- plugin.get_hook(name) -> callable
- plugin.hooks[name] -> callable
- plugin.<hook>(...) / plugin.on_<hook>(...) / plugin.hook_<hook>(...)

The runner does not attempt to define a global hook taxonomy; that remains a
Thomas concern.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class HookRunnerError(RuntimeError):
    """Deterministic error type for hook runner failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details: dict[str, JsonValue] = dict(details or {})

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class HookRunRequest:
    """Input contract for running a hook across plugins."""

    hook: str
    payload: Mapping[str, Any] | None = None

    # Optional filters / controls
    plugin_filter: Sequence[str] | None = None
    strict: bool = True
    continue_on_error: bool = True

    # Optional config-based loading
    config_path: str | Path | None = None


@dataclass(frozen=True, slots=True)
class HookError:
    """Machine-readable per-plugin error."""

    code: str
    message: str
    details: dict[str, JsonValue] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class PluginHookResult:
    """Result of running a hook for a single plugin."""

    plugin: str
    status: str  # ok | skipped | error
    output: JsonValue | None = None
    error: HookError | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "plugin": self.plugin,
            "status": self.status,
            "output": self.output,
            "error": None if self.error is None else self.error.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class HookRunResponse:
    """Output contract for a hook run."""

    hook: str
    ok: bool
    results: tuple[PluginHookResult, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "hook": self.hook,
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
        }


def request_json_schema() -> dict[str, Any]:
    """JSON schema for automation clients (request)."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "HookRunRequest",
        "type": "object",
        "required": ["hook"],
        "properties": {
            "hook": {"type": "string", "minLength": 1},
            "payload": {"type": "object"},
            "plugin_filter": {"type": "array", "items": {"type": "string"}},
            "strict": {"type": "boolean", "default": True},
            "continue_on_error": {"type": "boolean", "default": True},
            "config_path": {"type": "string"},
        },
        "additionalProperties": False,
    }


def response_json_schema() -> dict[str, Any]:
    """JSON schema for automation clients (response)."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "HookRunResponse",
        "type": "object",
        "required": ["hook", "ok", "results"],
        "properties": {
            "hook": {"type": "string"},
            "ok": {"type": "boolean"},
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["plugin", "status"],
                    "properties": {
                        "plugin": {"type": "string"},
                        "status": {"type": "string", "enum": ["ok", "skipped", "error"]},
                        "output": {},
                        "error": {
                            "type": ["object", "null"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {"type": "object"},
                            },
                        },
                    },
                },
            },
        },
        "additionalProperties": False,
    }


def run_hook(
    request: HookRunRequest,
    *,
    plugins: Sequence[Any] | None = None,
    plugin_manager: Any | None = None,
) -> HookRunResponse:
    """Run a hook across plugins.

    Args:
        request: HookRunRequest describing which hook to run.
        plugins: Optional explicit sequence of plugin instances.
        plugin_manager: Optional manager/registry object from which plugins can
            be discovered.

    Returns:
        HookRunResponse containing per-plugin results.

    Raises:
        HookRunnerError: For invalid input or missing/invalid config.
    """

    _validate_request(request)

    payload: Mapping[str, Any] = request.payload or {}

    plugin_objs = _resolve_plugins(request, plugins=plugins, plugin_manager=plugin_manager)
    filtered = _filter_plugins(plugin_objs, request.plugin_filter)

    results: list[PluginHookResult] = []
    ok = True

    for plugin in filtered:
        plugin_id = _plugin_id(plugin)
        hook_callable = _get_hook_callable(plugin, request.hook)

        if hook_callable is None:
            if request.strict:
                ok = False
                results.append(
                    PluginHookResult(
                        plugin=plugin_id,
                        status="error",
                        output=None,
                        error=HookError(
                            code="hook_not_found",
                            message=f"Plugin does not implement hook: {request.hook}",
                            details={"hook": request.hook},
                        ),
                    )
                )
                if not request.continue_on_error:
                    break
            else:
                results.append(
                    PluginHookResult(
                        plugin=plugin_id,
                        status="skipped",
                        output=None,
                        error=None,
                    )
                )
            continue

        try:
            output = _call_hook(hook_callable, hook=request.hook, payload=payload)
            results.append(
                PluginHookResult(
                    plugin=plugin_id,
                    status="ok",
                    output=_to_json_value(output),
                    error=None,
                )
            )
        except (
            RuntimeError,
            TypeError,
            AttributeError,
            KeyError,
            ValueError,
            OSError,
        ) as exc:  # REVIEWED: broad catch — isolate plugin hook failures
            ok = False
            results.append(
                PluginHookResult(
                    plugin=plugin_id,
                    status="error",
                    output=None,
                    error=HookError(
                        code="hook_failed",
                        message=str(exc) or exc.__class__.__name__,
                        details={
                            "exception_type": exc.__class__.__name__,
                            "hook": request.hook,
                        },
                    ),
                )
            )
            if not request.continue_on_error:
                break

    return HookRunResponse(hook=request.hook, ok=ok, results=tuple(results))


def _validate_request(request: HookRunRequest) -> None:
    if not isinstance(request.hook, str) or not request.hook.strip():
        raise HookRunnerError(
            "invalid_request",
            "Hook name must be a non-empty string",
            details={"field": "hook"},
        )

    if request.payload is not None and not isinstance(request.payload, Mapping):
        raise HookRunnerError(
            "invalid_request",
            "Payload must be an object/dict if provided",
            details={"field": "payload"},
        )

    if request.plugin_filter is not None:
        if not isinstance(request.plugin_filter, Sequence) or isinstance(
            request.plugin_filter, (str, bytes, bytearray)
        ):
            raise HookRunnerError(
                "invalid_request",
                "plugin_filter must be a list of plugin identifiers",
                details={"field": "plugin_filter"},
            )
        bad = [p for p in request.plugin_filter if not isinstance(p, str) or not p.strip()]
        if bad:
            raise HookRunnerError(
                "invalid_request",
                "plugin_filter entries must be non-empty strings",
                details={"invalid": [str(x) for x in bad]},
            )

    if request.config_path is not None and not isinstance(request.config_path, (str, Path)):
        raise HookRunnerError(
            "invalid_request",
            "config_path must be a string or Path",
            details={"field": "config_path"},
        )


def _filter_plugins(plugins: Sequence[Any], plugin_filter: Sequence[str] | None) -> list[Any]:
    if not plugin_filter:
        return list(plugins)
    wanted = {p for p in plugin_filter if isinstance(p, str)}
    return [p for p in plugins if _plugin_id(p) in wanted]


def _resolve_plugins(
    request: HookRunRequest,
    *,
    plugins: Sequence[Any] | None,
    plugin_manager: Any | None,
) -> list[Any]:
    if plugins is not None:
        return list(plugins)

    if plugin_manager is not None:
        discovered = _plugins_from_manager(plugin_manager)
        if discovered:
            return discovered

    if request.config_path is not None:
        return _plugins_from_config(Path(request.config_path))

    # Best-effort: attempt to locate a runtime plugin manager.
    for module_name in (
        "thomas.autonomy.plugin",
        "thomas.plugins",
        "thomas.plugin",
    ):
        try:
            mod = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError):
            continue

        # Common symbols.
        for attr in ("plugin_manager", "plugins", "manager", "registry"):
            if hasattr(mod, attr):
                discovered = _plugins_from_manager(getattr(mod, attr))
                if discovered:
                    return discovered

        # Common functions.
        for fn_name in ("get_plugin_manager", "get_plugins", "load_plugins"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    discovered = _plugins_from_manager(fn())
                except (RuntimeError, TypeError, AttributeError):  # REVIEWED: broad catch — best-effort discovery
                    continue
                if discovered:
                    return discovered

    raise HookRunnerError(
        "missing_config",
        "No plugins provided and no config/plugin manager available",
        details={"hint": "Pass plugins=..., plugin_manager=..., or set config_path."},
    )


def _plugins_from_manager(manager: Any) -> list[Any]:
    # Manager could already be a sequence of plugins.
    if isinstance(manager, Sequence) and not isinstance(manager, (str, bytes, bytearray)):
        return list(manager)

    # e.g. generator
    if isinstance(manager, Iterable) and not isinstance(manager, (str, bytes, bytearray, Mapping)):
        try:
            return list(manager)
        except TypeError:
            pass

    # Common manager attributes.
    for attr_name in ("plugins", "all_plugins", "registered_plugins"):
        value = getattr(manager, attr_name, None)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return list(value)
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
            try:
                return list(value)
            except (TypeError, ValueError):  # REVIEWED: broad catch — iterable conversion
                continue

    # Common manager methods.
    for method_name in ("get_plugins", "plugins", "all", "list", "iter_plugins"):
        meth = getattr(manager, method_name, None)
        if callable(meth):
            try:
                value = meth()
            except TypeError:
                # Might be property-like.
                value = meth
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return list(value)
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
                try:
                    return list(value)
                except (TypeError, ValueError):  # REVIEWED: broad catch — iterable conversion
                    continue

    return []


def _plugins_from_config(path: Path) -> list[Any]:
    if not path.exists():
        raise HookRunnerError(
            "missing_config",
            "Config file does not exist",
            details={"config_path": str(path)},
        )
    if not path.is_file():
        raise HookRunnerError(
            "invalid_config",
            "Config path is not a file",
            details={"config_path": str(path)},
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HookRunnerError(
            "invalid_config",
            "Failed to read config file",
            details={"config_path": str(path), "reason": exc.__class__.__name__},
        ) from exc

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HookRunnerError(
            "invalid_config",
            "Config file is not valid JSON",
            details={"config_path": str(path), "line": exc.lineno, "col": exc.colno},
        ) from exc

    if not isinstance(doc, Mapping):
        raise HookRunnerError(
            "invalid_config",
            "Config JSON must be an object",
            details={"config_path": str(path)},
        )

    plugin_specs = doc.get("plugins")
    if not isinstance(plugin_specs, Sequence) or isinstance(plugin_specs, (str, bytes, bytearray)):
        raise HookRunnerError(
            "invalid_config",
            "Config must contain a 'plugins' list",
            details={"config_path": str(path)},
        )

    plugins: list[Any] = []
    for idx, spec in enumerate(plugin_specs):
        try:
            plugins.append(_instantiate_plugin_spec(spec))
        except HookRunnerError:
            raise
        except (
            ImportError,
            ModuleNotFoundError,
            AttributeError,
            TypeError,
            RuntimeError,
        ) as exc:  # REVIEWED: broad catch — plugin instantiation
            raise HookRunnerError(
                "invalid_config",
                "Failed to load plugin from config",
                details={
                    "config_path": str(path),
                    "index": idx,
                    "exception_type": exc.__class__.__name__,
                },
            ) from exc

    return plugins


def _instantiate_plugin_spec(spec: Any) -> Any:
    if isinstance(spec, str):
        dotted = spec
        kwargs: dict[str, Any] = {}
    elif isinstance(spec, Mapping):
        path = spec.get("path") or spec.get("factory") or spec.get("plugin")
        if not isinstance(path, str) or not path.strip():
            raise HookRunnerError(
                "invalid_config",
                "Plugin spec objects must include a non-empty 'path' (or 'factory'/'plugin')",
            )
        dotted = path
        init = spec.get("init") or {}
        if init is None:
            init = {}
        if not isinstance(init, Mapping):
            raise HookRunnerError(
                "invalid_config",
                "Plugin spec 'init' must be an object if provided",
            )
        kwargs = dict(init)
    else:
        raise HookRunnerError(
            "invalid_config",
            "Plugin specs must be strings or objects",
        )

    obj = _import_dotted(dotted)

    # Class -> instantiate.
    if isinstance(obj, type):
        return obj(**kwargs)

    # Callable -> call to get instance.
    if callable(obj):
        return obj(**kwargs)

    # Already an instance.
    if kwargs:
        raise HookRunnerError(
            "invalid_config",
            "Plugin spec provided init kwargs but referenced a non-callable object",
            details={"path": dotted},
        )

    return obj


def _import_dotted(dotted: str) -> Any:
    dotted = dotted.strip()
    if ":" in dotted:
        module_name, attr = dotted.split(":", 1)
    else:
        if "." not in dotted:
            raise HookRunnerError(
                "invalid_config",
                "Plugin path must be in the form 'module:attr' or 'module.attr'",
                details={"path": dotted},
            )
        module_name, attr = dotted.rsplit(".", 1)

    module = importlib.import_module(module_name)
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise HookRunnerError(
            "invalid_config",
            "Plugin path attribute not found",
            details={"path": dotted},
        ) from exc


def _plugin_id(plugin: Any) -> str:
    for attr in ("id", "name", "slug"):
        value = getattr(plugin, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return plugin.__class__.__name__


def _get_hook_callable(plugin: Any, hook: str) -> Callable[..., Any] | None:
    # 1) Explicit getter
    getter = getattr(plugin, "get_hook", None)
    if callable(getter):
        try:
            candidate = getter(hook)
        except (KeyError, RuntimeError, TypeError, AttributeError):  # REVIEWED: broad catch — best-effort getter
            candidate = None
        if callable(candidate):
            return candidate

    # 2) Mapping attribute
    hooks_attr = getattr(plugin, "hooks", None)
    if isinstance(hooks_attr, Mapping):
        candidate = hooks_attr.get(hook)
        if callable(candidate):
            return candidate

    # 3) Method named hook, on_<hook>, hook_<hook>
    for name in (hook, f"on_{hook}", f"hook_{hook}"):
        candidate = getattr(plugin, name, None)
        if callable(candidate):
            return candidate

    return None


def _call_hook(hook_fn: Callable[..., Any], *, hook: str, payload: Mapping[str, Any]) -> Any:
    """Call a hook with a best-effort argument strategy.

    We try signature-guided dispatch first, then progressively looser fallbacks:

    1) hook_fn() (if nothing required)
    2) hook_fn(hook=..., payload=...) (if **kwargs)
    3) hook_fn(context) / hook_fn(payload) (if one required positional)
    4) hook_fn(hook, payload) (if two required positional)

    Finally, we attempt a few generic fallbacks.
    """

    context = {"hook": hook, "payload": payload}

    try:
        sig = inspect.signature(hook_fn)
    except (TypeError, ValueError):
        sig = None

    if sig is not None:
        params = list(sig.parameters.values())
        required = [
            p
            for p in params
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]

        if not required:
            return hook_fn()

        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            return hook_fn(hook=hook, payload=payload)

        positional = [
            p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        required_positional = [p for p in positional if p.default is inspect.Parameter.empty]

        if len(required_positional) == 1:
            pname = required_positional[0].name.lower()
            if pname in {"payload", "data", "event", "input"}:
                return hook_fn(payload)
            return hook_fn(context)

        if len(required_positional) == 2:
            p0 = required_positional[0].name.lower()
            p1 = required_positional[1].name.lower()
            if p0 in {"hook", "name", "hook_name"} and p1 in {"payload", "data", "event", "input"}:
                return hook_fn(hook, payload)
            if p1 in {"hook", "name", "hook_name"} and p0 in {"payload", "data", "event", "input"}:
                return hook_fn(payload, hook)
            # Default pairing.
            return hook_fn(hook, payload)

    # Fallback attempts.
    for attempt in (
        lambda: hook_fn(context),
        lambda: hook_fn(payload),
        lambda: hook_fn(hook=hook, payload=payload),
        lambda: hook_fn(),
    ):
        try:
            return attempt()
        except TypeError:
            continue

    # Let a final attempt raise a useful exception.
    return hook_fn(context)


def _to_json_value(value: Any) -> JsonValue:
    """Convert arbitrary Python objects into a JSON-friendly structure."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if dataclasses.is_dataclass(value):
        return _to_json_value(dataclasses.asdict(value))

    if isinstance(value, Mapping):
        return {str(k): _to_json_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_to_json_value(v) for v in value]

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _to_json_value(to_dict())
        except (RuntimeError, TypeError, ValueError, AttributeError):  # REVIEWED: broad catch — fallback to_dict
            pass

    return {"__type__": value.__class__.__name__}
