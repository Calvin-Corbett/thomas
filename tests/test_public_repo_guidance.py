from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_agent_readiness_docs_exist_and_point_to_status_sources() -> None:
    agent = _read("docs/AGENT_START_HERE.md")
    matrix = _read("docs/FEATURE_MATRIX.md")
    repo_map = _read("docs/REPO_MAP.md")
    architecture = _read("docs/ARCHITECTURE_OVERVIEW.md")

    assert "README.md" in agent
    assert "docs/FEATURE_MATRIX.md" in agent
    assert "docs/FUNCTIONALITY_INVENTORY.md" in agent
    assert "Do not assume every module is production-ready" in agent
    assert "Stable" in matrix
    assert "Beta" in matrix
    assert "Partial" in matrix
    assert "Planned" in matrix
    assert "Infinite app" in matrix
    assert "Thomas OS" in matrix
    assert "thomas/" in repo_map
    assert "127.0.0.1:8899" in architecture


def test_readme_and_index_surface_public_guidance() -> None:
    readme = _read("README.md")
    index = _read("DOCUMENTATION_INDEX.md")

    for required in (
        "docs/AGENT_START_HERE.md",
        "docs/FEATURE_MATRIX.md",
        "docs/REPO_MAP.md",
        "docs/ROADMAP.md",
    ):
        assert required in readme
        assert required in index

    assert "ThomasSetup_0.14.60.exe" in readme
    assert "support.cmd" in readme


def test_github_templates_cover_install_and_agent_tasks() -> None:
    expected = [
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/install_failure.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/agent_task.yml",
        ".github/pull_request_template.md",
        ".github/copilot-instructions.md",
        ".github/RELEASE_TEMPLATE.md",
    ]
    for relative_path in expected:
        assert (ROOT / relative_path).is_file(), relative_path

    install_template = _read(".github/ISSUE_TEMPLATE/install_failure.yml")
    pr_template = _read(".github/pull_request_template.md")
    copilot = _read(".github/copilot-instructions.md")

    assert "support.cmd" in install_template
    assert "127.0.0.1:8899" in install_template
    assert "github_publish_preflight.py" in pr_template
    assert "docs/AGENT_START_HERE.md" in copilot


def test_roadmap_marks_future_platforms_as_planned_not_shipped() -> None:
    roadmap = _read("docs/ROADMAP.md")
    infinite = _read("docs/THOMAS_INFINITE.md")

    assert "Phase 02: Infinite App" in roadmap
    assert "Private connectivity over Tailscale" in roadmap
    assert "app-grid/home-screen" in roadmap
    assert "Phase 03: Thomas OS Concept" in roadmap
    assert "concept only" in roadmap
    assert "Thomas Infinite is a companion app" in infinite
