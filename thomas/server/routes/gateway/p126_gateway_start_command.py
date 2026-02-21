from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, TypedDict, Literal

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

from aiohttp import web

# App-scoped key for storing gateway runtime state.
try:
    GATEWAY_STATE_KEY = web.AppKey("thomas.gateway.state", dict)  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    GATEWAY_STATE_KEY = "thomas.gateway.state"

# State dict entry keys.
GATEWAY_PROCESS_KEY = "process"

# For environments where mutating an already-started aiohttp Application dict is discouraged,
# we keep an out-of-band WeakKeyDictionary as a fallback.
_APP_STATE: "weakref.WeakKeyDictionary[web.Application, MutableMapping[str, Any]]" = weakref.WeakKeyDictionary()

# Serialize start/restart to avoid racy double-starts.
_START_LOCK = asyncio.Lock()


class GatewayStartRequest(TypedDict, total=False):
    """POST /v1/gateway/start body."""

    config_path: str
    force_restart: bool


class GatewayStartError(TypedDict):
    type: Literal["invalid_input", "missing_config", "external_failure"]
    message: str
    details: Dict[str, Any]


class GatewayStartResponse(TypedDict):
    ok: bool
    status: Literal["started", "already_running"]
    pid: Optional[int]
    config_path: str
    command: List[str]


@dataclass(frozen=True)
class GatewayConfig:
    command: List[str]
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class GatewayStartOutcome:
    status: Literal["started", "already_running"]
    pid: Optional[int]
    config_path: str
    command: List[str]

    def to_response(self) -> GatewayStartResponse:
        return {
            "ok": True,
            "status": self.status,
            "pid": self.pid,
            "config_path": self.config_path,
            "command": list(self.command),
        }


class GatewayStartException(Exception):
    """Deterministic error type for gateway-start flows."""

    def __init__(
        self,
        error_type: Literal["invalid_input", "missing_config", "external_failure"],
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.details: Dict[str, Any] = dict(details or {})
        self.http_status = http_status

    def to_error_payload(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "type": self.error_type,
                "message": self.message,
                "details": dict(self.details),
            },
        }


def _get_app_state(app: web.Application) -> MutableMapping[str, Any]:
    state = app.get(GATEWAY_STATE_KEY)
    if isinstance(state, dict):
        return state
    state = _APP_STATE.get(app)
    if state is None:
        state = {}
        _APP_STATE[app] = state
    return state


def get_gateway_process(app: web.Application) -> Optional[subprocess.Popen]:
    state = _get_app_state(app)
    proc = state.get(GATEWAY_PROCESS_KEY)
    return proc if isinstance(proc, subprocess.Popen) else None


def _resolve_config_path(config_path: str) -> str:
    p = Path(config_path).expanduser()
    # Do not require absolute; just normalize for stable error details.
    try:
        p = p.resolve()
    except Exception:
        p = p.absolute()
    return str(p)


def _parse_command(value: Any) -> List[str]:
    if isinstance(value, list):
        if not value:
            raise GatewayStartException(
                "invalid_input",
                "Invalid gateway command: list is empty.",
                details={"field": "command"},
                http_status=400,
            )
        if not all(isinstance(x, str) and x for x in value):
            raise GatewayStartException(
                "invalid_input",
                "Invalid gateway command: list must contain non-empty strings.",
                details={"field": "command"},
                http_status=400,
            )
        return list(value)

    if isinstance(value, str):
        try:
            parts = shlex.split(value)
        except ValueError as e:
            raise GatewayStartException(
                "invalid_input",
                "Invalid gateway command string.",
                details={"field": "command", "cause": type(e).__name__},
                http_status=400,
            )
        if not parts:
            raise GatewayStartException(
                "invalid_input",
                "Invalid gateway command: string is empty.",
                details={"field": "command"},
                http_status=400,
            )
        return parts

    raise GatewayStartException(
        "invalid_input",
        "Invalid gateway command: expected string or list of strings.",
        details={"field": "command", "value_type": type(value).__name__},
        http_status=400,
    )


def _safe_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _load_config_file(config_path: str) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists() or not path.is_file():
        raise GatewayStartException(
            "missing_config",
            "Missing gateway config file.",
            details={"config_path": str(path)},
            http_status=400,
        )

    raw = path.read_bytes()
    suffix = path.suffix.lower()

    if suffix in {".toml", ".tml"}:
        if tomllib is None:  # pragma: no cover
            raise GatewayStartException(
                "external_failure",
                "TOML support is unavailable in this runtime.",
                details={"config_path": str(path)},
                http_status=500,
            )
        try:
            return tomllib.loads(raw.decode("utf-8"))
        except Exception as e:
            raise GatewayStartException(
                "invalid_input",
                "Invalid gateway config TOML.",
                details={"config_path": str(path), "cause": type(e).__name__},
                http_status=400,
            )

    # default JSON
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise GatewayStartException(
            "invalid_input",
            "Invalid gateway config JSON.",
            details={"config_path": str(path), "cause": type(e).__name__},
            http_status=400,
        )


def load_gateway_config(config_path: str) -> GatewayConfig:
    """Load gateway config.

    Supported layouts:
      - {"command": [...], "cwd": "...", "env": {...}}
      - {"gateway": {"command": [...], "cwd": "...", "env": {...}}}
      - {"gateway_command": "..."} (fallback key)
    """
    doc = _load_config_file(config_path)

    gateway_section = doc.get("gateway") if isinstance(doc, dict) else None
    node: Any = gateway_section if isinstance(gateway_section, dict) else doc
    if not isinstance(node, dict):
        raise GatewayStartException(
            "invalid_input",
            "Invalid gateway config: expected an object at the top level.",
            details={"config_path": str(config_path)},
            http_status=400,
        )

    if "command" in node:
        cmd_value = node.get("command")
    elif "gateway_command" in node:
        cmd_value = node.get("gateway_command")
    else:
        raise GatewayStartException(
            "missing_config",
            "Missing gateway command in config.",
            details={"config_path": str(config_path), "expected_keys": ["command", "gateway.command"]},
            http_status=400,
        )

    command = _parse_command(cmd_value)

    cwd = _safe_str(node.get("cwd"))

    env_node = node.get("env")
    env: Optional[Dict[str, str]] = None
    if env_node is not None:
        if (
            not isinstance(env_node, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_node.items())
        ):
            raise GatewayStartException(
                "invalid_input",
                "Invalid gateway env: expected a string-to-string object.",
                details={"field": "env"},
                http_status=400,
            )
        env = dict(env_node)

    return GatewayConfig(command=command, cwd=cwd, env=env)


def _creationflags_for_platform() -> int:
    # Helps ensure terminate()/kill() target the process cleanly on Windows.
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        return int(subprocess.CREATE_NEW_PROCESS_GROUP)  # type: ignore[attr-defined]
    return 0


def start_gateway_process(
    *,
    state: MutableMapping[str, Any],
    config_path: str,
    force_restart: bool = False,
    post_start_check_seconds: float = 0.15,
) -> GatewayStartOutcome:
    """Start the gateway process described by config_path.

    Idempotent within the current server process: if a gateway process is already
    running in `state`, returns `already_running` unless `force_restart`.

    `post_start_check_seconds` performs a brief immediate-exit check: if the
    subprocess dies right away, the call fails deterministically.
    """
    resolved = _resolve_config_path(config_path)
    config = load_gateway_config(resolved)

    existing = state.get(GATEWAY_PROCESS_KEY)
    if isinstance(existing, subprocess.Popen) and existing.poll() is None:
        if not force_restart:
            return GatewayStartOutcome(
                status="already_running",
                pid=existing.pid,
                config_path=resolved,
                command=list(config.command),
            )

        # Force restart: stop existing before starting a new one.
        try:
            existing.terminate()
            existing.wait(timeout=5)
        except Exception:
            try:
                existing.kill()
            except Exception:
                pass

    env = os.environ.copy()
    if config.env:
        env.update(config.env)

    try:
        proc = subprocess.Popen(
            config.command,
            cwd=config.cwd or None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags_for_platform(),
        )
    except FileNotFoundError as e:
        raise GatewayStartException(
            "external_failure",
            "Failed to start gateway process: executable not found.",
            details={
                "config_path": resolved,
                "cause": type(e).__name__,
                "errno": getattr(e, "errno", None),
            },
            http_status=502,
        )
    except OSError as e:
        raise GatewayStartException(
            "external_failure",
            "Failed to start gateway process.",
            details={
                "config_path": resolved,
                "cause": type(e).__name__,
                "errno": getattr(e, "errno", None),
            },
            http_status=502,
        )

    # Immediate-exit check (common when config points to a script that errors instantly).
    if post_start_check_seconds > 0:
        time.sleep(post_start_check_seconds)
        rc = proc.poll()
        if rc is not None:
            raise GatewayStartException(
                "external_failure",
                "Gateway process exited immediately after start.",
                details={"config_path": resolved, "returncode": rc, "command": list(config.command)},
                http_status=502,
            )

    state[GATEWAY_PROCESS_KEY] = proc
    return GatewayStartOutcome(
        status="started",
        pid=proc.pid,
        config_path=resolved,
        command=list(config.command),
    )


async def _cleanup_gateway_process(app: web.Application) -> None:
    proc = get_gateway_process(app)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


routes = web.RouteTableDef()


@routes.post("/v1/gateway/start")
async def gateway_start(request: web.Request) -> web.Response:
    """Start the gateway described by the provided config."""
    try:
        body: Any = {}
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception as e:
                raise GatewayStartException(
                    "invalid_input",
                    "Invalid JSON request body.",
                    details={"cause": type(e).__name__},
                    http_status=400,
                )

        if body is None:
            body = {}

        if not isinstance(body, dict):
            raise GatewayStartException(
                "invalid_input",
                "Invalid request body: expected JSON object.",
                details={"value_type": type(body).__name__},
                http_status=400,
            )

        config_path_value = body.get("config_path")
        if config_path_value is None:
            config_path_value = os.environ.get("THOMAS_GATEWAY_CONFIG")

        if not isinstance(config_path_value, str) or not config_path_value.strip():
            raise GatewayStartException(
                "missing_config",
                "Missing config_path (and THOMAS_GATEWAY_CONFIG is not set).",
                details={"field": "config_path"},
                http_status=400,
            )

        force_restart_value = body.get("force_restart", False)
        if not isinstance(force_restart_value, bool):
            raise GatewayStartException(
                "invalid_input",
                "Invalid force_restart: expected boolean.",
                details={"field": "force_restart", "value_type": type(force_restart_value).__name__},
                http_status=400,
            )

        # Ensure we don't orphan a subprocess if the app shuts down.
        if _cleanup_gateway_process not in request.app.on_cleanup:
            request.app.on_cleanup.append(_cleanup_gateway_process)

        async with _START_LOCK:
            state = _get_app_state(request.app)
            outcome = start_gateway_process(
                state=state,
                config_path=config_path_value,
                force_restart=force_restart_value,
            )

        return web.json_response(outcome.to_response(), status=200)

    except GatewayStartException as e:
        return web.json_response(e.to_error_payload(), status=e.http_status)


def register(app: web.Application) -> None:
    """Registration hook for Thomas aiohttp app loaders."""
    # Pre-init state (best effort).
    app_state = app.get(GATEWAY_STATE_KEY)
    if not isinstance(app_state, dict):
        app[GATEWAY_STATE_KEY] = {}
    _APP_STATE.setdefault(app, {})

    app.add_routes(routes)

    if _cleanup_gateway_process not in app.on_cleanup:
        app.on_cleanup.append(_cleanup_gateway_process)


# Compatibility exports for different route loaders
ROUTE_TABLE = routes
ROUTES = routes
ROUTE_SPECS = [("POST", "/v1/gateway/start", gateway_start)]
