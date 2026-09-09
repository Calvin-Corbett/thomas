"""Tests for the fresh-machine, browser-only repo-to-PR workflow (CAP-104 L2).

All tests are hermetic:

* A throwaway "origin" git repo is built in a temp dir and opened via a **real**
  ``git clone`` of that local path (genuine git, no network).
* The web edit is a **real** commit made by the default :class:`GitWebEditor`.
* Validation and PR creation go through the governed flow (CAP-009); the PR
  gateway is :class:`AuthenticatedPrGateway` (CAP-070) driven by its own
  hermetic fake transport with a fake push runner -- nothing pushes or reaches
  the network.

Together this proves a user with only a browser can go opened -> edited ->
validated -> PR entirely server-side.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.integrations.github_pr_gateway import AuthenticatedPrGateway, FakeGitHubTransport
from thomas.tools.governed_git_pr import ValidationCheck, ValidationReport
from thomas.tools.web_repo_to_pr import (
    STEP_EDITED,
    STEP_OPENED,
    STEP_PR,
    STEP_VALIDATED,
    FileEdit,
    GitCloneWorkspaceProvider,
    WebRepoToPrWorkflow,
    WorkflowResult,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A local origin repo with one commit on ``main`` -- cloned offline in tests."""

    r = tmp_path / "origin"
    r.mkdir()
    _git(r, "init")
    _git(r, "config", "user.email", "origin@example.com")
    _git(r, "config", "user.name", "Origin User")
    _git(r, "checkout", "-b", "main")
    (r / "README.md").write_text("hello\n", encoding="utf-8")
    _git(r, "add", "README.md")
    _git(r, "commit", "-m", "initial commit")
    return r


def _passing_validator(_ctx) -> ValidationReport:
    return ValidationReport(checks=(ValidationCheck(name="pytest", passed=True, evidence="PYTEST_ok"),))


def _failing_validator(_ctx) -> ValidationReport:
    return ValidationReport(checks=(ValidationCheck(name="pytest", passed=False, evidence="PYTEST_1_failed"),))


class _RecordingPush:
    """Fake push runner: records calls, never touches the network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, remote: str, branch: str, repo_path) -> None:
        self.calls.append((remote, branch))


def _gateway(push: _RecordingPush, workspace_root: Path) -> AuthenticatedPrGateway:
    transport = FakeGitHubTransport(
        routes={("POST", "/pulls"): (201, {"html_url": "https://github.com/acme/widget/pull/7"})}
    )
    return AuthenticatedPrGateway.with_token(
        "acme/widget",
        "dummy-token",
        transport=transport,
        push_runner=push,
        repo_path=workspace_root,
    )


def _make_workflow(origin: Path, tmp_path: Path, *, gateway) -> tuple[WebRepoToPrWorkflow, Path]:
    ws_root = tmp_path / "server-workspaces"
    provider = GitCloneWorkspaceProvider(workspace_root=ws_root)
    ticks = iter(range(1000, 2000))
    workflow = WebRepoToPrWorkflow(
        workspace_provider=provider,
        gateway=gateway,
        clock=lambda: float(next(ticks)),
    )
    return workflow, ws_root


# ---------------------------------------------------------------------------
# ACCEPTANCE: full opened -> edited -> validated -> PR chain, linked PR returned
# ---------------------------------------------------------------------------


def test_full_chain_end_to_end_returns_linked_pr(origin: Path, tmp_path: Path) -> None:
    push = _RecordingPush()
    workflow, ws_root = _make_workflow(origin, tmp_path, gateway=_gateway(push, tmp_path))

    result = workflow.run(
        repo_ref=str(origin),
        branch="feature/web-edit",
        base="main",
        edits=[FileEdit(path="docs/change.md", content="edited via the web\n")],
        title="Web edit from a browser-only client",
        validator=_passing_validator,
    )

    assert isinstance(result, WorkflowResult)
    # The whole chain ran end-to-end and a linked PR came back.
    assert result.ok is True
    assert result.pr_created is True
    assert result.pr_url == "https://github.com/acme/widget/pull/7"
    # Each step is recorded in the trace, in order.
    assert result.step_names == (STEP_OPENED, STEP_EDITED, STEP_VALIDATED, STEP_PR)
    assert all(step.ok for step in result.trace)
    # The edit is a real commit in a server-side workspace under the workspace root.
    assert Path(result.workspace_path).parent == ws_root
    committed = (Path(result.workspace_path) / "docs" / "change.md").read_text(encoding="utf-8")
    assert committed == "edited via the web\n"
    # The gateway pushed the feature branch (server-side) before opening the PR.
    assert push.calls == [("origin", "feature/web-edit")]


# ---------------------------------------------------------------------------
# Validation red stops before PR: no PR on red
# ---------------------------------------------------------------------------


def test_validation_failure_stops_before_pr(origin: Path, tmp_path: Path) -> None:
    push = _RecordingPush()
    gw = _gateway(push, tmp_path)
    workflow, _ = _make_workflow(origin, tmp_path, gateway=gw)

    result = workflow.run(
        repo_ref=str(origin),
        branch="feature/bad",
        base="main",
        edits=[FileEdit(path="broken.txt", content="oops\n")],
        title="A change that fails validation",
        validator=_failing_validator,
    )

    assert result.ok is False
    assert result.pr_created is False
    assert result.pr_url == ""
    # The chain stopped at validation -- there is no PR step.
    assert result.step_names == (STEP_OPENED, STEP_EDITED, STEP_VALIDATED)
    assert STEP_PR not in result.step_names
    assert result.trace[-1].name == STEP_VALIDATED and result.trace[-1].ok is False
    assert result.refusal is not None
    # The gateway was never invoked: no push, no PR request.
    assert push.calls == []
    assert gw.transport.requests == []


# ---------------------------------------------------------------------------
# No client-local git/dev tools: every step is a server-side adapter
# ---------------------------------------------------------------------------


def test_flow_needs_no_client_local_tooling(origin: Path, tmp_path: Path) -> None:
    push = _RecordingPush()
    workflow, ws_root = _make_workflow(origin, tmp_path, gateway=_gateway(push, tmp_path))

    result = workflow.run(
        repo_ref=str(origin),
        branch="feature/server-side",
        base="main",
        edits=[FileEdit(path="a.txt", content="x\n")],
        title="Server-side only",
        validator=_passing_validator,
    )

    # Nothing ran on the client: every recorded step is a server-side adapter.
    assert result.client_local_tools_used is False
    assert all(step.server_side for step in result.trace)
    # Every step operated on the server-managed workspace, never a client path.
    assert Path(result.workspace_path).is_relative_to(ws_root)


# ---------------------------------------------------------------------------
# Determinism: identical inputs -> identical observable outcome
# ---------------------------------------------------------------------------


def test_determinism_across_runs(origin: Path, tmp_path: Path) -> None:
    def _run(tag: str) -> WorkflowResult:
        sub = tmp_path / tag
        sub.mkdir()
        push = _RecordingPush()
        workflow, _ = _make_workflow(origin, sub, gateway=_gateway(push, sub))
        return workflow.run(
            repo_ref=str(origin),
            branch="feature/deterministic",
            base="main",
            edits=[FileEdit(path="det.txt", content="same content\n")],
            title="Deterministic run",
            validator=_passing_validator,
        )

    first = _run("run-a")
    second = _run("run-b")

    assert first.step_names == second.step_names
    assert [s.ok for s in first.trace] == [s.ok for s in second.trace]
    assert first.pr_url == second.pr_url
    assert first.validation_summary == second.validation_summary
    assert first.ok == second.ok is True


# ---------------------------------------------------------------------------
# Governance: a protected feature branch is refused before any work
# ---------------------------------------------------------------------------


def test_protected_branch_refused_before_opening(origin: Path, tmp_path: Path) -> None:
    push = _RecordingPush()
    gw = _gateway(push, tmp_path)
    workflow, _ = _make_workflow(origin, tmp_path, gateway=gw)

    result = workflow.run(
        repo_ref=str(origin),
        branch="main",
        base="main",
        edits=[FileEdit(path="x.txt", content="nope\n")],
        title="Directly on main",
        validator=_passing_validator,
    )

    assert result.ok is False
    assert result.pr_created is False
    assert result.refused is True
    assert result.step_names == (STEP_OPENED,)
    assert result.trace[0].ok is False
    assert push.calls == []
    assert gw.transport.requests == []


# ---------------------------------------------------------------------------
# A workspace-open failure is surfaced cleanly, before any edit/PR
# ---------------------------------------------------------------------------


def test_open_failure_surfaces_and_stops(tmp_path: Path) -> None:
    push = _RecordingPush()
    ws_root = tmp_path / "workspaces"
    provider = GitCloneWorkspaceProvider(workspace_root=ws_root)
    workflow = WebRepoToPrWorkflow(
        workspace_provider=provider,
        gateway=_gateway(push, tmp_path),
        clock=lambda: 0.0,
    )

    result = workflow.run(
        repo_ref=str(tmp_path / "does-not-exist"),
        branch="feature/x",
        base="main",
        edits=[FileEdit(path="a.txt", content="x\n")],
        title="Missing repo",
        validator=_passing_validator,
    )

    assert result.ok is False
    assert result.step_names == (STEP_OPENED,)
    assert result.trace[0].ok is False
    assert result.refusal is not None
    assert push.calls == []
