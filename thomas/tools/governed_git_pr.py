"""Governed branch-to-push-to-PR flow with validation evidence in the PR body.

CAP-009 (Native git operations, Level 2): a single governed flow that goes
branch -> validate -> push -> PR, embedding structured validation evidence in
the composed PR body.

Governance guarantees:

1. Refuses to operate directly on a protected branch (``main``/``master``/``dev``
   and any other name in the configurable protected set). The *feature* branch is
   the thing we create and push; the *base* may legitimately be a protected branch
   (you branch off ``main``).
2. Runs an injectable validation step (checks run, pass/fail, evidence snippets --
   e.g. pytest/ruff outcomes) and REFUSES to proceed to PR creation if validation
   fails, surfacing the failure.
3. Composes a PR body that embeds the validation evidence (a structured section
   listing each check, its status, and its snippet) plus a branch/base/commit
   summary.
4. Performs push + PR-create through an injectable gateway. The default is a
   dry-run that returns the composed PR payload without any network/``gh`` call,
   so the whole flow is testable offline and never pushes in tests.

Real branch operations use the ``git`` binary via subprocess in the target repo.
Nothing here ever pushes or calls ``gh`` on its own -- that is exclusively the
gateway's job, and the default gateway is inert.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Branch names that must never be operated on directly as a feature branch.
DEFAULT_PROTECTED_BRANCHES: frozenset[str] = frozenset(
    {"main", "master", "dev", "develop", "trunk", "production", "release"}
)


class GitError(RuntimeError):
    """Raised when an underlying git subprocess command fails."""


# ---------------------------------------------------------------------------
# Validation data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationCheck:
    """One validation check: its name, whether it passed, and an evidence snippet."""

    name: str
    passed: bool
    evidence: str = ""


@dataclass(frozen=True)
class ValidationReport:
    """The structured result of the validation step: a set of checks."""

    checks: tuple[ValidationCheck, ...] = ()

    @property
    def passed(self) -> bool:
        """True only when at least one check ran and every check passed."""
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> tuple[ValidationCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def summary_line(self) -> str:
        total = len(self.checks)
        good = sum(1 for c in self.checks if c.passed)
        state = "PASSED" if self.passed else "FAILED"
        return f"{state} ({good}/{total} checks passed)"


@dataclass(frozen=True)
class ValidationContext:
    """Read-only context handed to a validator callable."""

    repo_path: Path
    branch: str
    base: str
    head_commit: str


# A validator receives the context and returns a ValidationReport, or a plain
# sequence of ValidationCheck (normalized for convenience).
Validator = Callable[[ValidationContext], "ValidationReport | Sequence[ValidationCheck]"]


def _coerce_report(raw: ValidationReport | Sequence[ValidationCheck]) -> ValidationReport:
    if isinstance(raw, ValidationReport):
        return raw
    checks = tuple(raw)
    for c in checks:
        if not isinstance(c, ValidationCheck):
            raise TypeError(f"validator returned a non-ValidationCheck item: {c!r}")
    return ValidationReport(checks=checks)


# ---------------------------------------------------------------------------
# Gateway data model (push + PR create)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrPayload:
    """The composed push/PR-create request handed to the gateway."""

    branch: str
    base: str
    title: str
    body: str
    head_commit: str


@dataclass(frozen=True)
class GatewayResult:
    """What a gateway reports back: whether it pushed and a URL or dry-run marker."""

    pushed: bool
    pr_url_or_dryrun: str


# A gateway performs the actual push + PR create. The default never touches the
# network; it just echoes the composed payload.
Gateway = Callable[[PrPayload], GatewayResult]


def default_dry_run_gateway(payload: PrPayload) -> GatewayResult:
    """Inert default gateway: returns the composed payload without pushing."""

    marker = (
        f"[DRY-RUN] would push branch '{payload.branch}' and open a PR into "
        f"'{payload.base}' (head {payload.head_commit}): {payload.title}"
    )
    return GatewayResult(pushed=False, pr_url_or_dryrun=marker)


# ---------------------------------------------------------------------------
# Flow result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GovernedPrResult:
    """Outcome of a governed PR flow run."""

    branch: str
    base: str
    validation: ValidationReport
    pr_body: str
    pushed: bool
    pr_url_or_dryrun: str
    # True only when the flow reached PR creation (governance + validation passed).
    pr_created: bool = False
    # Non-empty when the flow refused to proceed, explaining why.
    refusal: str | None = None

    @property
    def refused(self) -> bool:
        return self.refusal is not None


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------


# A git runner takes (args, cwd) and returns stdout, raising GitError on failure.
GitRunner = Callable[[Sequence[str], Path], str]


def _subprocess_git_runner(args: Sequence[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found in PATH") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GitError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.strip()


@dataclass
class GovernedPrFlow:
    """Governed branch -> validate -> push -> PR flow.

    Parameters
    ----------
    repo_path:
        Path to the git working tree to operate in.
    protected_branches:
        Branch names that may not be used as the feature branch. Defaults to
        :data:`DEFAULT_PROTECTED_BRANCHES`.
    gateway:
        Injectable push + PR-create callable. Defaults to an inert dry-run.
    git_runner:
        Injectable git command runner. Defaults to a real subprocess runner.
    """

    repo_path: Path
    protected_branches: frozenset[str] = field(default_factory=lambda: DEFAULT_PROTECTED_BRANCHES)
    gateway: Gateway = default_dry_run_gateway
    git_runner: GitRunner = _subprocess_git_runner

    def __post_init__(self) -> None:
        self.repo_path = Path(self.repo_path)
        self.protected_branches = frozenset(self.protected_branches)

    # -- git helpers -------------------------------------------------------

    def _git(self, *args: str) -> str:
        return self.git_runner(list(args), self.repo_path)

    def _prepare_branch(self, branch: str, base: str) -> str:
        """Create/checkout ``branch`` off ``base``; return the head commit sha."""

        # Base must resolve to a real ref/commit.
        self._git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
        existing = self._git("branch", "--list", branch)
        if existing.strip():
            self._git("checkout", branch)
        else:
            self._git("checkout", "-b", branch, base)
        return self._git("rev-parse", "--short", "HEAD")

    # -- PR body composition ----------------------------------------------

    @staticmethod
    def _compose_body(
        *,
        branch: str,
        base: str,
        head_commit: str,
        report: ValidationReport,
        summary: str | None,
    ) -> str:
        lines: list[str] = []
        if summary:
            lines.append(summary.strip())
            lines.append("")
        lines.append("## Branch -> Base")
        lines.append(f"- Branch: `{branch}`")
        lines.append(f"- Base: `{base}`")
        lines.append(f"- Head commit: `{head_commit}`")
        lines.append("")
        lines.append("## Validation Evidence")
        lines.append(f"Overall: **{report.summary_line()}**")
        lines.append("")
        if not report.checks:
            lines.append("_No validation checks were reported._")
        for check in report.checks:
            mark = "PASS" if check.passed else "FAIL"
            lines.append(f"### {check.name} -- {mark}")
            snippet = (check.evidence or "").strip()
            if snippet:
                lines.append("```")
                lines.append(snippet)
                lines.append("```")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    # -- main entry point --------------------------------------------------

    def run(
        self,
        *,
        branch: str,
        base: str,
        title: str,
        validator: Validator,
        summary: str | None = None,
    ) -> GovernedPrResult:
        """Execute the governed flow and return a :class:`GovernedPrResult`."""

        empty = ValidationReport()

        # 1. Governance: never operate directly on a protected feature branch.
        if branch in self.protected_branches:
            refusal = (
                f"Refusing to operate on protected branch '{branch}'. Protected "
                f"branches: {', '.join(sorted(self.protected_branches))}."
            )
            return GovernedPrResult(
                branch=branch,
                base=base,
                validation=empty,
                pr_body="",
                pushed=False,
                pr_url_or_dryrun="",
                pr_created=False,
                refusal=refusal,
            )

        # 2. Create/checkout the feature branch off the base.
        try:
            head_commit = self._prepare_branch(branch, base)
        except GitError as exc:
            return GovernedPrResult(
                branch=branch,
                base=base,
                validation=empty,
                pr_body="",
                pushed=False,
                pr_url_or_dryrun="",
                pr_created=False,
                refusal=f"Branch preparation failed: {exc}",
            )

        # 3. Validation step.
        report = _coerce_report(
            validator(
                ValidationContext(
                    repo_path=self.repo_path,
                    branch=branch,
                    base=base,
                    head_commit=head_commit,
                )
            )
        )

        # PR body always embeds the evidence, whether validation passed or not.
        body = self._compose_body(
            branch=branch,
            base=base,
            head_commit=head_commit,
            report=report,
            summary=summary,
        )

        # 4. Refuse PR creation on validation failure -- gateway is NOT called.
        if not report.passed:
            failed = report.failed_checks
            names = ", ".join(c.name for c in failed) or "(no checks reported)"
            return GovernedPrResult(
                branch=branch,
                base=base,
                validation=report,
                pr_body=body,
                pushed=False,
                pr_url_or_dryrun="",
                pr_created=False,
                refusal=f"Validation failed; refusing to open PR. Failing checks: {names}.",
            )

        # 5. Validation passed -> compose payload and hand to the gateway.
        payload = PrPayload(
            branch=branch,
            base=base,
            title=title,
            body=body,
            head_commit=head_commit,
        )
        outcome = self.gateway(payload)
        return GovernedPrResult(
            branch=branch,
            base=base,
            validation=report,
            pr_body=body,
            pushed=outcome.pushed,
            pr_url_or_dryrun=outcome.pr_url_or_dryrun,
            pr_created=True,
            refusal=None,
        )
