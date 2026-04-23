"""Compatibility layer for the split dependency scanner implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dep_scanner_core import (
    DEFAULT_MIN_SEVERITY,
    DEFAULT_OSV_TTL_S,
    DepScanError,
    VulnRecord,
    _apply_policy_filters,
    _auto_detect_target,
    _counts_from_vulns,
    _dedup,
    _infer_ecosystem_from_target,
    _load_config,
    _remediation_plan,
    _resolve_target_path,
    _stable_sort,
)
from .dep_scanner_npm import _npm_scan
from .dep_scanner_python import _python_scan


def deps_scan(request: dict[str, Any] | str | Path | None = None) -> dict[str, Any]:
    """Scan a dependency manifest and return a stable report payload."""

    if request is None:
        payload: dict[str, Any] = {}
    elif isinstance(request, (str, Path)):
        payload = {"target": str(request)}
    elif isinstance(request, dict):
        payload = dict(request)
    else:
        raise DepScanError("dep_scanner request must be a dict, path, or string target")

    if "target" in payload and str(payload.get("target") or "").strip():
        target = _resolve_target_path(str(payload.get("target")))
    else:
        target = _auto_detect_target(Path.cwd())

    ecosystem = str(payload.get("ecosystem") or "").strip().lower() or _infer_ecosystem_from_target(target)
    if ecosystem not in {"python", "npm"}:
        raise DepScanError(f"Unsupported ecosystem: {ecosystem}")

    cfg = _load_config(target.parent)
    cfg.update(payload)

    if ecosystem == "python":
        vulns = _python_scan(cfg, target)
    else:
        vulns = _npm_scan(cfg, target)

    vulns = _stable_sort(_apply_policy_filters(cfg, _dedup(vulns)))
    counts = _counts_from_vulns(vulns)

    return {
        "target": str(target),
        "ecosystem": ecosystem,
        "vulnerabilities": [item.as_dict() for item in vulns],
        **counts,
        "remediation": _remediation_plan(cfg, vulns),
    }


__all__ = [
    "DEFAULT_MIN_SEVERITY",
    "DEFAULT_OSV_TTL_S",
    "DepScanError",
    "VulnRecord",
    "_apply_policy_filters",
    "_dedup",
    "deps_scan",
]
