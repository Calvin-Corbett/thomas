from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import time
from collections.abc import Callable, Mapping, MutableSequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# -------------------------
# Deterministic error model
# -------------------------


@dataclass(frozen=True)
class HookErrorInfo:
    """Machine-readable error information for the tool-completion hook."""

    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class ToolCompletionHookError(RuntimeError):
    """Base error for the tool-completion hook implementation."""

    def __init__(self, info: HookErrorInfo):
        super().__init__(f"{info.code}: {info.message}")
        self.info = info


class InvalidInputError(ToolCompletionHookError):
    """Raised when user-provided input cannot be parsed or validated."""


class ConfigError(ToolCompletionHookError):
    """Raised when configuration is missing or invalid."""


class ExternalFailureError(ToolCompletionHookError):
    """Raised when an external side effect (e.g. log write) fails."""


# -------------------------
# Contracts (inputs/outputs)
# -------------------------


@dataclass(frozen=True)
class ToolCallSpec:
    """A minimal description of a tool invocation."""

    name: str
    input: Any


@dataclass(frozen=True)
class ToolCallOutcome:
    """A minimal description of a tool outcome."""

    ok: bool
    output: Any = None
    error: str | None = None


@dataclass(frozen=True)
class ToolCompletionEvent:
    """An event emitted after a tool finishes executing."""

    tool: ToolCallSpec
    outcome: ToolCallOutcome
    timestamp: float


@dataclass(frozen=True)
class ToolCompletionHookConfig:
    """Configuration for a tool completion audit plugin."""

    log_path: str | None = None
    include_input: bool = True
    include_output: bool = True
    clock: Callable[[], float] = time.time  # injected for testability; not serialized

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> ToolCompletionHookConfig:
        if not mapping:
            return cls()

        def _bool(key: str, default: bool) -> bool:
            val = mapping.get(key, default)
            if isinstance(val, bool):
                return val
            raise ConfigError(HookErrorInfo(code="config_invalid", message=f"Config key '{key}' must be boolean."))

        log_path = mapping.get("log_path")
        if log_path is not None and not isinstance(log_path, str):
            raise ConfigError(HookErrorInfo(code="config_invalid", message="Config key 'log_path' must be a string."))

        return cls(
            log_path=log_path,
            include_input=_bool("include_input", True),
            include_output=_bool("include_output", True),
        )


@dataclass(frozen=True)
class AfterToolHookRequest:
    """Input contract for running one tool call and capturing its completion."""

    tool_name: str
    tool_input: Any = dataclasses.field(default_factory=dict)
    config: Mapping[str, Any] | None = None
    config_path: str | None = None

    # For unit tests and embedding: bypass tool resolution and call this directly.
    tool_callable: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class AfterToolHookResponse:
    """Output contract for the runner/CLI."""

    ok: bool
    success: bool
    tool_output: Any = None
    events: tuple[ToolCompletionEvent, ...] = ()
    error: HookErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        # Manual conversion to avoid serializing config.clock etc.
        return _to_jsonable(
            {
                "ok": self.ok,
                "success": self.success,
                "tool_output": self.tool_output,
                "events": [dataclasses.asdict(e) for e in self.events],
                "error": None if self.error is None else self.error.to_dict(),
            }
        )


# -------------------------
# Utilities
# -------------------------


def _to_jsonable(obj: Any) -> Any:
    """Best-effort conversion into JSON-serializable values (deterministic)."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if dataclasses.is_dataclass(obj):
        return _to_jsonable(dataclasses.asdict(obj))

    if isinstance(obj, Mapping):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]

    # Fall back to a stable string representation.
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)


def _load_json_file(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise ConfigError(HookErrorInfo(code="config_not_found", message=f"Config file not found: {path}"))
    if path.is_dir():
        raise ConfigError(HookErrorInfo(code="config_invalid", message=f"Config path is a directory: {path}"))

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ConfigError(
            HookErrorInfo(code="config_invalid_json", message=f"Config file is not valid JSON: {path}")
        ) from None

    if not isinstance(data, dict):
        raise ConfigError(
            HookErrorInfo(code="config_invalid", message="Config JSON must be an object at the top level.")
        )
    return data


def _normalize_error(e: BaseException) -> str:
    # Deterministic string; no traceback, no reprs with memory addresses.
    msg = str(e)
    return f"{type(e).__name__}: {msg}" if msg else f"{type(e).__name__}"


# ---------------------------------------------
# Plugin implementation (Thomas-native behavior)
# ---------------------------------------------


def _plugin_base_type() -> type:
    """Best-effort lookup of Thomas' plugin base class without tight coupling."""
    try:
        mod = importlib.import_module("thomas.autonomy.plugin")
    except (ImportError, ModuleNotFoundError, AttributeError):
        return object

    for attr in ("Plugin", "BasePlugin", "AutonomyPlugin"):
        base = getattr(mod, attr, None)
        if isinstance(base, type):
            return base
    return object


_PluginBase = _plugin_base_type()


class ToolCompletionAuditPlugin(_PluginBase):
    """
    Plugin that records a tool completion event.

    Preferred hook entry point: `on_tool_completed(...)`.
    Aliases are provided for compatibility with different hook dispatchers.
    """

    # Common metadata names used by various plugin loaders
    plugin_id = "tool_completion_audit"
    id = plugin_id
    name = plugin_id

    def __init__(self, config: ToolCompletionHookConfig | None = None, **_kwargs: Any):
        # Be gentle with super().__init__(): only call it if it looks invokable.
        try:
            super_init = getattr(super(), "__init__", None)
            if callable(super_init):
                params = list(inspect.signature(super_init).parameters.values())
                if len(params) <= 1:
                    super_init()  # type: ignore[misc]
        except (TypeError, ValueError, AttributeError):
            pass

        self.config = config or ToolCompletionHookConfig()
        self.events: MutableSequence[ToolCompletionEvent] = []

    # ---- Thomas-native entrypoint (preferred) ----

    def on_tool_completed(self, *args: Any, **kwargs: Any) -> None:
        tool_name, tool_input, output, error = _extract_tool_completion_payload(args, kwargs)
        self.record_tool_completion(tool_name=tool_name, tool_input=tool_input, tool_output=output, tool_error=error)

    # ---- Compatibility aliases ----

    def after_tool(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        self.on_tool_completed(*args, **kwargs)

    def after_tool_call(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        self.on_tool_completed(*args, **kwargs)

    def on_tool_result(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        self.on_tool_completed(*args, **kwargs)

    # ---- Explicit recording API (useful for tests and dispatchers) ----

    def record_tool_completion(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        tool_output: Any = None,
        tool_error: str | None = None,
    ) -> ToolCompletionEvent:
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise InvalidInputError(
                HookErrorInfo(code="invalid_tool_name", message="Tool name must be a non-empty string.")
            )

        event = ToolCompletionEvent(
            tool=ToolCallSpec(name=tool_name, input=tool_input if self.config.include_input else None),
            outcome=ToolCallOutcome(
                ok=tool_error is None,
                output=tool_output if self.config.include_output else None,
                error=tool_error,
            ),
            timestamp=float(self.config.clock()),
        )

        self.events.append(event)
        self._persist_event(event)
        return event

    def _persist_event(self, event: ToolCompletionEvent) -> None:
        if not self.config.log_path:
            return

        path = Path(self.config.log_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(_to_jsonable(dataclasses.asdict(event)), ensure_ascii=False, sort_keys=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(payload)
                f.write("\n")
        except (OSError, UnicodeDecodeError, TypeError):
            raise ExternalFailureError(
                HookErrorInfo(code="external_failure", message=f"Failed to write tool audit log to: {path}")
            ) from None


def _extract_tool_completion_payload(
    args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> tuple[str, Any, Any, str | None]:
    """
    Extract (tool_name, tool_input, output, error) from a hook payload.

    The hook dispatcher shape varies across systems; this extractor is intentionally
    forgiving while still failing deterministically if tool name cannot be found.
    """
    tool_name = kwargs.get("tool_name") or kwargs.get("name") or kwargs.get("tool")
    tool_input = kwargs.get("tool_input") or kwargs.get("input") or kwargs.get("args") or kwargs.get("parameters")
    output = kwargs.get("output") or kwargs.get("result") or kwargs.get("tool_output")
    error = kwargs.get("error") or kwargs.get("exception") or kwargs.get("exc")

    # Resolve tool_name from a tool object.
    if tool_name is not None and not isinstance(tool_name, str):
        maybe_name = getattr(tool_name, "name", None) or getattr(tool_name, "tool_name", None)
        if isinstance(maybe_name, str):
            tool_name = maybe_name

    # Fall back to positional args if still missing.
    if tool_name is None:
        for a in args:
            if isinstance(a, str):
                tool_name = a
                break
            maybe_name = getattr(a, "name", None) or getattr(a, "tool_name", None)
            if isinstance(maybe_name, str):
                tool_name = maybe_name
                break

    if tool_input is None and len(args) >= 2:
        tool_input = args[1]

    # Output is commonly the last positional arg.
    if output is None and len(args) >= 3:
        output = args[-1]

    if error is None:
        error_str = None
    elif isinstance(error, str):
        error_str = error
    elif isinstance(error, BaseException):
        error_str = _normalize_error(error)
    else:
        error_str = f"{type(error).__name__}: {error}"

    if not isinstance(tool_name, str) or not tool_name.strip():
        raise InvalidInputError(
            HookErrorInfo(code="invalid_hook_payload", message="Could not determine tool name from hook payload.")
        )

    return tool_name, tool_input, output, error_str


# -------------------------
# JSON schema for automation
# -------------------------


def response_json_schema() -> dict[str, Any]:
    """A small JSON schema for the CLI's `--json` output."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AfterToolHookResponse",
        "type": "object",
        "required": ["ok", "success", "events"],
        "properties": {
            "ok": {"type": "boolean"},
            "success": {"type": "boolean"},
            "tool_output": {},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["tool", "outcome", "timestamp"],
                    "properties": {
                        "tool": {
                            "type": "object",
                            "required": ["name", "input"],
                            "properties": {"name": {"type": "string"}, "input": {}},
                        },
                        "outcome": {
                            "type": "object",
                            "required": ["ok", "output", "error"],
                            "properties": {
                                "ok": {"type": "boolean"},
                                "output": {},
                                "error": {"type": ["string", "null"]},
                            },
                        },
                        "timestamp": {"type": "number"},
                    },
                },
            },
            "error": {
                "type": ["object", "null"],
                "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
            },
        },
    }


# -----------------------------------------
# Runner: invoke tool, then emit completion
# -----------------------------------------


def run_after_tool_hook(request: AfterToolHookRequest) -> AfterToolHookResponse:
    """
    Execute one tool call and capture a completion event.

    In a full Thomas runtime, the agent loop may dispatch tool completion hooks into
    plugins; for the CLI and tests we make the behavior explicit and deterministic.
    """
    if not isinstance(request.tool_name, str) or not request.tool_name.strip():
        raise InvalidInputError(
            HookErrorInfo(code="invalid_tool_name", message="Tool name must be a non-empty string.")
        )

    # Load config (file first, then overlay explicit mapping).
    config_mapping: Mapping[str, Any] = {}
    if request.config_path is not None:
        config_mapping = dict(_load_json_file(Path(request.config_path)))
    if request.config:
        config_mapping = {**config_mapping, **dict(request.config)}

    plugin = ToolCompletionAuditPlugin(config=ToolCompletionHookConfig.from_mapping(config_mapping))

    tool_callable = request.tool_callable or _resolve_tool_callable(request.tool_name)
    if tool_callable is None:
        raise InvalidInputError(
            HookErrorInfo(code="tool_not_found", message=f"Tool not found or not invokable: {request.tool_name}")
        )

    output: Any = None
    err: str | None = None
    try:
        output = tool_callable(request.tool_input)
    except (RuntimeError, OSError, AttributeError) as e:  # pragma: no cover - execution paths vary
        err = _normalize_error(e)

    # If Thomas didn't dispatch a completion hook (or we're running standalone), record it ourselves.
    if not plugin.events:
        plugin.record_tool_completion(
            tool_name=request.tool_name,
            tool_input=request.tool_input,
            tool_output=output,
            tool_error=err,
        )

    ok = err is None
    error_info = None if ok else HookErrorInfo(code="tool_failed", message=err or "Tool execution failed.")
    return AfterToolHookResponse(
        ok=ok,
        success=ok,
        tool_output=output if ok else None,
        events=tuple(plugin.events),
        error=error_info,
    )


# -------------------------
# Tool resolution (CLI use)
# -------------------------


def _resolve_tool_callable(tool_name: str) -> Callable[[Any], Any] | None:
    """
    Resolve a tool callable.

    Prefer deterministic built-ins so the CLI works in minimal environments; otherwise
    try Thomas' tool registry via reflection.
    """
    if tool_name == "noop":
        return lambda _inp: None
    if tool_name == "echo":
        return lambda inp: inp

    try:
        reg_mod = importlib.import_module("thomas.tools.registry")
    except (ImportError, ModuleNotFoundError):
        return None

    registry = None
    for attr in (
        "get_default_registry",
        "default_registry",
        "get_registry",
        "registry",
        "REGISTRY",
        "TOOL_REGISTRY",
    ):
        candidate = getattr(reg_mod, attr, None)
        if candidate is None:
            continue
        registry = candidate() if callable(candidate) else candidate
        break

    if registry is None:
        cls = getattr(reg_mod, "ToolRegistry", None)
        if isinstance(cls, type):
            try:
                registry = cls()
            except (TypeError, ValueError, RuntimeError):
                registry = None

    if registry is None:
        return None

    method: Callable[..., Any] | None = None
    for name in ("invoke", "call", "run", "execute"):
        m = getattr(registry, name, None)
        if callable(m):
            method = m
            break

    if method is None:
        return None

    def _call(inp: Any) -> Any:
        return _call_registry_method(method, tool_name, inp)

    return _call


def _call_registry_method(method: Callable[..., Any], tool_name: str, tool_input: Any) -> Any:
    """Try a handful of common call shapes for tool registries."""
    candidates = [
        ((), {"tool_name": tool_name, "tool_input": tool_input}),
        ((), {"name": tool_name, "input": tool_input}),
        ((), {"name": tool_name, "args": tool_input}),
        ((), {"tool": tool_name, "input": tool_input}),
        ((tool_name, tool_input), {}),
        ((tool_name,), {"tool_input": tool_input}),
        ((tool_name,), {"input": tool_input}),
        ((tool_name,), {"args": tool_input}),
    ]

    # If method has signature info, prefer keyword matching where possible.
    try:
        sig = inspect.signature(method)
        param_names = {p.name for p in sig.parameters.values()}
        if "tool" in param_names and "input" in param_names:
            candidates.insert(0, ((), {"tool": tool_name, "input": tool_input}))
    except (ValueError, TypeError):
        pass

    for args, kwargs in candidates:
        try:
            return method(*args, **kwargs)
        except TypeError:
            continue

    raise InvalidInputError(
        HookErrorInfo(
            code="tool_invoke_shape_mismatch",
            message=f"Tool registry method signature did not accept common invocation shapes for tool '{tool_name}'.",
        )
    ) from None


# Export a conventional name that some plugin loaders may look for.
PLUGIN_CLASS = ToolCompletionAuditPlugin
