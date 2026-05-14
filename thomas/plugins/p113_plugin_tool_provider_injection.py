"""
P113 - Plugin tool provider injection

This module demonstrates Thomas-native plugin behavior where a plugin can
*inject* a tool provider into the runtime tool registry.

The goal is to validate that:
- A plugin can register a tool provider (not only individual tools).
- The injected provider's tools become discoverable/invokable through the registry.
- Failures are deterministic and machine-readable for automation.

This file intentionally avoids any OpenClaw naming reuse.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, TypedDict, runtime_checkable
from collections.abc import Mapping, Sequence

# -----------------------------
# Public contracts
# -----------------------------


class InjectionErrorCode:
    INVALID_INPUT = "invalid_input"
    MISSING_CONFIG = "missing_config"
    UNSUPPORTED_REGISTRY = "unsupported_registry"
    EXTERNAL_FAILURE = "external_failure"


@dataclass(frozen=True)
class ToolProviderInjectionRequest:
    """Input contract for a tool provider injection attempt."""

    provider_id: str
    tool_name: str
    enabled: bool = True


@dataclass(frozen=True)
class ToolProviderInjectionResult:
    """Output contract for a tool provider injection attempt."""

    ok: bool
    provider_id: str
    injected_tool_names: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        # Tuples are not JSON-serializable by default in some encoders; normalize.
        payload["injected_tool_names"] = list(self.injected_tool_names)
        return payload


# -----------------------------
# Deterministic errors
# -----------------------------


class ToolProviderInjectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class InvalidInputError(ToolProviderInjectionError):
    def __init__(self, message: str) -> None:
        super().__init__(InjectionErrorCode.INVALID_INPUT, message)


class MissingConfigError(ToolProviderInjectionError):
    def __init__(self, message: str) -> None:
        super().__init__(InjectionErrorCode.MISSING_CONFIG, message)


class UnsupportedRegistryError(ToolProviderInjectionError):
    def __init__(self, message: str) -> None:
        super().__init__(InjectionErrorCode.UNSUPPORTED_REGISTRY, message)


class ExternalFailureError(ToolProviderInjectionError):
    def __init__(self, message: str) -> None:
        super().__init__(InjectionErrorCode.EXTERNAL_FAILURE, message)


# -----------------------------
# Minimal tool/provider protocols (duck-typed)
# -----------------------------


class ToolCallParams(TypedDict, total=False):
    text: str


class ToolCallResult(TypedDict, total=False):
    echo: str
    tool: str
    provider: str


@runtime_checkable
class ToolLike(Protocol):
    name: str
    description: str

    def __call__(self, params: Mapping[str, Any]) -> Any: ...


@runtime_checkable
class ToolProviderLike(Protocol):
    """A minimal provider protocol.

    The real Thomas interfaces might differ; we implement multiple method aliases
    to be maximally compatible.
    """

    provider_id: str

    def list_tools(self) -> Sequence[Any]: ...

    def call_tool(self, tool_name: str, params: Mapping[str, Any]) -> Any: ...


# -----------------------------
# Tool + provider implementation
# -----------------------------


@dataclass
class EchoTool:
    """A tiny demo tool: echoes a `text` field."""

    name: str
    provider_id: str
    description: str = "Echo back the provided text."
    # Optional JSON schema-ish hints (safe for registries that accept dicts)
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }
    )
    output_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "echo": {"type": "string"},
                "tool": {"type": "string"},
                "provider": {"type": "string"},
            },
            "required": ["echo", "tool", "provider"],
            "additionalProperties": False,
        }
    )

    def __call__(self, params: Mapping[str, Any]) -> ToolCallResult:
        text_val = params.get("text")
        if not isinstance(text_val, str):
            raise InvalidInputError("Echo tool requires a string field 'text'.")
        return {"echo": text_val, "tool": self.name, "provider": self.provider_id}


@dataclass
class InjectedToolProvider:
    """Provides a single EchoTool.

    We expose multiple method names for compatibility with different registries.
    """

    provider_id: str
    tool: EchoTool

    # Canonical API (our own)
    def list_tools(self) -> Sequence[Any]:
        return [self.tool]

    def call_tool(self, tool_name: str, params: Mapping[str, Any]) -> Any:
        if tool_name != self.tool.name:
            raise InvalidInputError(f"Unknown tool '{tool_name}' for provider '{self.provider_id}'.")
        return self.tool(params)

    # Common aliases used by registries/frameworks
    def tools(self) -> Sequence[Any]:  # pragma: no cover - alias
        return self.list_tools()

    def get_tools(self) -> Sequence[Any]:  # pragma: no cover - alias
        return self.list_tools()

    def invoke(self, tool_name: str, params: Mapping[str, Any]) -> Any:  # pragma: no cover - alias
        return self.call_tool(tool_name, params)

    def execute(self, tool_name: str, params: Mapping[str, Any]) -> Any:  # pragma: no cover - alias
        return self.call_tool(tool_name, params)


# -----------------------------
# Injection logic
# -----------------------------


def inject_tool_provider(
    registry: Any,
    request: ToolProviderInjectionRequest,
) -> ToolProviderInjectionResult:
    """Inject a tool provider into a registry using best-effort compatibility.

    Deterministic failures:
    - INVALID_INPUT: bad types / malformed request
    - MISSING_CONFIG: disabled injection
    - UNSUPPORTED_REGISTRY: registry does not support provider registration
    - EXTERNAL_FAILURE: registry raised unexpectedly during registration
    """
    if registry is None:
        raise InvalidInputError("Registry must not be None.")

    if not isinstance(request.provider_id, str) or not request.provider_id.strip():
        raise InvalidInputError("provider_id must be a non-empty string.")
    if not isinstance(request.tool_name, str) or not request.tool_name.strip():
        raise InvalidInputError("tool_name must be a non-empty string.")
    if request.enabled is False:
        raise MissingConfigError("Injection disabled by configuration (enabled=false).")

    tool_name = request.tool_name.strip()
    provider_id = request.provider_id.strip()

    provider = InjectedToolProvider(provider_id=provider_id, tool=EchoTool(name=tool_name, provider_id=provider_id))

    # Try well-known provider registration methods first.
    register_fns: list[tuple[str, Any]] = []
    for attr in (
        "register_tool_provider",
        "register_provider",
        "add_tool_provider",
        "add_provider",
    ):
        fn = getattr(registry, attr, None)
        if callable(fn):
            register_fns.append((attr, fn))

    if not register_fns:
        raise UnsupportedRegistryError(
            "Registry does not support tool provider registration. "
            "Expected one of: register_tool_provider, register_provider, add_tool_provider, add_provider."
        )

    # Prefer the first discovered in the above priority order.
    method_name, register_fn = register_fns[0]
    try:
        try:
            register_fn(provider)
        except TypeError:
            try:
                register_fn(provider_id, provider)
            except TypeError as exc:
                raise UnsupportedRegistryError(
                    f"Registry.{method_name} has an unsupported signature; expected (provider) or (provider_id, provider)."
                ) from exc
    except ToolProviderInjectionError:
        raise
    except Exception as exc:
        raise ExternalFailureError(f"Registry.{method_name} raised {exc.__class__.__name__}.") from exc

    return ToolProviderInjectionResult(
        ok=True,
        provider_id=provider_id,
        injected_tool_names=(tool_name,),
    )




# -----------------------------
# Plugin entrypoint
# -----------------------------

# We try to integrate with whatever Thomas' plugin base class is, without hard
# dependency at import time (keeps this module importable in isolation).
try:  # pragma: no cover
    from thomas.autonomy.plugin import Plugin as _ThomasPluginBase  # type: ignore
except Exception:  # pragma: no cover
    _ThomasPluginBase = object  # fallback


@dataclass
class PluginToolProviderInjection(_ThomasPluginBase):  # type: ignore[misc]
    """Thomas plugin that injects a tool provider when registered."""

    plugin_id: str = "p113_tool_provider_injection"
    display_name: str = "P113 Tool Provider Injection"
    description: str = "Demonstrates injecting a tool provider into the tool registry."
    default_tool_name: str = "p113_echo"
    provider_id: str = "p113.injected"

    def register(self, *args: Any, **kwargs: Any) -> ToolProviderInjectionResult:
        """Register hook used by Thomas.

        We accept flexible signatures and attempt to locate a registry-like object
        among args/kwargs.
        """
        registry = _extract_registry(args, kwargs)
        tool_name = kwargs.get("tool_name", self.default_tool_name)
        enabled = bool(kwargs.get("enabled", True))
        req = ToolProviderInjectionRequest(provider_id=self.provider_id, tool_name=str(tool_name), enabled=enabled)
        return inject_tool_provider(registry, req)


def _extract_registry(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    # Common keyword names.
    for key in ("tool_registry", "registry", "tools"):
        if key in kwargs and kwargs[key] is not None:
            return kwargs[key]

    # If single positional argument looks like a registry, use it.
    if len(args) == 1:
        candidate = args[0]
        if _looks_like_registry(candidate):
            return candidate
        # Common wrapper objects
        for attr in ("tool_registry", "tools", "registry"):
            inner = getattr(candidate, attr, None)
            if inner is not None and _looks_like_registry(inner):
                return inner

    # Best-effort scan positional args for a registry-like object.
    for candidate in args:
        if _looks_like_registry(candidate):
            return candidate

    raise InvalidInputError("Could not locate a tool registry in plugin register() arguments.")


def _looks_like_registry(obj: Any) -> bool:
    if obj is None:
        return False
    for attr in ("register_tool_provider", "register_provider", "add_tool_provider", "add_provider"):
        if callable(getattr(obj, attr, None)):
            return True
    return False


# A conventional module-level handle for plugin discovery.
PLUGIN = PluginToolProviderInjection()
plugin = PLUGIN  # alias

# Additional discovery-friendly aliases used across different Thomas loaders.
PLUGIN_ID = getattr(PLUGIN, "plugin_id", "p113_tool_provider_injection")


def get_plugin() -> PluginToolProviderInjection:
    return PLUGIN


__all__ = [
    # contracts
    "InjectionErrorCode",
    "ToolProviderInjectionRequest",
    "ToolProviderInjectionResult",
    # errors
    "ToolProviderInjectionError",
    "InvalidInputError",
    "MissingConfigError",
    "UnsupportedRegistryError",
    "ExternalFailureError",
    # tool/provider
    "EchoTool",
    "InjectedToolProvider",
    # behavior
    "inject_tool_provider",
    # plugin entrypoints
    "PluginToolProviderInjection",
    "PLUGIN",
    "plugin",
    "PLUGIN_ID",
    "get_plugin",
]
