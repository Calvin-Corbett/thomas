"""Independent completion-claim verifier for Thomas evolve sessions.

The in-path promotion review (``decision.decide_for_session``) trusts the
transcript a finished session hands it: if the session dict *says* every
verification command exited 0, the gate believes it.  A false completion claim
with a plausible transcript therefore passes.  This module closes that hole by
being independent **in process**, not just in prompt:

1. It takes a completion claim (the checks that supposedly prove the work:
   pytest / py_compile / ruff commands with their claimed exit codes) and
   RERUNS the runnable evidence in a fresh ``subprocess.run`` child with an
   explicit cwd, timeout, and captured output.  It never trusts the claimant's
   transcript text.
2. An allowlist guard restricts what it will rerun (see *Rerun policy* below).
   Arbitrary shell strings that could mutate state are refused.
3. It returns a verdict object: ``claim_verified`` / ``claim_rejected`` (with
   the diverging evidence: expected vs actual exit code and output snippet) /
   ``unverifiable`` (no runnable evidence in the claim -- treated as NOT
   verified: an unverifiable claim never upgrades a decision).
4. An optional separate-model review hook (an injectable adapter) lets a
   DIFFERENT model judge non-runnable claims.  The default of ``None`` keeps
   the verifier process-independent only, so tests never touch a live model.

Rerun policy (the allowlist)
----------------------------
Only read-only or test-class commands are rerun:

- ``python -m <module>`` where the module is one of
  ``pytest``, ``py_compile``, ``compileall``, ``unittest``, or ``ruff``
  (lint/compile/test tools that do not mutate the candidate tree);
- a bare ``pytest`` invocation;
- ``git <subcommand>`` where the subcommand is read-only
  (``status``, ``diff``, ``log``, ``show``, ``rev-parse``).

Everything else is refused: ``python -c`` (arbitrary code), package managers,
deletion commands, and any command string containing shell metacharacters.
Refused checks contribute no rerun evidence; a claim whose checks are all
refused (or that has no checks) is ``unverifiable``.  Checks whose claimed
exit code is nonzero are skipped -- they do not assert success, and the
verifier's job is to falsify *success* claims, not to replay failures.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CLAIM_VERIFIED = "claim_verified"
CLAIM_REJECTED = "claim_rejected"
UNVERIFIABLE = "unverifiable"

EVIDENCE_MATCHED = "rerun_matched"
EVIDENCE_DIVERGED = "rerun_diverged"
EVIDENCE_REFUSED = "refused"
EVIDENCE_SKIPPED = "skipped_nonzero_claim"

DEFAULT_CHECK_TIMEOUT_SECONDS = 600
_SNIPPET_LIMIT = 800
_SHELL_METACHARS = (";", "&", "|", "<", ">", "`", "$(", "\n", "\r")
_PYTHON_EXECUTABLES = frozenset({"python", "python.exe", "python3", "python3.exe", "py", "py.exe"})

ALLOWED_PYTHON_MODULES = frozenset({"pytest", "py_compile", "compileall", "unittest", "ruff"})
ALLOWED_BARE_EXECUTABLES = frozenset({"pytest", "pytest.exe"})
ALLOWED_GIT_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "rev-parse"})

ModelReviewFn = Callable[["CompletionClaim"], Mapping[str, Any]]


def _snippet(value: Any, limit: int = _SNIPPET_LIMIT) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


@dataclass(frozen=True)
class ClaimedCheck:
    """One verifiable assertion inside a completion claim."""

    command: str | list[str]
    expected_returncode: int = 0
    source: str = ""
    description: str = ""

    @property
    def display_command(self) -> str:
        if isinstance(self.command, str):
            return self.command
        return " ".join(shlex.quote(str(part)) for part in self.command)


@dataclass(frozen=True)
class CompletionClaim:
    """What was supposedly done, plus the checks that supposedly prove it."""

    description: str = ""
    cwd: str = ""
    checks: tuple[ClaimedCheck, ...] = ()


@dataclass(frozen=True)
class CheckEvidence:
    """Outcome of independently rerunning (or refusing) one claimed check."""

    command: str
    status: str
    expected_returncode: int = 0
    actual_returncode: int | None = None
    stdout_snippet: str = ""
    stderr_snippet: str = ""
    timed_out: bool = False
    refusal_reason: str = ""

    @property
    def diverged(self) -> bool:
        return self.status == EVIDENCE_DIVERGED

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "status": self.status,
            "expected_returncode": self.expected_returncode,
            "actual_returncode": self.actual_returncode,
            "stdout_snippet": self.stdout_snippet,
            "stderr_snippet": self.stderr_snippet,
            "timed_out": self.timed_out,
            "refusal_reason": self.refusal_reason,
        }


@dataclass(frozen=True)
class IndependentVerdict:
    """Result of independently verifying a completion claim."""

    status: str
    reason: str
    evidence: tuple[CheckEvidence, ...] = ()
    model_reviewed: bool = False

    @property
    def verified(self) -> bool:
        return self.status == CLAIM_VERIFIED

    @property
    def rejected(self) -> bool:
        return self.status == CLAIM_REJECTED

    def summary(self) -> str:
        diverging = [item for item in self.evidence if item.diverged]
        return _diverging_reason(diverging) if diverging else self.reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "model_reviewed": self.model_reviewed,
            "evidence": [item.to_dict() for item in self.evidence],
        }


def _diverging_reason(diverging: list[CheckEvidence]) -> str:
    first = diverging[0]
    detail = first.stderr_snippet or first.stdout_snippet
    actual = "timeout" if first.timed_out else str(first.actual_returncode)
    text = f"{first.command}: expected exit {first.expected_returncode}, got {actual}"
    if detail:
        text += f"; output: {_snippet(detail, limit=240)}"
    if len(diverging) > 1:
        text += f" (+{len(diverging) - 1} more diverging check(s))"
    return text


def _parse_command(command: str | list[str]) -> tuple[list[str], str]:
    """Return (argv, refusal_reason). argv is empty when refused."""
    if isinstance(command, list):
        argv = [str(part) for part in command]
        return (argv, "") if argv else ([], "empty command")
    raw = str(command or "").strip()
    if not raw:
        return [], "empty command"
    for char in _SHELL_METACHARS:
        if char in raw:
            return [], f"shell metacharacter {char!r} in command"
    try:
        argv = shlex.split(raw, posix=True)
    except ValueError as exc:
        return [], f"unparseable command: {exc}"
    return (argv, "") if argv else ([], "empty command")


def allowlist_refusal_reason(argv: list[str]) -> str:
    """Explain why argv is not rerunnable, or return '' when it is allowed."""
    if not argv:
        return "empty command"
    executable = Path(argv[0]).name.lower()
    if executable in _PYTHON_EXECUTABLES:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in ALLOWED_PYTHON_MODULES:
            return ""
        if len(argv) >= 2 and argv[1] == "-m":
            module = argv[2] if len(argv) > 2 else "<missing>"
            return f"python module {module!r} is not allowlisted"
        return "only 'python -m <allowlisted module>' invocations are rerunnable (no 'python -c' or scripts)"
    if executable in ALLOWED_BARE_EXECUTABLES:
        return ""
    if executable in ("git", "git.exe"):
        subcommand = argv[1] if len(argv) > 1 else ""
        if subcommand in ALLOWED_GIT_SUBCOMMANDS:
            return ""
        return f"git subcommand {subcommand!r} is not read-only allowlisted"
    return f"executable {executable!r} is not allowlisted for independent rerun"


def _pin_python(argv: list[str]) -> list[str]:
    pinned = list(argv)
    if pinned and Path(pinned[0]).name.lower() in _PYTHON_EXECUTABLES:
        pinned[0] = sys.executable
    return pinned


def _rerun_check(
    check: ClaimedCheck,
    argv: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> CheckEvidence:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cwd)
    try:
        completed = subprocess.run(
            _pin_python(argv),
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CheckEvidence(
            command=check.display_command,
            status=EVIDENCE_DIVERGED,
            expected_returncode=check.expected_returncode,
            actual_returncode=None,
            stdout_snippet=_snippet(exc.stdout),
            stderr_snippet=_snippet(exc.stderr),
            timed_out=True,
        )
    except OSError as exc:
        return CheckEvidence(
            command=check.display_command,
            status=EVIDENCE_DIVERGED,
            expected_returncode=check.expected_returncode,
            actual_returncode=None,
            stderr_snippet=f"claimed command failed to launch on rerun: {exc}",
        )
    status = EVIDENCE_MATCHED if int(completed.returncode) == check.expected_returncode else EVIDENCE_DIVERGED
    return CheckEvidence(
        command=check.display_command,
        status=status,
        expected_returncode=check.expected_returncode,
        actual_returncode=int(completed.returncode),
        stdout_snippet=_snippet(completed.stdout),
        stderr_snippet=_snippet(completed.stderr),
    )


def _apply_model_review(
    claim: CompletionClaim,
    evidence: tuple[CheckEvidence, ...],
    model_review: ModelReviewFn,
) -> IndependentVerdict:
    judgment = dict(model_review(claim) or {})
    status = str(judgment.get("status") or "").strip().lower()
    reason = str(judgment.get("reason") or "separate-model review returned no reason")
    if status == CLAIM_REJECTED:
        return IndependentVerdict(CLAIM_REJECTED, f"separate-model review rejected claim: {reason}", evidence, True)
    if status == CLAIM_VERIFIED:
        return IndependentVerdict(CLAIM_VERIFIED, f"separate-model review accepted claim: {reason}", evidence, True)
    return IndependentVerdict(
        UNVERIFIABLE,
        f"separate-model review was inconclusive: {reason}",
        evidence,
        True,
    )


def verify_claim(
    claim: CompletionClaim,
    *,
    timeout_seconds: int = DEFAULT_CHECK_TIMEOUT_SECONDS,
    model_review: ModelReviewFn | None = None,
) -> IndependentVerdict:
    """Independently verify a completion claim by rerunning its evidence.

    Never trusts the claimed transcript: every allowlisted check is rerun in a
    fresh subprocess and its exit code compared against the claimed one.  Any
    divergence rejects the claim outright.  A claim with no rerunnable
    evidence is ``unverifiable`` (NOT verified); when ``model_review`` is
    injected, such claims are handed to the separate-model adapter to judge.
    """
    cwd_text = str(claim.cwd or "").strip()
    cwd: Path | None = None
    if cwd_text and Path(cwd_text).is_dir():
        cwd = Path(cwd_text)
    evidence: list[CheckEvidence] = []
    for check in claim.checks:
        if int(check.expected_returncode) != 0:
            evidence.append(
                CheckEvidence(
                    command=check.display_command,
                    status=EVIDENCE_SKIPPED,
                    expected_returncode=check.expected_returncode,
                    refusal_reason="claim does not assert success for this check",
                )
            )
            continue
        argv, parse_refusal = _parse_command(check.command)
        refusal = parse_refusal or allowlist_refusal_reason(argv)
        if not refusal and cwd is None:
            refusal = f"claim cwd is missing or not a directory: {cwd_text!r}"
        if refusal or cwd is None:
            evidence.append(
                CheckEvidence(
                    command=check.display_command,
                    status=EVIDENCE_REFUSED,
                    expected_returncode=check.expected_returncode,
                    refusal_reason=refusal,
                )
            )
            continue
        evidence.append(_rerun_check(check, argv, cwd, timeout_seconds))
    rows = tuple(evidence)
    diverged = [item for item in rows if item.diverged]
    matched = [item for item in rows if item.status == EVIDENCE_MATCHED]
    if diverged:
        return IndependentVerdict(CLAIM_REJECTED, _diverging_reason(diverged), rows)
    if matched:
        return IndependentVerdict(
            CLAIM_VERIFIED,
            f"{len(matched)} claimed check(s) reproduced independently",
            rows,
        )
    if model_review is not None:
        return _apply_model_review(claim, rows, model_review)
    return IndependentVerdict(UNVERIFIABLE, "claim carries no rerunnable evidence", rows)


def claim_from_session(session: Mapping[str, Any]) -> CompletionClaim:
    """Build a completion claim from an evolve session dict.

    Uses the session's recorded verification transcript as the *claim* (what
    the session says happened) and ``verification_root`` as the rerun cwd.
    """
    session = dict(session or {})
    checks: list[ClaimedCheck] = []
    for row in session.get("verification") or []:
        if not isinstance(row, dict):
            continue
        command = row.get("command")
        if not isinstance(command, (str, list)) or not str(command).strip():
            continue
        checks.append(
            ClaimedCheck(
                command=command if isinstance(command, list) else str(command),
                expected_returncode=int(row.get("returncode") or 0),
                source=str(row.get("source") or ""),
                description=str(row.get("description") or row.get("acceptance_check") or ""),
            )
        )
    return CompletionClaim(
        description=f"evolve session {session.get('session_id') or 'unknown'} completion claim",
        cwd=str(session.get("verification_root") or ""),
        checks=tuple(checks),
    )


@dataclass(frozen=True)
class SessionClaimVerifier:
    """Callable adapter: session dict -> IndependentVerdict.

    Suitable for injection into ``decision.decide_for_session`` so a rejected
    independent rerun overrides an approving in-path review.
    """

    timeout_seconds: int = DEFAULT_CHECK_TIMEOUT_SECONDS
    model_review: ModelReviewFn | None = field(default=None)

    def __call__(self, session: Mapping[str, Any]) -> IndependentVerdict:
        return verify_claim(
            claim_from_session(session),
            timeout_seconds=self.timeout_seconds,
            model_review=self.model_review,
        )


def build_session_verifier(
    *,
    timeout_seconds: int = DEFAULT_CHECK_TIMEOUT_SECONDS,
    model_review: ModelReviewFn | None = None,
) -> SessionClaimVerifier:
    """Build the default process-independent verifier for evolve sessions."""
    return SessionClaimVerifier(timeout_seconds=int(timeout_seconds), model_review=model_review)
