from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import json
import os
import sys
import tokenize
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


# ----------------------------
# Public contracts + schemas
# ----------------------------

REQUEST_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "search_paths": {"type": "array", "items": {"type": "string"}},
        "config_path": {"type": ["string", "null"]},
        "include_entry_points": {"type": "boolean", "default": True},
        "entry_point_group": {"type": "string", "default": "thomas.plugins"},
        "import_plugins": {"type": "boolean", "default": False},
        "recursive": {"type": "boolean", "default": False},
    },
    "required": [],
}

RESULT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scanned_paths": {"type": "array", "items": {"type": "string"}},
        "entry_point_group": {"type": "string"},
        "plugins": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "source": {"type": "string", "enum": ["filesystem", "entry_point"]},
                    "module": {"type": ["string", "null"]},
                    "file_path": {"type": ["string", "null"]},
                    "distribution": {"type": ["string", "null"]},
                    "version": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "import_checked": {"type": "boolean"},
                    "importable": {"type": ["boolean", "null"]},
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                            "required": ["code", "message"],
                        },
                    },
                },
                "required": [
                    "name",
                    "source",
                    "module",
                    "file_path",
                    "distribution",
                    "version",
                    "description",
                    "import_checked",
                    "importable",
                    "issues",
                ],
            },
        },
    },
    "required": ["scanned_paths", "entry_point_group", "plugins"],
}

ERROR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "details": {"type": "object"},
    },
    "required": ["code", "message"],
}


# ----------------------------
# Error handling
# ----------------------------


class PluginDiscoveryScannerError(Exception):
    """Deterministic, machine-readable error for plugin discovery scanning."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


# ----------------------------
# Data models
# ----------------------------


@dataclass(frozen=True)
class ScanIssue:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class PluginDiscoveryScanRequest:
    """Input contract for scanning plugin candidates.

    If `search_paths` is omitted/empty, the scanner will attempt to load a Thomas config file and
    read plugin paths from it. If no config is found, a deterministic `missing_config` error is raised.
    """

    search_paths: Sequence[str] | None = None
    config_path: str | None = None
    include_entry_points: bool = True
    entry_point_group: str = "thomas.plugins"
    import_plugins: bool = False
    recursive: bool = False


@dataclass(frozen=True)
class DiscoveredPlugin:
    name: str
    source: str  # "filesystem" | "entry_point"
    module: str | None
    file_path: str | None
    distribution: str | None
    version: str | None
    description: str | None
    import_checked: bool
    importable: bool | None
    issues: list[ScanIssue] = field(default_factory=list)

    def ok(self) -> bool:
        return len(self.issues) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "module": self.module,
            "file_path": self.file_path,
            "distribution": self.distribution,
            "version": self.version,
            "description": self.description,
            "import_checked": self.import_checked,
            "importable": self.importable,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass(frozen=True)
class PluginDiscoveryScanResult:
    scanned_paths: list[str]
    entry_point_group: str
    plugins: list[DiscoveredPlugin]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_paths": self.scanned_paths,
            "entry_point_group": self.entry_point_group,
            "plugins": [p.to_dict() for p in self.plugins],
        }


# ----------------------------
# Public API
# ----------------------------


def scan_plugins(request: PluginDiscoveryScanRequest) -> PluginDiscoveryScanResult:
    """Scan plugin candidates from filesystem paths and Python entry points."""
    search_paths, config_file = _resolve_search_paths(request)

    scanned_paths: list[str] = [str(Path(p).resolve()) for p in search_paths]
    plugins: list[DiscoveredPlugin] = []

    # Filesystem scan
    for base in search_paths:
        plugins.extend(
            _scan_filesystem(
                base_dir=Path(base),
                recursive=request.recursive,
                import_plugins=request.import_plugins,
            )
        )

    # Entry points scan
    if request.include_entry_points:
        plugins.extend(_scan_entry_points(group=request.entry_point_group, import_plugins=request.import_plugins))

    # Deterministic ordering for automation + tests
    plugins_sorted = sorted(plugins, key=lambda p: (p.name.lower(), p.source, p.module or "", p.file_path or ""))

    return PluginDiscoveryScanResult(
        scanned_paths=scanned_paths,
        entry_point_group=request.entry_point_group,
        plugins=plugins_sorted,
    )


def run(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convenience entry point for Gateway/API style calls.

    Returns a JSON-serializable dict matching RESULT_JSON_SCHEMA.
    Raises PluginDiscoveryScannerError for deterministic failures.
    """
    req = _parse_request_payload(request_payload)
    return scan_plugins(req).to_dict()


def run_json(request_payload: Mapping[str, Any]) -> str:
    """Same as `run`, but returns a JSON string."""
    return json.dumps(run(request_payload), indent=2, sort_keys=True)


# A simple plugin descriptor for environments that use duck-typed plugins.
PLUGIN: dict[str, Any] = {
    "id": "p100.plugin_discovery_scanner",
    "name": "Plugin discovery scanner",
    "description": "Scans the filesystem and Python entry points to discover Thomas plugin candidates.",
    "request_schema": REQUEST_JSON_SCHEMA,
    "result_schema": RESULT_JSON_SCHEMA,
    "error_schema": ERROR_JSON_SCHEMA,
    "run": run,
}


# ----------------------------
# Internals
# ----------------------------


def _parse_request_payload(payload: Mapping[str, Any]) -> PluginDiscoveryScanRequest:
    if not isinstance(payload, Mapping):
        raise PluginDiscoveryScannerError("invalid_request", "Request payload must be an object.")

    search_paths = payload.get("search_paths")
    if search_paths is None:
        parsed_paths: Sequence[str] | None = None
    else:
        if not isinstance(search_paths, list) or not all(isinstance(p, str) for p in search_paths):
            raise PluginDiscoveryScannerError(
                "invalid_request",
                "search_paths must be a list of strings.",
                details={"search_paths_type": type(search_paths).__name__},
            )
        parsed_paths = search_paths

    config_path = payload.get("config_path")
    if config_path is not None and not isinstance(config_path, str):
        raise PluginDiscoveryScannerError("invalid_request", "config_path must be a string or null.")

    include_entry_points = bool(payload.get("include_entry_points", True))
    entry_point_group = payload.get("entry_point_group", "thomas.plugins")
    if not isinstance(entry_point_group, str) or not entry_point_group.strip():
        raise PluginDiscoveryScannerError("invalid_request", "entry_point_group must be a non-empty string.")

    import_plugins = bool(payload.get("import_plugins", False))
    recursive = bool(payload.get("recursive", False))

    return PluginDiscoveryScanRequest(
        search_paths=parsed_paths,
        config_path=config_path,
        include_entry_points=include_entry_points,
        entry_point_group=entry_point_group.strip(),
        import_plugins=import_plugins,
        recursive=recursive,
    )


def _resolve_search_paths(request: PluginDiscoveryScanRequest) -> tuple[list[str], Path | None]:
    """Resolve search paths from explicit request or from config.

    Returns (paths, config_file_used).
    """
    config_file: Path | None = None

    # Explicit paths win.
    if request.search_paths:
        raw_paths = list(request.search_paths)
    else:
        config, config_file = _load_config(request.config_path)
        raw_paths = _extract_plugin_paths(config)

        if not raw_paths:
            origin = str(config_file) if config_file is not None else "<not found>"
            raise PluginDiscoveryScannerError(
                "missing_config",
                "No plugin search paths provided and none could be found in config.",
                details={"config_origin": origin},
            )

    base_for_rel = config_file.parent if config_file is not None else Path.cwd()

    normalized: list[str] = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw.strip():
            raise PluginDiscoveryScannerError("invalid_request", "Plugin search paths must be non-empty strings.")

        expanded = os.path.expandvars(raw.strip())
        p = Path(expanded).expanduser()
        if not p.is_absolute():
            p = (base_for_rel / p).resolve()

        if not p.exists():
            raise PluginDiscoveryScannerError(
                "path_not_found",
                f"Plugin search path does not exist: {raw}",
                details={"path": raw, "resolved": str(p)},
            )
        if not p.is_dir():
            raise PluginDiscoveryScannerError(
                "path_not_directory",
                f"Plugin search path is not a directory: {raw}",
                details={"path": raw, "resolved": str(p)},
            )
        normalized.append(str(p))

    return normalized, config_file


def _load_config(config_path: str | None) -> tuple[Mapping[str, Any], Path | None]:
    """Load config from explicit path or auto-discovery.

    Auto-discovery order:
      1) env THOMAS_CONFIG / THOMAS_CONFIG_PATH
      2) walk up from CWD for thomas.toml, thomas.json, pyproject.toml
    """
    if config_path:
        p = Path(os.path.expandvars(config_path)).expanduser()
        if not p.exists():
            raise PluginDiscoveryScannerError(
                "missing_config",
                "Config file not found.",
                details={"config_path": str(p)},
            )
        return _read_config_file(p), p

    env_path = os.environ.get("THOMAS_CONFIG") or os.environ.get("THOMAS_CONFIG_PATH")
    if env_path:
        p = Path(os.path.expandvars(env_path)).expanduser()
        if p.exists() and p.is_file():
            return _read_config_file(p), p

    found = _auto_find_config(Path.cwd())
    if not found:
        return {}, None
    return _read_config_file(found), found


def _auto_find_config(start: Path) -> Path | None:
    candidates = ("thomas.toml", "thomas.json", "pyproject.toml")
    cur = start.resolve()
    while True:
        for name in candidates:
            p = cur / name
            if p.exists() and p.is_file():
                return p
        if cur.parent == cur:
            return None
        cur = cur.parent


def _read_config_file(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as e:  # pragma: no cover
        raise PluginDiscoveryScannerError(
            "invalid_config",
            "Unable to read config file.",
            details={"config_path": str(path), "error": str(e)},
        ) from e

    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(raw.decode("utf-8"))
        if suffix == ".toml" or path.name == "pyproject.toml":
            if tomllib is None:  # pragma: no cover
                raise PluginDiscoveryScannerError("invalid_config", "TOML parsing is not available in this runtime.")
            return tomllib.loads(raw.decode("utf-8"))
    except PluginDiscoveryScannerError:
        raise
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        raise PluginDiscoveryScannerError(
            "invalid_config",
            "Failed to parse config file.",
            details={"config_path": str(path), "error": str(e)},
        ) from e

    raise PluginDiscoveryScannerError(
        "invalid_config",
        "Unsupported config format. Supported: .toml, .json, pyproject.toml",
        details={"config_path": str(path)},
    )


def _extract_plugin_paths(config: Mapping[str, Any]) -> list[str]:
    """Best-effort extraction of plugin paths from a config blob.

    Supports multiple key shapes to remain stable across config refactors.
    """
    if not config:
        return []

    # If this is a pyproject.toml, Thomas config might live under [tool.thomas]
    tool = config.get("tool") if isinstance(config, Mapping) else None
    if isinstance(tool, Mapping):
        thomas_cfg = tool.get("thomas")
        if isinstance(thomas_cfg, Mapping):
            config = thomas_cfg

    # Common patterns: plugins.paths / plugins.search_paths / plugins.dirs
    plugins = config.get("plugins") if isinstance(config, Mapping) else None
    if isinstance(plugins, Mapping):
        for key in ("paths", "search_paths", "directories", "dirs"):
            val = plugins.get(key)
            if isinstance(val, list) and all(isinstance(p, str) for p in val):
                return list(val)

    # Sometimes nested under autonomy/plugins or tools/plugins
    for top in ("autonomy", "tools"):
        maybe = config.get(top)
        if isinstance(maybe, Mapping):
            sub = maybe.get("plugins")
            if isinstance(sub, Mapping):
                for key in ("paths", "search_paths", "directories", "dirs"):
                    val = sub.get(key)
                    if isinstance(val, list) and all(isinstance(p, str) for p in val):
                        return list(val)

    # Alternate flattened keys
    for key in (
        "plugin_paths",
        "plugins_paths",
        "plugin_dirs",
        "plugins_dirs",
        "plugin_search_paths",
        "plugins_search_paths",
    ):
        val = config.get(key)
        if isinstance(val, list) and all(isinstance(p, str) for p in val):
            return list(val)

    return []


def _scan_filesystem(*, base_dir: Path, recursive: bool, import_plugins: bool) -> list[DiscoveredPlugin]:
    plugins: list[DiscoveredPlugin] = []
    if not base_dir.exists() or not base_dir.is_dir():
        return plugins

    for candidate in _iter_plugin_candidates(base_dir, recursive=recursive):
        plugins.append(
            _inspect_filesystem_candidate(base_dir=base_dir, candidate=candidate, import_plugins=import_plugins)
        )

    return plugins


def _iter_plugin_candidates(base_dir: Path, *, recursive: bool) -> Iterable[Path]:
    if recursive:
        for root, dirnames, filenames in os.walk(base_dir):
            root_path = Path(root)

            # Skip hidden/dunder/pycache dirs
            dirnames[:] = [
                d for d in dirnames if not d.startswith(".") and not d.startswith("__") and d != "__pycache__"
            ]

            # Yield package directories as candidates (excluding the base dir itself)
            for d in list(dirnames):
                pkg = root_path / d
                if pkg.is_dir() and (pkg / "__init__.py").exists():
                    yield pkg

            # Yield .py module files
            for filename in filenames:
                if filename.startswith(".") or filename.startswith("__"):
                    continue
                if filename == "__init__.py":
                    continue
                p = root_path / filename
                if p.is_file() and p.suffix == ".py":
                    yield p
    else:
        for p in base_dir.iterdir():
            if p.name.startswith(".") or p.name.startswith("__") or p.name == "__pycache__":
                continue
            if p.is_file() and p.suffix == ".py" and p.name != "__init__.py":
                yield p
            elif p.is_dir() and (p / "__init__.py").exists():
                yield p  # treat as package candidate


def _inspect_filesystem_candidate(*, base_dir: Path, candidate: Path, import_plugins: bool) -> DiscoveredPlugin:
    issues: list[ScanIssue] = []
    description: str | None = None
    version: str | None = None

    if candidate.is_dir():
        init_file = candidate / "__init__.py"
        source_path = init_file
        file_path = str(init_file)
        module_name = _module_name_for(base_dir=base_dir, candidate=candidate, is_package=True)
        default_name = candidate.name
    else:
        source_path = candidate
        file_path = str(candidate)
        module_name = _module_name_for(base_dir=base_dir, candidate=candidate, is_package=False)
        default_name = candidate.stem

    ast_meta = _extract_ast_metadata(source_path)
    name = ast_meta.get("name") or default_name
    version = ast_meta.get("version")
    description = ast_meta.get("description")

    # Syntax check without executing
    try:
        source_text = _read_python_text(source_path)
        compile(source_text, filename=str(source_path), mode="exec")
    except SyntaxError as e:
        issues.append(ScanIssue(code="syntax_error", message=f"{e.msg} (line {e.lineno})"))
        return DiscoveredPlugin(
            name=name,
            source="filesystem",
            module=module_name,
            file_path=file_path,
            distribution=None,
            version=version,
            description=description,
            import_checked=False,
            importable=None,
            issues=issues,
        )
    except (OSError, UnicodeDecodeError) as e:
        issues.append(ScanIssue(code="read_error", message=str(e)))
        return DiscoveredPlugin(
            name=name,
            source="filesystem",
            module=module_name,
            file_path=file_path,
            distribution=None,
            version=version,
            description=description,
            import_checked=False,
            importable=None,
            issues=issues,
        )

    if not import_plugins:
        return DiscoveredPlugin(
            name=name,
            source="filesystem",
            module=module_name,
            file_path=file_path,
            distribution=None,
            version=version,
            description=description,
            import_checked=False,
            importable=None,
            issues=issues,
        )

    # Import check (executes module code). Use a synthetic package name to improve relative imports.
    importable: bool | None = None
    unique_name = f"_thomas_plugin_scan_{_stable_hash(file_path)}"

    try:
        if candidate.is_dir():
            spec = importlib.util.spec_from_file_location(
                unique_name,
                str(source_path),
                submodule_search_locations=[str(candidate)],
            )
        else:
            spec = importlib.util.spec_from_file_location(unique_name, str(source_path))

        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to create import spec.")

        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        importable = True

        # Prefer runtime metadata if present
        runtime_name = getattr(module, "PLUGIN_NAME", None)
        if isinstance(runtime_name, str) and runtime_name.strip():
            name = runtime_name.strip()
        else:
            runtime_plugin = getattr(module, "PLUGIN", None)
            if isinstance(runtime_plugin, Mapping):
                v = runtime_plugin.get("name")
                if isinstance(v, str) and v.strip():
                    name = v.strip()

        runtime_version = getattr(module, "PLUGIN_VERSION", None) or getattr(module, "__version__", None)
        if isinstance(runtime_version, str) and runtime_version.strip():
            version = runtime_version.strip()
        else:
            runtime_plugin = getattr(module, "PLUGIN", None)
            if isinstance(runtime_plugin, Mapping):
                v = runtime_plugin.get("version")
                if isinstance(v, str) and v.strip():
                    version = v.strip()

        runtime_desc = getattr(module, "PLUGIN_DESCRIPTION", None)
        if isinstance(runtime_desc, str) and runtime_desc.strip():
            description = runtime_desc.strip()
        else:
            runtime_plugin = getattr(module, "PLUGIN", None)
            if isinstance(runtime_plugin, Mapping):
                v = runtime_plugin.get("description")
                if isinstance(v, str) and v.strip():
                    description = v.strip()

        if not description:
            doc = getattr(module, "__doc__", None)
            if isinstance(doc, str) and doc.strip():
                description = doc.strip().splitlines()[0].strip()

    except (
        ImportError,
        ModuleNotFoundError,
        RuntimeError,
        AttributeError,
        OSError,
    ) as e:  # REVIEWED: broad catch — import check
        importable = False
        issues.append(ScanIssue(code="import_error", message=str(e)))
    finally:
        _cleanup_import(unique_name)

    return DiscoveredPlugin(
        name=name,
        source="filesystem",
        module=module_name,
        file_path=file_path,
        distribution=None,
        version=version,
        description=description,
        import_checked=True,
        importable=importable,
        issues=issues,
    )


def _cleanup_import(unique_name: str) -> None:
    # Remove the module and any submodules imported under the synthetic namespace.
    for key in list(sys.modules.keys()):
        if key == unique_name or key.startswith(unique_name + "."):
            sys.modules.pop(key, None)


def _read_python_text(path: Path) -> str:
    # tokenize.open honors PEP-263 encoding declarations.
    with tokenize.open(str(path)) as f:
        return f.read()


def _module_name_for(*, base_dir: Path, candidate: Path, is_package: bool) -> str | None:
    try:
        rel = candidate.relative_to(base_dir)
    except ValueError:
        return None

    parts = list(rel.parts)
    if not parts:
        return None
    if not is_package:
        # Remove suffix
        if parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _extract_ast_metadata(path: Path) -> dict[str, str]:
    """Extract simple string metadata without importing/executing the module.

    Supports:
      - PLUGIN_NAME / PLUGIN_VERSION / PLUGIN_DESCRIPTION / __version__
      - PLUGIN = {\"name\": ..., \"version\": ..., \"description\": ...}  (literal dict)
      - module docstring (first line) as description fallback
    """
    try:
        source_text = _read_python_text(path)
        tree = ast.parse(source_text, filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError):  # REVIEWED: broad catch — fallback to empty
        return {}

    out: dict[str, str] = {}

    doc = ast.get_docstring(tree)
    if isinstance(doc, str) and doc.strip():
        out["doc"] = doc.strip().splitlines()[0].strip()

    for node in tree.body:
        if isinstance(node, ast.Assign):
            # Support: NAME = "..."
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                key = target.id

                if key in ("PLUGIN_NAME", "PLUGIN_VERSION", "PLUGIN_DESCRIPTION", "__version__"):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        out[key] = node.value.value.strip()

                if key == "PLUGIN" and isinstance(node.value, ast.Dict):
                    plugin_meta = _extract_literal_dict_strings(node.value)
                    for k_src, k_dst in (("name", "name"), ("version", "version"), ("description", "description")):
                        v = plugin_meta.get(k_src)
                        if isinstance(v, str) and v.strip():
                            out[f"PLUGIN.{k_dst}"] = v.strip()

    name = out.get("PLUGIN_NAME") or out.get("PLUGIN.name") or out.get("PLUGIN.name")
    version = out.get("PLUGIN_VERSION") or out.get("__version__") or out.get("PLUGIN.version")
    description = out.get("PLUGIN_DESCRIPTION") or out.get("PLUGIN.description") or out.get("doc")

    meta: dict[str, str] = {}
    if name:
        meta["name"] = name
    if version:
        meta["version"] = version
    if description:
        meta["description"] = description
    return meta


def _extract_literal_dict_strings(node: ast.Dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in zip(node.keys, node.values):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue
        if not (isinstance(v, ast.Constant) and isinstance(v.value, str)):
            continue
        out[str(k.value)] = str(v.value)
    return out


def _scan_entry_points(*, group: str, import_plugins: bool) -> list[DiscoveredPlugin]:
    plugins: list[DiscoveredPlugin] = []

    try:
        eps = importlib.metadata.entry_points()
        selected = _select_entry_points(eps, group=group)
    except (ImportError, RuntimeError, AttributeError) as e:  # REVIEWED: broad catch — entry point discovery
        # Deterministic, but non-fatal: surface as a single pseudo entry in results.
        return [
            DiscoveredPlugin(
                name=f"<entry_points:{group}>",
                source="entry_point",
                module=None,
                file_path=None,
                distribution=None,
                version=None,
                description=None,
                import_checked=False,
                importable=None,
                issues=[ScanIssue(code="entry_points_error", message=str(e))],
            )
        ]

    for ep in selected:
        issues: list[ScanIssue] = []
        dist_name: str | None = None
        dist_version: str | None = None
        dist_desc: str | None = None

        try:
            dist = getattr(ep, "dist", None)
            if dist is not None:
                dist_name = getattr(dist, "name", None)
                dist_version = getattr(dist, "version", None)
                md = getattr(dist, "metadata", None)
                if md is not None:
                    dist_desc = md.get("Summary") or md.get("Name")
        except (AttributeError, KeyError, TypeError):  # REVIEWED: broad catch — optional metadata extraction
            pass

        importable: bool | None = None
        import_checked = False

        if import_plugins:
            import_checked = True
            try:
                ep.load()
                importable = True
            except (
                ImportError,
                ModuleNotFoundError,
                RuntimeError,
                AttributeError,
            ) as e:  # REVIEWED: broad catch — entry point loading
                importable = False
                issues.append(ScanIssue(code="import_error", message=str(e)))

        plugins.append(
            DiscoveredPlugin(
                name=ep.name,
                source="entry_point",
                module=getattr(ep, "value", None),
                file_path=None,
                distribution=dist_name,
                version=dist_version,
                description=dist_desc,
                import_checked=import_checked,
                importable=importable,
                issues=issues,
            )
        )

    return plugins


def _select_entry_points(entry_points_obj: Any, *, group: str) -> list[Any]:
    # Python 3.11: EntryPoints has .select
    if hasattr(entry_points_obj, "select"):
        return list(entry_points_obj.select(group=group))

    # Python 3.10: could be dict-like
    if isinstance(entry_points_obj, Mapping):
        val = entry_points_obj.get(group, [])
        return list(val) if isinstance(val, (list, tuple)) else []

    # Fallback: iterable of entry points with .group attribute
    selected: list[Any] = []
    try:
        for ep in entry_points_obj:
            if getattr(ep, "group", None) == group:
                selected.append(ep)
    except (TypeError, AttributeError):  # REVIEWED: broad catch — iteration fallback
        return []
    return selected


def _stable_hash(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]
