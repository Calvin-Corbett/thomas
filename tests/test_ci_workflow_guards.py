from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


def _read_requirements(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_nightly_reliability_workflow_removed_from_public_ci() -> None:
    assert not Path(".github/workflows/nightly-reliability.yml").exists()


def test_pypi_publish_workflow_removed_from_public_ci() -> None:
    assert not Path(".github/workflows/publish.yml").exists()


def test_robustness_gates_targets_main_with_public_ci_suite() -> None:
    text = Path(".github/workflows/robustness-gates.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in text
    assert "test-collection-gate" in text
    assert "security-regression" in text
    assert "full-test-matrix" in text
    assert "quality-signals" in text
    assert "docker-smoke" in text
    assert "python -m pytest --collect-only -q" in text
    assert "python -m build" in text
    assert "python scripts/github_publish_preflight.py --json --strict" in text
    assert "python scripts/check_release_hygiene.py" in text
    assert "tests/test_ci_workflow_guards.py" in text
    assert "tests/test_github_publish_snapshot.py" in text
    assert "tests/test_github_publish_preflight.py" in text
    assert "tests/test_release_hygiene.py" in text
    assert "tests/test_release_contracts.py" in text
    assert ("com" + "petitor") not in text.lower()
    assert "workboard" not in text.lower()


def test_dockerfile_uses_server_runtime_requirements_subset() -> None:
    text = Path("Dockerfile").read_text(encoding="utf-8")
    assert "COPY requirements-server.txt ./" in text
    assert "pip install --no-cache-dir -r requirements-server.txt" in text
    assert "requirements-lock.txt" not in text
    assert '".[server]' not in text


def test_container_runtime_requirements_match_pyproject_server_runtime() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    expected = [*project["dependencies"], *project["optional-dependencies"]["server"]]
    actual = _read_requirements(Path("requirements-server.txt"))
    assert actual == expected


def test_legacy_full_requirements_lock_removed_from_public_release() -> None:
    assert not Path("requirements-lock.txt").exists()
    assert "requirements-server.txt" in Path("scripts/check_dependency_gate.py").read_text(encoding="utf-8")
    assert "requirements-lock.txt" not in Path("DEPLOYMENT.md").read_text(encoding="utf-8")


def test_github_publish_safety_targets_main_without_release_lanes() -> None:
    text = Path(".github/workflows/github-publish-safety.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in text
    assert "github_publish_preflight.py --deep --json --strict" in text
    assert "check_release_hygiene.py" in text
    assert ("check_" + "release_lane_policy.py") not in text
    assert "prod branch only" not in text


def test_public_repo_excludes_github_admin_release_lane_artifacts() -> None:
    forbidden = [
        "docs/GITHUB_BRANCH_PROTECTION_SETUP.md",
        "docs/GITHUB_PUBLISH_SAFETY_WORKFLOW.md",
        "scripts/apply_branch_protection.ps1",
        "scripts/apply_" + "release_lanes.ps1",
        "scripts/check_" + "release_lane_policy.py",
        "scripts/configure_" + "github_branch_protection.py",
        "scripts/setup_" + "github_release_lanes.py",
    ]
    for relative_path in forbidden:
        assert not Path(relative_path).exists(), relative_path
