"""Node host lifecycle service.

This module provides Thomas-native management of a *local* "node host" service.

Why a state-file service?
-------------------------
The upstream tool that inspired this prompt installs an OS-level background
service (systemd/launchd/Windows Service). The Thomas codebase is expected to run
in many environments where that isn't practical (CI runners, containers, locked
down developer machines).

To keep behavior deterministic and testable, this implementation models the
service lifecycle using two JSON files inside the Thomas config directory:

- ``node_host.json``: configuration (gateway address, TLS options, node identity)
- ``node_host_service_state.json``: lifecycle state (installed/running flags)

If a real service manager exists elsewhere in the codebase, it can be wired in
behind this interface later without changing the contracts exposed here.

Public API
----------
- ``NodeHostLifecycleService``: main entrypoint
- ``NodeHostInstallRequest`` / ``NodeHostActionResult`` / ``NodeHostStatus``:
  input/output contracts
- ``NodeHostServiceError`` / ``NodeHostServiceErrorCode``: deterministic errors

"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class NodeHostServiceErrorCode(str, Enum):
    """Stable, machine-readable error codes for lifecycle operations."""

    INVALID_INPUT = "invalid_input"
    NOT_INSTALLED = "not_installed"
    ALREADY_INSTALLED = "already_installed"
    CORRUPT_STATE = "corrupt_state"
    EXTERNAL_FAILURE = "external_failure"


class NodeHostServiceError(RuntimeError):
    """Deterministic exception type for node host service operations."""

    def __init__(
        self,
        code: NodeHostServiceErrorCode,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details: Dict[str, Any] = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": str(self),
            "details": self.details,
        }


@dataclass(frozen=True)
class NodeHostInstallRequest:
    """Input contract for installing/configuring the node host service."""

    gateway_host: str = "127.0.0.1"
    gateway_port: int = 18789
    tls: bool = False
    tls_fingerprint_sha256: Optional[str] = None

    node_id: Optional[str] = None
    display_name: Optional[str] = None

    runtime: str = "python"  # maps to an underlying runtime (implementation-defined)
    force: bool = False


@dataclass(frozen=True)
class NodeHostStatus:
    """Output contract for querying node host service status."""

    installed: bool
    running: bool

    gateway_host: Optional[str] = None
    gateway_port: Optional[int] = None
    tls: Optional[bool] = None
    tls_fingerprint_sha256: Optional[str] = None

    node_id: Optional[str] = None
    display_name: Optional[str] = None

    runtime: Optional[str] = None

    config_path: Optional[str] = None
    state_path: Optional[str] = None

    last_action: Optional[str] = None
    updated_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodeHostActionResult:
    """Output contract for lifecycle actions (install/stop/restart/uninstall)."""

    ok: bool
    action: str
    status: NodeHostStatus
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "message": self.message,
            "status": self.status.to_dict(),
        }


_FINGERPRINT_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def _normalize_fingerprint(value: str) -> str:
    """Normalize a fingerprint to lowercase 64 hex chars."""

    m = _FINGERPRINT_RE.match(value.strip())
    if not m:
        raise ValueError("expected 64 hex characters (optionally prefixed with 'sha256:')")
    return m.group(1).lower()


def _default_thomas_home() -> Path:
    """Resolve the Thomas config directory with minimal coupling."""

    # Prefer a shared helper if the wider codebase provides one.
    try:
        from thomas.config import get_thomas_home  # type: ignore

        home = get_thomas_home()
        return Path(home)
    except Exception:
        pass

    env_home = os.environ.get("THOMAS_HOME")
    if env_home:
        return Path(env_home)

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "thomas"

    return Path.home() / ".thomas"


class NodeHostLifecycleService:
    """Manage the lifecycle of the local node host service."""

    _CONFIG_FILE = "node_host.json"
    _STATE_FILE = "node_host_service_state.json"
    _SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        config_dir: Optional[Path] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config_dir = Path(config_dir) if config_dir else _default_thomas_home()
        self._clock = clock

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def config_path(self) -> Path:
        return self._config_dir / self._CONFIG_FILE

    @property
    def state_path(self) -> Path:
        return self._config_dir / self._STATE_FILE

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    def install(self, req: NodeHostInstallRequest) -> NodeHostActionResult:
        req = self._validate_install_request(req)

        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.EXTERNAL_FAILURE,
                "Failed to create config directory",
                details={"path": str(self._config_dir), "cause": e.__class__.__name__},
            ) from e

        if self.config_path.exists() and not req.force:
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.ALREADY_INSTALLED,
                "Node host service is already installed (use --force to overwrite)",
                details={"config_path": str(self.config_path)},
            )

        config_payload: Dict[str, Any] = {
            "schema": self._SCHEMA_VERSION,
            "gateway": {
                "host": req.gateway_host,
                "port": req.gateway_port,
                "tls": req.tls,
                "tls_fingerprint_sha256": req.tls_fingerprint_sha256,
            },
            "node": {
                "id": req.node_id,
                "display_name": req.display_name,
            },
            "service": {
                "runtime": req.runtime,
                "installed_at": self._clock(),
            },
        }

        state_payload: Dict[str, Any] = {
            "schema": self._SCHEMA_VERSION,
            "installed": True,
            "running": True,
            "runtime": req.runtime,
            "last_action": "install",
            "updated_at": self._clock(),
        }

        self._write_json_atomic(self.config_path, config_payload)
        self._write_json_atomic(self.state_path, state_payload)

        return NodeHostActionResult(
            ok=True,
            action="install",
            status=self.status(),
            message="Node host service installed",
        )

    def status(self) -> NodeHostStatus:
        if not self.config_path.exists() and not self.state_path.exists():
            return NodeHostStatus(
                installed=False,
                running=False,
                config_path=str(self.config_path),
                state_path=str(self.state_path),
            )

        config = self._read_json(self.config_path, kind="config") if self.config_path.exists() else None
        state = self._read_json(self.state_path, kind="state") if self.state_path.exists() else None

        # If state exists, it is authoritative. Otherwise, a config-only install is
        # treated as installed but not running.
        installed = bool(state.get("installed")) if state is not None else True
        running = bool(state.get("running")) if state is not None else False

        gateway = (config or {}).get("gateway", {})
        node = (config or {}).get("node", {})
        service = (config or {}).get("service", {})

        return NodeHostStatus(
            installed=installed,
            running=running,
            gateway_host=gateway.get("host"),
            gateway_port=gateway.get("port"),
            tls=gateway.get("tls"),
            tls_fingerprint_sha256=gateway.get("tls_fingerprint_sha256"),
            node_id=node.get("id"),
            display_name=node.get("display_name"),
            runtime=(state or {}).get("runtime") or service.get("runtime"),
            config_path=str(self.config_path),
            state_path=str(self.state_path),
            last_action=(state or {}).get("last_action"),
            updated_at=(state or {}).get("updated_at"),
        )

    def stop(self) -> NodeHostActionResult:
        self._require_state_for_action("stop")
        state = self._read_json(self.state_path, kind="state")
        state.update(
            {
                "running": False,
                "last_action": "stop",
                "updated_at": self._clock(),
            }
        )
        self._write_json_atomic(self.state_path, state)
        return NodeHostActionResult(
            ok=True,
            action="stop",
            status=self.status(),
            message="Node host service stopped",
        )

    def restart(self) -> NodeHostActionResult:
        self._require_state_for_action("restart")
        state = self._read_json(self.state_path, kind="state")
        state.update(
            {
                "running": True,
                "last_action": "restart",
                "updated_at": self._clock(),
            }
        )
        self._write_json_atomic(self.state_path, state)
        return NodeHostActionResult(
            ok=True,
            action="restart",
            status=self.status(),
            message="Node host service restarted",
        )

    def uninstall(self) -> NodeHostActionResult:
        # Uninstall is intentionally tolerant: if *either* marker exists, we try
        # to remove it. This keeps cleanup possible even if state is missing.
        if not self.config_path.exists() and not self.state_path.exists():
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.NOT_INSTALLED,
                "Cannot uninstall: node host service is not installed",
                details={"action": "uninstall"},
            )

        prior = self.status()

        for path in (self.config_path, self.state_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError as e:
                raise NodeHostServiceError(
                    NodeHostServiceErrorCode.EXTERNAL_FAILURE,
                    "Failed to remove service files",
                    details={"path": str(path), "cause": e.__class__.__name__},
                ) from e

        after = self.status()
        return NodeHostActionResult(
            ok=True,
            action="uninstall",
            status=after,
            message=f"Node host service uninstalled (was running={prior.running})",
        )

    # ------------------------------------------------------------------
    # Validation and persistence helpers
    # ------------------------------------------------------------------

    def _validate_install_request(self, req: NodeHostInstallRequest) -> NodeHostInstallRequest:
        if not isinstance(req.gateway_host, str) or not req.gateway_host.strip():
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.INVALID_INPUT,
                "gateway_host must be a non-empty string",
                details={"field": "gateway_host"},
            )

        if not isinstance(req.gateway_port, int) or not (1 <= req.gateway_port <= 65535):
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.INVALID_INPUT,
                "gateway_port must be an integer between 1 and 65535",
                details={"field": "gateway_port"},
            )

        if req.tls_fingerprint_sha256 is not None and not req.tls:
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.INVALID_INPUT,
                "tls_fingerprint_sha256 requires tls=True",
                details={"field": "tls_fingerprint_sha256"},
            )

        if req.tls_fingerprint_sha256 is not None:
            if not isinstance(req.tls_fingerprint_sha256, str) or not req.tls_fingerprint_sha256.strip():
                raise NodeHostServiceError(
                    NodeHostServiceErrorCode.INVALID_INPUT,
                    "tls_fingerprint_sha256 must be a non-empty string when provided",
                    details={"field": "tls_fingerprint_sha256"},
                )
            try:
                normalized = _normalize_fingerprint(req.tls_fingerprint_sha256)
            except ValueError as e:
                raise NodeHostServiceError(
                    NodeHostServiceErrorCode.INVALID_INPUT,
                    f"tls_fingerprint_sha256 is invalid: {e}",
                    details={"field": "tls_fingerprint_sha256"},
                ) from e
            req = NodeHostInstallRequest(
                gateway_host=req.gateway_host,
                gateway_port=req.gateway_port,
                tls=req.tls,
                tls_fingerprint_sha256=normalized,
                node_id=req.node_id,
                display_name=req.display_name,
                runtime=req.runtime,
                force=req.force,
            )

        if req.node_id is not None and (not isinstance(req.node_id, str) or not req.node_id.strip()):
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.INVALID_INPUT,
                "node_id must be a non-empty string when provided",
                details={"field": "node_id"},
            )

        if req.display_name is not None and (
            not isinstance(req.display_name, str) or not req.display_name.strip()
        ):
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.INVALID_INPUT,
                "display_name must be a non-empty string when provided",
                details={"field": "display_name"},
            )

        if not isinstance(req.runtime, str) or not req.runtime.strip():
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.INVALID_INPUT,
                "runtime must be a non-empty string",
                details={"field": "runtime"},
            )

        return req

    def _require_state_for_action(self, action: str) -> None:
        if not self.config_path.exists() and not self.state_path.exists():
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.NOT_INSTALLED,
                f"Cannot {action}: node host service is not installed",
                details={"action": action},
            )

        if not self.state_path.exists():
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.CORRUPT_STATE,
                f"Cannot {action}: service state is missing",
                details={"action": action, "state_path": str(self.state_path)},
            )

    def _read_json(self, path: Path, *, kind: str) -> Dict[str, Any]:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.EXTERNAL_FAILURE,
                f"Failed to read {kind} file",
                details={"path": str(path), "cause": e.__class__.__name__},
            ) from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.CORRUPT_STATE,
                f"{kind} file is not valid JSON",
                details={"path": str(path), "cause": e.__class__.__name__},
            ) from e

        if not isinstance(data, dict):
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.CORRUPT_STATE,
                f"{kind} file must contain a JSON object",
                details={"path": str(path)},
            )

        schema = data.get("schema")
        if schema not in (None, self._SCHEMA_VERSION):
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.CORRUPT_STATE,
                f"Unsupported {kind} schema version",
                details={"path": str(path), "schema": schema},
            )

        return data

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            raise NodeHostServiceError(
                NodeHostServiceErrorCode.EXTERNAL_FAILURE,
                "Failed to write service file",
                details={"path": str(path), "cause": e.__class__.__name__},
            ) from e
