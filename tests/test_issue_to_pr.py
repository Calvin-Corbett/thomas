"""Tests for issue -> PR async delegation (CAP-066 Level 2).

All tests are hermetic: a throwaway git repo in a temp dir, a fake builder that
edits files in that repo, an injectable validator, and a spy/dry-run gateway so
nothing ever pushes or calls ``gh``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.tools.governed_git_pr import (
    PrPayload,
    ValidationCheck,
    ValidationReport,
    default_dry_run_gateway,
)
from thomas.tools.issue_to_pr import (
    BuildOutput,
    Issue,
    IssueIntake,
    IssuePrResult,
    WorkItem,
    delegate_issue_to_pr,
)


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


ISSUE = Issue(
    id="42",
    title="Widget crashes on empty input",
    body="Repro: pass an empty string.",
    labels=("bug", "p1"),
)


def _fake_builder(repo_path: Path, item: WorkItem) -> BuildOutput:
    """A worker that fixes the 'bug' by writing a file into the temp repo."""

    (repo_path / "fix.py").write_text(f"# fix for issue {item.issue_id}\nVALUE = 1\n", encoding="utf-8")
    return BuildOutput(
        commit_message=f"fix: address #{item.issue_id}",
        summary="Guarded the empty-input path.",
    )


def _passing_validator(_ctx) -> ValidationReport:
    return ValidationReport(
        checks=(
            ValidationCheck(name="pytest", passed=True, evidence="PYTEST_OK_3_passed"),
            ValidationCheck(name="ruff", passed=True, evidence="RUFF_OK_all_checks_passed"),
        )
    )


def _failing_validator(_ctx) -> ValidationReport:
    return ValidationReport(
        checks=(ValidationCheck(name="pytest", passed=False, evidence="PYTEST_FAIL_1_failed_assert"),)
    )


class _SpyGateway:
    def __init__(self) -> None:
        self.calls: list[PrPayload] = []

    def __call__(self, payload: PrPayload):
        self.calls.append(payload)
        return default_dry_run_gateway(payload)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def test_intake_normalizes_issue_into_work_item() -> None:
    item = IssueIntake().normalize(ISSUE)

    assert isinstance(item, WorkItem)
    assert item.issue_id == "42"
    assert item.title == "Widget crashes on empty input"
    assert item.labels == ("bug", "p1")
    # Branch is derived deterministically from the issue.
    assert item.branch == "issue/42-widget-crashes-on-empty-input"
    assert item.link_ref == "Closes #42"


def test_intake_accepts_a_plain_mapping_and_strips_hash() -> None:
    item = IssueIntake().normalize({"id": "#7", "title": "Fix the Login Flow!!!", "labels": ["auth"]})
    assert item.issue_id == "7"
    assert item.branch == "issue/7-fix-the-login-flow"
    assert item.labels == ("auth",)


def test_intake_requires_an_id() -> None:
    with pytest.raises(ValueError):
        IssueIntake().normalize({"id": "", "title": "no id"})


# ---------------------------------------------------------------------------
# Happy path: linked + validated PR
# ---------------------------------------------------------------------------


def test_passing_build_produces_linked_validated_pr(repo: Path) -> None:
    spy = _SpyGateway()

    result = delegate_issue_to_pr(
        ISSUE,
        _fake_builder,
        _passing_validator,
        spy,
        repo_path=repo,
        base="main",
    )

    assert isinstance(result, IssuePrResult)
    assert result.pr_created is True
    assert result.refused is False

    # LINKED: the issue id is provably referenced in the PR body.
    assert result.linked is True
    assert "Closes #42" in result.pr_body
    assert "issue #42" in result.pr_body

    # VALIDATED: validation passed and its evidence is embedded in the body.
    assert result.validated is True
    assert "## Validation Evidence" in result.pr_body
    assert "PYTEST_OK_3_passed" in result.pr_body
    assert "RUFF_OK_all_checks_passed" in result.pr_body

    # Branch derives from the issue and is what the gateway was asked to push.
    assert result.branch == "issue/42-widget-crashes-on-empty-input"
    assert len(spy.calls) == 1
    assert spy.calls[0].branch == "issue/42-widget-crashes-on-empty-input"
    assert "Closes #42" in spy.calls[0].body

    # The builder's work is really committed on the feature branch.
    assert (repo / "fix.py").exists()
    log = _git(repo, "log", "--oneline")
    assert "fix: address #42" in log


def test_result_shape_carries_dryrun_marker(repo: Path) -> None:
    result = delegate_issue_to_pr(
        ISSUE,
        _fake_builder,
        _passing_validator,
        repo_path=repo,  # default inert dry-run gateway
    )
    assert result.pr_created is True
    assert "[DRY-RUN]" in result.pr_url_or_dryrun
    assert "issue/42-widget-crashes-on-empty-input" in result.pr_url_or_dryrun
    # Nothing was pushed: the repo has no remotes.
    assert _git(repo, "remote") == ""


# ---------------------------------------------------------------------------
# Failing validation: NO PR, failure surfaced, issue not silently closed
# ---------------------------------------------------------------------------


def test_failing_validation_produces_no_pr_and_surfaces_failure(repo: Path) -> None:
    spy = _SpyGateway()

    result = delegate_issue_to_pr(
        ISSUE,
        _fake_builder,
        _failing_validator,
        spy,
        repo_path=repo,
    )

    # No PR produced; the gateway (push/PR-create) was never invoked.
    assert result.pr_created is False
    assert result.linked is False
    assert result.validated is False
    assert spy.calls == []
    assert result.pr_url_or_dryrun == ""

    # The failure is surfaced rather than the issue being silently closed.
    assert result.refused is True
    assert result.refusal is not None
    assert "pytest" in result.refusal

    # The builder's branch + commit still exist (work is not lost), but no PR.
    assert "issue/42-widget-crashes-on-empty-input" in _git(
        repo, "branch", "--list", "issue/42-widget-crashes-on-empty-input"
    )


# ---------------------------------------------------------------------------
# Reuse of the CAP-009 governed flow (proved via composed body / result shape)
# ---------------------------------------------------------------------------


def test_reuses_governed_flow_body_and_result_shape(repo: Path) -> None:
    # The governed flow owns the "## Branch -> Base" + "## Validation Evidence"
    # sections; their presence in our body proves we drove that flow rather than
    # re-implementing PR composition.
    result = delegate_issue_to_pr(
        ISSUE,
        _fake_builder,
        _passing_validator,
        repo_path=repo,
    )
    assert "## Branch -> Base" in result.pr_body
    assert "`issue/42-widget-crashes-on-empty-input`" in result.pr_body
    assert "`main`" in result.pr_body
    assert "pytest -- PASS" in result.pr_body
    # Head commit summary (governed flow) reflects the builder's commit.
    head_short = _git(repo, "rev-parse", "--short", "HEAD")
    assert head_short in result.pr_body


class _ProtectedBranchIntake(IssueIntake):
    """Intake that (adversarially) derives a protected branch name."""

    def normalize(self, issue) -> WorkItem:  # type: ignore[override]
        item = super().normalize(issue)
        return WorkItem(
            issue_id=item.issue_id,
            title=item.title,
            body=item.body,
            labels=item.labels,
            branch="main",  # protected -> governance must refuse
            pr_title=item.pr_title,
            link_ref=item.link_ref,
        )


def test_derived_branch_hitting_a_protected_name_is_refused(repo: Path) -> None:
    spy = _SpyGateway()

    result = delegate_issue_to_pr(
        ISSUE,
        _fake_builder,
        _passing_validator,
        spy,
        repo_path=repo,
        intake=_ProtectedBranchIntake(),
    )
    assert result.refused is True
    assert "protected branch 'main'" in (result.refusal or "")
    assert result.pr_created is False
    assert spy.calls == []
    # Governance stopped before the builder ran: no fix.py written.
    assert not (repo / "fix.py").exists()
