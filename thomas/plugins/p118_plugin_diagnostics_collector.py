"""Plugin diagnostics collector.

Thomas-native behavior for collecting diagnostics about plugins under
``thomas.plugins`` and (optionally) correlating them with the tool registry.

Design goals:
- Deterministic error codes for automation.
- Best-effort operation: a single broken plugin should not prevent a report.
- Stable, machine-readable output (JSON-serializable dict).

Notes:
- We discover plugin modules without importing them (pkgutil scan), and then
  import individual modules while capturing failures.
- Tool registry correlation is intentionally best-effort. The registry API can
  vary across codebases, so we try common patterns.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# -------------------------
# Deterministic error model
# -------------------------


class PluginDiagnosticsCollectorError(RuntimeError):
    """A deterministic error with a stable code and JSON-serializable details."""

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = str(code)
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


ERROR_INVALID_INPUT = "invalid_input"
ERROR_UNKNOWN_PLUGIN = "unknown_plugin"
ERROR_MISSING_TOOL_REGISTRY = "missing_tool_registry"
ERROR_PLUGIN_IMPORT_FAILED = "plugin_import_failed"


# -------------------------
# Input / Output contracts
# -------------------------


@dataclass(frozen=True)
class PluginDiagnosticsInput:
    """Input contract for collecting plugin diagnostics."""

    plugin_names: Optional[List[str]] = None
    include_tools: bool = True
    strict: bool = False


@dataclass(frozen=True)
class DiagnosticIssue:
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginDiagnostic:
    name: str
    module: str
    status: str  # "loaded" | "error"
    tool_names: List[str] = field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class PluginDiagnosticsReport:
    ok: bool
    generated_at_utc: str
    python: str
    platform: str
    plugins: List[PluginDiagnostic]
    issues: List[DiagnosticIssue] = field(default_factory=list)


# JSON schema-ish structures for automation.
INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "plugin_names": {"type": ["array", "null"], "items": {"type": "string"}},
        "include_tools": {"type": "boolean"},
        "strict": {"type": "boolean"},
    },
}

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "generated_at_utc": {"type": "string"},
        "python": {"type": "string"},
        "platform": {"type": "string"},
        "plugins": {"type": "array"},
        "issues": {"type": "array"},
    },
}


@dataclass(frozen=True)
class _PluginModuleRef:
    base: str
    full: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_plugin_names(names: Optional[Sequence[str]]) -> Optional[List[str]]:
    if names is None:
        return None
    cleaned: List[str] = []
    for raw in names:
        if raw is None:
            raise PluginDiagnosticsCollectorError(
                ERROR_INVALID_INPUT,
                "plugin_names must not contain null values",
            )
        name = str(raw).strip()
        if not name:
            raise PluginDiagnosticsCollectorError(
                ERROR_INVALID_INPUT,
                "plugin_names must contain non-empty strings",
            )
        cleaned.append(name.replace("-", "_"))
    return sorted(set(cleaned))


def _discover_plugins() -> List[_PluginModuleRef]:
    """Discover plugin modules under thomas.plugins without importing them."""
    spec = importlib.util.find_spec("thomas.plugins")
    if spec is None or spec.submodule_search_locations is None:
        raise PluginDiagnosticsCollectorError(
            ERROR_INVALID_INPUT,
            "Plugins package 'thomas.plugins' was not found",
        )

    refs: List[_PluginModuleRef] = []
    for mod in pkgutil.iter_modules(list(spec.submodule_search_locations), prefix="thomas.plugins."):
        base = mod.name.rsplit(".", 1)[-1]
        if base.startswith("_"):
            continue
        refs.append(_PluginModuleRef(base=base, full=mod.name))

    refs.sort(key=lambda r: r.base)
    return refs


def _extract_tool_records(registry_obj: Any) -> List[Tuple[str, Optional[Any]]]:
    """Best-effort extraction of (tool_name, tool_callable) from a registry object."""
    # Mapping-like registry
    mapping: Optional[Mapping[Any, Any]] = None
    if isinstance(registry_obj, Mapping):
        mapping = registry_obj
    else:
        for attr in ("tools", "tool_map", "_tools", "registry", "_registry"):
            val = getattr(registry_obj, attr, None)
            if isinstance(val, Mapping):
                mapping = val
                break

    # Method-based registry
    if mapping is None:
        for method in ("items", "get_tools", "list_tools", "tool_items"):
            fn = getattr(registry_obj, method, None)
            if not callable(fn):
                continue
            try:
                res = fn()
            except TypeError:
                continue
            except Exception:
                continue
            if isinstance(res, Mapping):
                mapping = res
                break
            if isinstance(res, list):
                tmp: Dict[str, Any] = {}
                for idx, item in enumerate(res):
                    name = getattr(item, "name", None) or getattr(item, "tool_name", None) or str(idx)
                    tmp[str(name)] = item
                mapping = tmp
                break

    if mapping is None:
        return []

    records: List[Tuple[str, Optional[Any]]] = []
    for raw_name, raw_val in mapping.items():
        tool_name = str(raw_name)
        tool_callable: Optional[Any] = None

        if callable(raw_val):
            tool_callable = raw_val
        else:
            for attr in ("func", "function", "handler", "callable", "tool_func", "run", "__call__"):
                fn = getattr(raw_val, attr, None)
                if callable(fn):
                    tool_callable = fn
                    break
            if tool_callable is None and isinstance(raw_val, (tuple, list)):
                for candidate in reversed(raw_val):
                    if callable(candidate):
                        tool_callable = candidate
                        break

        records.append((tool_name, tool_callable))

    records.sort(key=lambda t: t[0])
    return records


def _load_tool_registry_snapshot() -> Dict[str, List[str]]:
    """Return mapping: origin_module -> list of tool names."""
    try:
        registry_mod = importlib.import_module("thomas.tools.registry")
    except Exception as e:
        raise PluginDiagnosticsCollectorError(
            ERROR_MISSING_TOOL_REGISTRY,
            "Tool registry module 'thomas.tools.registry' could not be imported",
            details={"error_type": type(e).__name__},
        ) from e

    registry_obj: Any = None
    for attr in ("registry", "tool_registry", "TOOL_REGISTRY", "TOOLS", "tools"):
        val = getattr(registry_mod, attr, None)
        if val is not None:
            registry_obj = val
            break

    if registry_obj is None:
        for fn_name in ("get_registry", "get_tool_registry", "default_registry", "build_registry"):
            fn = getattr(registry_mod, fn_name, None)
            if not callable(fn):
                continue
            try:
                registry_obj = fn()
                break
            except Exception:
                continue

    if registry_obj is None:
        raise PluginDiagnosticsCollectorError(
            ERROR_MISSING_TOOL_REGISTRY,
            "Tool registry object was not found in 'thomas.tools.registry'",
        )

    module_to_tools: Dict[str, List[str]] = {}
    for tool_name, tool_callable in _extract_tool_records(registry_obj):
        origin = getattr(tool_callable, "__module__", None) if tool_callable is not None else None
        origin_mod = str(origin) if origin else "<unknown>"
        module_to_tools.setdefault(origin_mod, []).append(tool_name)

    for k in list(module_to_tools.keys()):
        module_to_tools[k] = sorted(set(module_to_tools[k]))
    return module_to_tools


def _tools_for_plugin(plugin_module: str, module_to_tools: Mapping[str, List[str]]) -> List[str]:
    tools: List[str] = []
    for origin_mod, tool_names in module_to_tools.items():
        if origin_mod == plugin_module or origin_mod.startswith(plugin_module + "."):
            tools.extend(tool_names)
    return sorted(set(tools))


def collect_plugin_diagnostics(request: PluginDiagnosticsInput) -> PluginDiagnosticsReport:
    """Collect diagnostics for plugins and optionally correlate tool registrations."""
    plugin_names = _normalize_plugin_names(request.plugin_names)
    plugin_refs = _discover_plugins()

    if plugin_names:
        requested = set(plugin_names)
        filtered: List[_PluginModuleRef] = [
            ref for ref in plugin_refs if ref.base in requested or ref.full in requested
        ]
        if not filtered:
            raise PluginDiagnosticsCollectorError(
                ERROR_UNKNOWN_PLUGIN,
                "No matching plugins found",
                details={"requested": sorted(requested)},
            )
        plugin_refs = sorted(filtered, key=lambda r: r.base)

    issues: List[DiagnosticIssue] = []
    module_to_tools: Dict[str, List[str]] = {}
    if request.include_tools:
        try:
            module_to_tools = _load_tool_registry_snapshot()
        except PluginDiagnosticsCollectorError as e:
            if request.strict:
                raise
            issues.append(DiagnosticIssue(code=e.code, message=str(e), details=e.details))
            module_to_tools = {}

    plugins: List[PluginDiagnostic] = []
    ok = True

    for ref in plugin_refs:
        status = "loaded"
        err_type: Optional[str] = None
        err_msg: Optional[str] = None
        try:
            importlib.import_module(ref.full)
        except Exception as e:
            status = "error"
            err_type = type(e).__name__
            err_msg = str(e)
            ok = False

            issue_details = {"plugin": ref.base, "module": ref.full, "error_type": err_type}
            if request.strict:
                raise PluginDiagnosticsCollectorError(
                    ERROR_PLUGIN_IMPORT_FAILED,
                    f"Plugin '{ref.base}' failed to import",
                    details=issue_details,
                ) from e

            issues.append(
                DiagnosticIssue(
                    code=ERROR_PLUGIN_IMPORT_FAILED,
                    message="Plugin failed to import",
                    details=issue_details,
                )
            )

        tool_names = _tools_for_plugin(ref.full, module_to_tools) if module_to_tools else []
        plugins.append(
            PluginDiagnostic(
                name=ref.base,
                module=ref.full,
                status=status,
                tool_names=tool_names,
                error_type=err_type,
                error_message=err_msg,
            )
        )

    # A report with any issues is not OK.
    if issues:
        ok = False

    return PluginDiagnosticsReport(
        ok=ok,
        generated_at_utc=_utc_now_iso(),
        python=sys.version.split()[0],
        platform=platform.platform(),
        plugins=sorted(plugins, key=lambda p: p.name),
        issues=sorted(issues, key=lambda i: (i.code, i.message)),
    )


def report_to_dict(report: PluginDiagnosticsReport) -> Dict[str, Any]:
    """Convert the report to a JSON-serializable dict with deterministic ordering."""
    data = asdict(report)
    data["plugins"] = sorted(data.get("plugins", []), key=lambda p: p.get("name", ""))
    data["issues"] = sorted(
        data.get("issues", []), key=lambda i: (i.get("code", ""), i.get("message", ""))
    )
    return data


def tool(input_data: Optional[Mapping[str, Any]] = None, context: Any = None) -> Dict[str, Any]:
    """Tool-friendly wrapper. Accepts a mapping and returns a mapping."""
    payload = dict(input_data or {})
    req = PluginDiagnosticsInput(
        plugin_names=payload.get("plugin_names"),
        include_tools=bool(payload.get("include_tools", True)),
        strict=bool(payload.get("strict", False)),
    )
    report = collect_plugin_diagnostics(req)
    return report_to_dict(report)


# Convenience exports that some registries use.
TOOL_NAME = "plugin_diagnostics_collector"
TOOLS = [tool]


def _resolve_plugin_base() -> type:
    """Resolve a plugin base type from thomas.autonomy.plugin, if available."""
    try:
        plugin_mod = importlib.import_module("thomas.autonomy.plugin")
    except Exception:
        return object

    for name in ("AutonomyPlugin", "Plugin", "BasePlugin", "ThomasPlugin"):
        base = getattr(plugin_mod, name, None)
        if isinstance(base, type):
            return base
    return object


_PluginBase = _resolve_plugin_base()


class PluginDiagnosticsCollector(_PluginBase):
    """Compatibility wrapper that exposes a conventional plugin interface."""

    name = "plugin_diagnostics_collector"
    input_schema = INPUT_SCHEMA
    output_schema = OUTPUT_SCHEMA

    def run(self, input_data: Optional[Mapping[str, Any]] = None, context: Any = None) -> Dict[str, Any]:
        return tool(input_data, context=context)

    __call__ = run
    invoke = run


# Common plugin discovery patterns look for `PLUGIN`.
PLUGIN = PluginDiagnosticsCollector()
