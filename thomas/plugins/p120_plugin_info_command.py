"""
P120 - Plugin info command (core implementation).

Thomas-native: no OpenClaw naming reuse.

Public surface:
  - run_plugin_info_command(input) -> output
  - PluginInfoCommandInput / Output dataclasses
  - PluginInfoCommandError deterministic errors with stable codes
  - format_plugin_info_human(output) for CLI printing

Design notes:
  - Keeps imports lightweight.
  - Integrates with the broader Thomas runtime via lazy resolution, so unit
    tests can run without booting the whole system.
  - Produces JSON-serializable output for automation.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Callable, Mapping, Sequence


# -----------------------------
# Public contracts
# -----------------------------


@dataclass(frozen=True, slots=True)
class PluginInfoCommandInput:
    """Input contract for the plugin info command."""

    plugin_id: str
    include_install_record: bool = False


@dataclass(frozen=True, slots=True)
class PluginInfoCommandOutput:
    """Output contract for the plugin info command."""

    plugin: dict[str, Any]
    install: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"plugin": self.plugin, "install": self.install}


class PluginInfoCommandError(Exception):
    """Deterministic error for plugin info command failures."""

    def __init__(self, code: str, message: str, *, details: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = _to_jsonable(self.details)
        return payload


# -----------------------------
# Error codes (stable strings)
# -----------------------------

ERR_INVALID_INPUT = "invalid_input"
ERR_NOT_FOUND = "not_found"
ERR_MISSING_CONFIG = "missing_config"
ERR_EXTERNAL_FAILURE = "external_failure"


# -----------------------------
# JSON schema (for automation / routing)
# -----------------------------

PLUGIN_INFO_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "plugin_id": {"type": "string", "minLength": 1},
        "include_install_record": {"type": "boolean", "default": False},
    },
    "required": ["plugin_id"],
}

# Permissive plugin schema: plugin metadata evolves; consumers should accept
# unknown fields.
PLUGIN_INFO_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "plugin": {"type": "object"},
        "install": {"type": ["object", "null"]},
    },
    "required": ["plugin"],
}


# -----------------------------
# Main entry point
# -----------------------------


def run_plugin_info_command(
    params: PluginInfoCommandInput,
    *,
    status_report_provider: Callable[[], Any] | None = None,
    config_loader: Callable[[], Any] | None = None,
) -> PluginInfoCommandOutput:
    """
    Resolve a plugin by id or name and return a JSON-serializable plugin record.

    Args:
        params: Input contract for the command.
        status_report_provider: Optional dependency injection for unit tests.
        config_loader: Optional dependency injection for unit tests.

    Raises:
        PluginInfoCommandError: Deterministic error on failure.
    """
    plugin_ref = (params.plugin_id or "").strip()
    if not plugin_ref:
        raise PluginInfoCommandError(ERR_INVALID_INPUT, "Plugin id is required.")

    report_provider = status_report_provider or _build_plugin_status_report
    try:
        report = report_provider()
    except PluginInfoCommandError:
        raise
    except FileNotFoundError as exc:
        raise PluginInfoCommandError(
            ERR_MISSING_CONFIG,
            "Missing Thomas configuration required to inspect plugins.",
            details=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise PluginInfoCommandError(
            ERR_EXTERNAL_FAILURE,
            "Failed to build plugin status report.",
            details=str(exc),
        ) from exc

    plugins = _extract_plugins_from_report(report)
    plugin_entry = _find_plugin_by_id_or_name(plugins, plugin_ref)
    if plugin_entry is None:
        raise PluginInfoCommandError(ERR_NOT_FOUND, f"Plugin not found: {params.plugin_id}")

    plugin_dict = _normalize_plugin_entry(plugin_entry)
    if not isinstance(plugin_dict, dict):
        raise PluginInfoCommandError(
            ERR_EXTERNAL_FAILURE,
            "Plugin entry was not an object.",
            details={"plugin": repr(plugin_entry)},
        )

    install_record: dict[str, Any] | None = None
    if params.include_install_record:
        cfg_loader = config_loader or _load_config
        try:
            cfg = cfg_loader()
            install_record = _extract_install_record(cfg, str(plugin_dict.get("id") or plugin_ref))
        except PluginInfoCommandError:
            raise
        except FileNotFoundError:
            # Config isn't strictly required to display core plugin info; treat
            # it as missing install metadata rather than a hard failure.
            install_record = None
        except Exception:
            install_record = None

    return PluginInfoCommandOutput(plugin=plugin_dict, install=install_record)


# -----------------------------
# Formatting helpers (used by CLI)
# -----------------------------


def format_plugin_info_human(output: PluginInfoCommandOutput) -> str:
    """
    Render a human-friendly multi-line description of a plugin.

    Intended for terminal humans; automation should prefer `--json`.
    """
    plugin = output.plugin
    lines: list[str] = []

    header = (str(plugin.get("name") or plugin.get("id") or "")).strip() or "<unknown plugin>"
    lines.append(header)

    pid = (str(plugin.get("id") or "")).strip()
    name = (str(plugin.get("name") or "")).strip()
    if pid and name and pid != name:
        lines.append(f"id: {pid}")

    desc = plugin.get("description")
    if isinstance(desc, str) and desc.strip():
        lines.append(desc.strip())

    # key details
    def add(label: str, key: str) -> None:
        value = plugin.get(key)
        if value is None or value == "" or value == []:
            return
        if isinstance(value, list):
            value_str = ", ".join(str(v) for v in value)
        else:
            value_str = str(value)
        lines.append(f"{label}: {value_str}")

    if any(plugin.get(k) not in (None, "", []) for k in ("status", "version", "source", "origin")):
        lines.append("")

    add("Status", "status")
    add("Version", "version")
    add("Source", "source")
    add("Origin", "origin")

    # surfaces
    if any(
        plugin.get(k) not in (None, "", [])
        for k in ("toolNames", "hookNames", "gatewayMethods", "providerIds", "cliCommands", "services")
    ):
        lines.append("")

    add("Tools", "toolNames")
    add("Hooks", "hookNames")
    add("Gateway methods", "gatewayMethods")
    add("Providers", "providerIds")
    add("CLI commands", "cliCommands")
    add("Services", "services")

    err = plugin.get("error")
    if isinstance(err, str) and err.strip():
        lines.append("")
        lines.append(f"Error: {err.strip()}")

    install = output.install
    if isinstance(install, dict) and install:
        lines.append("")
        lines.append("Install record")
        if install.get("source"):
            lines.append(f"  source: {install['source']}")
        if install.get("spec"):
            lines.append(f"  spec: {install['spec']}")
        if install.get("sourcePath"):
            lines.append(f"  source_path: {install['sourcePath']}")
        if install.get("installPath"):
            lines.append(f"  install_path: {install['installPath']}")
        if install.get("version"):
            lines.append(f"  version: {install['version']}")
        if install.get("installedAt"):
            lines.append(f"  installed_at: {install['installedAt']}")

    return "\n".join(lines).rstrip() + "\n"


# -----------------------------
# Thomas integration (lazy resolution)
# -----------------------------


def _build_plugin_status_report() -> Any:
    """
    Build a plugin status report using the surrounding Thomas runtime.

    We resolve the status builder lazily to keep this module import-light and
    testable.

    The report is expected to contain a `plugins` sequence (or similar), where
    each entry contains at least `id` or `name`.
    """
    # Most likely candidates first.
    builder = _resolve_callable(
        [
            ("thomas.autonomy.plugin", ["build_plugin_status_report", "build_status_report", "plugin_status_report"]),
            ("thomas.plugins.status", ["build_plugin_status_report", "build_status_report", "plugin_status_report"]),
            (
                "thomas.plugins.status_report",
                ["build_plugin_status_report", "build_status_report", "plugin_status_report"],
            ),
            ("thomas.plugins", ["build_plugin_status_report", "build_status_report", "plugin_status_report"]),
        ]
    )

    if builder is None:
        # Fallback: find a runtime object that can produce a status report.
        runtime_getter = _resolve_callable(
            [
                ("thomas.autonomy.plugin", ["get_plugin_runtime", "get_runtime", "runtime"]),
                ("thomas.plugins", ["get_plugin_runtime", "get_runtime", "runtime"]),
            ]
        )
        if runtime_getter is not None:
            try:
                rt = runtime_getter()
                for attr in (
                    "build_plugin_status_report",
                    "build_status_report",
                    "status_report",
                    "report",
                    "snapshot",
                ):
                    fn = getattr(rt, attr, None)
                    if callable(fn):
                        return fn()
            except FileNotFoundError:
                raise
            except Exception as exc:
                raise PluginInfoCommandError(
                    ERR_EXTERNAL_FAILURE,
                    "Failed to build plugin status report.",
                    details=str(exc),
                ) from exc

        raise PluginInfoCommandError(
            ERR_EXTERNAL_FAILURE,
            "Plugin status reporting is not available in this Thomas build.",
        )

    try:
        return builder()
    except PluginInfoCommandError:
        raise
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise PluginInfoCommandError(
            ERR_EXTERNAL_FAILURE,
            "Failed to build plugin status report.",
            details=str(exc),
        ) from exc


def _load_config() -> Any:
    """
    Load Thomas config.

    Used only to display plugin install records in human output.
    """
    loader = _resolve_callable(
        [
            ("thomas.config", ["load_config", "load"]),
            ("thomas.config.config", ["load_config", "load"]),
            ("thomas.config.loader", ["load_config", "load"]),
        ]
    )
    if loader is None:
        raise PluginInfoCommandError(
            ERR_MISSING_CONFIG,
            "Thomas config loader was not found.",
        )

    try:
        return loader()
    except PluginInfoCommandError:
        raise
    except FileNotFoundError as exc:
        raise PluginInfoCommandError(
            ERR_MISSING_CONFIG,
            "Thomas config file not found.",
            details=str(exc),
        ) from exc
    except Exception as exc:
        raise PluginInfoCommandError(
            ERR_EXTERNAL_FAILURE,
            "Failed to load Thomas config.",
            details=str(exc),
        ) from exc


def _resolve_callable(candidates: Sequence[tuple[str, Sequence[str]]]) -> Callable[..., Any] | None:
    for module_name, attr_names in candidates:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for attr in attr_names:
            fn = getattr(module, attr, None)
            if callable(fn):
                return fn  # type: ignore[return-value]
    return None


# -----------------------------
# Report parsing helpers
# -----------------------------


def _extract_plugins_from_report(report: Any) -> list[Any]:
    if report is None:
        raise PluginInfoCommandError(ERR_EXTERNAL_FAILURE, "Plugin status report was empty.")

    plugins: Any | None = None
    if isinstance(report, Mapping):
        plugins = report.get("plugins") or report.get("entries") or report.get("items")
    else:
        plugins = getattr(report, "plugins", None) or getattr(report, "entries", None) or getattr(report, "items", None)

    if plugins is None:
        raise PluginInfoCommandError(
            ERR_EXTERNAL_FAILURE,
            "Plugin status report did not include a plugin list.",
        )

    if isinstance(plugins, list):
        return plugins

    if isinstance(plugins, Sequence) and not isinstance(plugins, (str, bytes)):
        return list(plugins)

    raise PluginInfoCommandError(
        ERR_EXTERNAL_FAILURE,
        "Plugin list was not a sequence.",
        details={"type": type(plugins).__name__},
    )


def _normalize_plugin_entry(entry: Any) -> dict[str, Any]:
    """
    Normalize a plugin entry into a dict.

    Supports:
      - dict with id/name fields
      - dict with nested `plugin` dict
      - dataclass / pydantic objects
    """
    d = _to_jsonable(entry)
    if isinstance(d, Mapping):
        # Some reports wrap metadata under `plugin`.
        inner = d.get("plugin")
        if isinstance(inner, Mapping):
            merged = {str(k): _to_jsonable(v) for k, v in inner.items()}
            for k, v in d.items():
                if k != "plugin" and k not in merged:
                    merged[str(k)] = _to_jsonable(v)
            return merged
        return {str(k): _to_jsonable(v) for k, v in d.items()}

    if isinstance(d, str):
        return {"id": d}
    return {"id": str(d)}


def _find_plugin_by_id_or_name(plugins: Sequence[Any], plugin_ref: str) -> Any | None:
    """
    Find by exact id/name; then case-insensitive fallback.
    """
    # exact match pass
    for entry in plugins:
        d = _normalize_plugin_entry(entry)
        pid = str(d.get("id") or d.get("plugin_id") or d.get("pluginId") or "").strip()
        name = str(d.get("name") or "").strip()
        if pid == plugin_ref or name == plugin_ref:
            return entry

    # case-insensitive fallback pass
    ref_l = plugin_ref.lower()
    for entry in plugins:
        d = _normalize_plugin_entry(entry)
        pid = str(d.get("id") or d.get("plugin_id") or d.get("pluginId") or "").strip()
        name = str(d.get("name") or "").strip()
        if (pid and pid.lower() == ref_l) or (name and name.lower() == ref_l):
            return entry

    return None


def _extract_install_record(config: Any, plugin_id: str) -> dict[str, Any] | None:
    cfg = _to_jsonable(config)
    if not isinstance(cfg, Mapping):
        return None

    plugins = cfg.get("plugins")
    if not isinstance(plugins, Mapping):
        return None

    installs = plugins.get("installs") or plugins.get("installed") or plugins.get("records")
    if not isinstance(installs, Mapping):
        return None

    record = installs.get(plugin_id)
    if isinstance(record, Mapping):
        return {str(k): _to_jsonable(v) for k, v in record.items()}
    return None


# -----------------------------
# JSON coercion
# -----------------------------


def _to_jsonable(value: Any) -> Any:
    """
    Convert common Thomas objects (dataclasses/pydantic/models) to JSON-safe
    primitives without importing optional dependencies.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {str(k): _to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]

    # pydantic v2
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _to_jsonable(dump())

    # pydantic v1
    dump = getattr(value, "dict", None)
    if callable(dump):
        return _to_jsonable(dump())

    # dataclasses
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(value):
            return _to_jsonable(asdict(value))
    except Exception:
        pass

    # generic object
    try:
        data = {k: _to_jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
        if data:
            return data
    except Exception:
        pass

    return str(value)
