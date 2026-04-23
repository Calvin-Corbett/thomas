from __future__ import annotations

from pathlib import Path


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
    assert "competitor" not in text.lower()
    assert "workboard" not in text.lower()


def test_github_publish_safety_targets_main_without_release_lanes() -> None:
    text = Path(".github/workflows/github-publish-safety.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in text
    assert "github_publish_preflight.py --deep --json --strict" in text
    assert "check_release_hygiene.py" in text
    assert "check_release_lane_policy.py" not in text
    assert "prod branch only" not in text
