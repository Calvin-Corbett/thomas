"""Plugin diagnostics ("doctor").

This module implements a Thomas-native plugin diagnostics utility that:
- discovers plugin modules under ``thomas.plugins``
- validates they can be imported
- (optionally) calls each plugin's registration hook to verify tool registration wiring

The command is designed to be usable from both CLI and automation:
- deterministic exceptions for invalid input / missing user-supplied config paths
- structured, machine-readable report via ``PluginDoctorReport.to_dict()``
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from collections.abc import Callable

TOOL_NAME = "plugins.doctor"
TOOL_DESCRIPTION = "Run diagnostics over installed Thomas plugins and return a structured report."
TOOL_VERSION = "1.1"

DoctorStatus = Literal["pass", "fail", "warn"]


# ----------------------------
# Contracts
# ----------------------------

@dataclass(frozen=True)
class PluginDoctorRequest:
    """Inputs for plugin diagnostics."""

    plugin: str | None = None
    config_path: str | None = None
    include_hidden: bool = False
    strict: bool = False


@dataclass(frozen=True)
class DoctorCheck:
    """A single diagnostic check result."""

    id: str
    status: DoctorStatus
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginDoctorReport:
    """Overall diagnostic report."""

    ok: bool
    inspected: list[str] = field(default_factory=list)
    checks: list[DoctorCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "inspected": list(self.inspected),
            "checks": [asdict(c) for c in self.checks],
        }


# ----------------------------
# Deterministic errors
# ----------------------------

class PluginDoctorError(RuntimeError):
    """Base class for deterministic doctor failures."""

    code: str = "PLUGIN_DOCTOR_ERROR"
    exit_code: int = 2

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code


class InvalidPluginDoctorInput(PluginDoctorError):
    code = "INVALID_INPUT"
    exit_code = 2


class PluginConfigNotFound(PluginDoctorError):
    code = "CONFIG_NOT_FOUND"
    exit_code = 2


_PLUGIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _normalize_path(p: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(p))
    return str(Path(expanded))


def _validate_request(req: PluginDoctorRequest) -> None:
    if req.plugin is not None:
        if not isinstance(req.plugin, str) or req.plugin.strip() != req.plugin or req.plugin == "":
            raise InvalidPluginDoctorInput(
                "plugin must be a non-empty string without leading/trailing whitespace"
            )
        if not _PLUGIN_TOKEN_RE.match(req.plugin):
            raise InvalidPluginDoctorInput(
                "plugin contains invalid characters; allowed: letters, numbers, '_', '-', '.'"
            )

    if req.config_path is not None:
        normalized = _normalize_path(req.config_path)
        if not Path(normalized).is_file():
            raise PluginConfigNotFound(f"config file not found: {normalized}")


def _resolve_plugin_module_name(plugin: str) -> str:
    # Accept fully-qualified module paths, or short names under thomas.plugins.
    if plugin.startswith("thomas."):
        return plugin
    if plugin.startswith("plugins."):
        return f"thomas.{plugin}"
    return f"thomas.plugins.{plugin}"


def _try_import_module(module_name: str) -> tuple[Any | None, str | None, dict[str, Any]]:
    """Try importing a module. Returns (module|None, error_summary|None, details)."""
    try:
        module = importlib.import_module(module_name)
        return module, None, {}
    except Exception as exc:  # pragma: no cover - exact exception varies
        return (
            None,
            f"{type(exc).__name__}: {exc}",
            {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            },
        )


def _discover_plugin_module_names(*, include_hidden: bool) -> tuple[list[str], str | None]:
    """Discover plugin module names under `thomas.plugins`.

    Returns (names, error_summary). If discovery fails (e.g. thomas.plugins missing),
    names will be empty and error_summary will be non-null.
    """
    plugins_mod, err, _details = _try_import_module("thomas.plugins")
    if plugins_mod is None:
        return [], err or "unknown error"

    pkg_path = getattr(plugins_mod, "__path__", None)
    if pkg_path is None:
        return [], "thomas.plugins has no __path__ (not a package?)"

    prefix = plugins_mod.__name__ + "."
    names: list[str] = []
    for mod in pkgutil.iter_modules(pkg_path, prefix=prefix):
        base = mod.name.split(".")[-1]
        if not include_hidden and base.startswith("_"):
            continue
        names.append(mod.name)

    return sorted(set(names)), None


class ToolRegistryProbe:
    """A minimal registry shim used to validate plugin registration wiring."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self._seen: dict[str, int] = {}
        self.duplicate_names: list[str] = []
        self.invalid_registrations: list[dict[str, Any]] = []

    def register_tool(self, name: Any, fn: Any, description: Any = None, **kwargs: Any) -> None:
        self._record(name, fn, description=description, extra=kwargs)

    def add_tool(self, name: Any, fn: Any, description: Any = None, **kwargs: Any) -> None:
        self._record(name, fn, description=description, extra=kwargs)

    def register(self, name: Any, fn: Any, description: Any = None, **kwargs: Any) -> None:
        self._record(name, fn, description=description, extra=kwargs)

    def _record(self, name: Any, fn: Any, *, description: Any, extra: dict[str, Any]) -> None:
        problems: list[str] = []

        if not isinstance(name, str) or name.strip() == "":
            problems.append("tool name must be a non-empty string")
        if not callable(fn):
            problems.append("tool callable must be callable")

        if problems:
            self.invalid_registrations.append(
                {
                    "name": name,
                    "description": description,
                    "problems": problems,
                }
            )
            return

        if name in self._seen:
            self.duplicate_names.append(name)
        self._seen[name] = self._seen.get(name, 0) + 1

        self.tools.append(
            {
                "name": name,
                "callable": getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn))),
                "description": description if isinstance(description, str) else None,
                "extra": dict(extra),
            }
        )


def _find_registration_entrypoint(module: Any) -> tuple[str | None, Callable[[Any], Any] | None]:
    """Best-effort detection of a plugin registration hook."""
    reg = getattr(module, "register", None)
    if callable(reg):
        return "module.register", reg

    # Common patterns: module-level plugin object with .register()
    for attr in ("PLUGIN", "plugin"):
        obj = getattr(module, attr, None)
        if obj is None:
            continue
        reg2 = getattr(obj, "register", None)
        if callable(reg2):
            return f"{attr}.register", reg2

    return None, None


def run_plugin_doctor(request: PluginDoctorRequest) -> PluginDoctorReport:
    """Run diagnostics and return a structured report."""
    _validate_request(request)

    checks: list[DoctorCheck] = []
    inspected: list[str] = []

    # Config presence validation is deterministic only when a path is supplied.
    if request.config_path:
        checks.append(
            DoctorCheck(
                id="config:path",
                status="pass",
                summary="config file present",
                details={"path": _normalize_path(request.config_path)},
            )
        )
    else:
        checks.append(
            DoctorCheck(
                id="config:skipped",
                status="pass",
                summary="config check skipped (no config path provided)",
                details={},
            )
        )

    # Core imports that Thomas relies on.
    for core_mod in ("thomas.autonomy.plugin", "thomas.tools.registry", "thomas.agent.loop"):
        _m, err, details = _try_import_module(core_mod)
        checks.append(
            DoctorCheck(
                id=f"core-import:{core_mod}",
                status="pass" if err is None else "fail",
                summary="import ok" if err is None else f"import failed: {err}",
                details=details,
            )
        )

    # Determine which plugin modules to inspect.
    plugin_modules: list[str] = []
    if request.plugin:
        resolved = _resolve_plugin_module_name(request.plugin)
        if importlib.util.find_spec(resolved) is None:
            raise InvalidPluginDoctorInput(f"unknown plugin module: {resolved}")
        plugin_modules = [resolved]
        checks.append(
            DoctorCheck(
                id="plugin-scope",
                status="pass",
                summary="inspection narrowed to a single plugin",
                details={"plugin": resolved},
            )
        )
    else:
        plugin_modules, discovery_err = _discover_plugin_module_names(
            include_hidden=request.include_hidden
        )
        if discovery_err is not None:
            checks.append(
                DoctorCheck(
                    id="plugin-discovery",
                    status="fail",
                    summary=f"plugin discovery failed: {discovery_err}",
                    details={},
                )
            )
        else:
            status: DoctorStatus = "pass" if plugin_modules else "warn"
            summary = (
                f"discovered {len(plugin_modules)} plugin module(s)"
                if plugin_modules
                else "no plugin modules discovered under thomas.plugins"
            )
            checks.append(
                DoctorCheck(
                    id="plugin-discovery",
                    status=status,
                    summary=summary,
                    details={"count": len(plugin_modules)},
                )
            )

    # Inspect plugin importability + wiring.
    global_tool_owner: dict[str, str] = {}
    collisions: list[dict[str, str]] = []

    for mod_name in plugin_modules:
        inspected.append(mod_name)
        module, err, details = _try_import_module(mod_name)
        if module is None:
            checks.append(
                DoctorCheck(
                    id=f"plugin-import:{mod_name}",
                    status="fail",
                    summary=f"import failed: {err}",
                    details=details,
                )
            )
            continue

        checks.append(
            DoctorCheck(
                id=f"plugin-import:{mod_name}",
                status="pass",
                summary="import ok",
                details={},
            )
        )

        entry_id, entry_fn = _find_registration_entrypoint(module)
        if entry_fn is None or entry_id is None:
            checks.append(
                DoctorCheck(
                    id=f"plugin-entrypoint:{mod_name}",
                    status="warn",
                    summary="no registration entrypoint found (expected `register(registry)` or `plugin.register(registry)`)",
                    details={},
                )
            )
            continue

        checks.append(
            DoctorCheck(
                id=f"plugin-entrypoint:{mod_name}",
                status="pass",
                summary="registration entrypoint found",
                details={"entrypoint": entry_id},
            )
        )

        probe = ToolRegistryProbe()
        try:
            entry_fn(probe)
        except Exception as exc:  # pragma: no cover
            checks.append(
                DoctorCheck(
                    id=f"plugin-register:{mod_name}",
                    status="fail",
                    summary=f"registration failed: {type(exc).__name__}: {exc}",
                    details={
                        "entrypoint": entry_id,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                )
            )
            continue

        # Validate probe results.
        if probe.invalid_registrations:
            checks.append(
                DoctorCheck(
                    id=f"plugin-register:{mod_name}",
                    status="fail",
                    summary="registration produced invalid tool registrations",
                    details={"invalid": probe.invalid_registrations},
                )
            )
            continue

        if probe.duplicate_names:
            checks.append(
                DoctorCheck(
                    id=f"plugin-register:{mod_name}",
                    status="fail",
                    summary="registration produced duplicate tool names",
                    details={"duplicates": sorted(set(probe.duplicate_names))},
                )
            )
            continue

        # Track cross-plugin collisions.
        for t in probe.tools:
            name = t["name"]
            if name in global_tool_owner and global_tool_owner[name] != mod_name:
                collisions.append({"tool": name, "first": global_tool_owner[name], "second": mod_name})
            else:
                global_tool_owner[name] = mod_name

        status = "pass" if probe.tools else "warn"
        summary = (
            f"registered {len(probe.tools)} tool(s)"
            if probe.tools
            else "registration entrypoint ran but registered no tools"
        )
        checks.append(
            DoctorCheck(
                id=f"plugin-register:{mod_name}",
                status=status,
                summary=summary,
                details={"tools": [t["name"] for t in probe.tools]},
            )
        )

    if collisions:
        checks.append(
            DoctorCheck(
                id="registry:tool-name-collisions",
                status="fail",
                summary="tool name collisions detected across plugins",
                details={"collisions": collisions},
            )
        )

    has_fail = any(c.status == "fail" for c in checks)
    has_warn = any(c.status == "warn" for c in checks)
    ok = (not has_fail) and (not (request.strict and has_warn))

    return PluginDoctorReport(ok=ok, inspected=inspected, checks=checks)


def register(registry: Any) -> None:
    """Best-effort tool registration for a ToolRegistry-like object."""
    fn = run_plugin_doctor

    for method_name in ("register_tool", "register", "add_tool"):
        method = getattr(registry, method_name, None)
        if method is None or not callable(method):
            continue
        try:
            method(TOOL_NAME, fn, description=TOOL_DESCRIPTION)
        except TypeError:
            # Signature mismatch: try minimal positional call.
            method(TOOL_NAME, fn)
        return

    raise PluginDoctorError(
        "unable to register tool with provided registry (unsupported registry interface)",
        code="REGISTRY_UNSUPPORTED",
        exit_code=2,
    )
