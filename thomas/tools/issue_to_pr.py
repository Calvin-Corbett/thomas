"""Issue -> PR async delegation (CAP-066, Level 2).

Turns an *issue assignment* into a linked, validated pull request by driving the
CAP-009 governed PR flow (:mod:`thomas.tools.governed_git_pr`). Nothing here
duplicates the branch/validate/PR machinery -- it composes on top of it.

The flow has four seams:

1. **Intake** -- :class:`IssueIntake` normalizes a raw issue (``id``, ``title``,
   ``body``, ``labels``) into a :class:`WorkItem` with a deterministic feature
   branch derived from the issue.
2. **Builder** -- an injectable callable that *does the work*: it edits files in
   the target repo and returns a :class:`BuildOutput` describing the commit. This
   is the asynchronous "delegate the task to a worker" seam; in tests it is a
   fake builder, never a live model.
3. **Governed PR** -- :func:`delegate_issue_to_pr` hands the branch off to
   :class:`~thomas.tools.governed_git_pr.GovernedPrFlow`, which validates and
   (only on success) composes + emits the PR through the injectable gateway.
4. **Result** -- :class:`IssuePrResult` reports whether the produced PR is
   provably *linked* to the issue (``Closes #<id>`` in the body) and *validated*
   (validation evidence embedded and passing).

A PR is produced **only** when validation passes. On failure no PR is emitted,
the issue is not silently "closed", and the validation failure is surfaced.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from thomas.tools.governed_git_pr import (
    Gateway,
    GitError,
    GitRunner,
    GovernedPrFlow,
    GovernedPrResult,
    Validator,
    _subprocess_git_runner,
    default_dry_run_gateway,
)

__all__ = [
    "Issue",
    "WorkItem",
    "IssueIntake",
    "BuildOutput",
    "Builder",
    "IssuePrResult",
    "delegate_issue_to_pr",
]

# Maximum slug length taken from the issue title for the branch name.
_MAX_SLUG_LEN = 48
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Issue + intake
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """A raw issue assignment as it arrives from a tracker."""

    id: str
    title: str
    body: str = ""
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkItem:
    """A normalized unit of work derived from an :class:`Issue`."""

    issue_id: str
    title: str
    body: str
    labels: tuple[str, ...]
    branch: str
    pr_title: str
    link_ref: str  # e.g. "Closes #42"


def _slugify(text: str) -> str:
    """Lowercase, hyphen-separated, alnum-only slug bounded to ``_MAX_SLUG_LEN``."""

    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    if len(slug) > _MAX_SLUG_LEN:
        slug = slug[:_MAX_SLUG_LEN].rstrip("-")
    return slug


class IssueIntake:
    """Normalizes raw issues into :class:`WorkItem` work units.

    Parameters
    ----------
    branch_prefix:
        Prefix for the derived feature branch (default ``"issue"``).
    """

    def __init__(self, branch_prefix: str = "issue") -> None:
        self.branch_prefix = branch_prefix.strip("/") or "issue"

    def normalize(self, issue: Issue | Mapping[str, object]) -> WorkItem:
        """Return a :class:`WorkItem` for ``issue`` (an :class:`Issue` or mapping)."""

        if isinstance(issue, Mapping):
            issue = Issue(
                id=str(issue.get("id", "")).strip(),
                title=str(issue.get("title", "")).strip(),
                body=str(issue.get("body", "") or ""),
                labels=tuple(str(x) for x in (issue.get("labels") or ())),
            )

        issue_id = issue.id.strip().lstrip("#")
        if not issue_id:
            raise ValueError("issue id is required for intake")

        title = issue.title.strip() or f"issue {issue_id}"
        slug = _slugify(title)
        branch = f"{self.branch_prefix}/{issue_id}"
        if slug:
            branch = f"{branch}-{slug}"

        return WorkItem(
            issue_id=issue_id,
            title=title,
            body=issue.body or "",
            labels=tuple(issue.labels),
            branch=branch,
            pr_title=f"Resolve #{issue_id}: {title}",
            link_ref=f"Closes #{issue_id}",
        )


# ---------------------------------------------------------------------------
# Builder seam
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildOutput:
    """What a builder reports after editing the repo for a work item."""

    commit_message: str
    summary: str = ""


# A builder edits files in the repo working tree for the given work item and
# returns a BuildOutput. It performs no git/PR operations itself.
Builder = Callable[[Path, WorkItem], BuildOutput]


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IssuePrResult:
    """Outcome of an issue -> PR delegation."""

    issue_id: str
    branch: str
    validated: bool
    pr_body: str
    linked: bool
    pr_url_or_dryrun: str
    # True only when a PR was actually produced (validation passed).
    pr_created: bool = False
    # Non-empty when the flow refused to produce a PR, explaining why.
    refusal: str | None = None

    @property
    def refused(self) -> bool:
        return self.refusal is not None


# ---------------------------------------------------------------------------
# Delegation flow
# ---------------------------------------------------------------------------


def _compose_issue_summary(item: WorkItem, build: BuildOutput) -> str:
    """Compose the issue-linking preamble that lands at the top of the PR body."""

    lines = [f"Resolves issue #{item.issue_id}: {item.title}", "", item.link_ref]
    if item.labels:
        lines.append(f"Labels: {', '.join(item.labels)}")
    detail = (build.summary or "").strip()
    if detail:
        lines.extend(["", detail])
    return "\n".join(lines)


def _result_from_governed(item: WorkItem, gov: GovernedPrResult) -> IssuePrResult:
    linked = gov.pr_created and item.link_ref in gov.pr_body
    return IssuePrResult(
        issue_id=item.issue_id,
        branch=item.branch,
        validated=gov.pr_created and gov.validation.passed,
        pr_body=gov.pr_body,
        linked=linked,
        pr_url_or_dryrun=gov.pr_url_or_dryrun,
        pr_created=gov.pr_created,
        refusal=gov.refusal,
    )


def delegate_issue_to_pr(
    issue: Issue | Mapping[str, object],
    builder: Builder,
    validator: Validator,
    gateway: Gateway = default_dry_run_gateway,
    *,
    repo_path: str | Path,
    base: str = "main",
    intake: IssueIntake | None = None,
    git_runner: GitRunner = _subprocess_git_runner,
) -> IssuePrResult:
    """Delegate an issue assignment to an autonomously produced, linked PR.

    Steps: intake normalizes the issue; the branch is created off ``base``; the
    ``builder`` does the work and commits; the CAP-009 governed flow validates and
    (only on success) emits a PR whose body links the issue and carries the
    validation evidence.
    """

    intake = intake or IssueIntake()
    item = intake.normalize(issue)
    repo = Path(repo_path)
    flow = GovernedPrFlow(repo, gateway=gateway, git_runner=git_runner)

    # Governance is owned by the flow: if the derived branch is protected, let the
    # flow refuse without ever creating a branch or running the builder.
    if item.branch in flow.protected_branches:
        gov = flow.run(branch=item.branch, base=base, title=item.pr_title, validator=validator)
        return _result_from_governed(item, gov)

    def _git(*args: str) -> str:
        return git_runner(list(args), repo)

    # Prepare the feature branch off the base, then let the builder do the work.
    try:
        _git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
        if _git("branch", "--list", item.branch).strip():
            _git("checkout", item.branch)
        else:
            _git("checkout", "-b", item.branch, base)
    except GitError as exc:
        return IssuePrResult(
            issue_id=item.issue_id,
            branch=item.branch,
            validated=False,
            pr_body="",
            linked=False,
            pr_url_or_dryrun="",
            pr_created=False,
            refusal=f"Branch preparation failed: {exc}",
        )

    build = builder(repo, item)

    # Commit the builder's changes (skip cleanly if it produced none).
    _git("add", "-A")
    if _git("status", "--porcelain").strip():
        _git("commit", "-m", build.commit_message)

    # Hand off to the governed flow: it re-checks out the (now built) branch,
    # validates, and only on success composes + emits the linked PR body.
    gov = flow.run(
        branch=item.branch,
        base=base,
        title=item.pr_title,
        validator=validator,
        summary=_compose_issue_summary(item, build),
    )
    return _result_from_governed(item, gov)
