from __future__ import annotations

import json
import os
import re
import time
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence, TypedDict


"""
P122 - Plugin lifecycle commands (runtime-backed)

This module provides a runtime-backed control plane for plugins via a running
Thomas gateway.

Design goals:
- Deterministic, machine-readable errors (stable `code` strings)
- Stable JSON output contract for automation
- Runtime-backed behavior (talk to a running gateway; do not assume local-only state)
- Conservative dependencies (standard library only)
"""

PluginLifecycleAction = Literal["list", "status", "start", "stop", "restart"]

DEFAULT_TIMEOUT_S: float = 5.0


# ------------------------------
# Contracts
# ------------------------------


class ErrorInfoDict(TypedDict, total=False):
    code: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> ErrorInfoDict:
        data: ErrorInfoDict = {"code": self.code, "message": self.message}
        if self.details:
            data["details"] = dict(self.details)
        return data


class PluginStateDict(TypedDict, total=False):
    name: str
    status: str
    version: str
    description: str
    meta: dict[str, Any]


@dataclass(frozen=True)
class PluginState:
    """Runtime-observed plugin state."""

    name: str
    status: Literal["running", "stopped", "unknown"]
    version: str | None = None
    description: str | None = None
    meta: Mapping[str, Any] | None = None

    def to_dict(self) -> PluginStateDict:
        out: PluginStateDict = {"name": self.name, "status": self.status}
        if self.version is not None:
            out["version"] = self.version
        if self.description is not None:
            out["description"] = self.description
        if self.meta:
            out["meta"] = dict(self.meta)
        return out


class PluginLifecycleResultDict(TypedDict, total=False):
    ok: bool
    action: str
    plugin: str | None
    runtime: dict[str, Any]
    plugins: list[PluginStateDict]
    plugin_state: PluginStateDict
    error: ErrorInfoDict


@dataclass(frozen=True)
class PluginLifecycleRequest:
    action: PluginLifecycleAction
    plugin: str | None = None
    gateway_url: str | None = None
    config_path: Path | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S


@dataclass(frozen=True)
class PluginLifecycleResult:
    ok: bool
    action: PluginLifecycleAction
    plugin: str | None = None
    runtime: Mapping[str, Any] = field(default_factory=dict)
    plugins: tuple[PluginState, ...] = ()
    plugin_state: PluginState | None = None
    error: ErrorInfo | None = None

    def to_dict(self) -> PluginLifecycleResultDict:
        out: PluginLifecycleResultDict = {
            "ok": self.ok,
            "action": self.action,
            "plugin": self.plugin,
            "runtime": dict(self.runtime),
        }
        if self.plugins:
            out["plugins"] = [p.to_dict() for p in self.plugins]
        if self.plugin_state is not None:
            out["plugin_state"] = self.plugin_state.to_dict()
        if self.error is not None:
            out["error"] = self.error.to_dict()
        return out


# ------------------------------
# Deterministic errors
# ------------------------------


class PluginLifecycleError(RuntimeError):
    """Base error for plugin lifecycle operations.

    The `code` field is intended to be stable for automation.
    """

    code: str
    details: Mapping[str, Any] | None

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details

    def to_error_info(self) -> ErrorInfo:
        return ErrorInfo(code=self.code, message=str(self), details=self.details)


class InvalidPluginLifecycleRequest(PluginLifecycleError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="invalid_request", message=message, details=details)


class MissingPluginRuntimeConfig(PluginLifecycleError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="missing_runtime_config", message=message, details=details)


class RuntimeUnavailable(PluginLifecycleError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="runtime_unavailable", message=message, details=details)


class RuntimeResponseError(PluginLifecycleError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="runtime_response_error", message=message, details=details)


class PluginNotFound(PluginLifecycleError):
    def __init__(self, plugin: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="plugin_not_found", message=f"Plugin not found: {plugin}", details=details)


class RuntimeOperationFailed(PluginLifecycleError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="runtime_operation_failed", message=message, details=details)


# ------------------------------
# Public API
# ------------------------------


_PLUGIN_ID_PATTERN = re.compile(r"^[^\s]+$")


def run_plugin_lifecycle(request: PluginLifecycleRequest) -> PluginLifecycleResult:
    """Run a plugin lifecycle operation using a runtime backend."""
    _validate_request(request)

    gateway_url, source = resolve_gateway_url(
        explicit_gateway_url=request.gateway_url,
        config_path=request.config_path,
    )

    base_url = _normalize_base_url(gateway_url)
    runtime_meta: dict[str, Any] = {"backend": "http", "gateway_url": base_url, "resolved_from": source}

    try:
        if request.action == "list":
            plugins = _gateway_list_plugins(base_url, timeout_s=request.timeout_s)
            return PluginLifecycleResult(ok=True, action=request.action, runtime=runtime_meta, plugins=tuple(plugins))

        assert request.plugin is not None
        if request.action == "status":
            plugin_state = _gateway_get_status(base_url, request.plugin, timeout_s=request.timeout_s)
            return PluginLifecycleResult(
                ok=True,
                action=request.action,
                plugin=request.plugin,
                runtime=runtime_meta,
                plugin_state=plugin_state,
            )

        if request.action == "start":
            plugin_state = _gateway_post_lifecycle(base_url, request.plugin, "start", timeout_s=request.timeout_s)
            return PluginLifecycleResult(ok=True, action=request.action, plugin=request.plugin, runtime=runtime_meta, plugin_state=plugin_state)

        if request.action == "stop":
            plugin_state = _gateway_post_lifecycle(base_url, request.plugin, "stop", timeout_s=request.timeout_s)
            return PluginLifecycleResult(ok=True, action=request.action, plugin=request.plugin, runtime=runtime_meta, plugin_state=plugin_state)

        if request.action == "restart":
            plugin_state = _gateway_post_lifecycle(base_url, request.plugin, "restart", timeout_s=request.timeout_s)
            return PluginLifecycleResult(ok=True, action=request.action, plugin=request.plugin, runtime=runtime_meta, plugin_state=plugin_state)

        raise InvalidPluginLifecycleRequest(f"Unsupported action: {request.action}")

    except PluginLifecycleError:
        raise
    except Exception as exc:  # pragma: no cover
        raise RuntimeOperationFailed("Unexpected failure while executing plugin lifecycle operation", {"exception": repr(exc)}) from exc


def list_plugins(*, gateway_url: str | None = None, config_path: Path | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> PluginLifecycleResult:
    return run_plugin_lifecycle(
        PluginLifecycleRequest(action="list", gateway_url=gateway_url, config_path=config_path, timeout_s=timeout_s)
    )


def plugin_status(
    plugin: str, *, gateway_url: str | None = None, config_path: Path | None = None, timeout_s: float = DEFAULT_TIMEOUT_S
) -> PluginLifecycleResult:
    return run_plugin_lifecycle(
        PluginLifecycleRequest(action="status", plugin=plugin, gateway_url=gateway_url, config_path=config_path, timeout_s=timeout_s)
    )


def start_plugin(
    plugin: str, *, gateway_url: str | None = None, config_path: Path | None = None, timeout_s: float = DEFAULT_TIMEOUT_S
) -> PluginLifecycleResult:
    return run_plugin_lifecycle(
        PluginLifecycleRequest(action="start", plugin=plugin, gateway_url=gateway_url, config_path=config_path, timeout_s=timeout_s)
    )


def stop_plugin(
    plugin: str, *, gateway_url: str | None = None, config_path: Path | None = None, timeout_s: float = DEFAULT_TIMEOUT_S
) -> PluginLifecycleResult:
    return run_plugin_lifecycle(
        PluginLifecycleRequest(action="stop", plugin=plugin, gateway_url=gateway_url, config_path=config_path, timeout_s=timeout_s)
    )


def restart_plugin(
    plugin: str, *, gateway_url: str | None = None, config_path: Path | None = None, timeout_s: float = DEFAULT_TIMEOUT_S
) -> PluginLifecycleResult:
    return run_plugin_lifecycle(
        PluginLifecycleRequest(action="restart", plugin=plugin, gateway_url=gateway_url, config_path=config_path, timeout_s=timeout_s)
    )


# ------------------------------
# Gateway URL resolution
# ------------------------------


_GATEWAY_URL_ENV_VARS: Sequence[str] = (
    "THOMAS_GATEWAY_URL",
    "THOMAS_RUNTIME_URL",
    "THOMAS_API_URL",
    "THOMAS_URL",
)


def resolve_gateway_url(*, explicit_gateway_url: str | None, config_path: Path | None) -> tuple[str, str]:
    """Resolve the gateway URL."""
    if explicit_gateway_url:
        return explicit_gateway_url, "argument"

    for key in _GATEWAY_URL_ENV_VARS:
        val = os.environ.get(key)
        if val:
            return val, f"env:{key}"

    if config_path is not None:
        cfg_url = _read_gateway_url_from_config(config_path)
        if cfg_url:
            return cfg_url, f"config:{config_path}"
        raise MissingPluginRuntimeConfig(
            "Gateway URL not found in config",
            details={"config_path": str(config_path), "expected_keys": ["gateway_url", "runtime_url", "api_url", "url"]},
        )

    raise MissingPluginRuntimeConfig(
        "Gateway URL not configured. Provide --gateway-url, set THOMAS_GATEWAY_URL, or pass --config.",
        details={"env_vars": list(_GATEWAY_URL_ENV_VARS)},
    )


def _read_gateway_url_from_config(config_path: Path) -> str | None:
    if not config_path.exists():
        raise MissingPluginRuntimeConfig("Config file does not exist", {"config_path": str(config_path)})

    suffix = config_path.suffix.lower()

    try:
        if suffix == ".json":
            data = json.loads(config_path.read_text(encoding="utf-8"))
        elif suffix in {".toml", ".tml"}:
            import tomllib

            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        else:
            raise MissingPluginRuntimeConfig(
                "Unsupported config format for gateway discovery",
                details={"config_path": str(config_path), "supported": [".json", ".toml"]},
            )
    except PluginLifecycleError:
        raise
    except Exception as exc:
        raise MissingPluginRuntimeConfig("Failed to read config file", {"config_path": str(config_path), "exception": repr(exc)}) from exc

    if not isinstance(data, dict):
        return None

    candidates: list[Any] = []
    for key in ("gateway_url", "runtime_url", "api_url", "url"):
        candidates.append(data.get(key))

    for nest_key in ("gateway", "runtime", "api"):
        nest = data.get(nest_key)
        if isinstance(nest, dict):
            for key in ("gateway_url", "runtime_url", "api_url", "url"):
                candidates.append(nest.get(key))

    for val in candidates:
        if isinstance(val, str) and val.strip():
            return val.strip()

    return None


# ------------------------------
# Request validation
# ------------------------------


def _validate_request(request: PluginLifecycleRequest) -> None:
    if request.action not in {"list", "status", "start", "stop", "restart"}:
        raise InvalidPluginLifecycleRequest(
            "Invalid action",
            details={"action": request.action, "allowed": ["list", "status", "start", "stop", "restart"]},
        )

    if request.action != "list":
        if not request.plugin:
            raise InvalidPluginLifecycleRequest("Plugin identifier is required for this action", {"action": request.action})
        if not _PLUGIN_ID_PATTERN.match(request.plugin):
            raise InvalidPluginLifecycleRequest("Plugin identifier must not contain whitespace", {"plugin": request.plugin})

    if request.timeout_s <= 0:
        raise InvalidPluginLifecycleRequest("timeout_s must be > 0", {"timeout_s": request.timeout_s})


# ------------------------------
# HTTP Gateway backend
# ------------------------------


def _normalize_base_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise MissingPluginRuntimeConfig("Empty gateway URL")

    if not (url.startswith("http://") or url.startswith("https://")):
        raise InvalidPluginLifecycleRequest(
            "Gateway URL must include a scheme (http:// or https://)",
            details={"gateway_url": url},
        )

    return url.rstrip("/")


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url}{path}"


def _gateway_list_plugins(base_url: str, *, timeout_s: float) -> list[PluginState]:
    endpoints = [
        ("GET", "/plugins"),
        ("GET", "/v1/plugins"),
        ("GET", "/api/plugins"),
        ("GET", "/gateway/plugins"),
    ]

    last_err: Exception | None = None
    for method, path in endpoints:
        try:
            status, payload = _http_json(method, _join_url(base_url, path), timeout_s=timeout_s)
        except RuntimeUnavailable as exc:
            last_err = exc
            break
        except RuntimeResponseError as exc:
            last_err = exc
            continue

        if 200 <= status < 300:
            return _parse_plugin_list(payload)

        last_err = RuntimeResponseError(
            "Non-2xx response from plugin list endpoint",
            {"status": status, "endpoint": path, "payload": _safe_preview(payload)},
        )

    try:
        return _rpc_list_plugins(base_url, timeout_s=timeout_s)
    except PluginLifecycleError as exc:
        if isinstance(last_err, PluginLifecycleError):
            raise last_err from exc
        raise exc


def _gateway_get_status(base_url: str, plugin: str, *, timeout_s: float) -> PluginState:
    endpoints = [
        ("GET", f"/plugins/{urllib.parse.quote(plugin)}"),
        ("GET", f"/v1/plugins/{urllib.parse.quote(plugin)}"),
        ("GET", f"/api/plugins/{urllib.parse.quote(plugin)}"),
    ]

    last_404_payload: Any | None = None
    last_err: Exception | None = None

    for method, path in endpoints:
        try:
            status, payload = _http_json(method, _join_url(base_url, path), timeout_s=timeout_s)
        except RuntimeUnavailable as exc:
            last_err = exc
            break
        except RuntimeResponseError as exc:
            last_err = exc
            continue

        if 200 <= status < 300:
            return _parse_single_plugin(payload, fallback_name=plugin)

        if status == 404:
            last_404_payload = payload
            continue

        last_err = RuntimeResponseError(
            "Non-2xx response from plugin status endpoint",
            {"status": status, "endpoint": path, "payload": _safe_preview(payload)},
        )

    try:
        return _rpc_plugin_status(base_url, plugin, timeout_s=timeout_s)
    except PluginLifecycleError as exc:
        if last_404_payload is not None and _looks_like_plugin_not_found(last_404_payload, plugin):
            raise PluginNotFound(plugin) from exc
        if isinstance(last_err, PluginLifecycleError):
            raise last_err from exc
        raise PluginNotFound(plugin) from exc


def _gateway_post_lifecycle(base_url: str, plugin: str, action: Literal["start", "stop", "restart"], *, timeout_s: float) -> PluginState:
    endpoints = [
        ("POST", f"/plugins/{urllib.parse.quote(plugin)}/{action}"),
        ("POST", f"/v1/plugins/{urllib.parse.quote(plugin)}/{action}"),
        ("POST", f"/api/plugins/{urllib.parse.quote(plugin)}/{action}"),
    ]

    last_404_payload: Any | None = None
    last_err: Exception | None = None

    for method, path in endpoints:
        try:
            status, payload = _http_json(method, _join_url(base_url, path), timeout_s=timeout_s)
        except RuntimeUnavailable as exc:
            last_err = exc
            break
        except RuntimeResponseError as exc:
            last_err = exc
            continue

        if 200 <= status < 300:
            return _parse_single_plugin(payload, fallback_name=plugin)

        if status == 404:
            last_404_payload = payload
            continue

        last_err = RuntimeResponseError(
            "Non-2xx response from plugin lifecycle endpoint",
            {"status": status, "endpoint": path, "payload": _safe_preview(payload)},
        )

    rpc_fn = {
        "start": _rpc_start_plugin,
        "stop": _rpc_stop_plugin,
        "restart": _rpc_restart_plugin,
    }[action]

    try:
        return rpc_fn(base_url, plugin, timeout_s=timeout_s)
    except PluginLifecycleError as exc:
        if last_404_payload is not None and _looks_like_plugin_not_found(last_404_payload, plugin):
            raise PluginNotFound(plugin) from exc
        if isinstance(last_err, PluginLifecycleError):
            raise last_err from exc
        raise RuntimeOperationFailed(f"Failed to {action} plugin", {"plugin": plugin}) from exc


def _http_json(method: str, url: str, *, timeout_s: float, payload: Any | None = None) -> tuple[int, Any]:
    data: bytes | None
    headers: dict[str, str] = {"Accept": "application/json"}
    if payload is None:
        data = None
    else:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 200))
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 500))
        try:
            raw = exc.read()
        except Exception:
            raw = b""
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise RuntimeUnavailable("Unable to reach plugin runtime gateway", {"url": url, "exception": repr(exc)}) from exc

    if not raw:
        return status, None

    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        text = raw.decode("utf-8", errors="replace")
        return status, {"raw": text}


# ------------------------------
# Response parsing
# ------------------------------


def _parse_plugin_list(payload: Any) -> list[PluginState]:
    if payload is None:
        return []

    if isinstance(payload, list):
        return [_coerce_plugin_state(item) for item in payload]

    if isinstance(payload, dict):
        for key in ("plugins", "items", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                return [_coerce_plugin_state(item) for item in val]

        result = payload.get("result")
        if isinstance(result, dict):
            for key in ("plugins", "items", "data"):
                val = result.get(key)
                if isinstance(val, list):
                    return [_coerce_plugin_state(item) for item in val]

    raise RuntimeResponseError("Unrecognized plugin list response", {"payload": _safe_preview(payload)})


def _parse_single_plugin(payload: Any, *, fallback_name: str) -> PluginState:
    if isinstance(payload, dict):
        if "plugin" in payload and isinstance(payload["plugin"], dict):
            return _coerce_plugin_state(payload["plugin"], fallback_name=fallback_name)

        if "result" in payload and isinstance(payload["result"], dict):
            inner = payload["result"]
            if "plugin" in inner and isinstance(inner["plugin"], dict):
                return _coerce_plugin_state(inner["plugin"], fallback_name=fallback_name)
            return _coerce_plugin_state(inner, fallback_name=fallback_name)

        return _coerce_plugin_state(payload, fallback_name=fallback_name)

    raise RuntimeResponseError("Unrecognized plugin response", {"payload": _safe_preview(payload)})


def _coerce_plugin_state(item: Any, *, fallback_name: str | None = None) -> PluginState:
    if not isinstance(item, dict):
        raise RuntimeResponseError("Plugin entry is not an object", {"entry": _safe_preview(item)})

    name = _first_str(item, ["name", "id", "plugin", "identifier"]) or fallback_name
    if not name:
        raise RuntimeResponseError("Plugin entry missing name", {"entry": _safe_preview(item)})

    status_raw: Any = item.get("status", item.get("state", item.get("lifecycle")))
    status: Literal["running", "stopped", "unknown"]

    if isinstance(status_raw, str):
        s = status_raw.strip().lower()
        if s in {"running", "started", "active", "up"}:
            status = "running"
        elif s in {"stopped", "inactive", "down"}:
            status = "stopped"
        else:
            status = "unknown"
    elif isinstance(status_raw, bool):
        status = "running" if status_raw else "stopped"
    else:
        running_flag = item.get("running")
        if isinstance(running_flag, bool):
            status = "running" if running_flag else "stopped"
        else:
            status = "unknown"

    version = _first_str(item, ["version"])
    description = _first_str(item, ["description", "summary"])

    meta: dict[str, Any] = {}
    for k, v in item.items():
        if k in {"name", "id", "plugin", "identifier", "status", "state", "lifecycle", "running", "version", "description", "summary"}:
            continue
        if _is_jsonable(v):
            meta[k] = v
        else:
            meta[k] = repr(v)

    return PluginState(name=name, status=status, version=version, description=description, meta=meta or None)


def _first_str(d: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _is_jsonable(val: Any) -> bool:
    try:
        json.dumps(val)
        return True
    except Exception:
        return False


def _safe_preview(val: Any, *, limit: int = 500) -> str:
    try:
        text = json.dumps(val)
    except Exception:
        text = repr(val)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _looks_like_plugin_not_found(payload: Any, plugin: str) -> bool:
    if payload is None:
        return True

    if isinstance(payload, dict):
        text_bits: list[str] = []
        for key in ("message", "error", "detail", "raw"):
            v = payload.get(key)
            if isinstance(v, str):
                text_bits.append(v)
            elif isinstance(v, dict):
                msg = v.get("message")
                if isinstance(msg, str):
                    text_bits.append(msg)

        blob = " ".join(text_bits).lower()
        return ("not found" in blob) or (plugin.lower() in blob)

    if isinstance(payload, str):
        blob = payload.lower()
        return ("not found" in blob) or (plugin.lower() in blob)

    return False


# ------------------------------
# JSON-RPC fallback
# ------------------------------


_RPC_ENDPOINTS: Sequence[str] = ("/rpc", "/jsonrpc", "/api/rpc", "/v1/rpc")


def _rpc_call(base_url: str, method: str, params: Mapping[str, Any] | None, *, timeout_s: float) -> Any:
    payload = {"jsonrpc": "2.0", "id": int(time.time() * 1000), "method": method, "params": params or {}}

    last_err: Exception | None = None
    for path in _RPC_ENDPOINTS:
        try:
            status, resp = _http_json("POST", _join_url(base_url, path), timeout_s=timeout_s, payload=payload)
        except RuntimeUnavailable as exc:
            last_err = exc
            break

        if not (200 <= status < 300):
            last_err = RuntimeResponseError("RPC endpoint returned non-2xx", {"status": status, "endpoint": path})
            continue

        if isinstance(resp, dict):
            if "error" in resp and resp["error"]:
                raise RuntimeOperationFailed("RPC error", {"rpc_error": resp["error"], "method": method})
            if "result" in resp:
                return resp["result"]

        raise RuntimeResponseError("Unrecognized RPC response", {"payload": _safe_preview(resp), "method": method})

    if last_err is None:
        raise RuntimeUnavailable("RPC endpoint not available")
    if isinstance(last_err, PluginLifecycleError):
        raise last_err
    raise RuntimeUnavailable("RPC call failed", {"exception": repr(last_err)})


def _rpc_list_plugins(base_url: str, *, timeout_s: float) -> list[PluginState]:
    result = _rpc_call(base_url, "plugins.list", None, timeout_s=timeout_s)
    return _parse_plugin_list(result)


def _rpc_plugin_status(base_url: str, plugin: str, *, timeout_s: float) -> PluginState:
    result = _rpc_call(base_url, "plugins.status", {"plugin": plugin}, timeout_s=timeout_s)
    return _parse_single_plugin(result, fallback_name=plugin)


def _rpc_start_plugin(base_url: str, plugin: str, *, timeout_s: float) -> PluginState:
    result = _rpc_call(base_url, "plugins.start", {"plugin": plugin}, timeout_s=timeout_s)
    return _parse_single_plugin(result, fallback_name=plugin)


def _rpc_stop_plugin(base_url: str, plugin: str, *, timeout_s: float) -> PluginState:
    result = _rpc_call(base_url, "plugins.stop", {"plugin": plugin}, timeout_s=timeout_s)
    return _parse_single_plugin(result, fallback_name=plugin)


def _rpc_restart_plugin(base_url: str, plugin: str, *, timeout_s: float) -> PluginState:
    result = _rpc_call(base_url, "plugins.restart", {"plugin": plugin}, timeout_s=timeout_s)
    return _parse_single_plugin(result, fallback_name=plugin)
