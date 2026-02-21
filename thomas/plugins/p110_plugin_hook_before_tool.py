"""
P110 - Plugin hook before-tool

This module implements a **Thomas-native** "before tool execution" hook contract.

It is intentionally small and dependency-free so it can be:
- loaded as a plugin module by the Thomas runtime (if supported),
- exercised via a CLI parity command, and
- tested deterministically.

Core idea:
    tool call (name + args)  ->  hook decision (allow|modify|block)  ->  tool execution
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Literal

BeforeToolAction = Literal["allow", "block", "modify"]


# -----------------------------
# Deterministic error types
# -----------------------------


class BeforeToolHookError(Exception):
    """Base error for the before-tool hook path."""

    code: str = "before_tool_hook_error"

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class HookConfigError(BeforeToolHookError):
    """Raised when configuration is missing or invalid."""


class HookInputError(BeforeToolHookError):
    """Raised when a tool call payload is invalid."""


class ToolBlockedError(BeforeToolHookError):
    """Raised when a hook blocks a tool invocation."""


class ExternalHookFailure(BeforeToolHookError):
    """Raised when an external validation step fails (simulated or real)."""


class ToolExecutionError(BeforeToolHookError):
    """Raised when the underlying tool execution fails."""


class HookRegistrationError(BeforeToolHookError):
    """Raised when we cannot attach the hook to a provided API object."""


# -----------------------------
# Input / output contracts
# -----------------------------


@dataclass(frozen=True)
class ToolCall:
    """A minimal, serializable tool invocation request."""

    name: str
    args: Dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise HookInputError("tool name must be a non-empty string", code="invalid_tool_name")
        if not isinstance(self.args, dict):
            raise HookInputError("tool args must be a dict", code="invalid_tool_args")


@dataclass(frozen=True)
class BeforeToolDecision:
    """Decision returned by a before-tool hook."""

    action: BeforeToolAction
    reason: Optional[str] = None
    modified_args: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "reason": self.reason, "modified_args": self.modified_args}


@dataclass(frozen=True)
class ErrorInfo:
    """Machine-readable error details."""

    code: str
    type: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "type": self.type, "message": self.message}


@dataclass(frozen=True)
class ToolCallReport:
    """Report of a tool call before/after hook processing."""

    name: str
    original_args: Dict[str, Any]
    final_args: Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "original_args": self.original_args, "final_args": self.final_args}


@dataclass(frozen=True)
class BeforeToolDemoData:
    """Structured output for a single before-tool hook demo run."""

    tool: ToolCallReport
    hook: BeforeToolDecision
    tool_executed: bool
    tool_result: Optional[Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool.to_dict(),
            "hook": self.hook.to_dict(),
            "tool_executed": self.tool_executed,
            "tool_result": _json_safe(self.tool_result),
        }


@dataclass(frozen=True)
class BeforeToolDemoOutput:
    """Top-level output envelope used by CLI and automation."""

    ok: bool
    data: Optional[BeforeToolDemoData] = None
    error: Optional[ErrorInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "data": None if self.data is None else self.data.to_dict(),
            "error": None if self.error is None else self.error.to_dict(),
        }


# -----------------------------
# Configuration contract
# -----------------------------


@dataclass(frozen=True)
class BeforeToolHookConfig:
    """
    Configuration for the reference before-tool hook plugin.

    mode:
      - allow:  do nothing and allow all calls (unless blocked by patterns)
      - modify: (default) modify certain calls (e.g., prefix args["text"])
      - block:  block all calls
    """

    mode: BeforeToolAction = "modify"
    prefix: str = "[p110 before-tool] "
    blocked_substrings: Tuple[str, ...] = ("rm -rf /", "DROP TABLE")
    blocked_tool_names: Tuple[str, ...] = ()
    simulate_external_failure: bool = False

    @classmethod
    def from_mapping(cls, cfg: Optional[Mapping[str, Any]], *, strict: bool = False) -> "BeforeToolHookConfig":
        if cfg is None:
            if strict:
                raise HookConfigError("missing plugin config", code="missing_config")
            return cls()

        mode = cfg.get("mode", "modify")
        if mode not in ("allow", "block", "modify"):
            raise HookConfigError(
                f"invalid mode: {mode!r} (expected 'allow', 'modify', or 'block')",
                code="invalid_mode",
            )

        prefix = cfg.get("prefix", cls.prefix)
        if not isinstance(prefix, str):
            raise HookConfigError("prefix must be a string", code="invalid_prefix")

        blocked_substrings = _coerce_str_tuple(cfg.get("blocked_substrings", cls.blocked_substrings), field="blocked_substrings")
        blocked_tool_names = _coerce_str_tuple(cfg.get("blocked_tool_names", cls.blocked_tool_names), field="blocked_tool_names")

        simulate_external_failure = cfg.get("simulate_external_failure", False)
        if not isinstance(simulate_external_failure, bool):
            raise HookConfigError("simulate_external_failure must be a bool", code="invalid_simulate_external_failure")

        return cls(
            mode=mode,  # type: ignore[arg-type]
            prefix=prefix,
            blocked_substrings=blocked_substrings,
            blocked_tool_names=blocked_tool_names,
            simulate_external_failure=simulate_external_failure,
        )


def _coerce_str_tuple(value: Any, *, field: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple) and all(isinstance(x, str) for x in value):
        return value
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return tuple(value)
    raise HookConfigError(f"{field} must be a list/tuple of strings", code=f"invalid_{field}")


# -----------------------------
# Reference plugin implementation
# -----------------------------


@dataclass
class P110BeforeToolHookPlugin:
    """
    Reference plugin for P110.

    The plugin can be used directly and also exposes `register(api)` for
    runtimes that support pre-tool hooks.

    The runtime integration is intentionally duck-typed:
      - We try a few likely method names for hook registration.
      - If not supported, we raise a deterministic HookRegistrationError.
    """

    config: BeforeToolHookConfig = field(default_factory=BeforeToolHookConfig)
    plugin_id: str = "p110_plugin_hook_before_tool"
    name: str = "P110: Before-Tool Hook"

    # --- primary hook (Thomas-native concept) ---

    def before_tool(self, call: ToolCall) -> BeforeToolDecision:
        """Evaluate the tool call and return a decision."""
        if not isinstance(call, ToolCall):
            raise HookInputError("call must be a ToolCall", code="invalid_call_type")

        if self.config.simulate_external_failure:
            raise ExternalHookFailure("simulated external validation failure", code="external_failure")

        if call.name in self.config.blocked_tool_names:
            return BeforeToolDecision(action="block", reason=f"blocked tool: {call.name}")

        args_blob = _stable_args_blob(call.args)
        for needle in self.config.blocked_substrings:
            if needle and needle in args_blob:
                return BeforeToolDecision(action="block", reason=f"blocked pattern: {needle}")

        if self.config.mode == "allow":
            return BeforeToolDecision(action="allow")
        if self.config.mode == "block":
            return BeforeToolDecision(action="block", reason="blocked by config mode")

        # mode == "modify"
        if "text" in call.args and isinstance(call.args["text"], str):
            new_args = dict(call.args)
            new_args["text"] = f"{self.config.prefix}{call.args['text']}"
            return BeforeToolDecision(action="modify", reason="prefixed text arg", modified_args=new_args)

        return BeforeToolDecision(action="allow", reason="no-op: nothing to modify")

    # --- compatibility aliases (do not change semantics) ---

    def before_tool_call(self, call: ToolCall) -> BeforeToolDecision:
        return self.before_tool(call)

    def on_before_tool(self, call: ToolCall) -> BeforeToolDecision:
        return self.before_tool(call)

    # --- runtime registration ---

    def register(self, api: Any) -> None:
        handler = self._handle_before_tool_event

        for attr in ("register_before_tool_hook", "register_tool_pre_hook", "register_tool_before_hook"):
            fn = getattr(api, attr, None)
            if callable(fn):
                fn(handler)
                return

        on = getattr(api, "on", None)
        if callable(on):
            for event_name in ("tool_before_execute", "tool_before_run", "before_tool", "before_tool_call"):
                try:
                    on(event_name, handler)
                    return
                except Exception:
                    continue

        raise HookRegistrationError(
            "plugin API does not support before-tool hook registration",
            code="hook_registration_failed",
        )

    def _handle_before_tool_event(self, event: Any, *args: Any, **kwargs: Any) -> Any:
        call = coerce_tool_call(event)
        decision = self.before_tool(call)

        if decision.action == "block":
            raise ToolBlockedError(decision.reason or "blocked", code="tool_blocked")

        if decision.action == "modify" and decision.modified_args is not None:
            _mutate_event_args(event, decision.modified_args)

        return decision.to_dict()


# Default module instance for plugin loaders that expect a singleton.
PLUGIN = P110BeforeToolHookPlugin()


def get_plugin() -> P110BeforeToolHookPlugin:
    """Common plugin-loader entrypoint."""
    return PLUGIN


def create_plugin(cfg: Optional[Mapping[str, Any]] = None) -> P110BeforeToolHookPlugin:
    """Factory for runtimes that instantiate plugins with config."""
    return P110BeforeToolHookPlugin(config=BeforeToolHookConfig.from_mapping(cfg))


def register(api: Any) -> None:
    """Module-level register hook for runtimes that expect `register(api)`."""
    PLUGIN.register(api)


# -----------------------------
# Helpers: coercion + execution
# -----------------------------


def coerce_tool_call(event: Any) -> ToolCall:
    """Best-effort extraction of tool name/args from common event shapes."""
    if isinstance(event, ToolCall):
        return event

    if isinstance(event, Mapping):
        name = event.get("name") or event.get("tool") or event.get("tool_name") or event.get("toolName")
        args = event.get("args") or event.get("arguments") or event.get("input") or {}
        if not isinstance(name, str) or not name.strip():
            raise HookInputError("event missing tool name", code="missing_tool_name")
        if not isinstance(args, dict):
            raise HookInputError("event tool args must be a dict", code="invalid_tool_args")
        return ToolCall(name=name, args=dict(args))

    name = getattr(event, "name", None) or getattr(event, "tool_name", None) or getattr(event, "toolName", None)
    args = getattr(event, "args", None) or getattr(event, "arguments", None) or getattr(event, "input", None) or {}
    if not isinstance(name, str) or not name.strip():
        raise HookInputError("event missing tool name", code="missing_tool_name")
    if not isinstance(args, dict):
        raise HookInputError("event tool args must be a dict", code="invalid_tool_args")
    return ToolCall(name=name, args=dict(args))


def apply_before_tool_hook(plugin: P110BeforeToolHookPlugin, call: ToolCall) -> Tuple[BeforeToolDecision, ToolCall]:
    """Apply the plugin's before-tool decision and return (decision, updated_call)."""
    decision = plugin.before_tool(call)
    if decision.action == "modify" and decision.modified_args is not None:
        return decision, ToolCall(name=call.name, args=dict(decision.modified_args))
    return decision, call


def run_tool_with_before_tool_hook(
    plugin: P110BeforeToolHookPlugin,
    tool_fn: Callable[..., Any],
    call: ToolCall,
) -> Tuple[Any, BeforeToolDecision]:
    """
    Execute a tool call with a before-tool hook applied.

    Raises:
      - ToolBlockedError
      - ExternalHookFailure
      - ToolExecutionError
    """
    decision, updated_call = apply_before_tool_hook(plugin, call)
    if decision.action == "block":
        raise ToolBlockedError(decision.reason or "blocked", code="tool_blocked")

    try:
        return tool_fn(**updated_call.args), decision
    except BeforeToolHookError:
        raise
    except Exception as exc:
        raise ToolExecutionError(f"tool execution failed: {exc}", code="tool_execution_failed") from exc


def run_demo(
    *,
    plugin: P110BeforeToolHookPlugin,
    tool_fn: Callable[..., Any],
    call: ToolCall,
) -> BeforeToolDemoOutput:
    """Convenience wrapper used by CLI/tests: never raises; returns a structured envelope."""

    original_args = dict(call.args)

    try:
        decision, updated_call = apply_before_tool_hook(plugin, call)
        if decision.action == "block":
            raise ToolBlockedError(decision.reason or "blocked", code="tool_blocked")

        result = tool_fn(**updated_call.args)

        data = BeforeToolDemoData(
            tool=ToolCallReport(name=call.name, original_args=original_args, final_args=dict(updated_call.args)),
            hook=decision,
            tool_executed=True,
            tool_result=result,
        )
        return BeforeToolDemoOutput(ok=True, data=data, error=None)
    except BeforeToolHookError as exc:
        data = BeforeToolDemoData(
            tool=ToolCallReport(name=call.name, original_args=original_args, final_args=None),
            hook=BeforeToolDecision(action="block", reason=str(exc)),
            tool_executed=False,
            tool_result=None,
        )
        return BeforeToolDemoOutput(
            ok=False,
            data=data,
            error=ErrorInfo(code=getattr(exc, "code", "error"), type=type(exc).__name__, message=str(exc)),
        )
    except Exception as exc:
        # Ensure tool execution failures are deterministic and machine-readable.
        err = ToolExecutionError(f"tool execution failed: {exc}", code="tool_execution_failed")
        data = BeforeToolDemoData(
            tool=ToolCallReport(name=call.name, original_args=original_args, final_args=None),
            hook=BeforeToolDecision(action="block", reason=str(err)),
            tool_executed=False,
            tool_result=None,
        )
        return BeforeToolDemoOutput(
            ok=False,
            data=data,
            error=ErrorInfo(code=err.code, type=type(err).__name__, message=str(err)),
        )


def _stable_args_blob(args: Dict[str, Any]) -> str:
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return repr(args)


def _mutate_event_args(event: Any, new_args: Dict[str, Any]) -> None:
    if isinstance(event, dict):
        for key in ("args", "arguments", "input"):
            if key in event and isinstance(event.get(key), dict):
                event[key] = new_args
                return
        return

    for attr in ("args", "arguments", "input"):
        if hasattr(event, attr):
            try:
                setattr(event, attr, new_args)
                return
            except Exception:
                continue


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


__all__ = [
    "BeforeToolAction",
    "BeforeToolDecision",
    "BeforeToolDemoData",
    "BeforeToolDemoOutput",
    "BeforeToolHookConfig",
    "BeforeToolHookError",
    "ExternalHookFailure",
    "HookConfigError",
    "HookInputError",
    "HookRegistrationError",
    "P110BeforeToolHookPlugin",
    "ToolBlockedError",
    "ToolCall",
    "ToolExecutionError",
    "apply_before_tool_hook",
    "coerce_tool_call",
    "create_plugin",
    "get_plugin",
    "register",
    "run_demo",
    "run_tool_with_before_tool_hook",
]
