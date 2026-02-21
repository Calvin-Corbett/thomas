"""Runtime-backed plugin listing (P121).

Goal
----
Provide a *runtime-backed* view of plugins without booting an agent loop:
- read the active config (to learn which plugins exist and whether enabled)
- inspect the plugins directory (to learn which plugin payloads are present)
- best-effort read plugin metadata from common manifests

Contracts are explicit (dataclasses + TypedDict) to support automation.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, TypedDict

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


PluginHealth = Literal["ok", "missing", "error"]
_DIR_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class PluginListError(RuntimeError):
    """Deterministic error for plugin listing failures."""

    def __init__(self, code: str, message: str, *, detail: str | None = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(self._format())

    def _format(self) -> str:
        if self.detail:
            return f"{self.code}: {self.message} ({self.detail})"
        return f"{self.code}: {self.message}"

    def to_dict(self) -> "PluginListErrorJSON":
        payload: PluginListErrorJSON = {"code": self.code, "message": self.message}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class PluginListErrorJSON(TypedDict, total=False):
    code: str
    message: str
    detail: str


@dataclass(frozen=True, slots=True)
class PluginListRequest:
    """Input contract for runtime-backed plugin listing."""

    config_path: Path | None = None
    plugins_dir: Path | None = None
    include_disabled: bool = True


@dataclass(frozen=True, slots=True)
class PluginListItem:
    """One plugin row returned by the runtime-backed listing."""

    plugin_id: str
    enabled: bool
    installed: bool
    status: PluginHealth
    name: str | None = None
    version: str | None = None
    source: str | None = None
    spec: str | None = None
    path: str | None = None
    error: str | None = None

    def to_dict(self) -> "PluginListItemJSON":
        return {
            "id": self.plugin_id,
            "enabled": self.enabled,
            "installed": self.installed,
            "status": self.status,
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "spec": self.spec,
            "path": self.path,
            "error": self.error,
        }


class PluginListItemJSON(TypedDict, total=False):
    id: str
    enabled: bool
    installed: bool
    status: PluginHealth
    name: str | None
    version: str | None
    source: str | None
    spec: str | None
    path: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class PluginListResult:
    """Output contract for runtime-backed plugin listing."""

    config_path: str
    plugins_dir: str
    plugins: tuple[PluginListItem, ...]

    def to_json(self) -> "PluginListResultJSON":
        return {
            "ok": True,
            "config_path": self.config_path,
            "plugins_dir": self.plugins_dir,
            "plugins": [p.to_dict() for p in self.plugins],
        }


class PluginListResultJSON(TypedDict):
    ok: bool
    config_path: str
    plugins_dir: str
    plugins: list[PluginListItemJSON]


class PluginListFailureJSON(TypedDict):
    ok: bool
    error: PluginListErrorJSON


PLUGIN_LIST_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "ok": {"const": True},
                "config_path": {"type": "string"},
                "plugins_dir": {"type": "string"},
                "plugins": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "enabled": {"type": "boolean"},
                            "installed": {"type": "boolean"},
                            "status": {"type": "string", "enum": ["ok", "missing", "error"]},
                            "name": {"type": ["string", "null"]},
                            "version": {"type": ["string", "null"]},
                            "source": {"type": ["string", "null"]},
                            "spec": {"type": ["string", "null"]},
                            "path": {"type": ["string", "null"]},
                            "error": {"type": ["string", "null"]},
                        },
                        "required": ["id", "enabled", "installed", "status"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["ok", "config_path", "plugins_dir", "plugins"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "ok": {"const": False},
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["code", "message"],
                    "additionalProperties": False,
                },
            },
            "required": ["ok", "error"],
            "additionalProperties": False,
        },
    ],
}


def failure_payload(error: PluginListError) -> PluginListFailureJSON:
    return {"ok": False, "error": error.to_dict()}


def list_plugins_runtime_backed(request: PluginListRequest) -> PluginListResult:
    """List plugins using local config + on-disk plugin payloads."""

    config_path = _resolve_config_path(request.config_path)
    config = _load_config(config_path)
    plugins_dir = _resolve_plugins_dir(request.plugins_dir, config_path, config)

    entries, installs = _extract_plugin_sections(config)
    plugin_ids = sorted(set(entries.keys()) | set(installs.keys()))

    plugins: list[PluginListItem] = []
    for plugin_id in plugin_ids:
        entry = entries.get(plugin_id, {})
        enabled = _extract_enabled(entry)
        if not request.include_disabled and not enabled:
            continue

        install_meta = installs.get(plugin_id, {})
        source = _safe_get_str(install_meta, "source")
        spec = (
            _safe_get_str(install_meta, "spec")
            or _safe_get_str(install_meta, "url")
            or _safe_get_str(install_meta, "ref")
        )

        plugin_path = _resolve_plugin_path(plugin_id, install_meta, plugins_dir, config_path.parent)
        installed = plugin_path.exists()
        status: PluginHealth = "ok" if installed else "missing"
        name: str | None = None
        version: str | None = _safe_get_str(install_meta, "version")
        error: str | None = None

        if installed:
            try:
                manifest = _read_manifest(plugin_path)
                name = _infer_name(plugin_id, manifest)
                version = _infer_version(version, manifest)
            except Exception as exc:  # noqa: BLE001
                status = "error"
                error = f"manifest_error: {type(exc).__name__}: {exc}"

        if not name:
            name = plugin_id

        plugins.append(
            PluginListItem(
                plugin_id=plugin_id,
                enabled=enabled,
                installed=installed,
                status=status,
                name=name,
                version=version,
                source=source,
                spec=spec,
                path=str(plugin_path),
                error=error,
            )
        )

    return PluginListResult(str(config_path), str(plugins_dir), tuple(plugins))


# ------------------------- config discovery/parsing -------------------------

def _resolve_config_path(explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit.expanduser()
        if path.exists() and not path.is_file():
            raise PluginListError("INVALID_INPUT", "config_path must be a file", detail=str(path))
        if not path.exists():
            raise PluginListError("CONFIG_MISSING", "configuration file not found", detail=str(path))
        return path

    env = os.getenv("THOMAS_CONFIG") or os.getenv("THOMAS_CONFIG_PATH")
    if env:
        path = Path(env).expanduser()
        if not path.exists():
            raise PluginListError("CONFIG_MISSING", "configuration file not found", detail=str(path))
        return path

    home = Path(os.getenv("THOMAS_HOME", "~/.thomas")).expanduser()
    for name in ("thomas.json", "thomas.yaml", "thomas.yml", "thomas.toml"):
        candidate = home / name
        if candidate.exists():
            return candidate

    raise PluginListError("CONFIG_MISSING", "configuration file not found", detail=str(home / "thomas.json"))


def _load_config(config_path: Path) -> dict[str, Any]:
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PluginListError(
            "EXTERNAL_FAILURE",
            "failed to read configuration file",
            detail=f"{config_path}: {type(exc).__name__}: {exc}",
        ) from exc

    suffix = config_path.suffix.lower()
    if suffix == ".json":
        return _as_mapping(_json_load(raw), config_path)
    if suffix in (".yaml", ".yml"):
        return _as_mapping(_yaml_load(raw), config_path)
    if suffix == ".toml":
        return _as_mapping(_toml_load(raw), config_path)

    last: str | None = None
    for name, loader in (("json", _json_load), ("toml", _toml_load), ("yaml", _yaml_load)):
        try:
            data = loader(raw)
            return _as_mapping(data, config_path)
        except PluginListError as exc:
            last = f"{name}: {exc.detail or exc.message}"
            continue
    raise PluginListError("CONFIG_INVALID", "unable to parse configuration file", detail=last or str(config_path))


def _json_load(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise PluginListError("CONFIG_INVALID", "invalid JSON", detail=f"{type(exc).__name__}: {exc}") from exc


def _toml_load(raw: str) -> Any:
    if tomllib is None:
        raise PluginListError("CONFIG_INVALID", "TOML parsing unavailable", detail="tomllib not available")
    try:
        return tomllib.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise PluginListError("CONFIG_INVALID", "invalid TOML", detail=f"{type(exc).__name__}: {exc}") from exc


def _yaml_load(raw: str) -> Any:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise PluginListError("CONFIG_INVALID", "YAML parsing unavailable", detail=str(exc)) from exc
    try:
        return yaml.safe_load(raw)
    except Exception as exc:  # noqa: BLE001
        raise PluginListError("CONFIG_INVALID", "invalid YAML", detail=f"{type(exc).__name__}: {exc}") from exc


def _as_mapping(data: Any, config_path: Path) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    raise PluginListError("CONFIG_INVALID", "config root must be a mapping/object", detail=str(config_path))


def _resolve_plugins_dir(explicit: Path | None, config_path: Path, config: Mapping[str, Any]) -> Path:
    if explicit is not None:
        return explicit.expanduser()

    env = os.getenv("THOMAS_PLUGINS_DIR")
    if env:
        return Path(env).expanduser()

    plugins_cfg = config.get("plugins")
    if isinstance(plugins_cfg, Mapping):
        maybe_dir = plugins_cfg.get("dir") or plugins_cfg.get("path") or plugins_cfg.get("root")
        if isinstance(maybe_dir, str) and maybe_dir.strip():
            return Path(maybe_dir).expanduser()

    maybe_dir2 = config.get("plugins_dir") or config.get("pluginsDir")
    if isinstance(maybe_dir2, str) and maybe_dir2.strip():
        return Path(maybe_dir2).expanduser()

    return config_path.parent / "plugins"


# -------------------------- plugin extraction --------------------------------

def _extract_plugin_sections(config: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    plugins = config.get("plugins")
    if not isinstance(plugins, Mapping):
        return {}, {}

    entries_raw = plugins.get("entries") or plugins.get("configured") or plugins.get("plugins")
    installs_raw = plugins.get("installs") or plugins.get("installations") or plugins.get("installed")
    return _coerce_id_map(entries_raw), _coerce_id_map(installs_raw)


def _coerce_id_map(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        out: dict[str, Any] = {}
        for item in value:
            if not isinstance(item, Mapping):
                continue
            pid = item.get("id") or item.get("plugin_id") or item.get("pluginId") or item.get("name")
            if isinstance(pid, str) and pid.strip():
                out[pid.strip()] = dict(item)
        return out
    return {}


def _extract_enabled(entry: Any) -> bool:
    if isinstance(entry, Mapping):
        enabled = entry.get("enabled")
        if isinstance(enabled, bool):
            return enabled
        disabled = entry.get("disabled")
        if isinstance(disabled, bool):
            return not disabled
    return True


def _safe_get_str(mapping: Mapping[str, Any], key: str) -> str | None:
    val = mapping.get(key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _plugin_dir_name(plugin_id: str) -> str:
    normalized = plugin_id.replace("/", "__").replace("\\", "__")
    normalized = _DIR_SAFE_RE.sub("_", normalized).strip("._")
    return normalized or "plugin"


def _resolve_plugin_path(plugin_id: str, install_meta: Mapping[str, Any], plugins_dir: Path, config_dir: Path) -> Path:
    for key in ("install_path", "installPath", "path", "dir", "root"):
        p = _safe_get_str(install_meta, key)
        if p:
            candidate = Path(p).expanduser()
            if not candidate.is_absolute():
                rel1 = (config_dir / candidate).resolve()
                if rel1.exists():
                    return rel1
                return (plugins_dir / candidate).resolve()
            return candidate
    return (plugins_dir / _plugin_dir_name(plugin_id)).resolve()


# ------------------------------ manifest -------------------------------------

def _read_manifest(plugin_path: Path) -> dict[str, Any]:
    if not plugin_path.exists():
        return {}
    if plugin_path.is_file():
        return _read_manifest_file(plugin_path)

    for c in (
        plugin_path / "plugin.json",
        plugin_path / "manifest.json",
        plugin_path / "package.json",
        plugin_path / "pyproject.toml",
    ):
        if c.exists() and c.is_file():
            return _read_manifest_file(c)
    return {}


def _read_manifest_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".toml":
        if tomllib is None:
            raise RuntimeError("tomllib not available")
        data = tomllib.loads(text)
        if isinstance(data, dict):
            project = data.get("project")
            if isinstance(project, Mapping):
                return {"name": project.get("name"), "version": project.get("version")}
            return data
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _infer_name(plugin_id: str, manifest: Mapping[str, Any]) -> str | None:
    for key in ("displayName", "title", "name"):
        val = manifest.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return plugin_id


def _infer_version(config_version: str | None, manifest: Mapping[str, Any]) -> str | None:
    val = manifest.get("version")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return config_version
