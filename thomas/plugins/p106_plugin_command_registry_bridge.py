"""Plugin command registry bridge.

This module implements Thomas-native behavior for invoking *plugin commands*
through a single "bridge tool" entry in the tool registry.

Why a bridge?
- Plugins may register many commands (maintenance tasks, integrations, etc.)
- Tools are what the agent/runtime can invoke (often via the gateway API)
- Registering every plugin command as a tool can bloat tool surfaces and
  complicate routing

So we expose **one** tool that dispatches by command name.

The design goals here are:
- Clear, machine-readable input/output contracts
- Deterministic failure modes (stable error codes)
- Compatibility with the existing Thomas registries via light duck-typing
  (without reusing any Reference CLI naming)

Owned by prompt P106.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Public contracts
# ---------------------------------------------------------------------------

ErrorCode = str


@dataclass(frozen=True)
class BridgeError:
    """Machine-readable error payload."""

    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class PluginCommandCall:
    """Input contract for invoking a plugin command through the bridge."""

    command: str
    args: dict[str, Any]


@dataclass(frozen=True)
class PluginCommandCallResult:
    """Output contract for invoking a plugin command through the bridge."""

    ok: bool
    command: str | None
    result: Any
    error: BridgeError | None


class PluginCommandBridgeError(RuntimeError):
    """Deterministic error type for bridge failures.

    These errors are intended to be stable and machine-readable.
    """

    def __init__(self, *, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_error(self) -> BridgeError:
        return BridgeError(code=self.code, message=self.message, details=self.details)


# ---------------------------------------------------------------------------
# JSON-ish schemas (for automation)
# ---------------------------------------------------------------------------


def request_schema() -> dict[str, Any]:
    """JSON schema for :class:`PluginCommandCall` (shape, not semantic validation)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "command": {"type": "string", "minLength": 1},
            "args": {"type": "object", "additionalProperties": True},
        },
        "required": ["command", "args"],
    }


def response_schema() -> dict[str, Any]:
    """JSON schema for :class:`PluginCommandCallResult` (shape)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ok": {"type": "boolean"},
            "command": {"type": ["string", "null"]},
            "result": {},
            "error": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": ["object", "null"], "additionalProperties": True},
                },
                "required": ["code", "message", "details"],
            },
        },
        "required": ["ok", "command", "result", "error"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_mapping(obj: Any) -> bool:
    return isinstance(obj, Mapping)


def _jsonable(obj: Any) -> Any:
    """Best-effort conversion to JSON-serializable values."""
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        pass

    # Common structured types
    if is_dataclass(obj):
        try:
            return asdict(obj)
        except (TypeError, ValueError, AttributeError):  # REVIEWED: broad catch — any dataclass conversion
            return str(obj)

    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            return obj.model_dump()
        except (TypeError, ValueError, AttributeError):  # REVIEWED: broad catch — any model serialization
            return str(obj)

    if hasattr(obj, "dict") and callable(obj.dict):
        # Pydantic v1
        try:
            return obj.dict()
        except (TypeError, ValueError, AttributeError):  # REVIEWED: broad catch — any model serialization
            return str(obj)

    return str(obj)


def _result_to_dict(result: PluginCommandCallResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "command": result.command,
        "result": _jsonable(result.result),
        "error": asdict(result.error) if result.error is not None else None,
    }


def _parse_call_payload(payload: Any) -> PluginCommandCall:
    if not isinstance(payload, Mapping):
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Payload must be an object.",
            details={"expected": request_schema(), "received_type": type(payload).__name__},
        )

    command = payload.get("command")
    args = payload.get("args")

    if not isinstance(command, str) or not command.strip():
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Field 'command' must be a non-empty string.",
            details={"command": command},
        )

    if args is None:
        args = {}

    if not isinstance(args, Mapping):
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Field 'args' must be an object.",
            details={"args_type": type(args).__name__},
        )

    return PluginCommandCall(command=command.strip(), args=dict(args))


# ---------------------------------------------------------------------------
# Command registry adapter
# ---------------------------------------------------------------------------


class _CommandRegistryInvoker(Protocol):
    def invoke(self, name: str, args: Mapping[str, Any]) -> Any: ...


class CommandRegistryAdapter:
    """Adapter for multiple command-registry shapes.

    Supported patterns include:
    - Registry has `invoke(name, args)` or `invoke(name, **kwargs)`
    - Registry has `get_command(name)` returning a callable / runnable object
    - Registry is a Mapping[str, Callable]
    """

    def __init__(self, registry: Any):
        self._registry = registry

    # ---- Discovery ----

    def list_commands(self) -> list[str]:
        reg = self._registry

        # Methods / properties that return command names or mappings
        for attr_name in ("list_commands", "list", "keys", "command_names"):
            attr = getattr(reg, attr_name, None)
            if attr is None:
                continue
            try:
                value = attr() if callable(attr) else attr
            except (TypeError, ValueError, RuntimeError):  # REVIEWED: broad catch — registry-specific method
                continue

            if isinstance(value, Mapping):
                return sorted([str(k) for k in value.keys()])
            if isinstance(value, (list, tuple, set)):
                return sorted([str(x) for x in value])

        # Common attribute holding a mapping
        for attr_name in ("commands", "registry", "_commands"):
            value = getattr(reg, attr_name, None)
            if isinstance(value, Mapping):
                return sorted([str(k) for k in value.keys()])

        # Mapping fallback
        if isinstance(reg, Mapping):
            return sorted([str(k) for k in reg.keys()])

        # Iterator fallback
        try:
            return sorted([str(x) for x in reg])  # type: ignore[iteration-over-non-sequence]
        except (TypeError, AttributeError):  # REVIEWED: broad catch — non-iterable fallback
            return []

    # ---- Invocation ----

    def invoke(self, name: str, args: Mapping[str, Any]) -> Any:
        """Invoke a command via registry-native methods if available."""
        reg = self._registry

        # Try dedicated registry invoke/execute/call/run methods first
        for meth_name in ("invoke", "execute", "call", "run"):
            meth = getattr(reg, meth_name, None)
            if not callable(meth):
                continue

            # Best effort call shapes: (name, **args) then (name, args)
            try:
                return meth(name, **dict(args))
            except TypeError:
                return meth(name, dict(args))

        # Fall back to resolving a command object and calling it
        cmd_obj = self.resolve(name)
        return _call_command_object(cmd_obj, dict(args))

    def resolve(self, name: str) -> Any:
        reg = self._registry

        # Getter methods
        for meth_name in ("get_command", "get", "resolve", "find"):
            meth = getattr(reg, meth_name, None)
            if not callable(meth):
                continue
            try:
                cmd = meth(name)
            except KeyError:
                cmd = None
            if cmd is not None:
                return cmd

        # Mapping attributes
        for attr_name in ("commands", "registry", "_commands"):
            mapping = getattr(reg, attr_name, None)
            if isinstance(mapping, Mapping) and name in mapping:
                return mapping[name]

        # Mapping itself
        if isinstance(reg, Mapping):
            if name in reg:
                return reg[name]
            cmd = reg.get(name)
            if cmd is not None:
                return cmd

        # __getitem__
        try:
            return reg[name]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):  # REVIEWED: broad catch — subscript access fallback
            pass

        raise PluginCommandBridgeError(
            code="COMMAND_NOT_FOUND",
            message="Plugin command not found.",
            details={"command": name},
        )


# ---------------------------------------------------------------------------
# Calling commands
# ---------------------------------------------------------------------------


def _call_command_object(command_obj: Any, args: dict[str, Any]) -> Any:
    """Call a command object in a few common shapes."""

    # Unwrap common command wrappers (e.g., click.Command)
    if hasattr(command_obj, "callback") and callable(command_obj.callback):
        command_obj = command_obj.callback

    # Prefer run/invoke if present
    for attr in ("run", "invoke"):
        meth = getattr(command_obj, attr, None)
        if callable(meth):
            return _call_callable(meth, args)

    # Otherwise treat it as callable
    if callable(command_obj):
        return _call_callable(command_obj, args)

    raise PluginCommandBridgeError(
        code="INVALID_COMMAND",
        message="Resolved object is not invokable as a command.",
        details={"type": type(command_obj).__name__},
    )


def _call_callable(fn: Callable[..., Any], args: dict[str, Any]) -> Any:
    """Call a function with dict args, with signature-aware validation.

    Deterministic failures:
    - If the function clearly cannot accept the provided keys and does not accept **kwargs,
      we surface INVALID_INPUT instead of a raw TypeError.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # Builtins etc. - best effort kwargs call
        return fn(**args)

    params = sig.parameters

    # If it accepts **kwargs, call directly.
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**args)

    # If it has exactly one parameter, allow passing the args dict positionally.
    if len(params) == 1:
        p = next(iter(params.values()))
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            # If caller supplied matching key, prefer kwargs; else send dict as positional.
            if p.name in args and set(args.keys()) == {p.name}:
                return fn(**args)
            if set(args.keys()).issubset({p.name}):
                # still safe to call kwargs
                return fn(**args)
            return fn(args)

    # Determine which parameters can be provided by keyword
    keywordable = {
        name
        for name, p in params.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }

    required = {
        name
        for name, p in params.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and p.default is inspect._empty
    }

    extra = sorted([k for k in args if k not in keywordable])
    missing = sorted([k for k in required if k not in args])

    if extra or missing:
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Arguments are not compatible with the command signature.",
            details={"missing": missing, "unexpected": extra, "signature": str(sig)},
        )

    try:
        return fn(**args)
    except TypeError as e:
        # Still deterministic, but include details
        raise PluginCommandBridgeError(
            code="INVALID_INPUT",
            message="Arguments are not compatible with the command signature.",
            details={"signature": str(sig), "error": str(e)},
        ) from e


# ---------------------------------------------------------------------------
# Bridge dispatch
# ---------------------------------------------------------------------------


def dispatch_plugin_command(
    payload: Any,
    *,
    command_registry: Any = None,
    command_registry_provider: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Dispatch a plugin command invocation.

    This function:
    - Never raises for expected failures
    - Returns a JSON-friendly dict matching :func:`response_schema`
    """
    provider = command_registry_provider or (lambda: command_registry)

    try:
        call = _parse_call_payload(payload)

        registry = provider()
        if registry is None:
            raise PluginCommandBridgeError(
                code="MISSING_CONFIG",
                message="No plugin command registry is configured/available.",
                details=None,
            )

        adapter = CommandRegistryAdapter(registry)
        value = adapter.invoke(call.command, call.args)

        return _result_to_dict(
            PluginCommandCallResult(ok=True, command=call.command, result=_jsonable(value), error=None)
        )

    except PluginCommandBridgeError as e:
        cmd_name = payload.get("command") if isinstance(payload, Mapping) else None
        return _result_to_dict(PluginCommandCallResult(ok=False, command=cmd_name, result=None, error=e.to_error()))

    except (RuntimeError, ValueError, TypeError, OSError) as e:  # REVIEWED: broad catch — external command failure
        cmd_name = payload.get("command") if isinstance(payload, Mapping) else None
        err = BridgeError(
            code="EXTERNAL_FAILURE",
            message="Plugin command execution failed.",
            details={"exception": type(e).__name__, "message": str(e)},
        )
        return _result_to_dict(PluginCommandCallResult(ok=False, command=cmd_name, result=None, error=err))


# ---------------------------------------------------------------------------
# Tool registry registration
# ---------------------------------------------------------------------------


def register_bridge_tool(
    tool_registry: Any,
    *,
    command_registry: Any = None,
    command_registry_provider: Callable[[], Any] | None = None,
    tool_name: str = "plugins.invoke",
    description: str = "Invoke a plugin command by name.",
) -> None:
    """Register the bridge tool with a ToolRegistry-like object.

    We try common ToolRegistry method names and signatures, and fall back to
    MutableMapping-style assignment.

    Importantly, the bridge tool is registered even if the command registry is
    not available *at registration time*; missing config becomes a deterministic
    runtime error from the bridge tool itself.
    """
    if tool_registry is None:
        raise PluginCommandBridgeError(code="INVALID_INPUT", message="tool_registry is required.", details=None)

    provider = command_registry_provider or (lambda: command_registry)

    def _tool(payload: Any) -> dict[str, Any]:
        return dispatch_plugin_command(payload, command_registry_provider=provider)

    # MutableMapping-style registry
    if isinstance(tool_registry, MutableMapping):
        tool_registry[tool_name] = _tool
        return

    # Common registry method names
    methods: Sequence[str] = (
        "register_tool",
        "register",
        "add",
        "add_tool",
        "tool",
    )
    candidates: list[Callable[..., Any]] = []
    for name in methods:
        m = getattr(tool_registry, name, None)
        if callable(m):
            candidates.append(m)

    if not candidates:
        raise PluginCommandBridgeError(
            code="UNSUPPORTED_REGISTRY",
            message="Tool registry does not support tool registration.",
            details={"type": type(tool_registry).__name__},
        )

    last_err: Exception | None = None
    for m in candidates:
        try:
            _try_register_with_method(
                m,
                tool_name=tool_name,
                description=description,
                fn=_tool,
                input_schema=request_schema(),
                output_schema=response_schema(),
            )
            return
        except (TypeError, ValueError, RuntimeError) as e:  # REVIEWED: broad catch — best-effort registration
            last_err = e
            continue

    raise PluginCommandBridgeError(
        code="UNSUPPORTED_REGISTRY",
        message="Unable to register tool with available registry methods.",
        details={"last_error": type(last_err).__name__ if last_err else None},
    )


def _try_register_with_method(
    method: Callable[..., Any],
    *,
    tool_name: str,
    description: str,
    fn: Callable[[Any], Any],
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> None:
    """Call a registration method with signature-aware adaptation."""
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        method(tool_name, fn)  # type: ignore[misc]
        return

    params = sig.parameters
    kwargs: dict[str, Any] = {}

    # name
    if "name" in params:
        kwargs["name"] = tool_name
    if "tool_name" in params:
        kwargs["tool_name"] = tool_name

    # callback
    for fn_key in ("fn", "func", "callback", "handler", "callable", "tool"):
        if fn_key in params:
            kwargs[fn_key] = fn
            break

    # description/help/doc
    for desc_key in ("description", "help", "doc"):
        if desc_key in params:
            kwargs[desc_key] = description
            break

    # schemas
    for key, value in (
        ("input_schema", input_schema),
        ("args_schema", input_schema),
        ("parameters", input_schema),
        ("output_schema", output_schema),
        ("returns_schema", output_schema),
    ):
        if key in params:
            kwargs[key] = value

    # Some registries are positional: (name, fn, ...)
    if not kwargs:
        method(tool_name, fn)
        return

    # Ensure at least name and fn are passed; fall back to positional if needed.
    try:
        method(**kwargs)
    except TypeError:
        method(tool_name, fn, **{k: v for k, v in kwargs.items() if k not in ("name", "tool_name")})


# ---------------------------------------------------------------------------
# Thomas plugin integration (best effort)
# ---------------------------------------------------------------------------


def discover_command_registry() -> Any:
    """Best-effort discovery of the plugin command registry from the Thomas runtime."""
    # 1) thomas.autonomy.plugin
    try:
        import thomas.autonomy.plugin as plugin_mod  # type: ignore

        for attr_name in ("PLUGIN_COMMAND_REGISTRY", "COMMAND_REGISTRY", "plugin_command_registry", "command_registry"):
            reg = getattr(plugin_mod, attr_name, None)
            if reg is not None:
                return reg

        for fn_name in ("get_plugin_command_registry", "get_command_registry"):
            fn = getattr(plugin_mod, fn_name, None)
            if callable(fn):
                try:
                    reg = fn()
                    if reg is not None:
                        return reg
                except (RuntimeError, ValueError, OSError):  # REVIEWED: broad catch — discovery fallback
                    continue
    except (ImportError, ModuleNotFoundError):
        pass

    # 2) thomas.agent.loop
    try:
        import thomas.agent.loop as loop_mod  # type: ignore

        for attr_name in ("PLUGIN_COMMAND_REGISTRY", "COMMAND_REGISTRY", "plugin_command_registry", "command_registry"):
            reg = getattr(loop_mod, attr_name, None)
            if reg is not None:
                return reg
    except (ImportError, ModuleNotFoundError):
        pass

    return None


def _resolve_thomas_plugin_base() -> type:
    """Resolve Thomas' plugin base class if available (keeps imports optional)."""
    try:
        import thomas.autonomy.plugin as plugin_mod  # type: ignore

        for name in ("Plugin", "AutonomyPlugin", "BasePlugin"):
            base = getattr(plugin_mod, name, None)
            if isinstance(base, type):
                return base
    except (ImportError, ModuleNotFoundError, AttributeError):
        pass
    return object


_ThomasPluginBase = _resolve_thomas_plugin_base()


class PluginCommandRegistryBridgePlugin(_ThomasPluginBase):
    """Plugin that registers the bridge tool into the tool registry.

    The bridge tool uses lazy registry discovery, so it can be registered even
    before plugins finish initializing.
    """

    name = "plugin_command_registry_bridge"

    def __init__(self, *, tool_name: str = "plugins.invoke", **kwargs: Any):
        try:
            super().__init__(**kwargs)  # type: ignore[misc]
        except (TypeError, AttributeError):  # REVIEWED: broad catch — optional base init
            # Base plugin may require specific constructor args; keep optional.
            pass
        self.tool_name = tool_name

    # Common hook names across plugin loaders
    def register(self, tool_registry: Any, **_kwargs: Any) -> None:  # pragma: no cover
        self._register_into(tool_registry)

    def register_tools(self, tool_registry: Any, **_kwargs: Any) -> None:  # pragma: no cover
        self._register_into(tool_registry)

    def setup(self, tool_registry: Any, **_kwargs: Any) -> None:  # pragma: no cover
        self._register_into(tool_registry)

    def _register_into(self, tool_registry: Any) -> None:
        # Always register the tool; missing registry becomes a deterministic runtime error.
        register_bridge_tool(
            tool_registry,
            command_registry_provider=discover_command_registry,
            tool_name=self.tool_name,
        )


# Conventional module-level handle(s) for plugin loaders.
PLUGIN = PluginCommandRegistryBridgePlugin()


def get_plugin() -> PluginCommandRegistryBridgePlugin:
    return PLUGIN
