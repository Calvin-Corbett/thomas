"""
Gateway state persistence model (Thomas-native).

Provides:
  - A small persistence layer for gateway state (memory or file).
  - aiohttp JSON endpoints to inspect/configure persistence and to read/write state.
  - Typed input/output contracts for automation.

Design goals:
  - No IO at import time.
  - Deterministic, machine-readable error payloads.
  - Safe, atomic file writes (best-effort fsync).
  - Optional optimistic concurrency via expected_version / If-Match.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional, TypedDict, cast

from aiohttp import web

# ----------------------------
# Contracts
# ----------------------------

PersistenceMode = Literal["memory", "file"]


class PersistenceModelRequest(TypedDict, total=False):
    mode: PersistenceMode
    state_dir: str  # base dir; module will persist under <state_dir>/gateway/
    max_state_bytes: int


class PersistenceModelResponse(TypedDict):
    schema_version: int
    mode: PersistenceMode
    state_dir: Optional[str]  # effective dir (includes /gateway when file mode)
    state_file: Optional[str]
    max_state_bytes: int


class GatewayStateEnvelope(TypedDict):
    schema_version: int
    version: int
    updated_at: float
    state: Dict[str, Any]


class GatewayStatePutRequest(TypedDict, total=False):
    state: Dict[str, Any]
    expected_version: int  # optional optimistic concurrency


class GatewayStateResponse(TypedDict):
    schema_version: int
    version: int
    updated_at: float
    state: Dict[str, Any]


# ----------------------------
# Deterministic errors
# ----------------------------


@dataclass(frozen=True)
class GatewayStatePersistenceError(Exception):
    code: str
    message: str
    http_status: int = 400

    def to_payload(self) -> Dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


def _json_error(err: GatewayStatePersistenceError) -> web.Response:
    return web.json_response(err.to_payload(), status=err.http_status)


# ----------------------------
# Persistence core
# ----------------------------

DEFAULT_SCHEMA_VERSION = 1
DEFAULT_MAX_STATE_BYTES = 256 * 1024  # 256KiB
DEFAULT_STATE_DIR_ENV = "THOMAS_STATE_DIR"
DEFAULT_STATE_SUBDIR = "gateway"
DEFAULT_STATE_FILENAME = "gateway_state.json"


@dataclass
class PersistenceConfig:
    schema_version: int = DEFAULT_SCHEMA_VERSION
    mode: PersistenceMode = "memory"
    state_dir: Optional[Path] = None  # effective dir (includes /gateway when file mode)
    max_state_bytes: int = DEFAULT_MAX_STATE_BYTES

    def state_file(self) -> Optional[Path]:
        if self.mode != "file" or not self.state_dir:
            return None
        return self.state_dir / DEFAULT_STATE_FILENAME

    def to_response(self) -> PersistenceModelResponse:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "state_dir": str(self.state_dir) if self.state_dir else None,
            "state_file": str(self.state_file()) if self.state_file() else None,
            "max_state_bytes": int(self.max_state_bytes),
        }


class GatewayStatePersistence:
    """
    Owns gateway state and persists it according to a persistence model.

    Modes:
      - memory: in-process only
      - file: atomic JSON file at <state_dir>/gateway/gateway_state.json
    """

    def __init__(self, config: Optional[PersistenceConfig] = None):
        self._lock = asyncio.Lock()
        self._config = config or PersistenceConfig()
        self._state: Dict[str, Any] = {}
        self._version: int = 0
        self._updated_at: float = 0.0

    @property
    def config(self) -> PersistenceConfig:
        return self._config

    async def configure(self, req: PersistenceModelRequest) -> PersistenceModelResponse:
        mode = req.get("mode")
        if mode is None:
            raise GatewayStatePersistenceError(
                code="invalid_request",
                message="Missing required field: mode",
                http_status=400,
            )
        if mode not in ("memory", "file"):
            raise GatewayStatePersistenceError(
                code="invalid_mode",
                message=f"Unsupported mode: {mode!r}. Expected 'memory' or 'file'.",
                http_status=400,
            )

        max_bytes = req.get("max_state_bytes", self._config.max_state_bytes)
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise GatewayStatePersistenceError(
                code="invalid_request",
                message="max_state_bytes must be a positive integer",
                http_status=400,
            )

        effective_state_dir: Optional[Path] = None
        if mode == "file":
            base_dir_str = req.get("state_dir") or os.environ.get(DEFAULT_STATE_DIR_ENV)
            if not base_dir_str:
                raise GatewayStatePersistenceError(
                    code="missing_config",
                    message=f"state_dir is required for file mode (or set {DEFAULT_STATE_DIR_ENV})",
                    http_status=400,
                )
            base_dir = Path(base_dir_str).expanduser().resolve()
            effective_state_dir = (base_dir / DEFAULT_STATE_SUBDIR).resolve()

        async with self._lock:
            self._config = PersistenceConfig(
                schema_version=DEFAULT_SCHEMA_VERSION,
                mode=cast(PersistenceMode, mode),
                state_dir=effective_state_dir,
                max_state_bytes=int(max_bytes),
            )

            if self._config.mode == "file":
                await self._ensure_state_dir()
                await self._load_from_disk_if_present()

        return self._config.to_response()

    async def get_state(self) -> GatewayStateResponse:
        async with self._lock:
            if self._config.mode == "file":
                await self._load_from_disk_if_present()
            return self._snapshot()

    async def set_state(self, state: Dict[str, Any], expected_version: Optional[int] = None) -> GatewayStateResponse:
        if not isinstance(state, dict):
            raise GatewayStatePersistenceError(
                code="invalid_request",
                message="state must be a JSON object",
                http_status=400,
            )

        try:
            encoded_state = json.dumps(state, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as e:
            raise GatewayStatePersistenceError(
                code="invalid_request",
                message=f"state must be JSON-serializable: {e}",
                http_status=400,
            ) from e

        async with self._lock:
            if self._config.mode == "file":
                await self._load_from_disk_if_present()

            if expected_version is not None:
                if not isinstance(expected_version, int) or expected_version < 0:
                    raise GatewayStatePersistenceError(
                        code="invalid_request",
                        message="expected_version must be a non-negative integer",
                        http_status=400,
                    )
                if expected_version != self._version:
                    raise GatewayStatePersistenceError(
                        code="version_conflict",
                        message=f"expected_version {expected_version} does not match current version {self._version}",
                        http_status=409,
                    )

            if len(encoded_state) > self._config.max_state_bytes:
                raise GatewayStatePersistenceError(
                    code="state_too_large",
                    message=f"state JSON exceeds max_state_bytes ({len(encoded_state)} > {self._config.max_state_bytes})",
                    http_status=413,
                )

            self._state = state
            self._version += 1
            self._updated_at = time.time()

            if self._config.mode == "file":
                await self._ensure_state_dir()
                await self._write_to_disk()

            return self._snapshot()

    def _snapshot(self) -> GatewayStateResponse:
        return {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "version": self._version,
            "updated_at": self._updated_at,
            "state": self._state,
        }

    async def _ensure_state_dir(self) -> None:
        if not self._config.state_dir:
            raise GatewayStatePersistenceError(
                code="missing_config",
                message="state_dir is not configured",
                http_status=500,
            )
        try:
            self._config.state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise GatewayStatePersistenceError(
                code="io_error",
                message=f"Failed to create state_dir: {e}",
                http_status=500,
            ) from e

        if not self._config.state_dir.is_dir():
            raise GatewayStatePersistenceError(
                code="io_error",
                message="state_dir exists but is not a directory",
                http_status=500,
            )

    async def _write_to_disk(self) -> None:
        state_file = self._config.state_file()
        if not state_file:
            raise GatewayStatePersistenceError(
                code="missing_config",
                message="state_file is not available in current mode",
                http_status=500,
            )

        envelope: GatewayStateEnvelope = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "version": self._version,
            "updated_at": self._updated_at,
            "state": self._state,
        }
        data = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

        tmp_path = state_file.with_suffix(state_file.suffix + ".tmp")
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, state_file)
        except OSError as e:
            raise GatewayStatePersistenceError(
                code="io_error",
                message=f"Failed to write state file: {e}",
                http_status=500,
            ) from e
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    async def _load_from_disk_if_present(self) -> None:
        state_file = self._config.state_file()
        if not state_file or not state_file.exists():
            return

        try:
            raw = state_file.read_bytes()
        except OSError as e:
            raise GatewayStatePersistenceError(
                code="io_error",
                message=f"Failed to read state file: {e}",
                http_status=500,
            ) from e

        if len(raw) > self._config.max_state_bytes * 8:
            raise GatewayStatePersistenceError(
                code="invalid_state_file",
                message="State file exceeds reasonable size limits",
                http_status=500,
            )

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise GatewayStatePersistenceError(
                code="invalid_state_file",
                message=f"State file is not valid JSON: {e}",
                http_status=500,
            ) from e

        if not isinstance(parsed, dict):
            raise GatewayStatePersistenceError(
                code="invalid_state_file",
                message="State file JSON must be an object",
                http_status=500,
            )

        schema_version = parsed.get("schema_version")
        if schema_version != DEFAULT_SCHEMA_VERSION:
            raise GatewayStatePersistenceError(
                code="unsupported_schema",
                message=f"Unsupported schema_version: {schema_version!r}",
                http_status=500,
            )

        state = parsed.get("state", {})
        version = parsed.get("version", 0)
        updated_at = parsed.get("updated_at", 0.0)

        if not isinstance(state, dict) or not isinstance(version, int) or not isinstance(updated_at, (int, float)):
            raise GatewayStatePersistenceError(
                code="invalid_state_file",
                message="State file fields have invalid types",
                http_status=500,
            )

        self._state = state
        self._version = version
        self._updated_at = float(updated_at)


# ----------------------------
# aiohttp routes
# ----------------------------

routes = web.RouteTableDef()
_APP_KEY = "thomas.gateway_state_persistence"


def _get_persistence(app: web.Application) -> GatewayStatePersistence:
    existing = app.get(_APP_KEY)
    if isinstance(existing, GatewayStatePersistence):
        return existing

    base_dir_str = os.environ.get(DEFAULT_STATE_DIR_ENV)
    effective_dir: Optional[Path] = None
    if base_dir_str:
        effective_dir = (Path(base_dir_str).expanduser().resolve() / DEFAULT_STATE_SUBDIR).resolve()

    persistence = GatewayStatePersistence(config=PersistenceConfig(mode="memory", state_dir=effective_dir))
    app[_APP_KEY] = persistence
    return persistence


def _set_state_headers(resp: web.Response, version: int) -> None:
    resp.headers["ETag"] = f'W/"{version}"'
    resp.headers["X-Thomas-Gateway-State-Version"] = str(version)


def _parse_if_match(request: web.Request) -> Optional[int]:
    raw = request.headers.get("If-Match")
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("W/"):
        raw = raw[2:].strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        raw = raw[1:-1]
    try:
        v = int(raw)
        return v if v >= 0 else None
    except Exception:
        return None


@routes.get("/v1/gateway/state/persistence-model")
async def get_persistence_model(request: web.Request) -> web.Response:
    persistence = _get_persistence(request.app)
    return web.json_response(persistence.config.to_response())


@routes.post("/v1/gateway/state/persistence-model")
async def set_persistence_model(request: web.Request) -> web.Response:
    persistence = _get_persistence(request.app)
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        return _json_error(GatewayStatePersistenceError("invalid_json", f"Request body must be valid JSON: {e}", 400))

    if not isinstance(body, dict):
        return _json_error(GatewayStatePersistenceError("invalid_request", "Request body must be a JSON object", 400))

    try:
        resp = await persistence.configure(cast(PersistenceModelRequest, body))
        return web.json_response(resp)
    except GatewayStatePersistenceError as err:
        return _json_error(err)


@routes.get("/v1/gateway/state")
async def get_gateway_state(request: web.Request) -> web.Response:
    persistence = _get_persistence(request.app)
    try:
        snap = await persistence.get_state()
        resp = web.json_response(snap)
        _set_state_headers(resp, snap["version"])
        return resp
    except GatewayStatePersistenceError as err:
        return _json_error(err)


@routes.put("/v1/gateway/state")
async def put_gateway_state(request: web.Request) -> web.Response:
    persistence = _get_persistence(request.app)
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        return _json_error(GatewayStatePersistenceError("invalid_json", f"Request body must be valid JSON: {e}", 400))

    if not isinstance(body, dict) or "state" not in body:
        return _json_error(
            GatewayStatePersistenceError("invalid_request", "Request body must be a JSON object with a 'state' field", 400)
        )

    state = body.get("state")
    expected_version = body.get("expected_version")
    if expected_version is None:
        expected_version = _parse_if_match(request)

    try:
        if not isinstance(state, dict):
            raise GatewayStatePersistenceError("invalid_request", "'state' must be a JSON object", 400)

        snap = await persistence.set_state(state, expected_version=cast(Optional[int], expected_version))
        resp = web.json_response(snap)
        _set_state_headers(resp, snap["version"])
        return resp
    except GatewayStatePersistenceError as err:
        return _json_error(err)


# ----------------------------
# Registration helpers
# ----------------------------


def register(app: web.Application) -> None:
    app.add_routes(routes)


def setup(app: web.Application) -> None:
    register(app)


def add_routes(app: web.Application) -> None:
    register(app)
