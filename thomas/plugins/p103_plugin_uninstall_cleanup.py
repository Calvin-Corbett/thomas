"""Plugin uninstall cleanup (P103).

Thomas can install plugins into a state directory under an ``extensions/`` root.
Uninstalling a plugin from configuration does not always remove on-disk artifacts.

This module provides a Thomas-native, idempotent cleanup operation that removes
the on-disk install directory for a plugin:

    <extensions_dir>/<plugin_id>

Key properties:

* Safe: guards against path traversal / escaping the extensions root.
* Idempotent: missing targets return status ``not_found``.
* Deterministic errors: callers can rely on stable ``code`` values.
* Machine-friendly: JSON-serializable input/output contracts + JSON Schemas.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypedDict

# -------------------------
# Errors
# -------------------------


@dataclass(frozen=True)
class PluginUninstallCleanupError(Exception):
    """Deterministic, machine-friendly error type."""

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover (trivial)
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


# -------------------------
# Contracts
# -------------------------


CleanupStatus = Literal["removed", "not_found", "dry_run"]
ManagedCleanupStatus = Literal["removed", "not_found", "state_cleaned"]


class PluginUninstallCleanupInput(TypedDict, total=False):
    """JSON-like input contract."""

    plugin_id: str
    dry_run: bool
    config_path: str
    state_dir: str
    extensions_dir: str
    prune_empty_parents: bool


class PluginUninstallCleanupOutput(TypedDict):
    """JSON-like output contract."""

    plugin_id: str
    status: CleanupStatus
    config_path: str
    state_dir: str
    extensions_dir: str
    removed: list[str]
    pruned_empty_dirs: list[str]


@dataclass(frozen=True)
class PluginUninstallCleanupRequest:
    """Python-native request."""

    plugin_id: str
    dry_run: bool = False
    config_path: Path | None = None
    state_dir: Path | None = None
    extensions_dir: Path | None = None
    prune_empty_parents: bool = True


@dataclass(frozen=True)
class PluginUninstallCleanupResult:
    """Python-native result."""

    plugin_id: str
    status: CleanupStatus
    config_path: Path
    state_dir: Path
    extensions_dir: Path
    removed: tuple[Path, ...] = ()
    pruned_empty_dirs: tuple[Path, ...] = ()

    def to_dict(self) -> PluginUninstallCleanupOutput:
        return {
            "plugin_id": self.plugin_id,
            "status": self.status,
            "config_path": str(self.config_path),
            "state_dir": str(self.state_dir),
            "extensions_dir": str(self.extensions_dir),
            "removed": [str(p) for p in self.removed],
            "pruned_empty_dirs": [str(p) for p in self.pruned_empty_dirs],
        }


@dataclass(frozen=True)
class ManagedPluginUninstallRequest:
    """Remove a plugin installed by p102 and its runtime manifest entry."""

    plugin_id: str
    install_root: Path


@dataclass(frozen=True)
class ManagedPluginUninstallResult:
    plugin_id: str
    status: ManagedCleanupStatus
    install_root: Path
    manifest_path: Path
    removed_path: Path | None = None
    manifest_updated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "status": self.status,
            "install_root": str(self.install_root),
            "manifest_path": str(self.manifest_path),
            "removed_path": str(self.removed_path) if self.removed_path else None,
            "manifest_updated": self.manifest_updated,
        }


# -------------------------
# JSON Schemas
# -------------------------


INPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["plugin_id"],
    "properties": {
        "plugin_id": {"type": "string", "minLength": 1},
        "dry_run": {"type": "boolean", "default": False},
        "config_path": {"type": "string"},
        "state_dir": {"type": "string"},
        "extensions_dir": {"type": "string"},
        "prune_empty_parents": {"type": "boolean", "default": True},
    },
}

OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "plugin_id",
        "status",
        "config_path",
        "state_dir",
        "extensions_dir",
        "removed",
        "pruned_empty_dirs",
    ],
    "properties": {
        "plugin_id": {"type": "string"},
        "status": {"type": "string"},
        "config_path": {"type": "string"},
        "state_dir": {"type": "string"},
        "extensions_dir": {"type": "string"},
        "removed": {"type": "array", "items": {"type": "string"}},
        "pruned_empty_dirs": {"type": "array", "items": {"type": "string"}},
    },
}


# -------------------------
# Core implementation
# -------------------------


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _normalize_plugin_id(plugin_id: str) -> str:
    if not isinstance(plugin_id, str):
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="plugin_id must be a string",
            details={"field": "plugin_id"},
        )

    candidate = plugin_id.strip()
    if not candidate:
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="plugin_id is required",
            details={"field": "plugin_id"},
        )

    # Disallow Windows separators and drive hints explicitly.
    if "\\" in candidate or ":" in candidate:
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="plugin_id contains invalid characters",
            details={"field": "plugin_id"},
        )

    if candidate.startswith("/") or candidate.endswith("/"):
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="plugin_id must be a relative identifier",
            details={"field": "plugin_id"},
        )

    if not _ID_RE.match(candidate):
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="plugin_id contains invalid characters",
            details={"field": "plugin_id"},
        )

    parts = PurePosixPath(candidate).parts
    if any(p in (".", "..") for p in parts):
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="plugin_id must not contain path traversal segments",
            details={"field": "plugin_id"},
        )

    # Canonical form: posix-joined parts.
    return "/".join(parts)


def _expand_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser()


def _resolve_config_path(req: PluginUninstallCleanupRequest) -> Path:
    if req.config_path is not None:
        return _expand_path(req.config_path)  # type: ignore[return-value]

    env = os.environ.get("THOMAS_CONFIG_PATH")
    if env:
        return Path(env).expanduser()

    # Default: <state_dir>/thomas.json
    state_dir = _resolve_state_dir(req, config_path=None)
    return state_dir / "thomas.json"


def _resolve_state_dir(req: PluginUninstallCleanupRequest, config_path: Path | None) -> Path:
    if req.state_dir is not None:
        return _expand_path(req.state_dir)  # type: ignore[return-value]

    if config_path is not None:
        # Explicit config path should anchor state resolution deterministically.
        return config_path.expanduser().parent

    env = os.environ.get("THOMAS_STATE_DIR")
    if env:
        return Path(env).expanduser()

    return Path("~/.thomas").expanduser()


def _resolve_extensions_dir(req: PluginUninstallCleanupRequest, state_dir: Path) -> Path:
    if req.extensions_dir is not None:
        return _expand_path(req.extensions_dir)  # type: ignore[return-value]
    return state_dir / "extensions"


def _ensure_inside_root(root: Path, target: Path) -> None:
    """Refuse to operate outside the extensions root."""

    root_abs = root.expanduser().resolve()
    target_abs = target.expanduser().resolve()

    common = Path(os.path.commonpath([str(root_abs), str(target_abs)]))
    if common != root_abs:
        raise PluginUninstallCleanupError(
            code="invalid_target",
            message="refusing to operate outside extensions directory",
            details={"root": str(root_abs), "target": str(target_abs)},
        )


def _remove_path(path: Path) -> None:
    """Remove a path (dir/file/symlink) with deterministic error mapping."""

    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except Exception as exc:  # noqa: BLE001
        raise PluginUninstallCleanupError(
            code="filesystem_error",
            message="failed to remove plugin artifacts",
            details={"path": str(path), "exc": exc.__class__.__name__},
        ) from exc


def _read_managed_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {"version": 1, "plugins": {}}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PluginUninstallCleanupError(
            code="bad_manifest",
            message="installed plugin manifest could not be read",
            details={"manifest_path": str(manifest_path), "reason": type(exc).__name__},
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("plugins"), dict):
        raise PluginUninstallCleanupError(
            code="bad_manifest",
            message="installed plugin manifest has an invalid structure",
            details={"manifest_path": str(manifest_path)},
        )
    return payload


def _write_managed_manifest_atomic(manifest_path: Path, payload: Mapping[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise PluginUninstallCleanupError(
            code="filesystem_error",
            message="failed to update installed plugin manifest",
            details={"manifest_path": str(manifest_path), "reason": type(exc).__name__},
        ) from exc


def uninstall_plugin_from_install_root(req: ManagedPluginUninstallRequest) -> ManagedPluginUninstallResult:
    """Atomically remove p102 payload and state, rolling the payload back on state-write failure."""

    plugin_id = _normalize_plugin_id(req.plugin_id)
    if "/" in plugin_id:
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="managed plugin_id must be a single path segment",
            details={"field": "plugin_id"},
        )
    install_root = Path(req.install_root).expanduser().resolve()
    manifest_path = install_root / "installed_plugins.json"
    payload = _read_managed_manifest(manifest_path)
    plugins = dict(payload.get("plugins") or {})
    record = plugins.get(plugin_id)
    plugin_dir = (install_root / plugin_id).resolve()
    _ensure_inside_root(install_root, plugin_dir)

    if isinstance(record, Mapping):
        recorded_path = str(record.get("installed_path") or "").strip()
        if recorded_path:
            try:
                recorded_resolved = Path(recorded_path).expanduser().resolve()
            except (OSError, RuntimeError, ValueError) as exc:
                raise PluginUninstallCleanupError(
                    code="bad_manifest",
                    message="installed plugin record contains an invalid path",
                    details={"plugin_id": plugin_id, "reason": type(exc).__name__},
                ) from exc
            if recorded_resolved != plugin_dir:
                raise PluginUninstallCleanupError(
                    code="bad_manifest",
                    message="installed plugin record points outside its managed slot",
                    details={"plugin_id": plugin_id, "installed_path": recorded_path},
                )

    payload_exists = plugin_dir.exists() or plugin_dir.is_symlink()
    record_exists = plugin_id in plugins
    if not payload_exists and not record_exists:
        return ManagedPluginUninstallResult(
            plugin_id=plugin_id,
            status="not_found",
            install_root=install_root,
            manifest_path=manifest_path,
        )

    tomb_parent: Path | None = None
    tombstone: Path | None = None
    if payload_exists:
        install_root.mkdir(parents=True, exist_ok=True)
        tomb_parent = Path(tempfile.mkdtemp(prefix=f".uninstalling-{plugin_id}-", dir=str(install_root)))
        tombstone = tomb_parent / plugin_id
        try:
            os.replace(plugin_dir, tombstone)
        except OSError as exc:
            shutil.rmtree(tomb_parent, ignore_errors=True)
            raise PluginUninstallCleanupError(
                code="filesystem_error",
                message="failed to stage plugin payload for removal",
                details={"path": str(plugin_dir), "reason": type(exc).__name__},
            ) from exc

    plugins.pop(plugin_id, None)
    next_payload = dict(payload)
    next_payload["version"] = int(payload.get("version") or 1)
    next_payload["plugins"] = dict(sorted(plugins.items()))
    try:
        _write_managed_manifest_atomic(manifest_path, next_payload)
    except PluginUninstallCleanupError:
        if tombstone is not None and tombstone.exists() and not plugin_dir.exists():
            try:
                os.replace(tombstone, plugin_dir)
            except OSError:
                pass
        if tomb_parent is not None:
            shutil.rmtree(tomb_parent, ignore_errors=True)
        raise

    if tomb_parent is not None:
        shutil.rmtree(tomb_parent, ignore_errors=True)
    return ManagedPluginUninstallResult(
        plugin_id=plugin_id,
        status="removed" if payload_exists else "state_cleaned",
        install_root=install_root,
        manifest_path=manifest_path,
        removed_path=plugin_dir if payload_exists else None,
        manifest_updated=record_exists,
    )


def _prune_empty_parents(start: Path, stop_at: Path) -> tuple[Path, ...]:
    """Prune empty directories up to (but not including) stop_at."""

    pruned: list[Path] = []
    cur = start
    while cur != stop_at and cur.exists():
        try:
            if any(cur.iterdir()):
                break
            cur.rmdir()
            pruned.append(cur)
            cur = cur.parent
        except OSError:
            break
    return tuple(pruned)


def run_plugin_uninstall_cleanup(req: PluginUninstallCleanupRequest) -> PluginUninstallCleanupResult:
    """Remove on-disk plugin install artifacts for an uninstalled plugin."""

    plugin_id = _normalize_plugin_id(req.plugin_id)

    config_path = _resolve_config_path(req).expanduser()
    if not config_path.exists():
        raise PluginUninstallCleanupError(
            code="missing_config",
            message="Thomas config file not found",
            details={"config_path": str(config_path)},
        )

    state_dir = _resolve_state_dir(req, config_path=config_path)
    extensions_dir = _resolve_extensions_dir(req, state_dir)

    rel_parts = list(PurePosixPath(plugin_id).parts)
    plugin_dir = extensions_dir.joinpath(*rel_parts)

    _ensure_inside_root(extensions_dir, plugin_dir)

    if not plugin_dir.exists():
        return PluginUninstallCleanupResult(
            plugin_id=plugin_id,
            status="not_found",
            config_path=config_path,
            state_dir=state_dir,
            extensions_dir=extensions_dir,
            removed=(),
            pruned_empty_dirs=(),
        )

    if req.dry_run:
        return PluginUninstallCleanupResult(
            plugin_id=plugin_id,
            status="dry_run",
            config_path=config_path,
            state_dir=state_dir,
            extensions_dir=extensions_dir,
            removed=(plugin_dir,),
            pruned_empty_dirs=(),
        )

    _remove_path(plugin_dir)

    pruned: tuple[Path, ...] = ()
    if req.prune_empty_parents:
        pruned = _prune_empty_parents(plugin_dir.parent, extensions_dir)

    return PluginUninstallCleanupResult(
        plugin_id=plugin_id,
        status="removed",
        config_path=config_path,
        state_dir=state_dir,
        extensions_dir=extensions_dir,
        removed=(plugin_dir,),
        pruned_empty_dirs=pruned,
    )


# -------------------------
# Tool / registry adapter
# -------------------------


def parse_tool_input(payload: Mapping[str, Any]) -> PluginUninstallCleanupRequest:
    if not isinstance(payload, Mapping):
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="payload must be an object",
            details={"field": "payload"},
        )

    def get_bool(key: str, default: bool) -> bool:
        if key not in payload:
            return default
        val = payload[key]
        if isinstance(val, bool):
            return val
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message=f"{key} must be a boolean",
            details={"field": key},
        )

    def get_path(key: str) -> Path | None:
        if key not in payload:
            return None
        val = payload[key]
        if val is None:
            return None
        if isinstance(val, str):
            return Path(val)
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message=f"{key} must be a string",
            details={"field": key},
        )

    pid = payload.get("plugin_id")
    if not isinstance(pid, str) or not pid.strip():
        raise PluginUninstallCleanupError(
            code="invalid_input",
            message="plugin_id is required",
            details={"field": "plugin_id"},
        )

    return PluginUninstallCleanupRequest(
        plugin_id=pid,
        dry_run=get_bool("dry_run", False),
        config_path=get_path("config_path"),
        state_dir=get_path("state_dir"),
        extensions_dir=get_path("extensions_dir"),
        prune_empty_parents=get_bool("prune_empty_parents", True),
    )


def tool_entrypoint(payload: Mapping[str, Any]) -> PluginUninstallCleanupOutput:
    req = parse_tool_input(payload)
    res = run_plugin_uninstall_cleanup(req)
    return res.to_dict()


def register_with_registry(registry: Any) -> None:
    """Best-effort registration with the Thomas tool registry."""

    tool_name = "plugin_uninstall_cleanup"
    spec = {
        "name": tool_name,
        "description": "Remove on-disk artifacts for an uninstalled plugin.",
        "input_schema": INPUT_JSON_SCHEMA,
        "output_schema": OUTPUT_JSON_SCHEMA,
    }

    # Common patterns in registries: register_tool/add_tool/register.
    if hasattr(registry, "register_tool"):
        try:
            registry.register_tool(tool_name, tool_entrypoint, spec)
            return
        except TypeError:
            try:
                registry.register_tool(tool_entrypoint, spec)
                return
            except Exception:
                pass

    if hasattr(registry, "add_tool"):
        try:
            registry.add_tool(tool_name, tool_entrypoint, spec)
            return
        except TypeError:
            try:
                registry.add_tool(tool_entrypoint, spec)
                return
            except Exception:
                pass

    if hasattr(registry, "register"):
        try:
            registry.register(tool_name, tool_entrypoint, spec)
            return
        except Exception:
            pass

    raise PluginUninstallCleanupError(
        code="registry_error",
        message="unable to register tool with registry",
        details={"registry_type": type(registry).__name__},
    )


# Compatibility aliases for plugin loaders that look for these.
TOOL_NAME = "plugin_uninstall_cleanup"
register = register_with_registry


__all__ = [
    "PluginUninstallCleanupError",
    "PluginUninstallCleanupRequest",
    "PluginUninstallCleanupResult",
    "PluginUninstallCleanupInput",
    "PluginUninstallCleanupOutput",
    "ManagedPluginUninstallRequest",
    "ManagedPluginUninstallResult",
    "INPUT_JSON_SCHEMA",
    "OUTPUT_JSON_SCHEMA",
    "run_plugin_uninstall_cleanup",
    "uninstall_plugin_from_install_root",
    "parse_tool_input",
    "tool_entrypoint",
    "register_with_registry",
    "register",
    "TOOL_NAME",
]
