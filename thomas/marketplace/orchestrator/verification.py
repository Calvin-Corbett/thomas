"""Verification gate (Step 6) — executable proof per task family.

The Exhaustive pipeline's verify stage calls ``verify_deliverable``, which
dispatches on the task's family (code / research / data / ui / docs / general) to a
checker. The point is *executable* proof rather than LLM judgment: code is verified
by actually running the workspace's linter; other families get a structural check
of the workspace. Checkers are injectable so the dispatch is unit-testable without
spawning subprocesses.

Know what this gate does and does NOT cover before trusting it:

- ``code`` is checked by ruff, so it verifies Python and nothing else. A
  workspace of HTML and JavaScript is reported as ``ruff_not_applicable``
  rather than clean.
- ``ui`` runs the deterministic web preflight from
  ``thomas.tools.web_preflight``: every script is parsed, unreferenced assets
  and duplicated script includes are reported, and a page whose JavaScript
  cannot be parsed fails. That is the same preflight the Forge/Code path runs,
  because it now lives in ``tools`` and both layers call it. It was hoisted
  there on 2026-07-28; ``marketplace`` may not import ``forge``, and both
  layers already depend on ``tools``.
- What ``ui`` still does NOT do is boot the page in a headless browser to
  confirm the canvas was drawn to. That check needs the Forge smoke runner and
  has not been hoisted, so a page that parses and loads everything it wrote can
  still render nothing and pass here.
- No tests are run here, for any family. An earlier version of this docstring
  said the live wiring also runs tests. It does not.
- Every other family gets the structural workspace check and nothing more.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from thomas.core.task_types import task_family
from thomas.tools.web_preflight import artifact_preflight_failures, workspace_web_files


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
    # Launching and reading a child process: a missing/unexecutable binary or a
    # permissions refusal is OSError, the 120s cap and other process faults are
    # subprocess.SubprocessError, and undecodable output is a ValueError subclass.
    # None of those mean the workspace is bad, so they must not fail the task.
    except (OSError, subprocess.SubprocessError, ValueError) as exc:  # pragma: no cover - environment dependent
        return VerificationResult(True, "code", f"lint runner error: {exc}", ("error",))
    ok = proc.returncode == 0
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if ok and "no python files found" in output.lower():
        # Saying "I did not check this" was honest, and it was still a green
        # tick: the run was recorded as verified and moved on, so a workspace of
        # deliberately broken JavaScript passed. Honest labelling is not the
        # same as checking.
        #
        # This is reachable for most of what Thomas builds. `build-feature`,
        # `fix-bug` and `quick-fix` all map to family `code` in
        # `thomas/core/task_types.py`, so "build me a web app" only meets the
        # web checks when it happens to be classified `design-ui`; every other
        # route handed a web deliverable to a Python linter. The checks were
        # never missing -- `run_web_preflight` is right below and this module
        # already calls it for `ui`. They were simply not reached from here.
        #
        # Reported under `code`, because the family belongs to the TASK; only
        # the checker changed. A workspace with neither Python nor web files
        # falls through unchanged: there is genuinely nothing to run, and
        # failing a config file or a shell script would be a new false negative
        # in place of the old false positive.
        if workspace_web_files(work_dir):
            return replace(run_web_preflight(work_dir, result_text), family="code")
        return VerificationResult(
            True,
            "code",
            "no Python files in this workspace, so ruff verified nothing, and there is no web output to check",
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
        # "found none", not "inspected none". It DID look -- that was the whole
        # point of replacing `_ = work_dir` -- and saying otherwise describes
        # the old behaviour, where nothing was examined and the pass came from
        # the reply being non-empty. The distinction is the fix.
        return VerificationResult(True, "general", "answer text only; the workspace holds no files", ("text_only",))
    return VerificationResult(False, "general", "no workspace files and no answer text", ("empty",))


_PREFLIGHT_EVIDENCE_FAILURES = 5


def run_web_preflight(work_dir: str, result_text: str = "") -> VerificationResult:
    """UI verification: actually open what was built and see whether it boots.

    `design-ui` maps to family `ui`, and until now `ui` had no checker at all --
    so the one task type whose entire purpose is building a UI was verified by
    the structural check, which passes as soon as any file exists. A page whose
    only script is a syntax error, a stylesheet nothing links, a script included
    twice so it dies on a redeclared const: all of them passed, and the pipeline
    reported the deliverable as verified.

    The checks are the ones the Forge/Code path has run for months, now shared
    from `thomas.tools.web_preflight` rather than reimplemented. Nothing here
    executes the generated JavaScript -- `node --check` parses without running
    it -- so verifying a page cannot hand that page the user's machine.

    When the workspace has no web files this does not invent an opinion. A `ui`
    task can legitimately deliver a written spec, and failing those would be a
    new false negative in place of the old false positive, so it falls back to
    the same structural check every other family gets and says which one ran.
    """

    files = workspace_web_files(work_dir) if work_dir else []
    if not files:
        # `replace` rather than a fresh result: the structural check owns what
        # it found and how it says it, and this only corrects the family label
        # so a reader can tell which checker answered.
        return replace(_generic_checker(work_dir, result_text), family="ui")

    failures = artifact_preflight_failures(work_dir, files)
    if failures:
        shown = "; ".join(failures[:_PREFLIGHT_EVIDENCE_FAILURES])
        if len(failures) > _PREFLIGHT_EVIDENCE_FAILURES:
            shown += f"; and {len(failures) - _PREFLIGHT_EVIDENCE_FAILURES} more"
        return VerificationResult(False, "ui", shown[:1000], ("web_preflight",))

    # Name the count, because "preflight clean" over one stray CSS file and over
    # a whole game read identically, and only one of them is worth trusting.
    return VerificationResult(
        True,
        "ui",
        f"web preflight clean over {len(files)} file(s): {', '.join(files[:_PREFLIGHT_EVIDENCE_FAILURES])}",
        ("web_preflight",),
    )


# Checkers by family. `checkers=` exists so this dispatch is unit-testable, and
# NOTHING in thomas/ passes it -- so this dict is what actually runs, and any
# family absent from it gets the generic structural check. The comment here used
# to say production injects richer ones such as pytest. It does not, and never
# did; grep for `checkers=` outside tests and there are no hits. A note claiming
# a safety property that is not there is worse than no note, because the next
# reader stops looking.
DEFAULT_CHECKERS: dict[str, Checker] = {
    "code": run_ruff_check,
    "ui": run_web_preflight,
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
