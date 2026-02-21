"""Thomas node host install (P031).

This module implements the Thomas-native behavior for the CLI command:

    thomas node install

The goal is to provision a *local* node-host configuration plus a service unit
file that operators (or automation) can enable using their preferred service
manager.

Design goals:
* Deterministic, machine-readable failures (stable error codes).
* Clear input/output contracts for programmatic use.
* Minimal assumptions about the wider Thomas environment.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

PROMPT_ID = "p031"
PARITY_COMMAND = "node install"

DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 18789


# ---- Automation schemas (route / --json) ------------------------------------

NODE_INSTALL_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {"type": ["string", "null"]},
        "port": {"type": ["integer", "null"], "minimum": 1, "maximum": 65535},
        "tls": {"type": "boolean"},
        "tls_fingerprint": {"type": ["string", "null"]},
        "node_id": {"type": ["string", "null"]},
        "display_name": {"type": ["string", "null"]},
        "runtime": {"type": "string"},
        "force": {"type": "boolean"},
    },
}

NODE_INSTALL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "ok": {"type": "boolean"},
        "node_id": {"type": "string"},
        "config_path": {"type": "string"},
        "env_path": {"type": "string"},
        "service_path": {"type": "string"},
        "gateway_host": {"type": "string"},
        "gateway_port": {"type": "integer"},
        "tls": {"type": "boolean"},
        "tls_fingerprint": {"type": ["string", "null"]},
        "runtime": {"type": "string"},
        "display_name": {"type": ["string", "null"]},
        "wrote_files": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
            },
        },
    },
}

# Friendly aliases in case other parts of Thomas use generic names.
REQUEST_SCHEMA = NODE_INSTALL_REQUEST_SCHEMA
RESPONSE_SCHEMA = NODE_INSTALL_RESPONSE_SCHEMA


# ---- Deterministic errors ----------------------------------------------------


class NodeInstallError(Exception):
    """Base exception for deterministic node-install failures."""

    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class NodeInstallInputError(NodeInstallError):
    """Raised when user input is invalid."""


class NodeInstallConfigError(NodeInstallError):
    """Raised when required configuration is missing or inconsistent."""


class NodeInstallExternalError(NodeInstallError):
    """Raised when the OS/filesystem prevents completing the install."""


# ---- Contracts --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NodeInstallRequest:
    """Input contract for node install."""

    host: str | None = None
    port: int | None = None
    tls: bool = False
    tls_fingerprint: str | None = None
    node_id: str | None = None
    display_name: str | None = None
    runtime: str = "python"
    force: bool = False

    # Advanced / programmatic knobs (not exposed in JSON schema by default).
    gateway_token: str | None = None
    home_dir: str | None = None


@dataclass(frozen=True, slots=True)
class NodeInstallResult:
    """Output contract for node install."""

    ok: bool
    node_id: str
    config_path: str
    env_path: str
    service_path: str
    gateway_host: str
    gateway_port: int
    tls: bool
    tls_fingerprint: str | None
    runtime: str
    display_name: str | None
    wrote_files: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- Validation helpers ------------------------------------------------------

_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalize_fingerprint(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", value).lower()
    if not _FINGERPRINT_HEX_RE.fullmatch(cleaned):
        raise NodeInstallInputError(
            "NODE_INSTALL_INVALID_TLS_FINGERPRINT",
            "TLS fingerprint must be a 64-character hex SHA-256 fingerprint.",
            details={"provided": value},
        )
    return cleaned


def _validate_host(host: str) -> str:
    host = host.strip()
    if not host:
        raise NodeInstallInputError("NODE_INSTALL_INVALID_HOST", "Gateway host must be non-empty.")
    if any(c.isspace() for c in host):
        raise NodeInstallInputError(
            "NODE_INSTALL_INVALID_HOST",
            "Gateway host must not contain whitespace.",
            details={"provided": host},
        )
    return host


def _validate_port(port: int) -> int:
    if not isinstance(port, int):
        raise NodeInstallInputError(
            "NODE_INSTALL_INVALID_PORT",
            "Gateway port must be an integer.",
            details={"provided": port},
        )
    if port < 1 or port > 65535:
        raise NodeInstallInputError(
            "NODE_INSTALL_INVALID_PORT",
            "Gateway port must be between 1 and 65535.",
            details={"provided": port},
        )
    return port


def _validate_runtime(runtime: str) -> str:
    runtime = runtime.strip().lower()
    allowed = {"python"}
    if runtime not in allowed:
        raise NodeInstallInputError(
            "NODE_INSTALL_INVALID_RUNTIME",
            f"Unsupported runtime '{runtime}'. Supported: {', '.join(sorted(allowed))}.",
            details={"provided": runtime},
        )
    return runtime


def _validate_gateway_token(token: str) -> str:
    # Keep this conservative; env files and service managers can be picky.
    token = token.strip()
    if not token:
        raise NodeInstallConfigError(
            "NODE_INSTALL_INVALID_GATEWAY_TOKEN",
            "Gateway token must be non-empty.",
        )
    if any(ch.isspace() for ch in token) or "\x00" in token:
        raise NodeInstallConfigError(
            "NODE_INSTALL_INVALID_GATEWAY_TOKEN",
            "Gateway token must not contain whitespace or NUL characters.",
        )
    return token


def _resolve_home_dir(request: NodeInstallRequest) -> Path:
    if request.home_dir:
        return Path(request.home_dir).expanduser().resolve()

    env_home = os.environ.get("THOMAS_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return (Path(xdg).expanduser() / "thomas").resolve()

    return (Path.home() / ".thomas").resolve()


def _atomic_write_text(path: Path, content: str, *, mode: int) -> None:
    """Write text atomically to *path* with best-effort permissions."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            try:
                os.chmod(tmp, mode)
            except OSError:
                # Best effort: chmod might be unsupported (e.g., some Windows setups).
                pass
            os.replace(tmp, path)
        finally:
            # If replace failed, ensure we don't leave temp files lying around.
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    except OSError as e:
        raise NodeInstallExternalError(
            "NODE_INSTALL_WRITE_FAILED",
            f"Failed to write '{path}': {e.strerror or str(e)}",
            details={"path": str(path), "errno": getattr(e, "errno", None)},
        ) from e


def _read_existing_config(path: Path, *, strict: bool) -> tuple[dict[str, Any] | None, str | None]:
    """Read existing node.json config.

    Returns (config_dict_or_none, warning_or_none).
    """

    if not path.exists():
        return None, None

    try:
        raw = path.read_text(encoding="utf-8")
        cfg = json.loads(raw)
        if isinstance(cfg, dict):
            return cfg, None
        if strict:
            raise NodeInstallConfigError(
                "NODE_INSTALL_INVALID_EXISTING_CONFIG",
                "Existing node.json must be a JSON object.",
                details={"config_path": str(path)},
            )
        return (
            None,
            "NODE_INSTALL_WARNING_INVALID_EXISTING_CONFIG: existing node.json was not an object and was ignored",
        )
    except NodeInstallError:
        raise
    except Exception as e:
        if strict:
            raise NodeInstallConfigError(
                "NODE_INSTALL_INVALID_EXISTING_CONFIG",
                "Existing node.json was not valid JSON.",
                details={"config_path": str(path)},
            ) from e
        return None, "NODE_INSTALL_WARNING_INVALID_EXISTING_CONFIG: existing node.json was invalid JSON and was ignored"


def _quote_arg(value: str) -> str:
    """Minimal quoting for systemd-style ExecStart= tokens."""

    if not value or any(ch.isspace() for ch in value) or any(ch in value for ch in ['"', "'", "\\"]):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _quote_unit_value(value: str) -> str:
    """Quote a unit-file directive value if it contains spaces or quotes."""

    if not value:
        return '""'
    if any(ch.isspace() for ch in value) or any(ch in value for ch in ['"', "\\"]):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


# ---- Core implementation -----------------------------------------------------


def install_node_command(
    request: NodeInstallRequest,
    *,
    node_id_factory: Callable[[], str] | None = None,
) -> NodeInstallResult:
    """Install a Thomas node host as a user service.

    Writes (relative to THOMAS_HOME or XDG config dir):
      * node.json  : node host configuration
      * node.env   : environment file containing THOMAS_GATEWAY_TOKEN
      * services/thomas-node.service : systemd-compatible user unit file
    """

    home_dir = _resolve_home_dir(request)
    config_path = home_dir / "node.json"
    env_path = home_dir / "node.env"
    service_path = home_dir / "services" / "thomas-node.service"

    if config_path.exists() and not request.force:
        raise NodeInstallConfigError(
            "NODE_INSTALL_ALREADY_INSTALLED",
            "Node host is already installed. Re-run with --force to overwrite.",
            details={"config_path": str(config_path)},
        )

    warnings: list[str] = []
    existing, warn = _read_existing_config(config_path, strict=False)
    if warn:
        warnings.append(warn)

    host = request.host or os.environ.get("THOMAS_GATEWAY_HOST") or DEFAULT_GATEWAY_HOST
    port: int | None = request.port
    if port is None:
        env_port = os.environ.get("THOMAS_GATEWAY_PORT")
        if env_port:
            try:
                port = int(env_port)
            except ValueError as e:
                raise NodeInstallConfigError(
                    "NODE_INSTALL_INVALID_GATEWAY_PORT",
                    "THOMAS_GATEWAY_PORT must be an integer.",
                    details={"provided": env_port},
                ) from e
        else:
            port = DEFAULT_GATEWAY_PORT

    host = _validate_host(host)
    port = _validate_port(port)

    if request.tls_fingerprint and not request.tls:
        raise NodeInstallInputError(
            "NODE_INSTALL_TLS_FINGERPRINT_REQUIRES_TLS",
            "--tls-fingerprint requires --tls.",
        )

    tls_fp = request.tls_fingerprint
    if tls_fp is not None:
        tls_fp = _normalize_fingerprint(tls_fp)

    runtime = _validate_runtime(request.runtime)

    token = request.gateway_token or os.environ.get("THOMAS_GATEWAY_TOKEN")
    if not token:
        raise NodeInstallConfigError(
            "NODE_INSTALL_MISSING_GATEWAY_TOKEN",
            "Missing gateway token. Set THOMAS_GATEWAY_TOKEN or pass gateway_token programmatically.",
        )
    token = _validate_gateway_token(token)

    # Reuse existing node id/display name when overwriting unless explicitly set.
    existing_node = (existing or {}).get("node", {}) if isinstance(existing, dict) else {}
    node_id = request.node_id or existing_node.get("id")
    if not node_id:
        factory = node_id_factory or (lambda: str(uuid.uuid4()))
        node_id = factory()
    node_id = str(node_id).strip()
    if not node_id or any(c.isspace() for c in node_id):
        raise NodeInstallInputError(
            "NODE_INSTALL_INVALID_NODE_ID",
            "node_id must be non-empty and must not contain whitespace.",
            details={"provided": node_id},
        )

    display_name = request.display_name
    if display_name is None:
        display_name = existing_node.get("display_name")
    if display_name is not None:
        display_name = str(display_name).strip()
        if not display_name:
            display_name = None
        elif len(display_name) > 128:
            raise NodeInstallInputError(
                "NODE_INSTALL_INVALID_DISPLAY_NAME",
                "display_name must be 128 characters or fewer.",
                details={"provided": display_name},
            )

    node_cfg: dict[str, Any] = {
        "node": {"id": node_id, "display_name": display_name},
        "gateway": {
            "host": host,
            "port": port,
            "tls": bool(request.tls),
            "tls_fingerprint": tls_fp,
        },
        "runtime": runtime,
    }

    wrote: list[str] = []

    _atomic_write_text(
        config_path,
        json.dumps(node_cfg, indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )
    wrote.append(str(config_path))

    # systemd EnvironmentFile format is "KEY=VALUE" per line. Keep it simple.
    _atomic_write_text(env_path, f"THOMAS_GATEWAY_TOKEN={token}\n", mode=0o600)
    wrote.append(str(env_path))

    # Keep the unit file inside THOMAS_HOME to avoid invasive system changes.
    # Operators can copy/symlink this into ~/.config/systemd/user/ if desired.
    exec_parts = [sys.executable, "-m", "thomas", "node", "run"]
    exec_start = " ".join(_quote_arg(p) for p in exec_parts)

    env_assignment = f"THOMAS_HOME={home_dir}"
    unit = "\n".join(
        [
            "[Unit]",
            "Description=Thomas Node Host",
            "After=network.target",
            "",
            "[Service]",
            "Type=simple",
            f"Environment={env_assignment}",
            f"EnvironmentFile={_quote_unit_value(str(env_path))}",
            f"WorkingDirectory={_quote_unit_value(str(home_dir))}",
            f"ExecStart={exec_start}",
            "Restart=on-failure",
            "RestartSec=2",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    _atomic_write_text(service_path, unit, mode=0o644)
    wrote.append(str(service_path))

    return NodeInstallResult(
        ok=True,
        node_id=node_id,
        config_path=str(config_path),
        env_path=str(env_path),
        service_path=str(service_path),
        gateway_host=host,
        gateway_port=port,
        tls=bool(request.tls),
        tls_fingerprint=tls_fp,
        runtime=runtime,
        display_name=display_name,
        wrote_files=tuple(wrote),
        warnings=tuple(warnings),
    )


def render_install_result_human(result: NodeInstallResult) -> str:
    lines = [
        "Node host installed.",
        f"Node ID: {result.node_id}",
        f"Gateway: {result.gateway_host}:{result.gateway_port}{' (tls)' if result.tls else ''}",
        f"Config: {result.config_path}",
        f"Env: {result.env_path}",
        f"Service unit: {result.service_path}",
    ]
    if result.display_name:
        lines.insert(2, f"Display name: {result.display_name}")
    if result.warnings:
        lines.append("Warnings:")
        lines.extend([f"- {w}" for w in result.warnings])
    return "\n".join(lines)


def render_install_error_json(err: NodeInstallError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": err.code, "message": str(err), "details": err.details},
    }


# ---- aiohttp route handler ---------------------------------------------------


async def aiohttp_node_install(request: Any):
    """aiohttp route handler for installing a node host.

    Expected JSON body keys align with :data:`NODE_INSTALL_REQUEST_SCHEMA`.
    """

    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    req = NodeInstallRequest(
        host=payload.get("host"),
        port=payload.get("port"),
        tls=bool(payload.get("tls", False)),
        tls_fingerprint=payload.get("tls_fingerprint"),
        node_id=payload.get("node_id"),
        display_name=payload.get("display_name"),
        runtime=payload.get("runtime", "python"),
        force=bool(payload.get("force", False)),
    )

    try:
        result = install_node_command(req)
        response_obj: dict[str, Any] = result.to_dict()
        status = 200
    except NodeInstallError as e:
        response_obj = render_install_error_json(e)
        status = 400
    except Exception as e:
        response_obj = {
            "ok": False,
            "error": {"code": "NODE_INSTALL_INTERNAL_ERROR", "message": str(e), "details": {}},
        }
        status = 500

    from aiohttp import web  # type: ignore

    return web.json_response(response_obj, status=status)


# Compatibility aliases for routers that look up a conventional name.
aiohttp_handler = aiohttp_node_install
AIOHTTP_HANDLER = aiohttp_node_install

# Compatibility aliases for direct core imports.
install = install_node_command
handle = aiohttp_node_install


__all__ = [
    "PROMPT_ID",
    "PARITY_COMMAND",
    "NODE_INSTALL_REQUEST_SCHEMA",
    "NODE_INSTALL_RESPONSE_SCHEMA",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "NodeInstallError",
    "NodeInstallInputError",
    "NodeInstallConfigError",
    "NodeInstallExternalError",
    "NodeInstallRequest",
    "NodeInstallResult",
    "install_node_command",
    "install",
    "render_install_result_human",
    "render_install_error_json",
    "aiohttp_node_install",
    "handle",
    "aiohttp_handler",
    "AIOHTTP_HANDLER",
]
