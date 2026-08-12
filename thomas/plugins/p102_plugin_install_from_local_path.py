"""
Plugin: install a plugin from a local filesystem path.

This module implements Thomas-native behavior for installing a plugin directory
into a managed "installed plugins" location.

Design goals:
- Deterministic validation and error codes
- Clear input/output contracts (dataclasses)
- Machine-readable execution for automation (run + JSON schema helpers)
- Minimal side effects (no import-time registration)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


TOOL_NAME = "plugins.install_from_local_path"
TOOL_DESCRIPTION = "Install a Thomas plugin from a local directory path."


class PluginInstallFromLocalPathError(RuntimeError):
    """Deterministic error for local-path plugin installation."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        self.code = str(code)
        self.details: dict[str, Any] = dict(details or {})
        super().__init__(str(message))

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": str(self), "details": self.details}}


@dataclass(frozen=True)
class PluginInstallFromLocalPathRequest:
    """Input contract for local-path plugin installation."""

    source_path: Path
    # Optional explicit name override. If omitted, name is derived from on-disk metadata.
    plugin_name: str | None = None
    # Where to install plugins. If omitted, uses THOMAS_PLUGINS_DIR, or THOMAS_HOME/plugins, or ~/.thomas/plugins.
    install_root: Path | None = None
    # Overwrite if the plugin already exists at destination.
    overwrite: bool = False


@dataclass(frozen=True)
class PluginInstallFromLocalPathResult:
    """Output contract for local-path plugin installation."""

    plugin_name: str
    source_path: Path
    installed_path: Path
    manifest_path: Path
    overwritten: bool = False


_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MAX_PLUGIN_FILES = 2000
_MAX_PLUGIN_BYTES = 100 * 1024 * 1024


def _default_thomas_home() -> Path:
    env = os.getenv("THOMAS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".thomas").resolve()


def _default_install_root() -> Path:
    env = os.getenv("THOMAS_PLUGINS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _default_thomas_home() / "plugins"


def _ensure_package_dir(path: Path) -> None:
    """Ensure a directory exists and is importable as a Python package."""
    path.mkdir(parents=True, exist_ok=True)
    init_py = path / "__init__.py"
    if not init_py.exists():
        init_py.write_text('"""Thomas-managed package directory."""\n', encoding="utf-8")


def _validate_plugin_name(name: str) -> str:
    n = name.strip()
    if not n:
        raise PluginInstallFromLocalPathError("invalid_plugin_name", "Plugin name must be non-empty.")
    if not _PLUGIN_NAME_RE.match(n):
        raise PluginInstallFromLocalPathError(
            "invalid_plugin_name",
            "Plugin name contains invalid characters.",
            details={"plugin_name": name},
        )
    return n


def _derive_name_from_pyproject(pyproject_path: Path) -> str | None:
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as e:
        raise PluginInstallFromLocalPathError(
            "bad_plugin_config",
            "Failed to parse pyproject.toml.",
            details={"path": str(pyproject_path), "reason": type(e).__name__},
        ) from e

    # PEP 621
    project = data.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

    # Poetry legacy
    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            name = poetry.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()

    return None


def _derive_name_from_setup_cfg(setup_cfg_path: Path) -> str | None:
    import configparser

    cfg = configparser.ConfigParser()
    try:
        cfg.read(setup_cfg_path, encoding="utf-8")
    except (OSError, ValueError) as e:
        raise PluginInstallFromLocalPathError(
            "bad_plugin_config",
            "Failed to parse setup.cfg.",
            details={"path": str(setup_cfg_path), "reason": type(e).__name__},
        ) from e

    if cfg.has_option("metadata", "name"):
        name = cfg.get("metadata", "name").strip()
        if name:
            return name
    return None


def _derive_name_from_json_manifest(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        raise PluginInstallFromLocalPathError(
            "bad_plugin_config",
            "Failed to parse plugin JSON manifest.",
            details={"path": str(path), "reason": type(e).__name__},
        ) from e

    if isinstance(data, dict):
        for key in ("name", "plugin_name"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _derive_name_from_toml_manifest(path: Path) -> str | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise PluginInstallFromLocalPathError(
            "bad_plugin_config",
            "Failed to parse plugin TOML manifest.",
            details={"path": str(path), "reason": type(e).__name__},
        ) from e

    if isinstance(data, dict):
        # Either top-level "name" or [plugin].name.
        v = data.get("name")
        if isinstance(v, str) and v.strip():
            return v.strip()
        plugin_tbl = data.get("plugin")
        if isinstance(plugin_tbl, dict):
            v2 = plugin_tbl.get("name")
            if isinstance(v2, str) and v2.strip():
                return v2.strip()
    return None


def _derive_plugin_name(source_path: Path) -> str:
    # 1) pyproject.toml
    pyproject = source_path / "pyproject.toml"
    if pyproject.exists():
        name = _derive_name_from_pyproject(pyproject)
        if name:
            return _validate_plugin_name(name)

    # 2) setup.cfg
    setup_cfg = source_path / "setup.cfg"
    if setup_cfg.exists():
        name = _derive_name_from_setup_cfg(setup_cfg)
        if name:
            return _validate_plugin_name(name)

    # 3) explicit plugin manifests (JSON/TOML)
    for candidate in ("thomas_plugin.json", "plugin.json"):
        p = source_path / candidate
        if p.exists():
            name = _derive_name_from_json_manifest(p)
            if name:
                return _validate_plugin_name(name)

    for candidate in ("thomas_plugin.toml", "plugin.toml"):
        p = source_path / candidate
        if p.exists():
            name = _derive_name_from_toml_manifest(p)
            if name:
                return _validate_plugin_name(name)

    # 4) setup.py (do NOT execute; directory name fallback)
    setup_py = source_path / "setup.py"
    if setup_py.exists():
        return _validate_plugin_name(source_path.name)

    # 5) python package directory (directory name)
    if (source_path / "__init__.py").exists():
        return _validate_plugin_name(source_path.name)

    raise PluginInstallFromLocalPathError(
        "missing_plugin_config",
        "Plugin directory is missing recognizable metadata.",
        details={"path": str(source_path)},
    )


def _validate_source_tree(source_path: Path) -> None:
    """Reject link escapes and unexpectedly large local plugin trees before copying."""

    file_count = 0
    total_bytes = 0
    try:
        for entry in source_path.rglob("*"):
            if entry.is_symlink():
                raise PluginInstallFromLocalPathError(
                    "unsafe_source_tree",
                    "Plugin source must not contain symbolic links.",
                    details={"path": str(entry)},
                )
            if not entry.is_file():
                continue
            file_count += 1
            total_bytes += entry.stat().st_size
            if file_count > _MAX_PLUGIN_FILES or total_bytes > _MAX_PLUGIN_BYTES:
                raise PluginInstallFromLocalPathError(
                    "plugin_too_large",
                    "Plugin source exceeds the safe local install limit.",
                    details={"file_count": file_count, "total_bytes": total_bytes},
                )
    except PluginInstallFromLocalPathError:
        raise
    except (OSError, RuntimeError) as exc:
        raise PluginInstallFromLocalPathError(
            "unsafe_source_tree",
            "Plugin source tree could not be validated safely.",
            details={"path": str(source_path), "reason": type(exc).__name__},
        ) from exc


def _validate_rich_manifest(source_path: Path, plugin_name: str) -> None:
    """Validate the v1 rich manifest and every declared knowledge attachment."""

    manifest_path = source_path / "manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PluginInstallFromLocalPathError(
            "bad_plugin_config",
            "Failed to parse rich plugin manifest.",
            details={"path": str(manifest_path), "reason": type(exc).__name__},
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "v1":
        return
    try:
        from thomas.plugins.p098_plugin_manifest_schema import PluginManifestSchemaError, validate_plugin_manifest

        validate_plugin_manifest(manifest)
    except PluginManifestSchemaError as exc:
        raise PluginInstallFromLocalPathError(
            "invalid_manifest",
            "Plugin manifest failed validation.",
            details={"path": str(manifest_path), "errors": list(exc.details.get("errors") or [])},
        ) from exc

    plugin = manifest.get("plugin") if isinstance(manifest.get("plugin"), dict) else {}
    manifest_id = str(plugin.get("id") or "").strip()
    if manifest_id and manifest_id != plugin_name:
        raise PluginInstallFromLocalPathError(
            "manifest_name_mismatch",
            "Plugin manifest id does not match the install name.",
            details={"plugin_name": plugin_name, "manifest_id": manifest_id},
        )

    assistant = manifest.get("assistant") if isinstance(manifest.get("assistant"), dict) else {}
    knowledge_files = assistant.get("knowledge_files") if isinstance(assistant.get("knowledge_files"), list) else []
    source_root = source_path.resolve()
    for raw_path in knowledge_files:
        relative = PurePosixPath(str(raw_path))
        candidate = source_path.joinpath(*relative.parts)
        try:
            if candidate.is_symlink():
                raise ValueError("symlink")
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(source_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PluginInstallFromLocalPathError(
                "unsafe_knowledge_path",
                "Plugin knowledge file is missing or escapes the plugin package.",
                details={"path": str(raw_path), "reason": type(exc).__name__},
            ) from exc
        if not resolved.is_file():
            raise PluginInstallFromLocalPathError(
                "unsafe_knowledge_path",
                "Plugin knowledge attachment must be a regular file.",
                details={"path": str(raw_path)},
            )


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {"version": 1, "plugins": {}}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        raise PluginInstallFromLocalPathError(
            "bad_manifest",
            "Failed to read installed plugins manifest.",
            details={"path": str(manifest_path), "reason": type(e).__name__},
        ) from e
    if not isinstance(data, dict):
        raise PluginInstallFromLocalPathError(
            "bad_manifest",
            "Installed plugins manifest must be a JSON object.",
            details={"path": str(manifest_path)},
        )
    return data


def _write_manifest_atomic(manifest_path: Path, manifest: Mapping[str, Any]) -> None:
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp_path, manifest_path)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:  # REVIEWED: broad catch — cleanup only, no error handling
            pass
        raise PluginInstallFromLocalPathError(
            "write_failed",
            "Failed to write installed plugins manifest.",
            details={"path": str(manifest_path), "reason": type(e).__name__},
        ) from e


def install_plugin_from_local_path(req: PluginInstallFromLocalPathRequest) -> PluginInstallFromLocalPathResult:
    """Install a plugin from a local directory path."""

    source_path = Path(req.source_path).expanduser()
    if not source_path.exists():
        raise PluginInstallFromLocalPathError(
            "invalid_path",
            "Source path does not exist.",
            details={"path": str(source_path)},
        )
    if not source_path.is_dir():
        raise PluginInstallFromLocalPathError(
            "not_a_directory",
            "Source path must be a directory.",
            details={"path": str(source_path)},
        )

    plugin_name = _validate_plugin_name(req.plugin_name) if req.plugin_name else _derive_plugin_name(source_path)
    _validate_source_tree(source_path)
    _validate_rich_manifest(source_path, plugin_name)
    install_root = Path(req.install_root).expanduser().resolve() if req.install_root else _default_install_root()

    _ensure_package_dir(install_root)

    installed_path = install_root / plugin_name
    already_exists = installed_path.exists()

    if already_exists and not req.overwrite:
        raise PluginInstallFromLocalPathError(
            "already_installed",
            "Plugin is already installed.",
            details={"plugin_name": plugin_name, "installed_path": str(installed_path)},
        )

    # Stage into a temp directory inside install_root, then rename into place.
    temp_parent = Path(tempfile.mkdtemp(prefix=f".installing-{plugin_name}-", dir=str(install_root)))
    staged_path = temp_parent / plugin_name
    backup_path = install_root / f".backup-{plugin_name}"

    try:
        shutil.copytree(source_path, staged_path)
        _ensure_package_dir(staged_path)

        # If overwriting, move old installation aside first so we can roll back cleanly.
        if already_exists:
            try:
                if backup_path.exists():
                    shutil.rmtree(backup_path)
                os.replace(installed_path, backup_path)
            except (OSError, shutil.Error) as e:
                raise PluginInstallFromLocalPathError(
                    "remove_failed",
                    "Failed to move existing plugin installation out of the way.",
                    details={
                        "plugin_name": plugin_name,
                        "installed_path": str(installed_path),
                        "backup_path": str(backup_path),
                        "reason": type(e).__name__,
                    },
                ) from e

        try:
            os.replace(staged_path, installed_path)
        except (OSError, shutil.Error):  # REVIEWED: broad catch — fallback to shutil.move
            try:
                shutil.move(str(staged_path), str(installed_path))
            except (OSError, shutil.Error) as e:
                # Attempt rollback if we had a backup.
                if backup_path.exists() and not installed_path.exists():
                    try:
                        os.replace(backup_path, installed_path)
                    except (OSError, shutil.Error):  # REVIEWED: broad catch — cleanup/rollback
                        pass
                raise PluginInstallFromLocalPathError(
                    "move_failed",
                    "Failed to finalize plugin installation.",
                    details={
                        "plugin_name": plugin_name,
                        "staged_path": str(staged_path),
                        "installed_path": str(installed_path),
                        "reason": type(e).__name__,
                    },
                ) from e
    except PluginInstallFromLocalPathError:
        raise
    except (OSError, shutil.Error) as e:
        raise PluginInstallFromLocalPathError(
            "copy_failed",
            "Failed to copy plugin into install directory.",
            details={
                "source_path": str(source_path),
                "staged_path": str(staged_path),
                "reason": type(e).__name__,
            },
        ) from e
    finally:
        try:
            if temp_parent.exists():
                shutil.rmtree(temp_parent, ignore_errors=True)
        except (OSError, shutil.Error):  # REVIEWED: broad catch — cleanup only
            pass

    # Update manifest (rollback on failure).
    manifest_path = install_root / "installed_plugins.json"
    manifest = _load_manifest(manifest_path)
    plugins: MutableMapping[str, Any] = manifest.get("plugins") if isinstance(manifest.get("plugins"), dict) else {}
    plugins[plugin_name] = {
        "source_path": str(source_path.resolve()),
        "installed_path": str(installed_path.resolve()),
    }
    manifest = dict(manifest)
    manifest["version"] = int(manifest.get("version") or 1)
    manifest["plugins"] = dict(sorted(plugins.items(), key=lambda kv: kv[0]))

    try:
        _write_manifest_atomic(manifest_path, manifest)
    except PluginInstallFromLocalPathError:
        # Roll back: remove new install and restore backup if present.
        try:
            if installed_path.exists():
                shutil.rmtree(installed_path, ignore_errors=True)
        finally:
            if backup_path.exists():
                try:
                    os.replace(backup_path, installed_path)
                except (OSError, shutil.Error):  # REVIEWED: broad catch — cleanup/rollback
                    pass
        raise
    finally:
        # If manifest succeeded, remove backup.
        if backup_path.exists():
            try:
                shutil.rmtree(backup_path, ignore_errors=True)
            except (OSError, shutil.Error):  # REVIEWED: broad catch — cleanup only
                pass

    return PluginInstallFromLocalPathResult(
        plugin_name=plugin_name,
        source_path=source_path.resolve(),
        installed_path=installed_path.resolve(),
        manifest_path=manifest_path.resolve(),
        overwritten=already_exists,
    )


def run(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Automation-friendly entrypoint (JSON-in / JSON-out)."""
    try:
        src = payload.get("source_path")
        if src is None:
            src = payload.get("path")  # legacy alias
        if not isinstance(src, str):
            raise PluginInstallFromLocalPathError("invalid_input", "Field 'source_path' must be a string path.")

        plugin_name = payload.get("plugin_name")
        if plugin_name is not None and not isinstance(plugin_name, str):
            raise PluginInstallFromLocalPathError("invalid_input", "Field 'plugin_name' must be a string.")

        install_root = payload.get("install_root")
        if install_root is not None and not isinstance(install_root, str):
            raise PluginInstallFromLocalPathError("invalid_input", "Field 'install_root' must be a string path.")

        req = PluginInstallFromLocalPathRequest(
            source_path=Path(src),
            plugin_name=plugin_name,
            install_root=Path(install_root) if install_root else None,
            overwrite=bool(payload.get("overwrite", False)),
        )
        result = install_plugin_from_local_path(req)
        out = asdict(result)
        out["ok"] = True
        for k in ("source_path", "installed_path", "manifest_path"):
            out[k] = str(out[k])
        return out
    except PluginInstallFromLocalPathError as e:
        return e.to_dict()
    except (OSError, ValueError, KeyError, TypeError) as e:
        err = PluginInstallFromLocalPathError(
            "unexpected_error",
            "Unexpected error during plugin installation.",
            details={"reason": type(e).__name__},
        )
        return err.to_dict()


def input_schema() -> dict[str, Any]:
    """JSON schema for the run() payload."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source_path": {"type": "string", "description": "Local directory path to the plugin source."},
            "path": {"type": "string", "description": "Alias of source_path for legacy callers."},
            "plugin_name": {"type": "string", "description": "Optional explicit plugin name override."},
            "install_root": {"type": "string", "description": "Optional install root override."},
            "overwrite": {"type": "boolean", "default": False},
        },
        "anyOf": [{"required": ["source_path"]}, {"required": ["path"]}],
    }


def output_schema() -> dict[str, Any]:
    """JSON schema for the run() response."""
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "plugin_name": {"type": "string"},
            "source_path": {"type": "string"},
            "installed_path": {"type": "string"},
            "manifest_path": {"type": "string"},
            "overwritten": {"type": "boolean"},
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                },
                "required": ["code", "message", "details"],
            },
        },
        "required": ["ok"],
    }


def register(registry: Any) -> None:
    """
    Best-effort tool registration hook.

    Adapts to common registry method names and parameter conventions so the
    plugin can be used in both CLI and Gateway-style tool registries.
    """
    import inspect

    def _try_call(fn: Any, **kwargs: Any) -> bool:
        try:
            sig = inspect.signature(fn)
            allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
            fn(**allowed)
            return True
        except (TypeError, AttributeError):  # REVIEWED: broad catch — best-effort registration
            return False

    candidates = []
    for name in ("register_tool", "register", "add_tool", "add", "register_handler"):
        if hasattr(registry, name):
            candidates.append(getattr(registry, name))

    payload = {
        "name": TOOL_NAME,
        "tool_name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "handler": run,
        "fn": run,
        "func": run,
        "input_schema": input_schema(),
        "output_schema": output_schema(),
        "schema_in": input_schema(),
        "schema_out": output_schema(),
    }

    for fn in candidates:
        if _try_call(fn, **payload):
            return

    raise RuntimeError("Unsupported tool registry interface for plugin registration.")


__all__ = [
    "TOOL_NAME",
    "TOOL_DESCRIPTION",
    "PluginInstallFromLocalPathError",
    "PluginInstallFromLocalPathRequest",
    "PluginInstallFromLocalPathResult",
    "install_plugin_from_local_path",
    "run",
    "input_schema",
    "output_schema",
    "register",
]
