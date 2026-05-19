from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ServiceLifecycleError(Exception):
    """Deterministic error for service lifecycle operations.

    The `code` field is stable and intended for automation.
    """

    code: str
    details: Mapping[str, Any]

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": dict(self.details)}


class InvalidInputError(ServiceLifecycleError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code="invalid_input", message=message, details=details)


class MissingConfigError(ServiceLifecycleError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code="missing_config", message=message, details=details)


class ExternalFailureError(ServiceLifecycleError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code="external_failure", message=message, details=details)


class ServiceState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    FAILED = "failed"


class LifecycleAction(str, Enum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    STATUS = "status"
    LIST = "list"


StartFn = Callable[[], Awaitable[None] | None]
StopFn = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True)
class ServiceDefinition:
    """Definition of a background service provided by a plugin (or core)."""

    service_id: str
    start: StartFn
    stop: StopFn
    description: str | None = None


@dataclass
class ServiceStatus:
    service_id: str
    state: ServiceState = ServiceState.STOPPED
    started_at_epoch_s: float | None = None
    stopped_at_epoch_s: float | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "state": self.state.value,
            "started_at_epoch_s": self.started_at_epoch_s,
            "stopped_at_epoch_s": self.stopped_at_epoch_s,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class ServiceLifecycleRequest:
    """Contract for lifecycle operations (tool / gateway / CLI friendly)."""

    action: LifecycleAction
    service_id: str | None = None
    timeout_s: float | None = None


@dataclass
class ServiceLifecycleResponse:
    ok: bool
    services: list[ServiceStatus] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "services": [s.to_dict() for s in self.services], "error": self.error}


SERVICE_LIFECYCLE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action"],
    "properties": {
        "action": {"type": "string", "enum": [a.value for a in LifecycleAction]},
        "service_id": {"type": ["string", "null"]},
        "timeout_s": {"type": ["number", "null"], "minimum": 0},
    },
}

SERVICE_LIFECYCLE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok", "services"],
    "properties": {
        "ok": {"type": "boolean"},
        "services": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["service_id", "state"],
                "properties": {
                    "service_id": {"type": "string"},
                    "state": {"type": "string", "enum": [s.value for s in ServiceState]},
                    "started_at_epoch_s": {"type": ["number", "null"]},
                    "stopped_at_epoch_s": {"type": ["number", "null"]},
                    "last_error": {"type": ["string", "null"]},
                },
            },
        },
        "error": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["code", "message", "details"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
            },
        },
    },
}


async def _maybe_await(result: Awaitable[None] | None, *, timeout_s: float | None) -> None:
    if result is None:
        return
    if timeout_s is None:
        await result
    else:
        await asyncio.wait_for(result, timeout=timeout_s)


def _sanitize_exception(exc: BaseException) -> str:
    """Return a deterministic exception marker for status surfaces."""
    return type(exc).__name__


class PluginServiceLifecycleManager:
    """Starts/stops plugin-defined background services with deterministic behavior."""

    def __init__(self, services: Iterable[ServiceDefinition] | None = None) -> None:
        self._services: dict[str, ServiceDefinition] = {}
        self._status: dict[str, ServiceStatus] = {}
        if services:
            for svc in services:
                self.register_service(svc)

    def register_service(self, service: ServiceDefinition) -> None:
        service_id = (service.service_id or "").strip()
        if not service_id:
            raise InvalidInputError(
                "Service id must be a non-empty string.", details={"service_id": service.service_id}
            )
        self._services[service_id] = service
        self._status.setdefault(service_id, ServiceStatus(service_id=service_id))

    def list_services(self) -> list[str]:
        return sorted(self._services.keys())

    def status(self, service_id: str) -> ServiceStatus:
        self._ensure_known(service_id)
        return self._status[service_id]

    def list_status(self) -> list[ServiceStatus]:
        return [self._status[sid] for sid in self.list_services()]

    async def start(self, service_id: str, *, timeout_s: float | None = None) -> ServiceStatus:
        svc = self._get(service_id)
        st = self._status[service_id]
        if st.state == ServiceState.RUNNING:
            return st  # idempotent

        try:
            await _maybe_await(svc.start(), timeout_s=timeout_s)
        except Exception as exc:  # noqa: BLE001
            st.state = ServiceState.FAILED
            st.last_error = _sanitize_exception(exc)
            st.stopped_at_epoch_s = time.time()
            raise ExternalFailureError(
                "Service failed to start.",
                details={"service_id": service_id, "exception_type": type(exc).__name__},
            ) from None

        st.state = ServiceState.RUNNING
        st.started_at_epoch_s = time.time()
        st.stopped_at_epoch_s = None
        st.last_error = None
        return st

    async def stop(self, service_id: str, *, timeout_s: float | None = None) -> ServiceStatus:
        svc = self._get(service_id)
        st = self._status[service_id]
        if st.state == ServiceState.STOPPED:
            return st  # idempotent

        try:
            await _maybe_await(svc.stop(), timeout_s=timeout_s)
        except Exception as exc:  # noqa: BLE001
            st.state = ServiceState.FAILED
            st.last_error = _sanitize_exception(exc)
            st.stopped_at_epoch_s = time.time()
            raise ExternalFailureError(
                "Service failed to stop.",
                details={"service_id": service_id, "exception_type": type(exc).__name__},
            ) from None

        st.state = ServiceState.STOPPED
        st.stopped_at_epoch_s = time.time()
        return st

    async def restart(self, service_id: str, *, timeout_s: float | None = None) -> ServiceStatus:
        await self.stop(service_id, timeout_s=timeout_s)
        return await self.start(service_id, timeout_s=timeout_s)

    async def start_all(self, *, timeout_s: float | None = None) -> list[ServiceStatus]:
        if not self._services:
            raise MissingConfigError("No services are registered.")
        started: list[str] = []
        try:
            for sid in self.list_services():
                await self.start(sid, timeout_s=timeout_s)
                started.append(sid)
        except ServiceLifecycleError:
            # Roll back any partial start, best-effort.
            for sid in reversed(started):
                try:
                    await self.stop(sid, timeout_s=timeout_s)
                except ServiceLifecycleError:
                    pass
            raise
        return self.list_status()

    async def stop_all(self, *, timeout_s: float | None = None) -> list[ServiceStatus]:
        if not self._services:
            raise MissingConfigError("No services are registered.")
        for sid in reversed(self.list_services()):
            await self.stop(sid, timeout_s=timeout_s)
        return self.list_status()

    def _ensure_known(self, service_id: str) -> None:
        if service_id not in self._services:
            raise InvalidInputError("Unknown service id.", details={"service_id": service_id})

    def _get(self, service_id: str) -> ServiceDefinition:
        if not self._services:
            raise MissingConfigError("No services are registered.")
        self._ensure_known(service_id)
        return self._services[service_id]


async def apply_lifecycle_request(
    manager: PluginServiceLifecycleManager, request: ServiceLifecycleRequest
) -> ServiceLifecycleResponse:
    """Apply a lifecycle request against a manager and return a structured response."""
    try:
        if request.action == LifecycleAction.LIST:
            return ServiceLifecycleResponse(ok=True, services=manager.list_status())

        if request.action == LifecycleAction.STATUS:
            if not request.service_id:
                raise InvalidInputError("service_id is required for status.", details={"action": request.action.value})
            return ServiceLifecycleResponse(ok=True, services=[manager.status(request.service_id)])

        if request.action == LifecycleAction.START:
            if not request.service_id:
                raise InvalidInputError("service_id is required for start.", details={"action": request.action.value})
            st = await manager.start(request.service_id, timeout_s=request.timeout_s)
            return ServiceLifecycleResponse(ok=True, services=[st])

        if request.action == LifecycleAction.STOP:
            if not request.service_id:
                raise InvalidInputError("service_id is required for stop.", details={"action": request.action.value})
            st = await manager.stop(request.service_id, timeout_s=request.timeout_s)
            return ServiceLifecycleResponse(ok=True, services=[st])

        if request.action == LifecycleAction.RESTART:
            if not request.service_id:
                raise InvalidInputError("service_id is required for restart.", details={"action": request.action.value})
            st = await manager.restart(request.service_id, timeout_s=request.timeout_s)
            return ServiceLifecycleResponse(ok=True, services=[st])

        raise InvalidInputError("Unknown action.", details={"action": request.action.value})
    except ServiceLifecycleError as exc:
        return ServiceLifecycleResponse(ok=False, services=[], error=exc.to_dict())


def parse_lifecycle_request(data: Mapping[str, Any]) -> ServiceLifecycleRequest:
    """Parse an untrusted mapping into a typed request with deterministic errors."""
    action_raw = data.get("action")
    if not isinstance(action_raw, str) or not action_raw.strip():
        raise InvalidInputError("action must be a non-empty string.", details={"action": action_raw})

    try:
        action = LifecycleAction(action_raw)
    except ValueError:
        raise InvalidInputError("Unknown action.", details={"action": action_raw}) from None

    service_id = data.get("service_id")
    if service_id is not None and not isinstance(service_id, str):
        raise InvalidInputError("service_id must be a string or null.", details={"service_id": service_id})

    timeout_s = data.get("timeout_s")
    if timeout_s is not None and not isinstance(timeout_s, (int, float)):
        raise InvalidInputError("timeout_s must be a number or null.", details={"timeout_s": timeout_s})
    if isinstance(timeout_s, (int, float)) and timeout_s < 0:
        raise InvalidInputError("timeout_s must be >= 0.", details={"timeout_s": timeout_s})

    return ServiceLifecycleRequest(
        action=action,
        service_id=service_id,
        timeout_s=float(timeout_s) if isinstance(timeout_s, (int, float)) else None,
    )


# Thomas-native tool surface (best-effort integration with ToolRegistry-like objects).
SERVICE_LIFECYCLE_TOOL_NAME = "plugins.service_lifecycle"
SERVICE_LIFECYCLE_TOOL_DESCRIPTION = "Manage lifecycle of plugin-defined background services."


async def handle_lifecycle_payload(
    manager: PluginServiceLifecycleManager, payload: Mapping[str, Any]
) -> dict[str, Any]:
    req = parse_lifecycle_request(payload)
    resp = await apply_lifecycle_request(manager, req)
    return resp.to_dict()


def handle_lifecycle_payload_sync(manager: PluginServiceLifecycleManager, payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(handle_lifecycle_payload(manager, payload))
    raise ExternalFailureError(
        "Cannot run lifecycle handler in sync mode while an event loop is already running.",
        details={"tool": SERVICE_LIFECYCLE_TOOL_NAME},
    )


def _try_register_tool(registry: Any, *, manager: PluginServiceLifecycleManager) -> None:
    """Register the lifecycle tool against a registry-like object (duck-typed).

    This intentionally avoids hard dependencies on a single ToolRegistry API.
    """
    tool_payload: dict[str, Any] = {
        "name": SERVICE_LIFECYCLE_TOOL_NAME,
        "description": SERVICE_LIFECYCLE_TOOL_DESCRIPTION,
        "input_schema": SERVICE_LIFECYCLE_REQUEST_SCHEMA,
        "output_schema": SERVICE_LIFECYCLE_RESPONSE_SCHEMA,
        "handler": lambda payload: handle_lifecycle_payload(manager, payload),
        "handler_sync": lambda payload: handle_lifecycle_payload_sync(manager, payload),
    }
    # Common patterns: registry.tools is a dict
    tools_attr = getattr(registry, "tools", None)
    if isinstance(tools_attr, dict):
        tools_attr[SERVICE_LIFECYCLE_TOOL_NAME] = tool_payload
        return
    # Common patterns: register_tool(name, tool) / register(tool) / add_tool(...)
    for method_name in ("register_tool", "register", "add_tool", "add"):
        fn = getattr(registry, method_name, None)
        if fn is None or not callable(fn):
            continue
        try:
            fn(SERVICE_LIFECYCLE_TOOL_NAME, tool_payload)
            return
        except TypeError:
            pass
        try:
            fn(tool_payload)
            return
        except TypeError:
            pass

        # Keyword-based attempts
        try:
            fn(name=SERVICE_LIFECYCLE_TOOL_NAME, tool=tool_payload)
            return
        except TypeError:
            pass
        try:
            fn(
                name=SERVICE_LIFECYCLE_TOOL_NAME,
                handler=tool_payload["handler"],
                input_schema=SERVICE_LIFECYCLE_REQUEST_SCHEMA,
                output_schema=SERVICE_LIFECYCLE_RESPONSE_SCHEMA,
                description=SERVICE_LIFECYCLE_TOOL_DESCRIPTION,
            )
            return
        except TypeError:
            pass
    # If we can't register, fail silently: host might not expose a registry here.
    return


class PluginServiceLifecycleManagerPlugin:
    """Plugin entrypoint exposing a lifecycle manager + tool registration."""

    plugin_id = "plugin-service-lifecycle-manager"
    display_name = "Plugin service lifecycle manager"

    def __init__(self) -> None:
        self.manager = PluginServiceLifecycleManager()

    def register(self, api: Any) -> None:  # pragma: no cover
        # Expose manager to the host runtime.
        try:
            api.plugin_service_manager = self.manager
        except Exception:
            pass

        # Best-effort tool registration.
        registry = getattr(api, "tool_registry", None) or getattr(api, "tools", None) or api
        try:
            _try_register_tool(registry, manager=self.manager)
        except Exception:
            # Never hard-fail plugin import/registration due to registry wiring differences.
            pass

    def register_tools(self, registry: Any) -> None:  # pragma: no cover
        _try_register_tool(registry, manager=self.manager)


# Multiple discovery patterns to maximize compatibility with existing plugin loaders.
PLUGIN = PluginServiceLifecycleManagerPlugin()
plugin = PLUGIN  # alternate discovery alias


def get_plugin() -> PluginServiceLifecycleManagerPlugin:  # pragma: no cover
    return PLUGIN


def register(api: Any) -> None:  # pragma: no cover
    PLUGIN.register(api)
