from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast
from collections.abc import Mapping

from aiohttp import web

# -----------------------------
# Contracts
# -----------------------------

class GatewayInstallCommandRequestDict(TypedDict, total=False):
    """JSON contract for /v1/gateway/install."""

    source: str
    name: str
    install_dir: str
    overwrite: bool
    dry_run: bool


class GatewayInstallCommandResultDict(TypedDict):
    name: str
    installed_path: str
    installed: bool
    dry_run: bool
    actions: list[str]
    message: str


@dataclass(frozen=True, slots=True)
class GatewayInstallCommandRequest:
    source: str
    name: str | None = None
    install_dir: str | None = None
    overwrite: bool = False
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class GatewayInstallCommandResult:
    name: str
    installed_path: str
    installed: bool
    dry_run: bool
    actions: list[str]
    message: str


# -----------------------------
# Errors
# -----------------------------

@dataclass(frozen=True, slots=True)
class GatewayInstallCommandError(Exception):
    """Deterministic error for gateway installation failures."""

    code: str
    message: str
    http_status: int = 400
    details: Mapping[str, Any] | None = None

    def to_error_payload(self) -> dict[str, Any]:
        err: dict[str, Any] = {
            "message": self.message,
            "type": "gateway_install_error",
            "code": self.code,
        }
        if self.details:
            err["details"] = dict(self.details)
        return {"error": err}


# -----------------------------
# Core logic
# -----------------------------

_ALLOWED_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SANITIZE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _sanitize_name(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise GatewayInstallCommandError(code="invalid_input", message="Plugin name is empty.", http_status=400)

    if _ALLOWED_NAME_RE.fullmatch(raw):
        return raw

    candidate = _SANITIZE_NAME_RE.sub("-", raw).strip("-._")[:128] or "plugin"
    if not _ALLOWED_NAME_RE.fullmatch(candidate):
        raise GatewayInstallCommandError(
            code="invalid_input",
            message="Plugin name is invalid after sanitization.",
            http_status=400,
            details={"name": raw, "candidate": candidate},
        )
    return candidate


def _resolve_install_dir(request: GatewayInstallCommandRequest, app: web.Application | None) -> Path:
    if request.install_dir:
        return Path(request.install_dir).expanduser()

    # 1) Best-effort app config (different bootstraps store config differently).
    if app is not None:
        for key_path in (
            ("gateway_install_dir",),
            ("gateway", "install_dir"),
            ("gateway", "plugins_dir"),
            ("gateway", "root_dir"),
            ("config", "gateway_install_dir"),
            ("config", "gateway", "install_dir"),
        ):
            cur: Any = app
            ok = True
            for key in key_path:
                if isinstance(cur, dict) and key in cur:
                    cur = cur[key]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str) and cur.strip():
                return Path(cur).expanduser()

    # 2) Environment variables
    for env_key in ("THOMAS_GATEWAY_INSTALL_DIR", "THOMAS_GATEWAY_PLUGINS_DIR", "THOMAS_GATEWAY_DIR"):
        env_val = os.environ.get(env_key)
        if env_val:
            return Path(env_val).expanduser()

    raise GatewayInstallCommandError(
        code="missing_config",
        message="Gateway install directory is not configured. Provide 'install_dir' or set THOMAS_GATEWAY_INSTALL_DIR.",
        http_status=422,
    )


def _derive_name_from_source(source_path: Path) -> str:
    return source_path.name if source_path.is_dir() else source_path.stem


def _is_unsafe_zip_member(name: str) -> bool:
    # Normalize separators for checks; zip uses forward slashes but can contain backslashes.
    n = name.replace("\\", "/")
    if not n or n.startswith("/") or n.startswith("\\"):
        return True
    # Drive letter (Windows)
    if re.match(r"^[A-Za-z]:", n):
        return True
    # Parent traversal
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return True
    return False


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> list[str]:
    actions: list[str] = []
    dest_resolved = dest_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for zi in zf.infolist():
            member = zi.filename
            if _is_unsafe_zip_member(member):
                raise GatewayInstallCommandError(
                    code="unsafe_archive",
                    message="Zip archive contains unsafe path entries.",
                    http_status=400,
                    details={"member": member},
                )

            member_norm = member.replace("\\", "/")
            target_path = (dest_dir / member_norm).resolve()
            # Final zip-slip guard
            if not str(target_path).startswith(str(dest_resolved) + os.sep) and target_path != dest_resolved:
                raise GatewayInstallCommandError(
                    code="unsafe_archive",
                    message="Zip archive attempted to write outside destination directory.",
                    http_status=400,
                    details={"member": member, "target": str(target_path)},
                )

            if member_norm.endswith("/"):
                actions.append(f"mkdir {target_path}")
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            actions.append(f"write {target_path}")
            with zf.open(zi, "r") as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

    return actions


def install_gateway_artifact(
    request: GatewayInstallCommandRequest,
    *,
    app: web.Application | None = None,
) -> GatewayInstallCommandResult:
    """Install a gateway artifact into install_dir/name.

    Thomas-native behavior:
    - Install a local directory OR extract a local .zip archive.
    - Uses safe zip extraction (zip-slip prevention).
    - Uses an atomic temp directory + rename for robust installs.
    """

    if not isinstance(request.source, str) or not request.source.strip():
        raise GatewayInstallCommandError(code="invalid_input", message="'source' must be a non-empty string.", http_status=400)

    source_path = Path(request.source).expanduser()
    if not source_path.exists():
        raise GatewayInstallCommandError(
            code="invalid_source",
            message="Source path does not exist.",
            http_status=404,
            details={"source": str(source_path)},
        )

    install_dir = _resolve_install_dir(request, app)

    name_raw = request.name or _derive_name_from_source(source_path)
    name = _sanitize_name(name_raw)
    dest_path = install_dir / name

    actions: list[str] = []
    if dest_path.exists() and not request.overwrite:
        raise GatewayInstallCommandError(
            code="already_installed",
            message="Destination already exists. Use overwrite=true to replace it.",
            http_status=409,
            details={"destination": str(dest_path)},
        )

    # Plan actions
    if dest_path.exists() and request.overwrite:
        actions.append(f"remove {dest_path}")

    tmp_suffix = f"{os.getpid()}-{os.urandom(4).hex()}"
    tmp_path = install_dir / f".{name}.installing-{tmp_suffix}"
    actions.append(f"stage {source_path} -> {tmp_path}")
    actions.append(f"activate {tmp_path} -> {dest_path}")

    if request.dry_run:
        return GatewayInstallCommandResult(
            name=name,
            installed_path=str(dest_path),
            installed=False,
            dry_run=True,
            actions=actions,
            message="Dry-run: no files were modified.",
        )

    # Ensure install_dir exists
    try:
        install_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GatewayInstallCommandError(
            code="external_failure",
            message="Failed to create install_dir.",
            http_status=502,
            details={"install_dir": str(install_dir), "error": type(exc).__name__},
        ) from exc

    # Remove destination if overwriting
    if dest_path.exists():
        try:
            if dest_path.is_dir():
                shutil.rmtree(dest_path)
            else:
                dest_path.unlink()
        except OSError as exc:
            raise GatewayInstallCommandError(
                code="external_failure",
                message="Failed to remove existing destination.",
                http_status=502,
                details={"destination": str(dest_path), "error": type(exc).__name__},
            ) from exc

    # Stage to tmp
    try:
        if source_path.is_dir():
            shutil.copytree(source_path, tmp_path, dirs_exist_ok=False)
        else:
            if source_path.suffix.lower() != ".zip":
                raise GatewayInstallCommandError(
                    code="invalid_source",
                    message="Source must be a directory or a .zip archive.",
                    http_status=400,
                    details={"source": str(source_path)},
                )
            tmp_path.mkdir(parents=True, exist_ok=False)
            _safe_extract_zip(source_path, tmp_path)
    except GatewayInstallCommandError:
        if tmp_path.exists():
            try:
                shutil.rmtree(tmp_path)
            except OSError:
                pass
        raise
    except Exception as exc:  # noqa: BLE001
        if tmp_path.exists():
            try:
                shutil.rmtree(tmp_path)
            except OSError:
                pass
        raise GatewayInstallCommandError(
            code="external_failure",
            message="Failed to stage gateway artifact.",
            http_status=502,
            details={"source": str(source_path), "staging": str(tmp_path), "error": type(exc).__name__},
        ) from exc

    # Activate (atomic rename within same directory)
    try:
        tmp_path.replace(dest_path)
    except OSError as exc:
        if tmp_path.exists():
            try:
                shutil.rmtree(tmp_path)
            except OSError:
                pass
        raise GatewayInstallCommandError(
            code="external_failure",
            message="Failed to activate staged install.",
            http_status=502,
            details={"staging": str(tmp_path), "destination": str(dest_path), "error": type(exc).__name__},
        ) from exc

    return GatewayInstallCommandResult(
        name=name,
        installed_path=str(dest_path),
        installed=True,
        dry_run=False,
        actions=actions,
        message="Installed successfully.",
    )


def parse_gateway_install_request(data: Mapping[str, Any]) -> GatewayInstallCommandRequest:
    if not isinstance(data, Mapping):
        raise GatewayInstallCommandError(code="invalid_input", message="JSON body must be an object.", http_status=400)

    source = data.get("source")
    name = data.get("name")
    install_dir = data.get("install_dir")
    overwrite = data.get("overwrite", False)
    dry_run = data.get("dry_run", False)

    if source is None or not isinstance(source, str):
        raise GatewayInstallCommandError(code="invalid_input", message="'source' is required and must be a string.", http_status=400)
    if name is not None and not isinstance(name, str):
        raise GatewayInstallCommandError(code="invalid_input", message="'name' must be a string when provided.", http_status=400)
    if install_dir is not None and not isinstance(install_dir, str):
        raise GatewayInstallCommandError(code="invalid_input", message="'install_dir' must be a string when provided.", http_status=400)
    if not isinstance(overwrite, bool):
        raise GatewayInstallCommandError(code="invalid_input", message="'overwrite' must be a boolean.", http_status=400)
    if not isinstance(dry_run, bool):
        raise GatewayInstallCommandError(code="invalid_input", message="'dry_run' must be a boolean.", http_status=400)

    return GatewayInstallCommandRequest(
        source=source,
        name=name,
        install_dir=install_dir,
        overwrite=overwrite,
        dry_run=dry_run,
    )


def gateway_install_schema() -> dict[str, Any]:
    """Compact JSON schema for automation clients."""

    return {
        "name": "gateway_install",
        "request": {
            "type": "object",
            "required": ["source"],
            "properties": {
                "source": {"type": "string", "description": "Path to a plugin directory or .zip archive"},
                "name": {"type": "string", "description": "Optional install name; defaults to source basename"},
                "install_dir": {"type": "string", "description": "Destination directory for gateway artifacts"},
                "overwrite": {"type": "boolean", "default": False},
                "dry_run": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "response": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "result": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "installed_path": {"type": "string"},
                        "installed": {"type": "boolean"},
                        "dry_run": {"type": "boolean"},
                        "actions": {"type": "array", "items": {"type": "string"}},
                        "message": {"type": "string"},
                    },
                    "required": ["name", "installed_path", "installed", "dry_run", "actions", "message"],
                },
                "error": {"type": "object"},
            },
            "required": ["ok"],
        },
    }


# -----------------------------
# Aiohttp routes
# -----------------------------

routes = web.RouteTableDef()


@routes.get("/v1/gateway/install/schema")
async def get_gateway_install_schema(request: web.Request) -> web.Response:
    return web.json_response(gateway_install_schema())


@routes.post("/v1/gateway/install")
async def post_gateway_install(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        err = GatewayInstallCommandError(
            code="invalid_json",
            message="Request body must be valid JSON.",
            http_status=400,
            details={"error": type(exc).__name__},
        )
        return web.json_response(err.to_error_payload(), status=err.http_status)

    try:
        req_obj = parse_gateway_install_request(cast(Mapping[str, Any], payload))
        result = install_gateway_artifact(req_obj, app=request.app)
    except GatewayInstallCommandError as exc:
        return web.json_response(exc.to_error_payload(), status=exc.http_status)

    return web.json_response({"ok": True, "result": dataclasses.asdict(result)})


def setup_routes(app: web.Application) -> None:
    """Optional explicit registration hook for app bootstraps that don't scan RouteTableDef objects."""

    app.add_routes(routes)
