"""
Gateway uninstall command (server-side).

This module exposes an aiohttp route plus a small, testable core that performs the
uninstall action.

Design goals:
- Deterministic, machine-readable errors (stable `code` values).
- Clear request/response contracts (TypedDict + dataclasses).
- Thomas-native naming (no OpenClaw naming reuse).

Uninstall behavior is intentionally conservative and idempotent:
- If the Gateway footprint is missing, uninstall returns success with `already_absent=true`.
- It only removes the gateway directory and gateway config file(s) inside the resolved
  Thomas state directory.
- It refuses to operate on filesystem roots (e.g. `/` or `C:\\`) to avoid footguns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Any, Mapping, Optional, TypedDict, cast

from aiohttp import web


# ---------------------------
# Contracts
# ---------------------------

class GatewayUninstallRequestPayload(TypedDict, total=False):
    """JSON body accepted by the Gateway uninstall route."""

    state_dir: str
    dry_run: bool
    purge_state: bool


class GatewayUninstallResultPayload(TypedDict):
    """JSON body returned on success."""

    uninstalled: bool
    already_absent: bool
    dry_run: bool
    removed_paths: list[str]
    ran_external_uninstall: bool
    external_uninstall_command: Optional[list[str]]


class GatewayUninstallErrorPayload(TypedDict):
    """JSON body returned on failure."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class GatewayUninstallRequest:
    """Parsed request for uninstalling the Gateway."""

    state_dir: Optional[str] = None
    dry_run: bool = False
    purge_state: bool = False

    @staticmethod
    def from_payload(payload: Mapping[str, Any]) -> "GatewayUninstallRequest":
        if not isinstance(payload, Mapping):
            raise GatewayUninstallError.invalid_request("Request body must be an object.")

        allowed_keys = {"state_dir", "dry_run", "purge_state"}
        unknown = [k for k in payload.keys() if k not in allowed_keys]
        if unknown:
            raise GatewayUninstallError.invalid_request(
                f"Unknown field(s): {', '.join(sorted(map(str, unknown)))}"
            )

        state_dir = payload.get("state_dir")
        if state_dir is not None and not isinstance(state_dir, str):
            raise GatewayUninstallError.invalid_request("state_dir must be a string.")

        dry_run = payload.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise GatewayUninstallError.invalid_request("dry_run must be a boolean.")

        purge_state = payload.get("purge_state", False)
        if not isinstance(purge_state, bool):
            raise GatewayUninstallError.invalid_request("purge_state must be a boolean.")

        return GatewayUninstallRequest(
            state_dir=cast(Optional[str], state_dir),
            dry_run=dry_run,
            purge_state=purge_state,
        )


@dataclass(frozen=True, slots=True)
class GatewayUninstallResult:
    """Result of the uninstall action."""

    uninstalled: bool
    already_absent: bool
    dry_run: bool
    removed_paths: list[str] = field(default_factory=list)
    ran_external_uninstall: bool = False
    external_uninstall_command: Optional[list[str]] = None

    def to_payload(self) -> GatewayUninstallResultPayload:
        return GatewayUninstallResultPayload(
            uninstalled=self.uninstalled,
            already_absent=self.already_absent,
            dry_run=self.dry_run,
            removed_paths=list(self.removed_paths),
            ran_external_uninstall=self.ran_external_uninstall,
            external_uninstall_command=list(self.external_uninstall_command)
            if self.external_uninstall_command
            else None,
        )


# ---------------------------
# Errors
# ---------------------------

class GatewayUninstallError(RuntimeError):
    """Deterministic error for Gateway uninstall failures."""

    def __init__(self, *, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    def to_payload(self) -> GatewayUninstallErrorPayload:
        return GatewayUninstallErrorPayload(code=self.code, message=str(self))

    @staticmethod
    def invalid_request(message: str) -> "GatewayUninstallError":
        return GatewayUninstallError(code="invalid_request", message=message, http_status=400)

    @staticmethod
    def missing_config(message: str) -> "GatewayUninstallError":
        return GatewayUninstallError(code="missing_configuration", message=message, http_status=409)

    @staticmethod
    def external_failure(message: str) -> "GatewayUninstallError":
        return GatewayUninstallError(code="external_uninstall_failed", message=message, http_status=502)

    @staticmethod
    def filesystem_failure(message: str) -> "GatewayUninstallError":
        return GatewayUninstallError(code="filesystem_error", message=message, http_status=500)


# ---------------------------
# Core implementation
# ---------------------------

_GATEWAY_DIRNAME = "gateway"
_GATEWAY_CONFIG_FILENAMES = ("gateway.json", "gateway_config.json")
_STATE_DIR_ENV = "THOMAS_STATE_DIR"
_GATEWAY_UNINSTALL_ENV = "THOMAS_GATEWAY_UNINSTALL_CMD"


def _coerce_uninstall_command(raw: Any) -> Optional[list[str]]:
    """Normalize an uninstall command value into argv list.

    Supported forms:
    - None
    - string (shlex-split)
    - list/tuple of strings
    """

    if raw is None:
        return None
    if isinstance(raw, str):
        argv = shlex.split(raw)
        return argv or None
    if isinstance(raw, (list, tuple)):
        if not all(isinstance(x, str) for x in raw):
            raise GatewayUninstallError.invalid_request("uninstall_command must be a string list.")
        argv = [x for x in raw if x.strip()]
        return argv or None
    raise GatewayUninstallError.invalid_request("uninstall_command must be a string or string list.")


def _resolve_state_dir(req: GatewayUninstallRequest, app_config: Optional[Mapping[str, Any]] = None) -> Path:
    """Resolve the Thomas state directory.

    Priority:
      1) request override
      2) app_config keys (best-effort)
      3) env var THOMAS_STATE_DIR
      4) ~/.thomas
    """

    if req.state_dir:
        candidate = Path(req.state_dir)
    else:
        state_dir_val: Optional[str] = None
        if app_config:
            for key in ("state_dir", "thomas_state_dir", "data_dir", "home_dir"):
                v = app_config.get(key)  # type: ignore[arg-type]
                if isinstance(v, str) and v.strip():
                    state_dir_val = v
                    break
        if state_dir_val is None:
            env_v = os.getenv(_STATE_DIR_ENV)
            if env_v and env_v.strip():
                state_dir_val = env_v
        candidate = Path(state_dir_val) if state_dir_val else (Path.home() / ".thomas")

    try:
        resolved = candidate.expanduser().resolve()
    except Exception as e:  # pragma: no cover
        raise GatewayUninstallError.invalid_request("Invalid state_dir.") from e

    # Refuse filesystem roots (`/`, `C:\`, UNC shares, etc.)
    if resolved.parent == resolved:
        raise GatewayUninstallError.invalid_request("state_dir cannot be a filesystem root.")

    return resolved


def _load_gateway_config(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise GatewayUninstallError.missing_config("Invalid gateway config JSON.") from e
    if not isinstance(data, dict):
        raise GatewayUninstallError.missing_config("Gateway config must be a JSON object.")
    return cast(Mapping[str, Any], data)


def _predict_removed_paths(state_dir: Path) -> list[str]:
    removed: list[str] = []
    gateway_dir = state_dir / _GATEWAY_DIRNAME
    if gateway_dir.exists():
        removed.append(str(gateway_dir))
    for name in _GATEWAY_CONFIG_FILENAMES:
        p = state_dir / name
        if p.exists():
            removed.append(str(p))
    return removed


def uninstall_gateway(
    req: GatewayUninstallRequest,
    *,
    app_config: Optional[Mapping[str, Any]] = None,
) -> GatewayUninstallResult:
    """Uninstall the local Gateway installation (idempotent)."""

    state_dir = _resolve_state_dir(req, app_config=app_config)

    # Predict first; this supports idempotent behavior when absent.
    predicted = _predict_removed_paths(state_dir)
    installed = len(predicted) > 0

    if not installed:
        return GatewayUninstallResult(
            uninstalled=False,
            already_absent=True,
            dry_run=req.dry_run,
            removed_paths=[],
            ran_external_uninstall=False,
            external_uninstall_command=None,
        )

    # Try to load config (if present) to discover an optional external uninstall command.
    gateway_config_paths = [state_dir / name for name in _GATEWAY_CONFIG_FILENAMES]
    config_path = next((p for p in gateway_config_paths if p.exists()), None)
    config = _load_gateway_config(config_path) if config_path else None

    uninstall_cmd_raw: Any = None
    if config and "uninstall_command" in config:
        uninstall_cmd_raw = config.get("uninstall_command")
    if uninstall_cmd_raw is None:
        uninstall_cmd_raw = os.getenv(_GATEWAY_UNINSTALL_ENV)

    uninstall_cmd = _coerce_uninstall_command(uninstall_cmd_raw)

    if req.dry_run:
        return GatewayUninstallResult(
            uninstalled=False,
            already_absent=False,
            dry_run=True,
            removed_paths=predicted,
            ran_external_uninstall=False,
            external_uninstall_command=uninstall_cmd,
        )

    ran_external = False
    if uninstall_cmd:
        try:
            subprocess.run(uninstall_cmd, check=True, capture_output=True, text=True)
            ran_external = True
        except FileNotFoundError as e:
            raise GatewayUninstallError.external_failure(
                f"External uninstall command not found: {uninstall_cmd[0]}"
            ) from e
        except subprocess.CalledProcessError as e:
            raise GatewayUninstallError.external_failure(
                f"External uninstall command failed (exit_code={e.returncode})."
            ) from e
        except Exception as e:  # pragma: no cover
            raise GatewayUninstallError.external_failure("External uninstall command failed.") from e

    # Remove local filesystem state (only within the state_dir).
    removed_paths: list[str] = []
    gateway_dir = state_dir / _GATEWAY_DIRNAME

    try:
        # Safety check: ensure the target is inside state_dir.
        try:
            gateway_resolved = gateway_dir.resolve()
        except Exception:
            gateway_resolved = gateway_dir

        if hasattr(gateway_resolved, "is_relative_to"):
            if not gateway_resolved.is_relative_to(state_dir):
                raise GatewayUninstallError.filesystem_failure(
                    "Refusing to remove path outside state_dir."
                )

        if gateway_dir.exists():
            shutil.rmtree(gateway_dir)
            removed_paths.append(str(gateway_dir))

        for p in gateway_config_paths:
            if p.exists():
                p.unlink()
                removed_paths.append(str(p))

    except GatewayUninstallError:
        raise
    except Exception as e:
        raise GatewayUninstallError.filesystem_failure("Failed to remove gateway files.") from e

    return GatewayUninstallResult(
        uninstalled=True,
        already_absent=False,
        dry_run=False,
        removed_paths=removed_paths,
        ran_external_uninstall=ran_external,
        external_uninstall_command=uninstall_cmd,
    )


# ---------------------------
# aiohttp route
# ---------------------------

routes = web.RouteTableDef()


async def _read_json_body(request: web.Request) -> GatewayUninstallRequestPayload:
    if not request.can_read_body:
        return GatewayUninstallRequestPayload()
    if request.content_length == 0:
        return GatewayUninstallRequestPayload()
    try:
        body = await request.json()
    except Exception as e:
        raise GatewayUninstallError.invalid_request("Invalid JSON body.") from e
    if body is None:
        return GatewayUninstallRequestPayload()
    if not isinstance(body, dict):
        raise GatewayUninstallError.invalid_request("Request body must be an object.")
    return cast(GatewayUninstallRequestPayload, body)


@routes.post("/v1/gateway/uninstall")
@routes.post("/gateway/uninstall")
async def gateway_uninstall(request: web.Request) -> web.Response:
    """HTTP endpoint to uninstall the Gateway."""

    try:
        payload = await _read_json_body(request)
        req_obj = GatewayUninstallRequest.from_payload(payload)

        # Best-effort app config lookup; keep this permissive to avoid coupling.
        app_cfg: Optional[Mapping[str, Any]] = None
        for key in ("config", "settings"):
            v = request.app.get(key)
            if isinstance(v, Mapping):
                app_cfg = cast(Mapping[str, Any], v)
                break

        result = uninstall_gateway(req_obj, app_config=app_cfg)
        return web.json_response({"ok": True, "result": result.to_payload()}, status=200)

    except GatewayUninstallError as e:
        return web.json_response({"ok": False, "error": e.to_payload()}, status=e.http_status)


def register_routes(app: web.Application) -> None:
    """Thomas route discovery hook (common pattern across route modules)."""

    app.add_routes(routes)


# Common aliases for different loaders/registries.
register = register_routes
setup_routes = register_routes
setup = register_routes

ROUTES = routes
