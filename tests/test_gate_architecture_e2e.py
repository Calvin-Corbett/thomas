"""Contract tests for the gate-architecture-2026-05-26 artifacts.

These tests validate that the architecture's *artifacts* exist and are
wired correctly. They cannot validate the actual end-to-end "agent runs
`git commit --no-verify` and push gets rejected" scenario — that requires
pushing to GitHub and observing branch protection's response. The
artifacts checked here are what makes that scenario work:

- .github/workflows/gates.yml has all required jobs
- gates-required aggregator depends on every per-gate job
- signed-commits-check exists for PR signature verification
- .github/CODEOWNERS routes safety-critical paths to the product owner
- docs/SAFETY_ARCHITECTURE.md exists and references companion docs
- docs/SIGNING_KEY_SETUP.md and BRANCH_PROTECTION_SETUP.md exist
- agent_safety.toml [protected] list is unchanged (regression guard)

If these pass, the LOCAL artifacts that enable server-side enforcement
are in place. The the product owner-side verification (per BRANCH_PROTECTION_SETUP.md)
is the other half — see docs/SAFETY_ARCHITECTURE.md § Verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

GATES_YAML = REPO_ROOT / ".github" / "workflows" / "gates.yml"
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"
SAFETY_DOC = REPO_ROOT / "docs" / "SAFETY_ARCHITECTURE.md"
SIGNING_DOC = REPO_ROOT / "docs" / "SIGNING_KEY_SETUP.md"
BRANCH_DOC = REPO_ROOT / "docs" / "BRANCH_PROTECTION_SETUP.md"


# ---------------------------------------------------------------------------
# Artifact existence
# ---------------------------------------------------------------------------


def test_gates_workflow_exists() -> None:
    assert GATES_YAML.is_file(), f"missing: {GATES_YAML}"


def test_codeowners_exists() -> None:
    assert CODEOWNERS.is_file(), f"missing: {CODEOWNERS}"


def test_safety_architecture_doc_exists() -> None:
    assert SAFETY_DOC.is_file(), f"missing: {SAFETY_DOC}"


def test_signing_key_doc_exists() -> None:
    assert SIGNING_DOC.is_file(), f"missing: {SIGNING_DOC}"


def test_branch_protection_doc_exists() -> None:
    assert BRANCH_DOC.is_file(), f"missing: {BRANCH_DOC}"


# ---------------------------------------------------------------------------
# gates.yml structure
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gates_yaml() -> dict:
    return yaml.safe_load(GATES_YAML.read_text(encoding="utf-8"))


def test_gates_yaml_parses(gates_yaml: dict) -> None:
    assert isinstance(gates_yaml, dict)
    assert "jobs" in gates_yaml


def test_gates_yaml_triggers_on_dev_and_main(gates_yaml: dict) -> None:
    """Workflow must trigger on PRs and pushes to dev/main."""
    # PyYAML normalizes the bare `on:` key to True (Python boolean).
    on = gates_yaml.get("on") or gates_yaml.get(True)
    assert on is not None, "workflow has no `on:` trigger"

    pr = on.get("pull_request", {})
    assert "dev" in pr.get("branches", []), "PR trigger must include dev"
    assert "main" in pr.get("branches", []), "PR trigger must include main"

    push = on.get("push", {})
    assert "dev" in push.get("branches", []), "push trigger must include dev"
    assert "main" in push.get("branches", []), "push trigger must include main"


REQUIRED_GATE_JOBS = {
    "protected-files-gate",
    "protected-deletions-gate",
    "bulk-commit-guard",
    "commit-growth-guard",
    "public-repo-leak-guard",
    "monolith-guard",
    "monolith-filename-guard",
    "duplicate-filename-gate",
    "circular-imports-gate",
    "exception-handler-gate",
    "workboard-claims-gate",
    "workboard-task-problems-gate",
    "workboard-changed-files-gate",
    "changelog-gate",
    "plan-structure-gate",
    "repo-hygiene-gate",
    "repo-identity-gate",
    "xfail-growth-gate",
}


def test_gates_yaml_has_required_per_gate_jobs(gates_yaml: dict) -> None:
    """Every gate listed as required-for-safety must have its own job."""
    jobs = set(gates_yaml["jobs"].keys())
    missing = REQUIRED_GATE_JOBS - jobs
    assert not missing, f"gates.yml missing required jobs: {sorted(missing)}"


def test_gates_yaml_has_aggregator(gates_yaml: dict) -> None:
    """The gates-required aggregator must exist; this is what the product owner marks
    as a required status check in branch protection."""
    assert "gates-required" in gates_yaml["jobs"], (
        "gates-required aggregator missing — branch protection has no "
        "single-name target. Add a job named 'gates-required' that depends "
        "on every per-gate job."
    )


def test_gates_required_depends_on_every_per_gate_job(gates_yaml: dict) -> None:
    """The aggregator must list every per-gate job in its `needs:`. If a
    new gate is added without updating `needs:`, the aggregator could pass
    while that gate fails — silently weakening enforcement."""
    aggregator = gates_yaml["jobs"]["gates-required"]
    needs = aggregator.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    needs_set = set(needs)
    missing = REQUIRED_GATE_JOBS - needs_set
    assert not missing, (
        f"gates-required aggregator doesn't depend on: {sorted(missing)}. Add these to its `needs:` list."
    )


def test_signed_commits_check_exists(gates_yaml: dict) -> None:
    """A separate job verifies all PR commits are signed. This catches
    the `--no-verify` scenario when signing isn't locally configured."""
    assert "signed-commits-check" in gates_yaml["jobs"], (
        "signed-commits-check job missing — `--no-verify` commits with "
        "no signing configured would slip past undetected."
    )


# ---------------------------------------------------------------------------
# CODEOWNERS routing
# ---------------------------------------------------------------------------


SAFETY_CRITICAL_PATHS_THAT_MUST_REQUIRE_OWNER = (
    "/agent_safety.toml",
    "/.pre-commit-config.yaml",
    "/scripts/forge/gates/",
    "/scripts/active_folders.py",
    "/scripts/breakglass_auth.py",
    "/scripts/commit_breakglass_guard.py",
    "/scripts/install_commit_breakglass_hooks.py",
    "/thomas/core/agent_presence.py",
    "/thomas/tools/native_auth.py",
    "/thomas/tools/windows_auth.py",
    "/thomas/tools/filesystem.py",
    "/.github/workflows/gates.yml",
    "/.github/CODEOWNERS",
    "/docs/SAFETY_ARCHITECTURE.md",
)


@pytest.fixture(scope="module")
def codeowners_content() -> str:
    return CODEOWNERS.read_text(encoding="utf-8")


def test_codeowners_lists_owner(codeowners_content: str) -> None:
    assert "@Calvin-Corbett" in codeowners_content, "CODEOWNERS must route reviews to @Calvin-Corbett at minimum"


@pytest.mark.parametrize("path", SAFETY_CRITICAL_PATHS_THAT_MUST_REQUIRE_OWNER)
def test_codeowners_routes_safety_critical_path(codeowners_content: str, path: str) -> None:
    """Each safety-critical path must appear in CODEOWNERS with an owner.
    Otherwise PRs touching that path can merge without review."""
    # The path appears at the start of a non-comment line, followed by spaces
    # and the @owner mention.
    lines = [
        line.strip() for line in codeowners_content.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    assert any(line.startswith(path) for line in lines), (
        f"CODEOWNERS missing entry for {path!r}. Add a line like:\n  {path}  @Calvin-Corbett"
    )


# ---------------------------------------------------------------------------
# Doc cross-references
# ---------------------------------------------------------------------------


def test_safety_doc_references_companion_runbooks() -> None:
    """SAFETY_ARCHITECTURE.md must link to the the product owner-runbooks so future
    readers can find them."""
    content = SAFETY_DOC.read_text(encoding="utf-8")
    assert "SIGNING_KEY_SETUP.md" in content, "SAFETY doc must reference SIGNING_KEY_SETUP"
    assert "BRANCH_PROTECTION_SETUP.md" in content, "SAFETY doc must reference BRANCH_PROTECTION_SETUP"


def test_signing_doc_references_branch_protection() -> None:
    content = SIGNING_DOC.read_text(encoding="utf-8")
    assert "BRANCH_PROTECTION_SETUP.md" in content


def test_branch_protection_doc_references_signing() -> None:
    content = BRANCH_DOC.read_text(encoding="utf-8")
    assert "SIGNING_KEY_SETUP.md" in content


def test_safety_doc_describes_no_verify_handling() -> None:
    """The doc must explicitly explain what happens with --no-verify under
    the new architecture, since that's the motivating scenario."""
    content = SAFETY_DOC.read_text(encoding="utf-8")
    assert "--no-verify" in content, (
        "SAFETY_ARCHITECTURE.md doesn't mention --no-verify; the doc's "
        "purpose is explaining what changed about that flag's effect."
    )


# ---------------------------------------------------------------------------
# Regression guards — make sure my work didn't weaken existing protection
# ---------------------------------------------------------------------------


def test_agent_safety_toml_still_lists_protected_runtime_dirs() -> None:
    """My filesystem.py change added an opt-in kwarg. The runtime_protection
    listings should be unchanged. Catches accidental scope shrinkage."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found, no-redef]

    cfg = tomllib.loads((REPO_ROOT / "agent_safety.toml").read_text(encoding="utf-8"))
    protected_dirs = cfg["runtime_protection"]["protected_dirs"]
    # These five must always be in the protected runtime list.
    for required in ("thomas/tools/", "thomas/agent/", "thomas/core/", "thomas/server/", "scripts/"):
        assert required in protected_dirs, (
            f"runtime_protection.protected_dirs lost {required!r}; "
            "this would let agents write to a runtime path that used to be protected"
        )


def test_protected_files_gate_still_lists_safety_config() -> None:
    """The pre-commit-level protected_files_gate (separate from runtime
    protection) must still cover agent_safety.toml and .pre-commit-config.yaml."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found, no-redef]

    cfg = tomllib.loads((REPO_ROOT / "agent_safety.toml").read_text(encoding="utf-8"))
    policy = cfg["protected"]["policy_files"]
    assert "agent_safety.toml" in policy
    assert ".pre-commit-config.yaml" in policy


def test_filesystem_module_imports_cleanly() -> None:
    """My filesystem.py edit shouldn't have broken module import."""
    import importlib

    mod = importlib.import_module("thomas.tools.filesystem")
    assert hasattr(mod, "_is_protected_runtime_path")
    sig = mod._is_protected_runtime_path.__doc__
    assert "allow_native_auth_override" in (sig or ""), (
        "_is_protected_runtime_path docstring must document the new kwarg"
    )
