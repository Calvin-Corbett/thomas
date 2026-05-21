"""Node host restart command.

This module implements the Thomas-native behavior for restarting a local *node host*
service (the background node process that connects back to a gateway).

It intentionally does not reuse legacy/Reference CLI naming internally.

Contracts
---------
Input: ``NodeRestartRequest``
Output: ``NodeRestartResult``

Failures raise ``NodeRestartError`` with deterministic ``code`` values suitable for
automation.

Error codes
-----------
* ``invalid_input`` — request fields are invalid (e.g., non-positive timeout).
* ``missing_config`` — node host is not installed/configured (no node.json).
* ``invalid_config`` — config exists but is unreadable/invalid JSON.
* ``unsupported_platform`` — platform/service manager cannot be determined.
* ``external_failure`` — service manager invocation failed.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_NODE_CONFIG_FILENAME = "node.json"
DEFAULT_NODE_SERVICE_NAME = "thomas-node"

ENV_STATE_DIR = "THOMAS_STATE_DIR"


@dataclass(frozen=True, slots=True)
class NodeRestartRequest:
    """Inputs for restarting the local node host service."""

    # Where Thomas keeps local state (used to locate node.json) if config_path is not set.
    state_dir: Path | None = None

    # Explicit path to the node config file (overrides state_dir).
    config_path: Path | None = None

    # Optional override for the service name. If omitted, resolved from config or default.
    service_name: str | None = None

    # Max time to wait for each service-manager step.
    timeout_s: float = 30.0

    # Force a specific service manager (mainly for tests/automation). If None, we auto-detect.
    manager: str | None = None


@dataclass(frozen=True, slots=True)
class NodeRestartStep:
    """One external step executed to perform the restart."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NodeRestartResult:
    """Result of a restart attempt."""

    ok: bool
    service_name: str
    manager: str
    steps: list[NodeRestartStep]
    started_at_s: float
    finished_at_s: float
    meta: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure Mapping is concretely serializable.
        d["meta"] = dict(self.meta)
        # dataclasses.asdict already handled steps, but keep explicit for clarity.
        d["steps"] = [s.to_dict() for s in self.steps]
        return d


class NodeRestartError(RuntimeError):
    """Deterministic restart failure.

    ``code`` values are stable for programmatic handling.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})
        self.exit_code = exit_code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": dict(self.details)}


def restart_node_host_service(req: NodeRestartRequest) -> NodeRestartResult:
    """Restart the local node host service.

    Raises:
        NodeRestartError: for invalid input, missing/invalid config, unsupported
            platform, or external failures.
    """
    _validate_request(req)

    config_path = _resolve_config_path(req)
    config = _read_node_config(config_path)

    service_name = _resolve_service_name(req, config)
    manager = _resolve_manager(req, config)

    started = time.time()
    steps: list[NodeRestartStep] = []
    meta: dict[str, Any] = {"config_path": str(config_path)}

    # Build the intended steps. For Windows we have a best-effort primary plan and
    # a deterministic fallback if PowerShell is missing.
    planned_steps = _build_restart_steps(manager, service_name)

    try:
        for cmd in planned_steps:
            step = _run_step(cmd, timeout_s=req.timeout_s)
            steps.append(step)
            if step.returncode != 0:
                raise NodeRestartError(
                    "external_failure",
                    "Failed to restart node service.",
                    details={
                        "manager": manager,
                        "service_name": service_name,
                        "steps": [s.to_dict() for s in steps],
                    },
                    exit_code=1,
                )
    except FileNotFoundError as e:
        # Windows fallback: PowerShell may not exist in minimal environments.
        if manager.lower() == "windows" and planned_steps and planned_steps[0]:
            primary_exe = planned_steps[0][0].lower()
            if primary_exe in ("powershell", "powershell.exe"):
                meta["windows_fallback"] = "sc"
                steps.clear()
                for cmd in _build_windows_sc_fallback_steps(service_name):
                    step = _run_step(cmd, timeout_s=req.timeout_s)
                    steps.append(step)
                    if step.returncode != 0:
                        raise NodeRestartError(
                            "external_failure",
                            "Failed to restart node service.",
                            details={
                                "manager": manager,
                                "service_name": service_name,
                                "steps": [s.to_dict() for s in steps],
                            },
                            exit_code=1,
                        )
            else:
                raise NodeRestartError(
                    "external_failure",
                    "Service manager command not found.",
                    details={"manager": manager, "command": planned_steps[0], "error": str(e)},
                    exit_code=1,
                ) from e
        else:
            raise NodeRestartError(
                "external_failure",
                "Service manager command not found.",
                details={"manager": manager, "error": str(e)},
                exit_code=1,
            ) from e
    except subprocess.TimeoutExpired as e:
        raise NodeRestartError(
            "external_failure",
            "Timed out while restarting node service.",
            details={
                "manager": manager,
                "service_name": service_name,
                "timeout_s": req.timeout_s,
                "command": getattr(e, "cmd", None),
            },
            exit_code=1,
        ) from e
    finally:
        finished = time.time()

    return NodeRestartResult(
        ok=True,
        service_name=service_name,
        manager=manager,
        steps=steps,
        started_at_s=started,
        finished_at_s=finished,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_request(req: NodeRestartRequest) -> None:
    if req.timeout_s <= 0:
        raise NodeRestartError(
            "invalid_input",
            "timeout_s must be > 0.",
            details={"timeout_s": req.timeout_s},
            exit_code=2,
        )
    if req.service_name is not None and not req.service_name.strip():
        raise NodeRestartError(
            "invalid_input",
            "service_name must be a non-empty string when provided.",
            details={"service_name": req.service_name},
            exit_code=2,
        )
    if req.manager is not None and not str(req.manager).strip():
        raise NodeRestartError(
            "invalid_input",
            "manager must be a non-empty string when provided.",
            details={"manager": req.manager},
            exit_code=2,
        )


def _resolve_config_path(req: NodeRestartRequest) -> Path:
    if req.config_path is not None:
        path = Path(req.config_path).expanduser()
    else:
        state_dir = Path(req.state_dir).expanduser() if req.state_dir is not None else _default_state_dir()
        path = state_dir / DEFAULT_NODE_CONFIG_FILENAME

    if not path.exists():
        raise NodeRestartError(
            "missing_config",
            "Node host is not configured. Run `thomas nodes install` first.",
            details={"config_path": str(path)},
            exit_code=2,
        )

    if not path.is_file():
        raise NodeRestartError(
            "invalid_config",
            "Node config path is not a file.",
            details={"config_path": str(path)},
            exit_code=2,
        )

    return path


def _default_state_dir() -> Path:
    # Explicit override.
    if env := os.environ.get(ENV_STATE_DIR):
        return Path(env).expanduser()

    # XDG convention (Linux-ish).
    if xdg := os.environ.get("XDG_CONFIG_HOME"):
        return Path(xdg).expanduser() / "thomas"

    return Path.home() / ".thomas"


def _read_node_config(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise NodeRestartError(
            "invalid_config",
            "Could not read node config.",
            details={"config_path": str(path), "error": str(e)},
            exit_code=2,
        ) from e

    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise NodeRestartError(
            "invalid_config",
            "Node config is not valid JSON.",
            details={"config_path": str(path), "error": str(e)},
            exit_code=2,
        ) from e

    if not isinstance(data, dict):
        raise NodeRestartError(
            "invalid_config",
            "Node config must be a JSON object.",
            details={"config_path": str(path)},
            exit_code=2,
        )

    return data


def _resolve_service_name(req: NodeRestartRequest, config: Mapping[str, Any]) -> str:
    if req.service_name is not None:
        return req.service_name.strip()

    # Common shapes:
    # - {"serviceName": "..."}
    # - {"nodeHost": {"serviceName": "..."}}
    for key in ("serviceName", "service_name", "service"):
        val = config.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    node_host = config.get("nodeHost")
    if isinstance(node_host, dict):
        for key in ("serviceName", "service_name", "service"):
            val = node_host.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    return DEFAULT_NODE_SERVICE_NAME


def _resolve_manager(req: NodeRestartRequest, config: Mapping[str, Any]) -> str:
    if req.manager is not None:
        return str(req.manager).strip()

    # Config override (if present).
    for key in ("manager", "serviceManager", "service_manager"):
        val = config.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    node_host = config.get("nodeHost")
    if isinstance(node_host, dict):
        for key in ("manager", "serviceManager", "service_manager"):
            val = node_host.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    return _detect_manager()


def _detect_manager() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "systemd"
    if system == "darwin":
        return "launchd"
    if system == "windows":
        return "windows"

    raise NodeRestartError(
        "unsupported_platform",
        "Unsupported platform for node service control.",
        details={"platform": platform.system()},
        exit_code=1,
    )


def _build_restart_steps(manager: str, service_name: str) -> list[list[str]]:
    m = manager.lower()
    if m == "systemd":
        # User-level systemd unit.
        return [["systemctl", "--user", "restart", service_name]]

    if m == "launchd":
        target = service_name
        if "/" not in target:
            # Default to user GUI domain. This is best-effort and can be overridden by
            # providing a fully-qualified target in service_name, e.g.:
            #   gui/501/com.example.thomas-node
            uid = getattr(os, "getuid", lambda: 0)()
            target = f"gui/{uid}/{target}"
        return [["launchctl", "kickstart", "-k", target]]

    if m == "windows":
        # Primary path: PowerShell Restart-Service, which handles stop/start sequencing.
        escaped = service_name.replace("'", "''")
        ps = f"Restart-Service -Name '{escaped}' -Force"
        return [["powershell", "-NoProfile", "-Command", ps]]

    raise NodeRestartError(
        "invalid_input",
        "Unknown service manager.",
        details={"manager": manager},
        exit_code=2,
    )


def _build_windows_sc_fallback_steps(service_name: str) -> list[list[str]]:
    # Fallback path if PowerShell isn't present.
    return [["sc", "stop", service_name], ["sc", "start", service_name]]


def _run_step(cmd: Sequence[str], *, timeout_s: float) -> NodeRestartStep:
    proc = subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return NodeRestartStep(
        command=list(cmd),
        returncode=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


# Compatibility aliases for potential registry/older callsites.
restart = restart_node_host_service
restart_node = restart_node_host_service
