"""Dependency policy checks for Thomas release hygiene."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


DISALLOWED_URL_MARKERS = ("git+", "git://", "http://", "https://", "github:", "file:")
VERSION_OPERATORS = ("==", ">=", "<=", "~=", ">", "<", "!=")
NODE_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
NODE_WORKSPACE_RE = re.compile(r"^workspace:")

MANAGED_NODE_PROJECTS = (
    (
        "thomas/integrations/discord_bridge_service",
        "thomas/integrations/discord_bridge_service/package.json",
        "thomas/integrations/discord_bridge_service/package-lock.json",
    ),
    (
        "extensions/vault-fortress",
        "extensions/vault-fortress/package.json",
        "extensions/vault-fortress/package-lock.json",
    ),
)

SCRIPT_POLICY_TARGETS = (
    "scripts/setup.ps1",
    "scripts/repair.ps1",
    "scripts/run-ui.ps1",
    "scripts/ensure_discord_bridge_deps.ps1",
)
WORKFLOW_POLICY_GLOBS = (".github/workflows/*.yml",)

FORBIDDEN_SOURCE_PATTERNS = (
    (
        re.compile(r'Invoke-Native\s+\$npm\s+@\("install",\s*"-g",\s*"@openai/codex"\)', re.IGNORECASE),
        "dependency.workflow.unattended_global_npm_install",
        "Unattended global npm installs are disallowed.",
        "Require explicit user approval before installing global tools.",
    ),
    (
        re.compile(r"&\s+powershell[^\n]*-File\s+\$setupScript[^\n]*-AutoInstallTools\b", re.IGNORECASE),
        "dependency.workflow.unattended_tool_install",
        "Unattended tool installation flags are disallowed in setup entrypoints.",
        "Require explicit confirmation before passing tool-install flags.",
    ),
    (
        re.compile(r'@\("install",\s*"--no-audit"', re.IGNORECASE),
        "dependency.workflow.npm_install_disallowed",
        "Managed Node projects must use npm ci instead of npm install.",
        "Commit a lockfile and use npm ci for managed Node installs.",
    ),
)

RUN_UI_MUTATION_PATTERN = re.compile(r'Install-WithWinget\s+-PackageId|@\("-m",\s*"pip",\s*"install"', re.IGNORECASE)


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


def _add_issue(target: list[dict[str, str]], *, code: str, message: str, remediation: str, **extra: str) -> None:
    item = {"code": code, "message": message, "remediation": remediation}
    item.update({key: value for key, value in extra.items() if value != ""})
    target.append(item)


def _evaluate_python_policy(pyproject_path: Path, errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> int:
    data = _read_toml(pyproject_path)
    seen: set[str] = set()

    for section, raw_dep in _iter_declared_dependencies(data):
        dep = _normalize_dep_text(raw_dep)
        if not dep or dep in seen:
            continue
        seen.add(dep)

        lowered = dep.lower()
        if " @ " in dep or any(marker in lowered for marker in DISALLOWED_URL_MARKERS):
            _add_issue(
                errors,
                code="dependency.direct_url_disallowed",
                dependency=dep,
                section=section,
                message="Direct URL or VCS dependency is disallowed by dependency policy.",
                remediation="Use a registry-published versioned package dependency.",
            )
            continue

        if "==*" in dep or dep.strip().endswith("*"):
            _add_issue(
                errors,
                code="dependency.wildcard_disallowed",
                dependency=dep,
                section=section,
                message="Wildcard dependency constraints are disallowed.",
                remediation="Use explicit version constraints (for example >=x.y).",
            )

        if not _has_any_version_constraint(dep):
            _add_issue(
                warnings,
                code="dependency.unconstrained",
                dependency=dep,
                section=section,
                message="Dependency has no explicit version constraint.",
                remediation="Add an explicit version bound to improve reproducibility.",
            )

    return len(seen)


def _iter_node_dependencies(package_data: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    for section in ("dependencies", "devDependencies"):
        deps = package_data.get(section)
        if not isinstance(deps, dict):
            continue
        for name, spec in deps.items():
            dep_name = str(name or "").strip()
            dep_spec = str(spec or "").strip()
            if dep_name and dep_spec:
                yield section, dep_name, dep_spec


def _is_node_direct_url(spec: str) -> bool:
    lowered = spec.lower()
    return any(marker in lowered for marker in DISALLOWED_URL_MARKERS)


def _evaluate_node_policy(repo_root: Path, errors: list[dict[str, str]]) -> int:
    dep_count = 0
    for project_name, package_rel, lock_rel in MANAGED_NODE_PROJECTS:
        package_path = repo_root / package_rel
        lock_path = repo_root / lock_rel
        if not package_path.exists():
            continue

        if not lock_path.exists():
            _add_issue(
                errors,
                code="dependency.node.lockfile_required",
                file=str(package_path),
                project=project_name,
                message="Managed Node project is missing package-lock.json.",
                remediation="Commit a package-lock.json generated from npm ci/package-lock-only.",
            )

        try:
            package_data = json.loads(package_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _add_issue(
                errors,
                code="dependency.node.package_json_invalid",
                file=str(package_path),
                project=project_name,
                message=f"Could not parse package.json: {type(exc).__name__}: {exc}",
                remediation="Fix the package.json syntax before continuing.",
            )
            continue

        for section, dep_name, dep_spec in _iter_node_dependencies(package_data):
            dep_count += 1
            if NODE_WORKSPACE_RE.match(dep_spec):
                continue
            if _is_node_direct_url(dep_spec):
                _add_issue(
                    errors,
                    code="dependency.node.direct_url_disallowed",
                    file=str(package_path),
                    project=project_name,
                    dependency=dep_name,
                    section=section,
                    message="Direct URL, git, or file dependency is disallowed for managed Node projects.",
                    remediation="Use a registry-published exact version.",
                )
                continue
            if dep_spec == "*" or dep_spec.startswith("^") or dep_spec.startswith("~"):
                _add_issue(
                    errors,
                    code="dependency.node.range_disallowed",
                    file=str(package_path),
                    project=project_name,
                    dependency=dep_name,
                    section=section,
                    message="Managed Node dependencies must be pinned exactly.",
                    remediation="Replace floating ranges with exact versions and refresh the lockfile.",
                )
                continue
            if not NODE_EXACT_VERSION_RE.match(dep_spec):
                _add_issue(
                    errors,
                    code="dependency.node.exact_version_required",
                    file=str(package_path),
                    project=project_name,
                    dependency=dep_name,
                    section=section,
                    message="Managed Node dependencies must use exact semver versions.",
                    remediation="Pin the dependency to a concrete version like 1.2.3.",
                )

    return dep_count


def _evaluate_script_policy(repo_root: Path, errors: list[dict[str, str]]) -> int:
    inspected = 0
    for rel_path in SCRIPT_POLICY_TARGETS:
        path = repo_root / rel_path
        if not path.exists():
            continue
        inspected += 1
        text = path.read_text(encoding="utf-8")
        for pattern, code, message, remediation in FORBIDDEN_SOURCE_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                _add_issue(
                    errors,
                    code=code,
                    file=str(path),
                    line=str(line_no),
                    message=message,
                    remediation=remediation,
                )
        if rel_path == "scripts/run-ui.ps1" and RUN_UI_MUTATION_PATTERN.search(text):
            if "ConfirmedInstallChanges" not in text or "Confirm-LauncherMutation" not in text:
                _add_issue(
                    errors,
                    code="dependency.workflow.launcher_confirmation_required",
                    file=str(path),
                    message="Launcher-managed installs must require explicit confirmation.",
                    remediation="Gate run-ui mutation paths behind ConfirmedInstallChanges and Confirm-LauncherMutation.",
                )
            if "Get-ConfiguredSecurityProfileName" not in text or "Test-InstallChangesAllowed" not in text:
                _add_issue(
                    errors,
                    code="dependency.workflow.launcher_security_profile_required",
                    file=str(path),
                    message="Launcher-managed installs must honor the configured security profile.",
                    remediation="Read the configured profile and block launcher mutations when the profile is locked.",
                )
    workflow_pattern = re.compile(r"run:\s*npm\s+(install|i)\b(?!\s*ci\b)", re.IGNORECASE)
    for glob in WORKFLOW_POLICY_GLOBS:
        for path in repo_root.glob(glob):
            inspected += 1
            text = path.read_text(encoding="utf-8")
            for match in workflow_pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                _add_issue(
                    errors,
                    code="dependency.workflow.npm_install_disallowed",
                    file=str(path),
                    line=str(line_no),
                    message="Managed Node workflows must use npm ci instead of npm install.",
                    remediation="Switch workflow install steps to npm ci.",
                )
    return inspected


def evaluate_dependency_policy(pyproject_path: Path) -> dict[str, Any]:
    pyproject_path = pyproject_path.resolve()
    repo_root = pyproject_path.parent
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    python_dependency_count = _evaluate_python_policy(pyproject_path, errors, warnings)
    node_dependency_count = _evaluate_node_policy(repo_root, errors)
    inspected_script_count = _evaluate_script_policy(repo_root, errors)

    return {
        "ok": len(errors) == 0,
        "pyproject_path": str(pyproject_path),
        "repo_root": str(repo_root),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "dependency_count": python_dependency_count + node_dependency_count,
            "python_dependency_count": python_dependency_count,
            "node_dependency_count": node_dependency_count,
            "inspected_script_count": inspected_script_count,
        },
    }
