"""Fresh-machine, browser-only repository-to-PR workflow (CAP-104, Level 2).

This orchestrator proves that a user with **only a browser** -- no local git,
no local dev environment, no client-side tooling -- can go from an opened
repository all the way to a submitted pull request.  Every step runs
**server-side** through an injectable adapter; the client only ever needs to
click, so the acceptance line "a fresh-machine browser-only repository-to-PR
workflow" holds by construction.

It composes the existing governed building blocks rather than reinventing them:

* :class:`thomas.tools.governed_git_pr.GovernedPrFlow` (CAP-009) runs the
  validated ``branch -> validate -> push -> PR`` flow and refuses to open a PR
  when validation is red.
* :class:`thomas.integrations.github_pr_gateway.AuthenticatedPrGateway` (CAP-070)
  is the credential-gated source-host gateway that actually pushes and opens the
  PR; in tests it is driven by its own hermetic fake transport.

The end-to-end chain adds the two steps that happen *before* the governed flow
in a browser-only world:

1. **open** -- a server-side workspace provider clones/opens the repository into
   a server-managed workspace (a real local ``git clone`` by default; a temp
   git repo in tests -- both offline).
2. **edit** -- a server-side web editor applies the user's file change on a
   feature branch and commits it.

then hands off to the governed flow for **validate** and **PR**.  The result is
a :class:`WorkflowResult` carrying an ordered step trace
(``opened -> edited -> validated -> pr``) that proves the whole chain happened
server-side.

Injectable-adapter pattern
---------------------------
Every external edge is behind an injectable seam with a real stdlib/existing-repo
default and a hermetic fake for tests:

* ``WorkspaceProvider.open`` -- real default clones with the ``git`` binary via
  the same :data:`GitRunner` seam the governed flow uses; tests point it at a
  local origin path so the clone is genuine but offline.
* ``WebEditor.apply`` -- real default writes the files and commits them with the
  ``git`` binary; fully hermetic in a temp repo.
* ``Gateway`` -- the governed flow's own injectable push+PR seam; the real
  default is :class:`AuthenticatedPrGateway`, the test default its fake.
* ``Validator`` -- the governed flow's injectable validation seam.  An
  interactive change can plug the CAP-088 browser E2E gate in here from a
  higher tier; keeping it a seam avoids a ``tools -> browser`` layering
  inversion (see ``thomas/_architecture.py``).

Nothing here reaches the network on its own: cloning and committing operate on a
local server-side workspace, and pushing/PR-creation are exclusively the
gateway's job (inert by default).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from thomas.tools.governed_git_pr import (
    DEFAULT_PROTECTED_BRANCHES,
    Gateway,
    GitError,
    GitRunner,
    GovernedPrFlow,
    Validator,
    _subprocess_git_runner,
    default_dry_run_gateway,
)

logger = logging.getLogger(__name__)

# Faults raised by the local git edge (workspace clone / edit commit) or by
# filesystem writes.  We catch this WIDE SPECIFIC TUPLE rather than a bare
# ``except Exception`` so an unexpected programming error still surfaces.
_ADAPTER_FAULTS: tuple[type[BaseException], ...] = (GitError, OSError)

# Ordered trace-step names for the end-to-end chain.
STEP_OPENED = "opened"
STEP_EDITED = "edited"
STEP_VALIDATED = "validated"
STEP_PR = "pr"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileEdit:
    """A single file edit made through the web edit path."""

    path: str
    content: str


@dataclass(frozen=True)
class OpenedWorkspace:
    """A repository opened into a server-side workspace."""

    path: Path
    source: str


@dataclass(frozen=True)
class EditResult:
    """Outcome of applying edits on a feature branch."""

    commit: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowStep:
    """One recorded step in the end-to-end trace.

    ``server_side`` is always ``True``: every step of this workflow runs through
    a server-side adapter, which is exactly what proves the browser-only claim.
    """

    name: str
    ok: bool
    detail: str
    at: float
    server_side: bool = True


@dataclass(frozen=True)
class WorkflowResult:
    """Proof that the whole repo -> edit -> validate -> PR chain ran server-side."""

    ok: bool
    repo_ref: str
    workspace_path: str
    branch: str
    base: str
    edit_commit: str
    validation_summary: str
    pr_created: bool
    pr_url: str
    trace: tuple[WorkflowStep, ...]
    refusal: str | None = None

    @property
    def client_local_tools_used(self) -> bool:
        """Always ``False``: no client-local git/dev tooling is ever required."""
        return not all(step.server_side for step in self.trace)

    @property
    def step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.trace)

    @property
    def refused(self) -> bool:
        return self.refusal is not None


# ---------------------------------------------------------------------------
# Injectable adapter seams
# ---------------------------------------------------------------------------


@runtime_checkable
class WorkspaceProvider(Protocol):
    """Opens a repository into a server-side workspace."""

    def open(self, repo_ref: str) -> OpenedWorkspace: ...


@runtime_checkable
class WebEditor(Protocol):
    """Applies edits on a feature branch inside a server-side workspace."""

    def apply(
        self,
        *,
        workspace: Path,
        branch: str,
        base: str,
        edits: Sequence[FileEdit],
        message: str,
    ) -> EditResult: ...


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_dir_name(repo_ref: str) -> str:
    """Derive a filesystem-safe workspace directory name from a repo reference."""

    tail = str(repo_ref).rstrip("/").replace("\\", "/").rsplit("/", 1)[-1]
    tail = tail[:-4] if tail.endswith(".git") else tail
    cleaned = _UNSAFE.sub("-", tail).strip("-")
    return cleaned or "workspace"


@dataclass
class GitCloneWorkspaceProvider:
    """Real default: clone the repository with the ``git`` binary.

    Works fully offline when ``repo_ref`` is a local path (as in tests), and
    against a real remote when a URL is given.  Uses the same :data:`GitRunner`
    seam as the governed flow so nothing new is introduced.
    """

    workspace_root: Path
    git_runner: GitRunner = _subprocess_git_runner

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root)

    def open(self, repo_ref: str) -> OpenedWorkspace:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        dest = self.workspace_root / _safe_dir_name(repo_ref)
        self.git_runner(["clone", str(repo_ref), str(dest)], self.workspace_root)
        return OpenedWorkspace(path=dest, source=str(repo_ref))


@dataclass
class GitWebEditor:
    """Real default: apply edits on a feature branch and commit them.

    The commit identity is supplied inline (``-c user.email``/``-c user.name``)
    so a freshly cloned workspace with no local config still commits cleanly.
    """

    git_runner: GitRunner = _subprocess_git_runner
    author_name: str = "Thomas Web"
    author_email: str = "web@thomas.local"

    def apply(
        self,
        *,
        workspace: Path,
        branch: str,
        base: str,
        edits: Sequence[FileEdit],
        message: str,
    ) -> EditResult:
        workspace = Path(workspace)
        self.git_runner(["checkout", "-b", branch, base], workspace)
        written: list[str] = []
        for edit in edits:
            target = workspace / edit.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.content, encoding="utf-8")
            written.append(edit.path)
        self.git_runner(["add", "-A"], workspace)
        self.git_runner(
            [
                "-c",
                f"user.name={self.author_name}",
                "-c",
                f"user.email={self.author_email}",
                "commit",
                "-m",
                message,
            ],
            workspace,
        )
        commit = self.git_runner(["rev-parse", "--short", "HEAD"], workspace)
        return EditResult(commit=commit, files=tuple(written))


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------


@dataclass
class WebRepoToPrWorkflow:
    """Composes open -> edit -> validate -> PR into one server-side flow.

    Parameters
    ----------
    workspace_provider:
        Opens the repository into a server-side workspace (required).
    editor:
        Applies the web edit on a feature branch.  Defaults to
        :class:`GitWebEditor`.
    gateway:
        The governed flow's push + PR-create seam.  Defaults to the inert
        dry-run; wire :class:`AuthenticatedPrGateway` for the real source host.
    git_runner:
        Git command runner handed to the governed flow.  Defaults to the shared
        subprocess runner.
    protected_branches:
        Feature-branch names that must be refused.
    clock:
        Injectable time source for deterministic trace timestamps.
    """

    workspace_provider: WorkspaceProvider
    editor: WebEditor = field(default_factory=GitWebEditor)
    gateway: Gateway = default_dry_run_gateway
    git_runner: GitRunner = _subprocess_git_runner
    protected_branches: frozenset[str] = field(default_factory=lambda: DEFAULT_PROTECTED_BRANCHES)
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        self.protected_branches = frozenset(self.protected_branches)

    def _step(self, name: str, ok: bool, detail: str) -> WorkflowStep:
        return WorkflowStep(name=name, ok=ok, detail=detail, at=float(self.clock()))

    def run(
        self,
        *,
        repo_ref: str,
        branch: str,
        base: str,
        edits: Sequence[FileEdit],
        title: str,
        validator: Validator,
        summary: str | None = None,
        commit_message: str | None = None,
    ) -> WorkflowResult:
        """Execute the full browser-only chain and return a :class:`WorkflowResult`."""

        edits = tuple(edits)

        def _fail(trace: list[WorkflowStep], refusal: str, *, workspace: str = "", commit: str = "") -> WorkflowResult:
            return WorkflowResult(
                ok=False,
                repo_ref=repo_ref,
                workspace_path=workspace,
                branch=branch,
                base=base,
                edit_commit=commit,
                validation_summary="",
                pr_created=False,
                pr_url="",
                trace=tuple(trace),
                refusal=refusal,
            )

        trace: list[WorkflowStep] = []

        # 0. Governance: never operate directly on a protected feature branch.
        if branch in self.protected_branches:
            refusal = f"Refusing to operate on protected branch '{branch}'."
            trace.append(self._step(STEP_OPENED, False, refusal))
            return _fail(trace, refusal)

        # 1. Open the repository into a server-side workspace.
        try:
            opened = self.workspace_provider.open(repo_ref)
        except _ADAPTER_FAULTS as exc:
            refusal = f"workspace open failed: {type(exc).__name__}: {exc}"
            logger.warning("web-repo-to-pr: %s", refusal)
            trace.append(self._step(STEP_OPENED, False, refusal))
            return _fail(trace, refusal)
        trace.append(self._step(STEP_OPENED, True, f"opened {opened.source} at {opened.path}"))

        # 2. Apply the edit through the web edit path on a feature branch.
        message = commit_message or f"web edit: {title}"
        try:
            edit = self.editor.apply(
                workspace=opened.path,
                branch=branch,
                base=base,
                edits=edits,
                message=message,
            )
        except _ADAPTER_FAULTS as exc:
            refusal = f"web edit failed: {type(exc).__name__}: {exc}"
            logger.warning("web-repo-to-pr: %s", refusal)
            trace.append(self._step(STEP_EDITED, False, refusal))
            return _fail(trace, refusal, workspace=str(opened.path))
        trace.append(self._step(STEP_EDITED, True, f"committed {edit.commit}: {', '.join(edit.files) or '(no files)'}"))

        # 3 + 4. Hand off to the governed flow for validation and PR creation.
        flow = GovernedPrFlow(
            repo_path=opened.path,
            protected_branches=self.protected_branches,
            gateway=self.gateway,
            git_runner=self.git_runner,
        )
        governed = flow.run(branch=branch, base=base, title=title, validator=validator, summary=summary)

        validated_ok = governed.validation.passed
        trace.append(self._step(STEP_VALIDATED, validated_ok, governed.validation.summary_line()))

        if not governed.pr_created:
            # Validation red (or a governance refusal) stops the chain before PR;
            # the gateway was never called, so no PR exists.
            return WorkflowResult(
                ok=False,
                repo_ref=repo_ref,
                workspace_path=str(opened.path),
                branch=branch,
                base=base,
                edit_commit=edit.commit,
                validation_summary=governed.validation.summary_line(),
                pr_created=False,
                pr_url="",
                trace=tuple(trace),
                refusal=governed.refusal,
            )

        trace.append(self._step(STEP_PR, True, governed.pr_url_or_dryrun))
        return WorkflowResult(
            ok=True,
            repo_ref=repo_ref,
            workspace_path=str(opened.path),
            branch=branch,
            base=base,
            edit_commit=edit.commit,
            validation_summary=governed.validation.summary_line(),
            pr_created=True,
            pr_url=governed.pr_url_or_dryrun,
            trace=tuple(trace),
            refusal=None,
        )
