"""Tests for the governed branch->validate->push->PR flow (CAP-009 Level 2).

All tests are hermetic: they build a throwaway git repo in a temp dir, run real
branch operations via the git binary, and use an injectable gateway so nothing
ever pushes or calls ``gh``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.tools.governed_git_pr import (
    GovernedPrFlow,
    GovernedPrResult,
    PrPayload,
    ValidationCheck,
    ValidationReport,
    default_dry_run_gateway,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A temp git repo with one commit on a ``main`` base branch."""

    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test User")
    _git(r, "checkout", "-b", "main")
    (r / "README.md").write_text("hello\n", encoding="utf-8")
    _git(r, "add", "README.md")
    _git(r, "commit", "-m", "initial commit")
    return r


def _passing_validator(_ctx) -> ValidationReport:
    return ValidationReport(
        checks=(
            ValidationCheck(name="pytest", passed=True, evidence="PYTEST_EVIDENCE_42_passed_in_1s"),
            ValidationCheck(name="ruff", passed=True, evidence="RUFF_EVIDENCE_all_checks_passed"),
        )
    )


def _failing_validator(_ctx) -> ValidationReport:
    return ValidationReport(
        checks=(
            ValidationCheck(name="pytest", passed=True, evidence="PYTEST_EVIDENCE_ok"),
            ValidationCheck(name="ruff", passed=False, evidence="RUFF_EVIDENCE_F401_unused_import"),
        )
    )


class _SpyGateway:
    """Records whether it was called (proves failing validation blocks the gateway)."""

    def __init__(self) -> None:
        self.calls: list[PrPayload] = []

    def __call__(self, payload: PrPayload):
        self.calls.append(payload)
        return default_dry_run_gateway(payload)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_refuses_to_target_a_protected_branch(repo: Path) -> None:
    spy = _SpyGateway()
    flow = GovernedPrFlow(repo, gateway=spy)

    result = flow.run(
        branch="main",  # protected -> must be refused
        base="main",
        title="do not do this",
        validator=_passing_validator,
    )

    assert isinstance(result, GovernedPrResult)
    assert result.refused is True
    assert "protected branch 'main'" in (result.refusal or "")
    assert result.pr_created is False
    assert result.pushed is False
    # Governance stopped the flow before any validation or gateway work.
    assert spy.calls == []
    assert result.validation.checks == ()


def test_failing_validation_blocks_pr_creation_and_surfaces_failure(repo: Path) -> None:
    spy = _SpyGateway()
    flow = GovernedPrFlow(repo, gateway=spy)

    result = flow.run(
        branch="feature/widget",
        base="main",
        title="Add widget",
        validator=_failing_validator,
    )

    # PR creation is refused; the gateway was never invoked.
    assert result.pr_created is False
    assert result.pushed is False
    assert spy.calls == []
    # The failure is surfaced, naming the failing check.
    assert result.refusal is not None
    assert "ruff" in result.refusal
    assert result.validation.passed is False
    # The real feature branch was still created off the base.
    assert "feature/widget" in _git(repo, "branch", "--list", "feature/widget")


def test_passing_validation_composes_body_with_evidence_for_each_check(repo: Path) -> None:
    flow = GovernedPrFlow(repo)  # default dry-run gateway

    result = flow.run(
        branch="feature/widget",
        base="main",
        title="Add widget",
        validator=_passing_validator,
        summary="This PR adds a widget.",
    )

    assert result.pr_created is True
    assert result.refused is False
    # Every check's evidence snippet is embedded in the PR body.
    assert "PYTEST_EVIDENCE_42_passed_in_1s" in result.pr_body
    assert "RUFF_EVIDENCE_all_checks_passed" in result.pr_body
    # Each check name and status appears in the structured evidence section.
    assert "pytest -- PASS" in result.pr_body
    assert "ruff -- PASS" in result.pr_body
    assert "## Validation Evidence" in result.pr_body


def test_dry_run_gateway_returns_payload_without_pushing(repo: Path) -> None:
    # No remote is configured, so a real push would fail; the dry-run must not push.
    flow = GovernedPrFlow(repo)  # default inert gateway

    result = flow.run(
        branch="feature/widget",
        base="main",
        title="Add widget",
        validator=_passing_validator,
    )

    assert result.pr_created is True
    assert result.pushed is False
    assert "[DRY-RUN]" in result.pr_url_or_dryrun
    assert "feature/widget" in result.pr_url_or_dryrun
    # Nothing was pushed: the repo has no remotes at all.
    assert _git(repo, "remote") == ""


def test_branch_base_and_commit_summary_appear_in_body(repo: Path) -> None:
    head_short = _git(repo, "rev-parse", "--short", "HEAD")
    flow = GovernedPrFlow(repo)

    result = flow.run(
        branch="feature/widget",
        base="main",
        title="Add widget",
        validator=_passing_validator,
    )

    assert "`feature/widget`" in result.pr_body
    assert "`main`" in result.pr_body
    assert head_short in result.pr_body
    assert "## Branch -> Base" in result.pr_body


def test_creating_branch_off_missing_base_is_refused(repo: Path) -> None:
    spy = _SpyGateway()
    flow = GovernedPrFlow(repo, gateway=spy)

    result = flow.run(
        branch="feature/widget",
        base="does-not-exist",
        title="Add widget",
        validator=_passing_validator,
    )

    assert result.refused is True
    assert "Branch preparation failed" in (result.refusal or "")
    assert result.pr_created is False
    assert spy.calls == []


def test_custom_protected_set_is_honored(repo: Path) -> None:
    flow = GovernedPrFlow(repo, protected_branches=frozenset({"sacred"}))

    # 'main' is no longer protected under the custom set, so this proceeds.
    ok = flow.run(
        branch="feature/ok",
        base="main",
        title="fine",
        validator=_passing_validator,
    )
    assert ok.pr_created is True

    blocked = flow.run(
        branch="sacred",
        base="main",
        title="nope",
        validator=_passing_validator,
    )
    assert blocked.refused is True
