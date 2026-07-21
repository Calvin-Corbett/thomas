"""CI-native execution for Anvil (CAP-065).

Let Thomas run INSIDE a CI job, inspect a failure, drive a real fix, and report a
machine-readable result. This is a thin, honest orchestration over seams that
already exist and are never rewritten here:

* :func:`thomas.forge.anvil.build_verify.verify_python_changes` — the RUN/TEST
  step. A REAL subprocess byte-compiles/imports (or pytests) the changed files
  and reflects its GENUINE exit code. Nothing in this module fabricates a
  pass/fail; the status is whatever that subprocess returned.
* :func:`thomas.forge.anvil.build_verify._verify_and_iterate` — the bounded
  reason→edit→verify LOOP. This module drives it with an injected fix editor and
  the real verifier so a failing check is handed back for a fix and re-verified.
* :func:`thomas.forge.anvil.run_report.build_run_report` — the machine-readable
  post-run structure (CAP-141). The CI result embeds it verbatim.

Three edges are injectable so the whole capability is provable OFFLINE while the
production wiring stays honest:

1. VERIFY edge — real default is ``verify_python_changes`` (real subprocess,
   genuine exit codes). Tests use the REAL default in a throwaway git repo; it is
   hermetic because it only byte-compiles files in a temp dir — no network.
2. FIX-EDITOR edge — the reason→edit adapter (``fix_editor(prompt) -> (rc,out)``).
   In production this is wired to Thomas's model dispatch
   (``thomas.forge.anvil.dispatch_*``), which is credential/model-gated: that is
   the live lane and is NOT exercised here. Tests inject a hermetic fake that
   writes the corrected file. A run with no editor wired degrades honestly to
   "inspected + reported, no fix applied" rather than pretending to fix.
3. CI-OUTPUT edge — GitHub-Actions annotations (``::error``/``::notice`` workflow
   commands) and step output vars. The real default writes annotations to stdout
   (how the Actions runner captures them) and appends ``name=value`` to the file
   named by ``$GITHUB_OUTPUT``. Tests inject an in-memory sink and a temp file.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .build_verify import _verify_and_iterate, verify_python_changes
from .run_report import build_run_report

# --- schema ----------------------------------------------------------------

SCHEMA_NAME = "thomas.ci.result"
SCHEMA_VERSION = 1

# The fields every machine-readable CI result MUST carry. A consumer (a later CI
# step, a dashboard, a bot) parses the JSON artifact and relies on these being
# present, so the test asserts the set explicitly.
REQUIRED_RESULT_FIELDS = (
    "schema",
    "schema_version",
    "status",
    "exit_code",
    "fixed",
    "findings",
    "changed_files",
    "report",
    "annotations",
    "output_vars",
)

# --- failure-context parsing -----------------------------------------------

# ``FAILED tests/test_x.py::test_y - AssertionError: ...`` (pytest summary line).
_PYTEST_RESULT_RE = re.compile(
    r"^(?P<status>FAILED|ERROR)\s+(?P<file>[\w./\\-]+\.py)(?P<node>::[^\s]+)?"
    r"(?:\s+-\s+(?P<msg>.+))?\s*$"
)
# ``File "path/x.py", line 12, in fn`` (a python traceback frame).
_TRACEBACK_FILE_RE = re.compile(r'File "(?P<file>[^"]+?\.py)", line (?P<line>\d+)')
# ``app.py:3: SyntaxError: ...`` or flake8 ``app.py:3:5: E999 ...`` (compile/lint).
_COMPILE_REF_RE = re.compile(r"^(?P<file>[\w./\\-]+\.py):(?P<line>\d+)(?::\d+)?:\s*(?P<msg>.+)$")
# ``AssertionError: ...`` / ``E   SyntaxError: ...`` (a bare exception summary).
_EXC_RE = re.compile(r"^(?:E\s+)?(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Warning)):\s*(?P<msg>.+)$")

_MAX_FINDINGS = 25
_MSG_CHARS = 240


@dataclass
class CiFailureContext:
    """A parsed-but-structured view of ONE failing CI step.

    ``command`` is what the step ran, ``output`` is its combined stdout/stderr,
    and ``exit_code`` is the step's real non-zero return. ``job``/``step`` name
    the GitHub-Actions job and step for annotation grouping. This is INJECTED
    into the runner — the runner never shells out to discover it — so tests feed a
    fixed context and the parse is deterministic.
    """

    command: str
    output: str
    exit_code: int
    job: str = ""
    step: str = ""


@dataclass
class CiFinding:
    """One structured finding distilled from a failure context."""

    file: str
    line: int | None
    message: str
    kind: str  # "test_failure" | "compile_error" | "exception" | "command_failure"
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(text: Any, limit: int = _MSG_CHARS) -> str:
    return " ".join(str(text or "").split())[:limit]


def parse_failure_context(context: CiFailureContext) -> list[CiFinding]:
    """Parse a CI failure context into structured, deduplicated findings.

    Recognizes pytest ``FAILED``/``ERROR`` summary lines, python traceback frames
    (attaching the following exception line as the message), and
    compile/lint ``file:line:`` references. When the step failed but yielded no
    recognizable finding, a single ``command_failure`` finding preserves the fact
    that the step returned non-zero — the failure is never silently dropped.
    """
    findings: list[CiFinding] = []
    seen: set[tuple[str, int | None, str]] = set()

    def add(file: str, line: int | None, message: str, kind: str, evidence: str) -> None:
        key = (file, line, message)
        if key in seen or len(findings) >= _MAX_FINDINGS:
            return
        seen.add(key)
        findings.append(
            CiFinding(file=file, line=line, message=_clean(message), kind=kind, evidence=_clean(evidence, 400))
        )

    lines = str(context.output or "").splitlines()
    pending_frame: tuple[str, int] | None = None
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        pytest_match = _PYTEST_RESULT_RE.match(stripped)
        if pytest_match:
            node = pytest_match.group("node") or ""
            msg = pytest_match.group("msg") or f"{pytest_match.group('status')} {pytest_match.group('file')}{node}"
            add(pytest_match.group("file"), None, msg, "test_failure", stripped)
            continue

        compile_match = _COMPILE_REF_RE.match(stripped)
        if compile_match:
            add(
                compile_match.group("file"),
                int(compile_match.group("line")),
                compile_match.group("msg"),
                "compile_error",
                stripped,
            )
            continue

        frame_match = _TRACEBACK_FILE_RE.search(stripped)
        if frame_match:
            # Remember the deepest frame; the exception message usually follows.
            pending_frame = (frame_match.group("file"), int(frame_match.group("line")))
            continue

        exc_match = _EXC_RE.match(stripped)
        if exc_match:
            file, line_no = pending_frame if pending_frame else ("", None)
            add(file, line_no, f"{exc_match.group('exc')}: {exc_match.group('msg')}", "exception", stripped)
            pending_frame = None

    if not findings and context.exit_code != 0:
        add(
            "",
            None,
            f"command failed (exit {context.exit_code}): {_clean(context.command, 120)}",
            "command_failure",
            _clean(context.output, 400) or context.command,
        )
    return findings


# --- GitHub-Actions workflow-command emission ------------------------------


def _escape_data(value: str) -> str:
    """Escape a workflow-command DATA payload per the Actions toolkit rules."""
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    """Escape a workflow-command PROPERTY value (adds ``:`` and ``,``)."""
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def format_annotation(level: str, message: str, *, file: str = "", line: int | None = None, title: str = "") -> str:
    """Format one ``::error``/``::notice``/``::warning`` workflow command line."""
    props: list[str] = []
    if title:
        props.append(f"title={_escape_property(title)}")
    if file:
        props.append(f"file={_escape_property(file)}")
        if line is not None:
            props.append(f"line={line}")
    prop_text = (" " + ",".join(props)) if props else ""
    return f"::{level}{prop_text}::{_escape_data(message)}"


def _default_annotation_sink(line: str) -> None:
    """Real default: print the workflow command to stdout (the Actions runner
    scrapes annotations from the step's stdout stream)."""
    import sys

    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except (OSError, ValueError):
        # A closed/detached stdout must not crash the CI step mid-report; the
        # annotation is best-effort surface, and the JSON artifact still carries
        # every annotation string for a consumer that reads the file instead.
        pass


def write_output_vars(output_vars: dict[str, str], path: str | os.PathLike[str] | None) -> bool:
    """Append ``name=value`` step outputs to ``path`` (``$GITHUB_OUTPUT``).

    Returns True iff written. ``path`` of ``None`` (the var unset, e.g. running
    outside Actions) is a no-op that returns False — never an error.
    """
    if not path:
        return False
    lines = "".join(f"{name}={value}\n" for name, value in output_vars.items())
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(lines)
    except OSError:
        return False
    return True


# --- result ----------------------------------------------------------------


@dataclass
class CiRunResult:
    """The machine-readable outcome of one CI-native run."""

    status: str  # "passed" | "failed"
    exit_code: int
    fixed: bool
    findings: list[CiFinding]
    changed_files: list[str]
    report: dict[str, Any]
    annotations: list[str]
    output_vars: dict[str, str]

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "exit_code": self.exit_code,
            "fixed": self.fixed,
            "findings": [f.to_dict() for f in self.findings],
            "changed_files": list(self.changed_files),
            "report": self.report,
            "annotations": list(self.annotations),
            "output_vars": dict(self.output_vars),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    def write_artifact(self, path: str | os.PathLike[str]) -> bool:
        """Write the machine-readable JSON artifact. Returns True iff written."""
        try:
            Path(path).write_text(self.to_json(), encoding="utf-8")
        except OSError:
            return False
        return True


def _no_fix_editor(prompt: str) -> tuple[int, str]:
    """Default fix editor: no model wired, so it honestly declines to edit.

    Returning non-zero makes the bounded loop stop after the first failed verify
    without pretending a fix happened; the run is reported as ``failed`` with the
    inspected findings intact. Production wires a real, credential-gated dispatch
    editor in its place (the live lane).
    """
    return 1, "no fix editor configured (live model dispatch is credential-gated); inspection-only run"


class CiRunner:
    """Run inside CI: inspect a failure, drive a real fix, emit a machine result.

    ``verifier`` defaults to the REAL ``verify_python_changes`` (genuine
    subprocess exit codes); a test may inject a fake, but the offline proof uses
    the real one because it is hermetic. ``max_fix_iters`` bounds the
    reason→edit→verify loop.
    """

    def __init__(self, *, verifier: Any = None, max_fix_iters: int = 2) -> None:
        self._verifier = verifier or verify_python_changes
        self.max_fix_iters = max(0, int(max_fix_iters))

    # -- (1) INSPECT FAILURES ----------------------------------------------

    def inspect_failures(self, context: CiFailureContext) -> list[CiFinding]:
        """Parse a CI failure context into structured findings."""
        return parse_failure_context(context)

    # -- (3) MACHINE-READABLE OUTPUTS --------------------------------------

    def build_annotations(
        self,
        context: CiFailureContext,
        findings: list[CiFinding],
        *,
        passed: bool,
        exit_code: int,
        fixed: bool,
    ) -> list[str]:
        """Build the GitHub-Actions annotation lines for this run.

        A failing run emits one ``::error`` per finding (grouped by the job/step
        title). A passing run emits a single ``::notice`` — including the case
        where the fix loop turned an initial failure green.
        """
        title = " / ".join(part for part in (context.job, context.step) if part) or "thomas-ci"
        if not passed:
            if not findings:
                return [format_annotation("error", f"CI step failed (exit {exit_code})", title=title)]
            return [format_annotation("error", f.message, file=f.file, line=f.line, title=title) for f in findings]
        if fixed:
            return [
                format_annotation(
                    "notice",
                    f"Thomas fixed the failure and re-verification passed (exit {exit_code})",
                    title=title,
                )
            ]
        return [format_annotation("notice", f"CI verification passed (exit {exit_code})", title=title)]

    def build_output_vars(self, *, passed: bool, exit_code: int, fixed: bool, findings: int) -> dict[str, str]:
        """Build the GitHub-Actions step output variables for this run."""
        return {
            "status": "passed" if passed else "failed",
            "exit_code": str(exit_code),
            "fixed": "true" if fixed else "false",
            "findings": str(findings),
        }

    # -- (1)+(2)+(3) end to end --------------------------------------------

    def run(
        self,
        context: CiFailureContext,
        *,
        cwd: str | Path,
        snap_before: dict[str, str],
        fix_editor: Callable[[str], tuple[int, str]] | None = None,
        goal: str = "",
        definition: str = "",
        artifact_path: str | os.PathLike[str] | None = None,
        output_path: str | os.PathLike[str] | None = None,
        annotate: Callable[[str], None] | None = None,
    ) -> CiRunResult:
        """Inspect → fix → report for one failing CI step.

        Drives ``build_verify._verify_and_iterate`` (the REAL reason→edit→verify
        loop) with the injected ``fix_editor`` and the runner's verifier, then
        assembles a machine-readable :class:`CiRunResult`, writes the JSON
        artifact, appends step output vars, and emits GitHub-Actions annotations.

        ``snap_before`` is a ``forge_code_git`` snapshot taken before the run so
        the loop verifies only what this run touched. ``output_path`` defaults to
        ``$GITHUB_OUTPUT``; ``annotate`` defaults to stdout — both overridable for
        hermetic tests.
        """
        from . import forge_code_git

        findings = self.inspect_failures(context)

        editor = fix_editor or _no_fix_editor
        events: list[dict[str, Any]] = []

        # The real reason→edit→verify loop. Its return value is the GENUINE final
        # exit code: 0 iff the verifier subprocess ultimately passed.
        final_rc = _verify_and_iterate(
            cwd,
            snap_before,
            events.append,
            editor,
            goal or _clean(context.command, 120),
            verifier=self._verifier,
            max_fix_iters=self.max_fix_iters,
        )
        passed = final_rc == 0
        changed_files = forge_code_git.delta_since(cwd, snap_before)
        fixed = passed and any(e.get("fc") == "meta" for e in events)

        report = build_run_report(
            goal=goal or context.command,
            definition=definition,
            events=events,
            changed_files=changed_files,
            returncode=final_rc,
            ok=passed,
            outcome="completed" if passed else "failed",
            reason=f"CI fix loop exited {final_rc}" + (f"; {len(findings)} inspected finding(s)" if findings else ""),
        )

        annotations = self.build_annotations(context, findings, passed=passed, exit_code=final_rc, fixed=fixed)
        output_vars = self.build_output_vars(passed=passed, exit_code=final_rc, fixed=fixed, findings=len(findings))

        result = CiRunResult(
            status="passed" if passed else "failed",
            exit_code=final_rc,
            fixed=fixed,
            findings=findings,
            changed_files=changed_files,
            report=report,
            annotations=annotations,
            output_vars=output_vars,
        )

        if artifact_path is not None:
            result.write_artifact(artifact_path)
        sink = annotate or _default_annotation_sink
        for line in annotations:
            sink(line)
        write_output_vars(output_vars, output_path if output_path is not None else os.environ.get("GITHUB_OUTPUT"))
        return result
