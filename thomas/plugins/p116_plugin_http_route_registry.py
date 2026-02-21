"""Plugin HTTP route registry.

This module implements an in-process registry of HTTP routes contributed by Thomas plugins.

Why this exists:
- Plugins may expose HTTP endpoints (webhooks, callbacks, admin endpoints).
- A gateway/HTTP server can mount those endpoints, but we also want a deterministic way to
  *inspect* what routes exist for debugging, parity checks, and automation.

Design principles:
- **Deterministic**: stable sorting, stable error codes, stable JSON output.
- **Simple**: a route is identified by its normalized **path**. (HTTP method selection is left
  to the hosting server/handler.)
- **Defensive**: invalid inputs, config failures, and filesystem errors produce structured,
  deterministic errors.

Public API surface:
- PluginHttpRouteRegistry: register/list/clear routes.
- load_routes_from_config(): load & register from a JSON config file.
- plugin_http_routes_output_schema(): JSON Schema for CLI automation output.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, TypedDict


# -----------------------------
# Error model (deterministic)
# -----------------------------


class PluginHttpRouteRegistryError(RuntimeError):
    """Base class for deterministic route-registry errors."""

    code: str
    details: Dict[str, Any]

    def __init__(self, *, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class InvalidRouteRegistrationError(PluginHttpRouteRegistryError):
    """Raised when a registration input is invalid."""


class DuplicateRouteError(PluginHttpRouteRegistryError):
    """Raised when attempting to register a route path twice."""


class MissingConfigError(PluginHttpRouteRegistryError):
    """Raised when a requested config file is missing or unreadable."""


class InvalidConfigError(PluginHttpRouteRegistryError):
    """Raised when a config file exists but cannot be parsed/understood."""


# Backwards-friendly aliases (tests/CLI glue may refer to these)
PluginRouteRegistryError = PluginHttpRouteRegistryError
InvalidRouteInputError = InvalidRouteRegistrationError


# -----------------------------
# Contracts
# -----------------------------


class HttpRouteRegistration(TypedDict, total=False):
    """Input contract for route registration (commonly from config)."""

    plugin_id: str
    path: str
    source: str


class PluginHttpRouteDict(TypedDict):
    plugin_id: str
    path: str
    source: Optional[str]


class ErrorPayload(TypedDict, total=False):
    code: str
    message: str
    details: Dict[str, Any]


class PluginHttpRoutesSuccess(TypedDict):
    count: int
    routes: List[PluginHttpRouteDict]


class PluginHttpRoutesFailure(TypedDict):
    error: ErrorPayload


@dataclass(frozen=True, slots=True)
class PluginHttpRoute:
    """A registered plugin HTTP route."""

    plugin_id: str
    path: str
    source: Optional[str] = None

    def to_dict(self) -> PluginHttpRouteDict:
        # Always include `source` for stable JSON output (null when unknown).
        return {"plugin_id": self.plugin_id, "path": self.path, "source": self.source}


# -----------------------------
# Normalization / validation
# -----------------------------


def _invalid(field: str, message: str, *, value: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
    details: Dict[str, Any] = {"field": field}
    if value is not None:
        details["value"] = value
    if extra:
        details.update(extra)
    raise InvalidRouteRegistrationError(code="invalid_input", message=message, details=details)


def normalize_plugin_id(plugin_id: str) -> str:
    pid = (plugin_id or "").strip()
    if not pid:
        _invalid("plugin_id", "plugin_id is required")
    return pid


def normalize_http_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        _invalid("path", "path is required")

    # Avoid hidden characters that make routes un-inspectable / ambiguous.
    if any(ord(ch) < 32 for ch in raw):
        _invalid("path", "path must not include control characters", value=raw)

    if any(ch.isspace() for ch in raw):
        _invalid("path", "path must not contain whitespace", value=raw)

    # Query/fragment are not part of a route path.
    if "?" in raw or "#" in raw:
        _invalid("path", "path must not include query string or fragment", value=raw)

    # Windows-style slashes are a sharp edge; keep canonical by rejecting.
    if "\\" in raw:
        _invalid("path", "path must not contain backslashes", value=raw)

    normalized = raw if raw.startswith("/") else f"/{raw}"

    # Prevent obviously suspicious traversal segments. This is *not* a filesystem path,
    # but `..` segments create ambiguity and can surprise proxy layers.
    segments = [seg for seg in normalized.split("/") if seg]
    if any(seg == ".." for seg in segments):
        _invalid("path", "path must not contain '..' segments", value=raw)

    return normalized


# -----------------------------
# Registry
# -----------------------------


class PluginHttpRouteRegistry:
    """Thread-safe registry for plugin HTTP routes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_path: Dict[str, PluginHttpRoute] = {}

    def clear(self) -> None:
        with self._lock:
            self._by_path.clear()

    def register(
        self,
        *,
        plugin_id: str,
        path: str,
        source: Optional[str] = None,
    ) -> PluginHttpRoute:
        """Register a single route.

        Raises DuplicateRouteError if the path is already registered.
        """
        pid = normalize_plugin_id(plugin_id)
        normalized_path = normalize_http_path(path)
        src = source.strip() if isinstance(source, str) and source.strip() else None

        with self._lock:
            existing = self._by_path.get(normalized_path)
            if existing is not None:
                raise DuplicateRouteError(
                    code="duplicate_route",
                    message=f"route already registered: {normalized_path}",
                    details={
                        "path": normalized_path,
                        "existing_plugin_id": existing.plugin_id,
                        "new_plugin_id": pid,
                    },
                )

            route = PluginHttpRoute(plugin_id=pid, path=normalized_path, source=src)
            self._by_path[normalized_path] = route
            return route

    def register_many(
        self,
        registrations: Iterable[HttpRouteRegistration],
        *,
        default_plugin_id: Optional[str] = None,
        default_source: Optional[str] = None,
    ) -> List[PluginHttpRoute]:
        """Register many routes as a single operation.

        This method validates everything first, then mutates the registry.
        If any entry is invalid (or duplicates another), the registry is not modified.
        """
        prepared: List[Tuple[str, PluginHttpRoute]] = []
        seen_paths: Dict[str, str] = {}

        for idx, reg in enumerate(registrations):
            if not isinstance(reg, dict):
                raise InvalidRouteRegistrationError(
                    code="invalid_input",
                    message="route registration must be an object",
                    details={"index": idx},
                )

            pid_raw = reg.get("plugin_id") or default_plugin_id
            path_raw = reg.get("path")
            src_raw = reg.get("source") if reg.get("source") is not None else default_source

            try:
                pid = normalize_plugin_id(str(pid_raw) if pid_raw is not None else "")
                pth = normalize_http_path(str(path_raw) if path_raw is not None else "")
            except PluginHttpRouteRegistryError as e:
                # Add context deterministically.
                details = dict(e.details)
                details.setdefault("index", idx)
                raise type(e)(code=e.code, message=str(e), details=details) from e

            src = src_raw.strip() if isinstance(src_raw, str) and src_raw.strip() else None

            if pth in seen_paths:
                raise DuplicateRouteError(
                    code="duplicate_route",
                    message=f"duplicate route in input: {pth}",
                    details={
                        "path": pth,
                        "index": idx,
                        "first_plugin_id": seen_paths[pth],
                        "new_plugin_id": pid,
                    },
                )
            seen_paths[pth] = pid

            prepared.append((pth, PluginHttpRoute(plugin_id=pid, path=pth, source=src)))

        with self._lock:
            for pth, route in prepared:
                existing = self._by_path.get(pth)
                if existing is not None:
                    raise DuplicateRouteError(
                        code="duplicate_route",
                        message=f"route already registered: {pth}",
                        details={
                            "path": pth,
                            "existing_plugin_id": existing.plugin_id,
                            "new_plugin_id": route.plugin_id,
                        },
                    )

            for pth, route in prepared:
                self._by_path[pth] = route

        prepared.sort(key=lambda item: (item[0], item[1].plugin_id))
        return [route for _, route in prepared]

    def list_routes(self, *, plugin_id: Optional[str] = None) -> List[PluginHttpRoute]:
        pid = normalize_plugin_id(plugin_id) if plugin_id is not None else None

        with self._lock:
            routes = list(self._by_path.values())

        if pid is not None:
            routes = [r for r in routes if r.plugin_id == pid]

        routes.sort(key=lambda r: (r.path, r.plugin_id))
        return routes

    # Backwards-friendly alias
    def list(self, *, plugin_id: Optional[str] = None) -> List[PluginHttpRoute]:
        return self.list_routes(plugin_id=plugin_id)

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        return plugin_http_routes_output_schema()


_DEFAULT_REGISTRY = PluginHttpRouteRegistry()


def get_default_registry() -> PluginHttpRouteRegistry:
    """Return the process-global route registry."""
    return _DEFAULT_REGISTRY


# -----------------------------
# Config loading
# -----------------------------


def _extract_routes_from_config(config: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """Extract route registrations from a config mapping.

    Supported shapes (first match wins):
    - {"plugin_http_routes": [ ... ]}
    - {"http_routes": [ ... ]}
    - {"plugins": {"http_routes": [ ... ]}}
    - {"plugins": {"http": {"routes": [ ... ]}}}
    """

    def _as_route_list(val: Any) -> Optional[Sequence[Mapping[str, Any]]]:
        if isinstance(val, list) and all(isinstance(item, dict) for item in val):
            return val  # type: ignore[return-value]
        return None

    candidates: List[Optional[Sequence[Mapping[str, Any]]]] = [
        _as_route_list(config.get("plugin_http_routes")),
        _as_route_list(config.get("http_routes")),
    ]

    plugins = config.get("plugins")
    if isinstance(plugins, dict):
        candidates.append(_as_route_list(plugins.get("http_routes")))
        http = plugins.get("http")
        if isinstance(http, dict):
            candidates.append(_as_route_list(http.get("routes")))

    for candidate in candidates:
        if candidate is not None:
            return candidate

    return []


def load_routes_from_json_config(
    config_path: Path,
    *,
    registry: Optional[PluginHttpRouteRegistry] = None,
    default_plugin_id: Optional[str] = None,
    default_source: Optional[str] = None,
) -> List[PluginHttpRoute]:
    """Load route registrations from a JSON config file."""

    if not isinstance(config_path, Path):
        config_path = Path(str(config_path))

    if not config_path.exists():
        raise MissingConfigError(
            code="missing_config",
            message=f"config file not found: {config_path}",
            details={"path": str(config_path)},
        )

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as e:
        raise MissingConfigError(
            code="config_read_failed",
            message=f"failed to read config file: {config_path}",
            details={"path": str(config_path), "reason": str(e)},
        ) from e

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise InvalidConfigError(
            code="invalid_config",
            message=f"config file is not valid JSON: {config_path}",
            details={"path": str(config_path), "line": e.lineno, "col": e.colno},
        ) from e

    if not isinstance(parsed, dict):
        raise InvalidConfigError(
            code="invalid_config",
            message="config root must be a JSON object",
            details={"path": str(config_path)},
        )

    entries = _extract_routes_from_config(parsed)
    reg = registry or get_default_registry()

    # Validate required keys for a deterministic config-error category.
    prepared: List[HttpRouteRegistration] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InvalidConfigError(
                code="invalid_config",
                message="route entries must be objects",
                details={"index": idx},
            )

        pid = entry.get("plugin_id") or entry.get("pluginId") or default_plugin_id
        path = entry.get("path")
        src = entry.get("source") if entry.get("source") is not None else default_source

        if not pid:
            raise InvalidConfigError(
                code="invalid_config",
                message="route entry missing plugin_id",
                details={"index": idx, "path": path},
            )
        if not path:
            raise InvalidConfigError(
                code="invalid_config",
                message="route entry missing path",
                details={"index": idx, "plugin_id": pid},
            )

        prepared.append(
            {
                "plugin_id": str(pid),
                "path": str(path),
                # register_many treats empty-string source as None
                "source": str(src) if src else "",
            }
        )

    # Atomic registration: do not partially mutate registry if later entries fail.
    return reg.register_many(
        prepared,
        default_plugin_id=default_plugin_id,
        default_source=default_source,
    )


def load_routes_from_config(
    config_path: Path,
    *,
    registry: Optional[PluginHttpRouteRegistry] = None,
    default_plugin_id: Optional[str] = None,
    default_source: Optional[str] = None,
) -> List[PluginHttpRoute]:
    """Compatibility alias for config-based route loading."""

    return load_routes_from_json_config(
        config_path,
        registry=registry,
        default_plugin_id=default_plugin_id,
        default_source=default_source,
    )


# -----------------------------
# Schema
# -----------------------------


def plugin_http_routes_output_schema() -> Dict[str, Any]:
    """JSON Schema for the CLI `--json` output.

    The CLI emits either:
    - success: {"count": <int>, "routes": [ {plugin_id, path, source}, ... ]}
    - error:   {"error": {"code": <str>, "message": <str>, "details": {...}}}
    """

    route_obj = {
        "type": "object",
        "additionalProperties": False,
        "required": ["plugin_id", "path", "source"],
        "properties": {
            "plugin_id": {"type": "string", "minLength": 1},
            "path": {"type": "string", "pattern": r"^/"},
            "source": {"type": ["string", "null"]},
        },
    }

    success_obj = {
        "type": "object",
        "additionalProperties": False,
        "required": ["count", "routes"],
        "properties": {
            "count": {"type": "integer", "minimum": 0},
            "routes": {"type": "array", "items": route_obj},
        },
    }

    error_obj = {
        "type": "object",
        "additionalProperties": False,
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string", "minLength": 1},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                },
            }
        },
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Thomas plugin HTTP routes output",
        "oneOf": [success_obj, error_obj],
    }
