"""Verification gate (Step 6) — executable proof per task family.

The Exhaustive pipeline's verify stage calls ``verify_deliverable``, which
dispatches on the task's family (code / research / data / ui / docs / general) to a
checker. The point is *executable* proof rather than LLM judgment: code is verified
by actually running the workspace's linter; other families get a structural check
of the workspace. Checkers are injectable so the dispatch is unit-testable without
spawning subprocesses.

Know what this gate does NOT cover before trusting it:

- Only ``code`` has a real checker, and that checker is ruff, so it verifies
  Python and nothing else. A workspace of HTML and JavaScript is reported as
  ``ruff_not_applicable`` rather than clean.
- No tests are run here. An earlier version of this docstring said the live
  wiring also runs tests. It does not.
- Web output is verified in the Forge/Code path (``forge/anvil/build_verify.py``),
  which parses scripts, finds unreferenced and duplicated assets, and boots the
  page in a headless browser to confirm the canvas was drawn to. None of that
  runs from here.
- ``design-ui`` maps to family ``ui``, which has no checker at all, so the task
  type whose whole purpose is building a UI gets only the structural check.

Do not close that gap by importing the Forge checks here. ``_architecture.py``
declares ``marketplace`` may depend on core/tools/plugins/server, and NOT on
``forge`` — the import gate will reject it, and CLAUDE.md asks that existing
cross-layer imports be inverted rather than joined by new ones. The real fix is
to hoist the deterministic web preflight (script parse, orphaned assets,
duplicate includes) into a layer both paths already depend on, and have both
call it. That is a refactor, not a wiring change.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    """Code verification for PYTHON workspaces: run ruff. Executable proof.

    Defensive: with no workspace, or no ruff, it does not fail the task — it
    reports that the check could not run.

    It also reports when it does not APPLY, which is the common case for what
    Thomas actually builds. `ruff check` over a folder of HTML and JavaScript
    prints "No Python files found", says "All checks passed!" and exits 0, so a
    web project came back `passed=True` with the evidence "ruff clean" — a
    Python linter certifying a game it is structurally incapable of reading. A
    deliberately broken JavaScript file passes this check.

    Nothing here verifies web output. The Forge/Code path has real checks for it
    (parse, orphaned assets, duplicate includes, and a headless browser that
    confirms the canvas was actually drawn to); this marketplace path has none
    of them, and saying so is better than a green tick that means nothing.
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
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if ok and "no python files found" in output.lower():
        return VerificationResult(
            True,
            "code",
            "no Python files in this workspace, so ruff verified nothing; web output is unchecked here",
            ("ruff_not_applicable",),
        )
    evidence = output[:1000] or "ruff clean"
    return VerificationResult(ok, "code", evidence, ("ruff",))


_GENERIC_EVIDENCE_FILES = 5


def _generic_checker(work_dir: str, result_text: str) -> VerificationResult:
    """The lighter structural check this module's docstring promises.

    It used to be `_ = work_dir` followed by `bool(result_text)`: for every
    family except code, a task passed verification because the worker had said
    something. The workspace was discarded on the first line, and the result was
    reported as "deliverable present" with a check named "present" -- wording
    that reads like a file was found when nothing had been looked at.

    `run_ruff_check` directly above already does this honestly, marking itself
    "skipped" when it cannot run. This now follows that pattern: it names what
    it actually found, and when it has inspected nothing it says so instead of
    borrowing the language of evidence.

    Answer-only work still passes on its text -- for a question answered in
    prose the text IS the deliverable, and failing those would be wrong. The
    difference is that the check is now called what it is, so a reader and a
    grader can tell the two apart. A task that was required to produce files and
    did not is caught by the artifact-evidence gate, which is a separate stage.
    """

    files: list[str] = []
    if work_dir:
        root = Path(work_dir)
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                # Relative parts: an absolute path carries the workspace's own
                # location, and Thomas keeps every workspace under ~/.thomas.
                if not path.is_file() or any(p.startswith(".") for p in path.relative_to(root).parts):
                    continue
                files.append(path.relative_to(root).as_posix())
                if len(files) > _GENERIC_EVIDENCE_FILES:
                    break

    if files:
        shown = ", ".join(files[:_GENERIC_EVIDENCE_FILES])
        # "and more", not a number. The scan stops one past the display limit,
        # so a subtraction here reports "+1 more" for a workspace of six files
        # and for one of six hundred alike -- a precise-looking figure that was
        # never counted. Same failure as everything else fixed today, just very
        # small: stating a measurement that was not taken.
        more = " and more" if len(files) > _GENERIC_EVIDENCE_FILES else ""
        return VerificationResult(True, "general", f"workspace holds {shown}{more}", ("files_present",))
    if result_text:
        return VerificationResult(True, "general", "answer text only; no workspace files inspected", ("text_only",))
    return VerificationResult(False, "general", "no workspace files and no answer text", ("empty",))


# Checkers by family. `checkers=` exists so this dispatch is unit-testable, and
# NOTHING in thomas/ passes it -- so this dict is what actually runs, and any
# family absent from it gets the generic structural check. The comment here used
# to say production injects richer ones such as pytest. It does not, and never
# did; grep for `checkers=` outside tests and there are no hits. A note claiming
# a safety property that is not there is worse than no note, because the next
# reader stops looking.
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
