"""
Plugin update planner (Thomas-native).

This module provides:
- `plan_plugin_updates(request)`: tool-style entry point
- `build_update_plan(...)`: deterministic planner core
- deterministic error types with stable codes for automation
- JSON schemas for request/response payloads

The planner never installs or mutates plugins. It only compares:
- installed plugin versions
- available versions from an in-memory mapping, a local JSON file, or a JSON URL
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple, TypedDict, Union, cast

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]


# =============================================================================
# Deterministic error model
# =============================================================================


def _resolve_base_error() -> type[Exception]:
    """
    Thomas may provide a project-wide base exception for user-facing errors.
    Try common import locations; fall back to Exception if not found.

    Keeping this lookup here prevents hard coupling to internal layouts.
    """
    candidates: list[tuple[str, str]] = [
        ("thomas.errors", "ThomasError"),
        ("thomas.errors", "UserFacingError"),
        ("thomas.exceptions", "ThomasError"),
        ("thomas.exceptions", "UserFacingError"),
        ("thomas.core.errors", "ThomasError"),
        ("thomas.core.errors", "UserFacingError"),
        ("thomas.cli.errors", "ThomasError"),
        ("thomas.cli.errors", "UserFacingError"),
    ]
    for module_name, cls_name in candidates:
        try:
            module = __import__(module_name, fromlist=[cls_name])
        except Exception:
            continue
        base = getattr(module, cls_name, None)
        if isinstance(base, type) and issubclass(base, Exception):
            return cast(type[Exception], base)
    return Exception


_ThomasBaseError = _resolve_base_error()


class PluginUpdatePlannerError(_ThomasBaseError):
    """Base error for plugin update planning."""

    code: str
    message: str
    details: Dict[str, Any]

    def __init__(self, *, code: str, message: str, details: Optional[Mapping[str, Any]] = None):
        # Some Thomas base errors may not accept message; keep it robust.
        try:
            super().__init__(message)
        except TypeError:
            try:
                super().__init__(message=message)  # type: ignore[misc]
            except TypeError:
                super().__init__()  # type: ignore[misc]

        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "details": self.details}}


class PluginUpdatePlannerInputError(PluginUpdatePlannerError):
    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(code="invalid_input", message=message, details=details)


class PluginUpdatePlannerConfigError(PluginUpdatePlannerError):
    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(code="missing_config", message=message, details=details)


class PluginUpdatePlannerExternalError(PluginUpdatePlannerError):
    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(code="external_failure", message=message, details=details)


# =============================================================================
# Input / output contracts
# =============================================================================


class InstalledPluginDict(TypedDict, total=False):
    """
    Minimal representation of an installed plugin.

    Required:
      - id: plugin identifier
      - version: installed version string (semver-ish)
    Optional:
      - pinned: bool
      - source: string

    Aliases normalized:
      - plugin_id / pluginId / name -> id
      - current_version / currentVersion -> version
    """

    id: str
    version: str
    pinned: bool
    source: str

    plugin_id: str
    pluginId: str
    name: str
    current_version: str
    currentVersion: str


class PluginUpdatePlannerRequest(TypedDict, total=False):
    """
    Planner request.

    Required:
      - installed: list or an object containing a list under installed/entries/plugins

    Provide exactly one source of available versions:
      - available: mapping {id: version | [versions] | {"versions":[...]} }
      - catalog_path: JSON file with catalog
      - catalog_url: URL to JSON catalog (GET)

    Options:
      - include_prereleases: include prerelease versions when selecting "latest"
      - timeout_s: HTTP timeout for catalog_url (seconds)
    """

    installed: Union[List[Union[InstalledPluginDict, str]], Dict[str, Any]]
    available: Dict[str, Any]
    catalog_path: str
    catalog_url: str
    include_prereleases: bool
    timeout_s: float


class PluginUpdateActionDict(TypedDict):
    id: str
    current_version: str
    latest_version: Optional[str]
    status: Literal["update", "up_to_date", "unknown"]
    bump: Literal["major", "minor", "patch", "none", "unknown"]
    risk: Literal["high", "medium", "low", "unknown"]
    recommended: bool
    reason: str
    pinned: bool
    source: Optional[str]


class PluginUpdatePlannerResponse(TypedDict):
    ok: bool
    actions: List[PluginUpdateActionDict]
    summary: Dict[str, int]


REQUEST_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["installed"],
    "properties": {
        "installed": {
            "oneOf": [
                {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "additionalProperties": True,
                                "required": ["id", "version"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "version": {"type": "string"},
                                    "pinned": {"type": "boolean"},
                                    "source": {"type": "string"},
                                },
                            },
                        ]
                    },
                },
                {"type": "object"},
            ]
        },
        "available": {"type": "object", "additionalProperties": True},
        "catalog_path": {"type": "string"},
        "catalog_url": {"type": "string"},
        "include_prereleases": {"type": "boolean", "default": False},
        "timeout_s": {"type": "number", "default": 10.0, "minimum": 0},
    },
}

RESPONSE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok", "actions", "summary"],
    "properties": {
        "ok": {"type": "boolean"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "current_version",
                    "latest_version",
                    "status",
                    "bump",
                    "risk",
                    "recommended",
                    "reason",
                    "pinned",
                    "source",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "current_version": {"type": "string"},
                    "latest_version": {"type": ["string", "null"]},
                    "status": {"type": "string"},
                    "bump": {"type": "string"},
                    "risk": {"type": "string"},
                    "recommended": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "pinned": {"type": "boolean"},
                    "source": {"type": ["string", "null"]},
                },
            },
        },
        "summary": {"type": "object", "additionalProperties": {"type": "integer"}},
    },
}


# =============================================================================
# SemVer parsing (dependency-free) + proper prerelease precedence
# =============================================================================

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)"
    r"(?:\.(?P<minor>0|[1-9]\d*))?"
    r"(?:\.(?P<patch>0|[1-9]\d*))?"
    r"(?P<prerelease>-(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?P<build>\+(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _normalize_version_string(s: str) -> str:
    """
    Normalize common prefixes so we accept lockfile-ish versions.

    Examples:
      - v1.2.3 -> 1.2.3
      - ^1.2.3 -> 1.2.3
      - ~1.2.3 -> 1.2.3
      - =1.2.3 -> 1.2.3
      - 1.2 -> 1.2.0
      - 1 -> 1.0.0
    """
    s = (s or "").strip()
    if not s:
        return s
    if s.startswith("v") and len(s) > 1 and s[1].isdigit():
        s = s[1:]
    while s and s[0] in "^~=":
        s = s[1:].lstrip()
    return s


def _split_prerelease(pr: str) -> List[str]:
    # pr includes leading '-' by our parsing; strip it for comparison.
    if pr.startswith("-"):
        pr = pr[1:]
    if not pr:
        return []
    return pr.split(".")


def _prerelease_key(pr: Optional[str]) -> Tuple[int, List[Tuple[int, Union[int, str]]]]:
    """
    Create a sortable key with SemVer rules:
      - No prerelease has higher precedence than prerelease
      - Identifiers compared in order:
          numeric < non-numeric
          numeric compared numerically
          non-numeric lexicographically
      - When equal so far, shorter set has lower precedence
    """
    if pr is None:
        return (1, [])  # stable is highest (after comparing major/minor/patch)
    parts = _split_prerelease(pr)
    key_parts: List[Tuple[int, Union[int, str]]] = []
    for p in parts:
        if p.isdigit():
            key_parts.append((0, int(p)))
        else:
            key_parts.append((1, p))
    return (0, key_parts)


@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: Optional[str] = None  # includes leading '-' if present

    @classmethod
    def parse(cls, s: str) -> "SemVer":
        raw = _normalize_version_string(s)
        m = _SEMVER_RE.match(raw or "")
        if not m:
            raise PluginUpdatePlannerInputError(
                "Invalid version string; expected semver like '1.2.3'.", details={"version": s}
            )
        major = int(m.group("major"))
        minor = int(m.group("minor") or 0)
        patch = int(m.group("patch") or 0)
        prerelease = m.group("prerelease")
        return cls(major=major, minor=minor, patch=patch, prerelease=prerelease)

    def __lt__(self, other: "SemVer") -> bool:
        a = (self.major, self.minor, self.patch)
        b = (other.major, other.minor, other.patch)
        if a != b:
            return a < b

        # Both have same core version: compare prerelease.
        # stable > prerelease
        a_pr = _prerelease_key(self.prerelease)
        b_pr = _prerelease_key(other.prerelease)
        if a_pr[0] != b_pr[0]:
            return a_pr[0] < b_pr[0]  # prerelease (0) < stable (1)

        # Both stable -> equal
        if a_pr[0] == 1:
            return False

        # Compare prerelease identifiers
        a_parts = a_pr[1]
        b_parts = b_pr[1]
        for ap, bp in zip(a_parts, b_parts):
            if ap == bp:
                continue
            # numeric vs non-numeric
            if ap[0] != bp[0]:
                return ap[0] < bp[0]
            # both numeric or both non-numeric
            return ap[1] < bp[1]  # type: ignore[operator]
        # All equal so far; shorter one has lower precedence
        return len(a_parts) < len(b_parts)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return False
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (other.major, other.minor, other.patch, other.prerelease)

    def bump_kind(self, newer: "SemVer") -> Literal["major", "minor", "patch", "none"]:
        """
        Classify bump by core version changes.
        If core versions equal but prerelease differs (e.g. 1.0.0-alpha -> 1.0.0),
        we treat it as a patch-level bump for risk/communication purposes.
        """
        if (newer.major, newer.minor, newer.patch) == (self.major, self.minor, self.patch):
            if newer.prerelease == self.prerelease:
                return "none"
            return "patch"
        if newer.major != self.major:
            return "major"
        if newer.minor != self.minor:
            return "minor"
        return "patch"


def _risk_for_bump(bump: str) -> Literal["high", "medium", "low", "unknown"]:
    return {"major": "high", "minor": "medium", "patch": "low", "none": "low"}.get(bump, "unknown")


# =============================================================================
# Core planner
# =============================================================================


@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    plugin_id: str
    version: str
    pinned: bool = False
    source: Optional[str] = None

    def semver(self) -> SemVer:
        return SemVer.parse(self.version)


@dataclass(frozen=True, slots=True)
class PluginUpdateAction:
    plugin_id: str
    current_version: str
    latest_version: Optional[str]
    status: Literal["update", "up_to_date", "unknown"]
    bump: Literal["major", "minor", "patch", "none", "unknown"]
    risk: Literal["high", "medium", "low", "unknown"]
    recommended: bool
    reason: str
    pinned: bool
    source: Optional[str]

    def to_dict(self) -> PluginUpdateActionDict:
        return {
            "id": self.plugin_id,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "status": self.status,
            "bump": self.bump,
            "risk": self.risk,
            "recommended": self.recommended,
            "reason": self.reason,
            "pinned": self.pinned,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class PluginUpdatePlan:
    actions: List[PluginUpdateAction]

    def summary(self) -> Dict[str, int]:
        total = len(self.actions)
        update = sum(1 for a in self.actions if a.status == "update")
        up_to_date = sum(1 for a in self.actions if a.status == "up_to_date")
        unknown = sum(1 for a in self.actions if a.status == "unknown")
        return {"total": total, "update": update, "up_to_date": up_to_date, "unknown": unknown}

    def to_dict(self) -> PluginUpdatePlannerResponse:
        return {"ok": True, "actions": [a.to_dict() for a in self.actions], "summary": self.summary()}


def _normalize_installed_entry(entry: Union[InstalledPluginDict, str]) -> InstalledPlugin:
    if isinstance(entry, str):
        # Support "id@version" shorthand; allow scoped packages by splitting at the last "@"
        s = entry.strip()
        at = s.rfind("@")
        if at > 0 and at < len(s) - 1:
            pid = s[:at].strip()
            ver = s[at + 1 :].strip()
            if pid and ver:
                return InstalledPlugin(plugin_id=pid, version=ver)
        raise PluginUpdatePlannerInputError(
            "Invalid installed plugin entry; expected object or 'id@version' string.", details={"value": entry}
        )

    pid = (entry.get("id") or entry.get("plugin_id") or entry.get("pluginId") or entry.get("name") or "").strip()
    ver = (entry.get("version") or entry.get("current_version") or entry.get("currentVersion") or "").strip()
    if not pid:
        raise PluginUpdatePlannerInputError("Installed plugin is missing required field 'id'.", details={"entry": entry})
    if not ver:
        raise PluginUpdatePlannerInputError(
            "Installed plugin is missing required field 'version'.", details={"entry": entry}
        )
    return InstalledPlugin(
        plugin_id=pid,
        version=ver,
        pinned=bool(entry.get("pinned", False)),
        source=cast(Optional[str], entry.get("source")),
    )


def _extract_installed_list(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("installed", "entries", "plugins"):
            if key in raw and isinstance(raw[key], list):
                return cast(List[Any], raw[key])
    return []


def _parse_catalog_json(data: Any) -> Dict[str, Any]:
    """
    Accept multiple catalog shapes and normalize into a dict:
      {id: version | [versions] | {"versions":[...]} }
    """
    if isinstance(data, dict):
        # Direct mapping
        if all(isinstance(k, str) for k in data.keys()):
            return cast(Dict[str, Any], data)

        for key in ("entries", "plugins"):
            if key in data and isinstance(data[key], list):
                return _parse_catalog_json(data[key])

    if isinstance(data, list):
        out: Dict[str, Any] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            pid = item.get("id") or item.get("plugin_id") or item.get("pluginId") or item.get("name")
            if not isinstance(pid, str) or not pid.strip():
                continue
            # Prefer explicit versions list, then single version fields.
            if "versions" in item and isinstance(item["versions"], list):
                out[pid] = item["versions"]
                continue
            ver = item.get("latest") or item.get("version") or item.get("latest_version") or item.get("latestVersion")
            if isinstance(ver, str):
                out[pid] = ver
        if out:
            return out

    raise PluginUpdatePlannerInputError(
        "Unsupported catalog JSON shape; expected mapping or list/object with entries.",
        details={"type": type(data).__name__},
    )


def _load_catalog_from_path(path: str) -> Dict[str, Any]:
    if not path:
        raise PluginUpdatePlannerConfigError("catalog_path is empty.")
    if not os.path.exists(path):
        raise PluginUpdatePlannerConfigError("Catalog file not found.", details={"catalog_path": path})
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise PluginUpdatePlannerInputError("Catalog file is not valid JSON.", details={"catalog_path": path, "error": str(e)})
    except OSError as e:
        raise PluginUpdatePlannerExternalError("Failed to read catalog file.", details={"catalog_path": path, "error": str(e)})
    return _parse_catalog_json(raw)


def _load_catalog_from_url(url: str, *, timeout_s: float) -> Dict[str, Any]:
    if requests is None:
        raise PluginUpdatePlannerExternalError("HTTP catalog fetch is unavailable (requests import failed).")
    if not url:
        raise PluginUpdatePlannerConfigError("catalog_url is empty.")
    try:
        resp = requests.get(url, timeout=timeout_s)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        raise PluginUpdatePlannerExternalError("Failed to fetch catalog from URL.", details={"catalog_url": url, "error": str(e)})
    return _parse_catalog_json(raw)


def _coerce_versions(value: Any) -> List[str]:
    """
    Normalize any "available versions" value into a list of strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, dict):
        # Accept {"versions":[...]} or {"latest":"..."} shapes.
        if "versions" in value and isinstance(value["versions"], list):
            return [v for v in value["versions"] if isinstance(v, str)]
        for key in ("latest", "version", "latest_version", "latestVersion"):
            if key in value and isinstance(value[key], str):
                return [value[key]]
    return []


def _select_latest_version(versions: Sequence[str], *, include_prereleases: bool) -> Optional[str]:
    """
    Choose the latest version according to SemVer ordering.
    If prereleases are excluded, ignore prerelease versions when selecting.
    """
    parsed: List[Tuple[SemVer, str]] = []
    for v in versions:
        try:
            sv = SemVer.parse(v)
        except PluginUpdatePlannerError:
            # Treat invalid catalog versions as input errors: deterministic.
            raise
        parsed.append((sv, v))

    if not include_prereleases:
        parsed = [t for t in parsed if t[0].prerelease is None]

    if not parsed:
        return None

    parsed.sort(key=lambda t: t[0])
    return parsed[-1][1]


def _recommendation_for(bump: str, pinned: bool) -> Tuple[bool, str]:
    if pinned:
        return False, "Update available but plugin is pinned."
    if bump == "major":
        return False, "Major update available; review changelog before upgrading."
    return True, "Update available."


def build_update_plan(
    installed: Sequence[InstalledPlugin],
    available_versions: Mapping[str, Any],
    *,
    include_prereleases: bool = False,
) -> PluginUpdatePlan:
    actions: List[PluginUpdateAction] = []

    for p in installed:
        current_sv = p.semver()

        raw_av = available_versions.get(p.plugin_id)
        versions = _coerce_versions(raw_av)
        if not versions:
            actions.append(
                PluginUpdateAction(
                    plugin_id=p.plugin_id,
                    current_version=p.version,
                    latest_version=None,
                    status="unknown",
                    bump="unknown",
                    risk="unknown",
                    recommended=False,
                    reason="No catalog entry for this plugin.",
                    pinned=p.pinned,
                    source=p.source,
                )
            )
            continue

        latest = _select_latest_version(versions, include_prereleases=include_prereleases)
        if latest is None:
            actions.append(
                PluginUpdateAction(
                    plugin_id=p.plugin_id,
                    current_version=p.version,
                    latest_version=None,
                    status="unknown",
                    bump="unknown",
                    risk="unknown",
                    recommended=False,
                    reason="Only prerelease versions are available and prereleases are excluded.",
                    pinned=p.pinned,
                    source=p.source,
                )
            )
            continue

        latest_sv = SemVer.parse(latest)

        if latest_sv < current_sv:
            actions.append(
                PluginUpdateAction(
                    plugin_id=p.plugin_id,
                    current_version=p.version,
                    latest_version=latest,
                    status="unknown",
                    bump="unknown",
                    risk="unknown",
                    recommended=False,
                    reason="Catalog version is older than installed version; refusing to plan a downgrade.",
                    pinned=p.pinned,
                    source=p.source,
                )
            )
            continue

        if latest_sv == current_sv:
            actions.append(
                PluginUpdateAction(
                    plugin_id=p.plugin_id,
                    current_version=p.version,
                    latest_version=latest,
                    status="up_to_date",
                    bump="none",
                    risk="low",
                    recommended=False,
                    reason="Already up to date.",
                    pinned=p.pinned,
                    source=p.source,
                )
            )
            continue

        bump = current_sv.bump_kind(latest_sv)
        risk = _risk_for_bump(bump)
        recommended, reason = _recommendation_for(bump, p.pinned)

        actions.append(
            PluginUpdateAction(
                plugin_id=p.plugin_id,
                current_version=p.version,
                latest_version=latest,
                status="update",
                bump=cast(Literal["major", "minor", "patch", "none"], bump),
                risk=risk,
                recommended=recommended,
                reason=reason,
                pinned=p.pinned,
                source=p.source,
            )
        )

    # Deterministic ordering:
    # 1) updates first, 2) recommended updates first, 3) by risk high->low, 4) id.
    risk_rank = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    actions.sort(
        key=lambda a: (
            0 if a.status == "update" else 1,
            0 if a.recommended else 1,
            risk_rank.get(a.risk, 9),
            a.plugin_id,
        )
    )
    return PluginUpdatePlan(actions=actions)


# =============================================================================
# Tool entry point
# =============================================================================


def plan_plugin_updates(request: PluginUpdatePlannerRequest) -> PluginUpdatePlannerResponse:
    """
    Plan plugin updates.

    Raises:
      - PluginUpdatePlannerInputError
      - PluginUpdatePlannerConfigError
      - PluginUpdatePlannerExternalError
    """
    if not isinstance(request, dict):
        raise PluginUpdatePlannerInputError("Request must be an object.", details={"type": type(request).__name__})

    installed_list = _extract_installed_list(request.get("installed"))
    if not installed_list:
        raise PluginUpdatePlannerInputError(
            "'installed' must be a non-empty list (or an object containing one).",
            details={"installed": request.get("installed")},
        )
    installed = [_normalize_installed_entry(cast(Union[InstalledPluginDict, str], e)) for e in installed_list]

    include_prereleases = bool(request.get("include_prereleases", False))

    if "available" in request:
        raw_av = request.get("available")
        if not isinstance(raw_av, dict):
            raise PluginUpdatePlannerInputError("'available' must be a mapping.", details={"available": raw_av})
        available: Dict[str, Any] = cast(Dict[str, Any], raw_av)
    elif "catalog_path" in request:
        available = _load_catalog_from_path(str(request.get("catalog_path") or ""))
    elif "catalog_url" in request:
        timeout_s = float(request.get("timeout_s", 10.0))
        available = _load_catalog_from_url(str(request.get("catalog_url") or ""), timeout_s=timeout_s)
    else:
        raise PluginUpdatePlannerConfigError(
            "Missing available versions. Provide 'available', 'catalog_path', or 'catalog_url'."
        )

    plan = build_update_plan(installed=installed, available_versions=available, include_prereleases=include_prereleases)
    return plan.to_dict()


# =============================================================================
# Plugin integration (best-effort)
# =============================================================================


def register_tools(registry: Any) -> None:
    """
    Best-effort registry integration.

    We support common registry APIs:
      - registry.register_tool(...)
      - registry.register(...)
      - registry.add_tool(...)
      - registry.add(...)
    """
    if registry is None:
        raise PluginUpdatePlannerInputError("registry is required.")

    tool_obj: Any = plan_plugin_updates
    name = "plan_plugin_updates"

    for method_name in ("register_tool", "register", "add_tool", "add"):
        method = getattr(registry, method_name, None)
        if not callable(method):
            continue

        attempts = [
            ((), {"tool": tool_obj}),
            ((tool_obj,), {}),
            ((name, tool_obj), {}),
            ((name, tool_obj), {"input_schema": REQUEST_JSON_SCHEMA, "output_schema": RESPONSE_JSON_SCHEMA}),
        ]
        for args, kwargs in attempts:
            try:
                method(*args, **kwargs)
                return
            except TypeError:
                continue
            except Exception as e:
                raise PluginUpdatePlannerExternalError(
                    "Tool registration failed.",
                    details={"registry_type": type(registry).__name__, "method": method_name, "error": str(e)},
                )

    raise PluginUpdatePlannerExternalError(
        "Failed to register tool with registry; unsupported registry interface.",
        details={"registry_type": type(registry).__name__},
    )


def register(registry: Any) -> None:
    register_tools(registry)


class PluginUpdatePlannerPlugin:
    plugin_id = "plugin_update_planner"
    name = "Plugin Update Planner"
    description = "Plan updates for installed plugins using a versions catalog."

    def register(self, registry: Any) -> None:
        register_tools(registry)

    def tools(self) -> List[Any]:
        return [plan_plugin_updates]


PLUGIN = PluginUpdatePlannerPlugin()
TOOLS = [plan_plugin_updates]
