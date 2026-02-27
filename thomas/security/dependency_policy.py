"""Dependency policy checks for Thomas release hygiene."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


DISALLOWED_URL_MARKERS = ("git+", "http://", "https://")
VERSION_OPERATORS = ("==", ">=", "<=", "~=", ">", "<", "!=")


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return data if isinstance(data, dict) else {}


def _iter_declared_dependencies(pyproject: dict[str, Any]) -> Iterable[tuple[str, str]]:
    project = pyproject.get("project") if isinstance(pyproject.get("project"), dict) else {}

    runtime = project.get("dependencies") if isinstance(project.get("dependencies"), list) else []
    for item in runtime:
        text = str(item or "").strip()
        if text:
            yield "project.dependencies", text

    opt = project.get("optional-dependencies")
    if isinstance(opt, dict):
        for group, values in opt.items():
            if not isinstance(values, list):
                continue
            for item in values:
                text = str(item or "").strip()
                if text:
                    yield f"project.optional-dependencies.{group}", text


def _normalize_dep_text(raw: str) -> str:
    text = str(raw or "").strip()
    if ";" in text:
        text = text.split(";", 1)[0].strip()
    return text


def _has_any_version_constraint(dep_text: str) -> bool:
    return any(op in dep_text for op in VERSION_OPERATORS)


def evaluate_dependency_policy(pyproject_path: Path) -> dict[str, Any]:
    data = _read_toml(pyproject_path)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    seen: set[str] = set()
    for section, raw_dep in _iter_declared_dependencies(data):
        dep = _normalize_dep_text(raw_dep)
        if not dep:
            continue

        if dep in seen:
            continue
        seen.add(dep)

        lowered = dep.lower()
        if " @ " in dep or any(marker in lowered for marker in DISALLOWED_URL_MARKERS):
            errors.append(
                {
                    "code": "dependency.direct_url_disallowed",
                    "dependency": dep,
                    "section": section,
                    "message": "Direct URL or VCS dependency is disallowed by dependency policy.",
                    "remediation": "Use a registry-published versioned package dependency.",
                }
            )
            continue

        if "==*" in dep or dep.strip().endswith("*"):
            errors.append(
                {
                    "code": "dependency.wildcard_disallowed",
                    "dependency": dep,
                    "section": section,
                    "message": "Wildcard dependency constraints are disallowed.",
                    "remediation": "Use explicit version constraints (for example >=x.y).",
                }
            )

        if not _has_any_version_constraint(dep):
            warnings.append(
                {
                    "code": "dependency.unconstrained",
                    "dependency": dep,
                    "section": section,
                    "message": "Dependency has no explicit version constraint.",
                    "remediation": "Add an explicit version bound to improve reproducibility.",
                }
            )

    return {
        "ok": len(errors) == 0,
        "pyproject_path": str(pyproject_path),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "dependency_count": len(seen),
        },
    }
