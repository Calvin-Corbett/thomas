from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

GatewayHandler = Callable[..., Any]

_HANDLER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class GatewayHandlerRegistryError(RuntimeError):
    """Deterministic errors for gateway handler registry operations."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details) if details is not None else None
        super().__init__(self._format())

    def _format(self) -> str:
        if not self.details:
            return f"{self.code}: {self.message}"
        # stable repr for tests/logs
        return f"{self.code}: {self.message} | details={json.dumps(self.details, sort_keys=True, ensure_ascii=True)}"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True, slots=True)
class GatewayHandlerSpec:
    name: str
    plugin_id: str | None = None
    description: str | None = None
    input_schema: Mapping[str, Any] | None = None
    output_schema: Mapping[str, Any] | None = None
    source: str | None = None
    is_core: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "plugin_id": self.plugin_id,
            "description": self.description,
            "input_schema": _make_jsonable(self.input_schema),
            "output_schema": _make_jsonable(self.output_schema),
            "source": self.source,
            "is_core": self.is_core,
        }


@dataclass(frozen=True, slots=True)
class GatewayHandlerEntry:
    spec: GatewayHandlerSpec
    handler: GatewayHandler


@dataclass(frozen=True, slots=True)
class GatewayHandlerRegistrySnapshot:
    handlers: tuple[GatewayHandlerSpec, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"handlers": [h.to_dict() for h in self.handlers]}


@dataclass(frozen=True, slots=True)
class GatewayHandlerRegistryConfig:
    plugin_modules: tuple[str, ...]
    allow_overrides: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"plugin_modules": list(self.plugin_modules), "allow_overrides": self.allow_overrides}


def _make_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _make_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_jsonable(v) for v in value]
    # last resort: deterministic string
    return str(value)


def _normalize_handler_name(raw: Any) -> str:
    if not isinstance(raw, str):
        raise GatewayHandlerRegistryError(
            "invalid_handler_name",
            "handler name must be a string",
            details={"type": type(raw).__name__},
        )
    name = raw.strip()
    if not name:
        raise GatewayHandlerRegistryError("invalid_handler_name", "handler name is required")
    if not _HANDLER_NAME_RE.fullmatch(name):
        raise GatewayHandlerRegistryError(
            "invalid_handler_name",
            "handler name contains invalid characters",
            details={"name": name},
        )
    return name


class GatewayHandlerRegistry:
    """In-memory registry for gateway handlers (core + plugin)."""

    def __init__(self, *, core_handlers: Mapping[str, GatewayHandler] | None = None):
        self._core: dict[str, GatewayHandlerEntry] = {}
        self._plugin: dict[str, GatewayHandlerEntry] = {}

        if core_handlers:
            for raw_name, handler in core_handlers.items():
                name = _normalize_handler_name(raw_name)
                if not callable(handler):
                    raise GatewayHandlerRegistryError(
                        "invalid_handler",
                        "core handler must be callable",
                        details={"name": name},
                    )
                spec = GatewayHandlerSpec(name=name, is_core=True)
                self._core[name] = GatewayHandlerEntry(spec=spec, handler=handler)

    def register(
        self,
        name: str,
        handler: GatewayHandler,
        *,
        plugin_id: str | None = None,
        description: str | None = None,
        input_schema: Mapping[str, Any] | None = None,
        output_schema: Mapping[str, Any] | None = None,
        source: str | None = None,
        allow_override: bool = False,
    ) -> GatewayHandlerSpec:
        normalized = _normalize_handler_name(name)
        if not callable(handler):
            raise GatewayHandlerRegistryError(
                "invalid_handler",
                "handler must be callable",
                details={"name": normalized},
            )

        if normalized in self._core:
            raise GatewayHandlerRegistryError(
                "handler_already_registered",
                "handler name is reserved by core",
                details={"name": normalized},
            )

        if (not allow_override) and normalized in self._plugin:
            raise GatewayHandlerRegistryError(
                "handler_already_registered",
                "handler already registered",
                details={"name": normalized},
            )

        normalized_plugin_id = plugin_id.strip() if isinstance(plugin_id, str) and plugin_id.strip() else None
        spec = GatewayHandlerSpec(
            name=normalized,
            plugin_id=normalized_plugin_id,
            description=description.strip() if isinstance(description, str) and description.strip() else None,
            input_schema=input_schema,
            output_schema=output_schema,
            source=source,
            is_core=False,
        )
        self._plugin[normalized] = GatewayHandlerEntry(spec=spec, handler=handler)
        return spec

    def get(self, name: str) -> GatewayHandler:
        normalized = _normalize_handler_name(name)
        entry = self._plugin.get(normalized) or self._core.get(normalized)
        if not entry:
            raise GatewayHandlerRegistryError(
                "handler_not_found",
                "handler not found",
                details={"name": normalized},
            )
        return entry.handler

    def get_spec(self, name: str) -> GatewayHandlerSpec:
        normalized = _normalize_handler_name(name)
        entry = self._plugin.get(normalized) or self._core.get(normalized)
        if not entry:
            raise GatewayHandlerRegistryError(
                "handler_not_found",
                "handler not found",
                details={"name": normalized},
            )
        return entry.spec

    def list_specs(self, *, include_core: bool = True) -> list[GatewayHandlerSpec]:
        specs: list[GatewayHandlerSpec] = []
        if include_core:
            specs.extend([entry.spec for entry in self._core.values()])
        specs.extend([entry.spec for entry in self._plugin.values()])
        # deterministic ordering: core first, then name
        return sorted(specs, key=lambda s: (0 if s.is_core else 1, s.name))

    def snapshot(self, *, include_core: bool = True) -> GatewayHandlerRegistrySnapshot:
        return GatewayHandlerRegistrySnapshot(handlers=tuple(self.list_specs(include_core=include_core)))

    def invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        handler = self.get(name)
        try:
            return handler(*args, **kwargs)
        except GatewayHandlerRegistryError:
            raise
        except Exception as exc:
            raise GatewayHandlerRegistryError(
                "handler_failed",
                "handler raised an exception",
                details={
                    "name": _normalize_handler_name(name),
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            ) from exc


def parse_gateway_handler_registry_config(raw: Mapping[str, Any] | None) -> GatewayHandlerRegistryConfig:
    if raw is None:
        raise GatewayHandlerRegistryError("missing_config", "missing gateway handler registry config")

    # Accept multiple key names to be more forgiving for callers.
    modules = raw.get("plugin_modules")
    if modules is None:
        modules = raw.get("plugins")

    if modules is None:
        raise GatewayHandlerRegistryError(
            "missing_config",
            "config missing required key 'plugin_modules'",
            details={"expected_key": "plugin_modules"},
        )

    if not isinstance(modules, (list, tuple)):
        raise GatewayHandlerRegistryError(
            "invalid_config",
            "plugin_modules must be a list of strings",
            details={"type": type(modules).__name__},
        )

    cleaned: list[str] = []
    for item in modules:
        if not isinstance(item, str) or not item.strip():
            raise GatewayHandlerRegistryError(
                "invalid_config",
                "plugin_modules must contain non-empty strings",
                details={"bad_value_type": type(item).__name__},
            )
        cleaned.append(item.strip())

    allow_overrides = bool(raw.get("allow_overrides", False))

    return GatewayHandlerRegistryConfig(plugin_modules=tuple(cleaned), allow_overrides=allow_overrides)


def build_gateway_handler_registry_from_config(
    raw: Mapping[str, Any] | None,
    *,
    core_handlers: Mapping[str, GatewayHandler] | None = None,
) -> GatewayHandlerRegistry:
    cfg = parse_gateway_handler_registry_config(raw)
    registry = GatewayHandlerRegistry(core_handlers=core_handlers)
    load_gateway_handlers_from_modules(
        registry,
        cfg.plugin_modules,
        allow_overrides=cfg.allow_overrides,
    )
    return registry


def load_gateway_handlers_from_modules(
    registry: GatewayHandlerRegistry,
    module_names: Sequence[str],
    *,
    allow_overrides: bool = False,
) -> None:
    for module_name in module_names:
        if not isinstance(module_name, str) or not module_name.strip():
            raise GatewayHandlerRegistryError(
                "invalid_config",
                "plugin module name must be a non-empty string",
                details={"module": str(module_name)},
            )
        module_name = module_name.strip()

        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            raise GatewayHandlerRegistryError(
                "plugin_import_failed",
                "failed to import plugin module",
                details={
                    "module": module_name,
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            ) from exc

        # Preferred: explicit registration hook
        register_fn = getattr(mod, "register_gateway_handlers", None)
        if callable(register_fn):
            try:
                register_fn(registry)
            except GatewayHandlerRegistryError:
                raise
            except Exception as exc:
                raise GatewayHandlerRegistryError(
                    "plugin_registration_failed",
                    "plugin failed while registering gateway handlers",
                    details={
                        "module": module_name,
                        "exception_type": type(exc).__name__,
                        "exception": str(exc),
                    },
                ) from exc
            continue

        # Conventional: mapping export.
        mapping = None
        for attr in ("GATEWAY_HANDLERS", "gateway_handlers", "GATEWAY_HANDLER_MAP"):
            if hasattr(mod, attr):
                mapping = getattr(mod, attr)
                break

        if mapping is None:
            raise GatewayHandlerRegistryError(
                "plugin_missing_handlers",
                "plugin module did not expose gateway handlers",
                details={
                    "module": module_name,
                    "expected": ["register_gateway_handlers", "GATEWAY_HANDLERS"],
                },
            )

        if not isinstance(mapping, Mapping):
            raise GatewayHandlerRegistryError(
                "invalid_plugin_handlers",
                "gateway handler export must be a mapping",
                details={"module": module_name, "type": type(mapping).__name__},
            )

        plugin_id = None
        for attr in ("PLUGIN_ID", "plugin_id", "ID", "id"):
            value = getattr(mod, attr, None)
            if isinstance(value, str) and value.strip():
                plugin_id = value.strip()
                break
        if not plugin_id:
            plugin_id = module_name

        for raw_name, raw_value in mapping.items():
            handler_name = _normalize_handler_name(raw_name)

            handler: GatewayHandler | None = None
            description: str | None = None
            input_schema: Mapping[str, Any] | None = None
            output_schema: Mapping[str, Any] | None = None
            source: str | None = getattr(mod, "__file__", None)

            if callable(raw_value):
                handler = raw_value
            elif isinstance(raw_value, Mapping):
                maybe_handler = raw_value.get("handler")
                if callable(maybe_handler):
                    handler = maybe_handler
                description = raw_value.get("description") if isinstance(raw_value.get("description"), str) else None
                input_schema = (
                    raw_value.get("input_schema") if isinstance(raw_value.get("input_schema"), Mapping) else None
                )
                output_schema = (
                    raw_value.get("output_schema") if isinstance(raw_value.get("output_schema"), Mapping) else None
                )
            elif (
                isinstance(raw_value, tuple)
                and len(raw_value) == 2
                and callable(raw_value[0])
                and isinstance(raw_value[1], str)
            ):
                handler = raw_value[0]
                description = raw_value[1]

            if handler is None:
                raise GatewayHandlerRegistryError(
                    "invalid_plugin_handlers",
                    "handler definition must be a callable or a mapping with 'handler'",
                    details={"module": module_name, "name": handler_name},
                )

            registry.register(
                handler_name,
                handler,
                plugin_id=plugin_id,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                source=source,
                allow_override=allow_overrides,
            )


# A process-wide default registry. Gateways can inject core handlers when constructing their own instance.
_DEFAULT_REGISTRY = GatewayHandlerRegistry()


def get_gateway_handler_registry() -> GatewayHandlerRegistry:
    return _DEFAULT_REGISTRY


@dataclass(frozen=True, slots=True)
class PluginGatewayHandlerRegistry:
    """Thomas plugin wrapper that exposes the gateway handler registry to the host runtime."""

    plugin_id: str = "p115.plugin_gateway_handler_registry"
    name: str = "Gateway handler registry"
    description: str = "Registry for gateway handlers contributed by plugins."

    def register(self, api: Any) -> None:
        # Best-effort integration: attach the registry if the host exposes a hook for it.
        setter = getattr(api, "set_gateway_handler_registry", None)
        if callable(setter):
            try:
                setter(get_gateway_handler_registry())
            except Exception as exc:
                raise GatewayHandlerRegistryError(
                    "external_failure",
                    "host rejected gateway handler registry",
                    details={"exception_type": type(exc).__name__, "exception": str(exc)},
                ) from exc


PLUGIN = PluginGatewayHandlerRegistry()
plugin = PLUGIN
PLUGIN_ID = PLUGIN.plugin_id


def get_plugin() -> PluginGatewayHandlerRegistry:
    return PLUGIN


def register(api: Any | None = None, *args: Any, **kwargs: Any) -> None:
    """Entry point for plugin loaders that expect a module-level register()/activate() function."""
    _ = (args, kwargs)
    if api is None:
        return
    PLUGIN.register(api)


# Common alias names used by different plugin loader conventions.
activate = register
setup = register
