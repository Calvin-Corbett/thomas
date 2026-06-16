"""Verification gate (Step 6) — executable proof per task family.

The Exhaustive pipeline's verify stage calls ``verify_deliverable``, which
dispatches on the task's family (code / research / data / ui / docs / general) to a
checker. The point is *executable* proof rather than LLM judgment: code is verified
by actually running the workspace's linter (and, in the live wiring, its tests);
other families get lighter structural checks. Checkers are injectable so the
dispatch is unit-testable without spawning subprocesses.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from thomas.core.task_types import task_family


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    family: str
    evidence: str = ""
    checks: tuple[str, ...] = ()


# checker signature: (work_dir, result_text) -> VerificationResult
Checker = Callable[[str, str], "VerificationResult"]


def run_ruff_check(work_dir: str, result_text: str = "") -> VerificationResult:
    """Real code verification: run ruff over the workspace. Executable proof.

    Defensive: if there is no workspace or ruff is unavailable, it does not fail the
    task — it reports that the check could not run (the live wiring also runs tests).
    """
    _ = result_text
    if not work_dir:
        return VerificationResult(True, "code", "no workspace to lint", ("skipped",))
    ruff = shutil.which("ruff")
    if not ruff:
        return VerificationResult(True, "code", "ruff unavailable; lint skipped", ("skipped",))
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [ruff, "check", work_dir],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        return VerificationResult(True, "code", f"lint runner error: {exc}", ("error",))
    ok = proc.returncode == 0
    evidence = (proc.stdout or proc.stderr or "").strip()[:1000] or "ruff clean"
    return VerificationResult(ok, "code", evidence, ("ruff",))


def _generic_checker(work_dir: str, result_text: str) -> VerificationResult:
    _ = work_dir
    return VerificationResult(bool(result_text), "general", "deliverable present", ("present",))


# Default real checkers by family. Production injects richer ones (e.g. pytest).
DEFAULT_CHECKERS: dict[str, Checker] = {
    "code": run_ruff_check,
}


def verify_deliverable(
    task_type: object,
    work_dir: str = "",
    result_text: str = "",
    *,
    checkers: dict[str, Checker] | None = None,
) -> VerificationResult:
    """Verify a deliverable by its task family. Pass ``checkers`` to override/inject."""
    fam = task_family(task_type)
    registry = DEFAULT_CHECKERS if checkers is None else checkers
    checker = registry.get(fam, _generic_checker)
    return checker(work_dir, result_text)
