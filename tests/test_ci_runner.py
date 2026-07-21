"""CAP-065 — CI-native execution.

Acceptance line: "Let Thomas run inside CI, inspect failures, create a fix, and
report a machine-readable result."

These tests prove every clause OFFLINE:

* INSPECT — a real CI failure context (pytest summary, traceback, compile error)
  parses into structured findings.
* CREATE A FIX — the runner drives ``build_verify``'s real reason→edit→verify
  loop over a throwaway git repo; the loop's pass/fail comes from the GENUINE
  exit code of a real byte-compile subprocess. A fake fix editor (no live model)
  writes the corrected file; a non-fixing editor leaves it broken.
* MACHINE-READABLE — the emitted result carries every required field and
  round-trips through ``json.loads``.
* CI-NATIVE OUTPUTS — GitHub-Actions ``::error``/``::notice`` annotations and
  ``name=value`` step output vars are emitted for both a failing and a passing
  run, captured via an in-memory sink and a temp ``$GITHUB_OUTPUT`` file.

The VERIFY edge uses the REAL ``verify_python_changes`` (hermetic: it only
byte-compiles files in a temp dir — no network). The model-edit edge and CI
output edges are injected fakes. No live model dispatch runs here.
"""

from __future__ import annotations

import json
from pathlib import Path

from thomas.forge.anvil import forge_code_git
from thomas.forge.anvil.ci_runner import (
    REQUIRED_RESULT_FIELDS,
    CiFailureContext,
    CiRunner,
    format_annotation,
    parse_failure_context,
    write_output_vars,
)
from thomas.forge.anvil.forge_code_git import _run_git

_GOOD_SOURCE = "def add(a, b):\n    return a + b\n"
_BROKEN_SOURCE = "def add(a, b):\n    return a +\n"  # SyntaxError: invalid syntax
# A valid fix that DIFFERS from the committed baseline, so git shows a real
# net delta for the run (a real CI fix lands new content, not the old bytes).
_FIXED_SOURCE = '"""Adds two numbers."""\n\n\ndef add(a, b):\n    return a + b\n'


def _init_repo(root: Path) -> None:
    _run_git(root, ["init"])
    _run_git(root, ["config", "user.email", "ci@example.com"])
    _run_git(root, ["config", "user.name", "CI Test"])
    _run_git(root, ["config", "commit.gpgsign", "false"])


def _commit_all(root: Path, message: str = "seed") -> None:
    _run_git(root, ["add", "-A"])
    _run_git(root, ["commit", "-m", message])


def _repo_with_broken_file(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    """Commit a good module, snapshot clean, then break it on disk.

    Returns ``(root, relpath, snap_before)`` where ``snap_before`` predates the
    break, so ``delta_since`` sees the broken file as this run's change.
    """
    root = tmp_path
    _init_repo(root)
    rel = "calc.py"
    (root / rel).write_text(_GOOD_SOURCE, encoding="utf-8")
    _commit_all(root)
    snap_before = forge_code_git.snapshot(root)  # clean tree
    (root / rel).write_text(_BROKEN_SOURCE, encoding="utf-8")  # introduce the failure
    return root, rel, snap_before


# --- (1) INSPECT FAILURES ---------------------------------------------------

_PYTEST_OUTPUT = "\n".join(
    [
        "============================= test session starts ==============================",
        'File "calc.py", line 2, in add',
        "    return a +",
        "SyntaxError: invalid syntax",
        "=========================== short test summary info ============================",
        "FAILED tests/test_calc.py::test_add - assert 3 == 5",
        "ERROR src/mod.py::test_boot - ImportError: cannot import name x",
        "======================== 1 failed, 2 passed in 0.12s ===========================",
    ]
)


def test_inspect_parses_failure_context_into_structured_findings() -> None:
    context = CiFailureContext(command="pytest -q", output=_PYTEST_OUTPUT, exit_code=1, job="ci", step="tests")
    findings = parse_failure_context(context)

    kinds = {f.kind for f in findings}
    assert "test_failure" in kinds
    # The pytest FAILED summary parsed to a structured finding on the right file.
    failed = next(f for f in findings if f.kind == "test_failure" and f.file == "tests/test_calc.py")
    assert "assert 3 == 5" in failed.message
    # The traceback frame + following exception line combined into one finding.
    exc = next(f for f in findings if f.kind == "exception")
    assert exc.file == "calc.py" and exc.line == 2
    assert exc.message.startswith("SyntaxError")


def test_inspect_falls_back_to_command_failure_when_unparseable() -> None:
    context = CiFailureContext(command="make build", output="totally opaque blob", exit_code=2)
    findings = parse_failure_context(context)
    assert len(findings) == 1
    assert findings[0].kind == "command_failure"
    assert "exit 2" in findings[0].message


# --- (2) CREATE A FIX — pass/fail from the REAL exit code -------------------


def test_fix_loop_reports_pass_from_real_exit_code(tmp_path: Path) -> None:
    root, rel, snap_before = _repo_with_broken_file(tmp_path)
    context = CiFailureContext(command="pytest -q", output=_PYTEST_OUTPUT, exit_code=1, job="ci", step="tests")

    fix_calls: list[str] = []

    def fake_editor(prompt: str) -> tuple[int, str]:
        # The reason→edit adapter: a hermetic stand-in for the live model that
        # actually writes the corrected file, then reports its edit pass exit 0.
        fix_calls.append(prompt)
        (root / rel).write_text(_FIXED_SOURCE, encoding="utf-8")
        return 0, "applied fix"

    sink: list[str] = []
    result = CiRunner(max_fix_iters=2).run(
        context,
        cwd=root,
        snap_before=snap_before,
        fix_editor=fake_editor,
        goal="keep calc.py importable",
        annotate=sink.append,
        output_path=tmp_path / "gh_output.txt",
    )

    # Real subprocess byte-compiled the fixed file and returned 0.
    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.fixed is True
    assert fix_calls, "the fix editor was actually driven by the loop"
    # The failure prompt carried the real verifier output back to the editor.
    assert "SyntaxError" in fix_calls[0] or "exit" in fix_calls[0]
    assert rel in result.changed_files


def test_fix_loop_reports_fail_from_real_exit_code(tmp_path: Path) -> None:
    root, rel, snap_before = _repo_with_broken_file(tmp_path)
    context = CiFailureContext(command="pytest -q", output=_PYTEST_OUTPUT, exit_code=1)

    def non_fixing_editor(prompt: str) -> tuple[int, str]:
        # Edits, but leaves the file broken — re-verification must still fail from
        # the genuine non-zero exit code, never be papered over.
        (root / rel).write_text(_BROKEN_SOURCE + "\nstill broken +\n", encoding="utf-8")
        return 0, "edited but not fixed"

    result = CiRunner(max_fix_iters=1).run(
        context,
        cwd=root,
        snap_before=snap_before,
        fix_editor=non_fixing_editor,
        annotate=lambda _line: None,
        output_path=tmp_path / "gh_output.txt",
    )
    assert result.status == "failed"
    assert result.exit_code != 0


def test_default_editor_declines_and_run_stays_inspection_only(tmp_path: Path) -> None:
    root, _rel, snap_before = _repo_with_broken_file(tmp_path)
    context = CiFailureContext(command="pytest -q", output=_PYTEST_OUTPUT, exit_code=1, job="ci", step="tests")
    # No fix_editor injected -> the honest default declines; run reports failed.
    result = CiRunner().run(
        context, cwd=root, snap_before=snap_before, annotate=lambda _l: None, output_path=tmp_path / "o.txt"
    )
    assert result.status == "failed"
    assert result.fixed is False
    assert result.findings, "inspection findings survive even when no fix is applied"


# --- (3) MACHINE-READABLE RESULT — required fields + re-parse --------------


def test_machine_readable_result_has_required_fields_and_reparses(tmp_path: Path) -> None:
    root, rel, snap_before = _repo_with_broken_file(tmp_path)
    context = CiFailureContext(command="pytest -q", output=_PYTEST_OUTPUT, exit_code=1, job="ci", step="tests")

    def fake_editor(_prompt: str) -> tuple[int, str]:
        (root / rel).write_text(_FIXED_SOURCE, encoding="utf-8")
        return 0, "fixed"

    artifact = tmp_path / "ci_result.json"
    result = CiRunner(max_fix_iters=2).run(
        context,
        cwd=root,
        snap_before=snap_before,
        fix_editor=fake_editor,
        goal="Build calc.\n- add two numbers",
        annotate=lambda _l: None,
        output_path=tmp_path / "gh_output.txt",
        artifact_path=artifact,
    )

    payload = result.to_dict()
    for field_name in REQUIRED_RESULT_FIELDS:
        assert field_name in payload, f"missing required field {field_name}"

    # The embedded machine-readable report keeps all five CAP-141 sections.
    assert set(payload["report"]) == {
        "attempts",
        "validations",
        "open_risks",
        "attention_pointers",
        "rubric_mapping",
    }
    # Re-parses from disk with every field intact.
    assert artifact.exists()
    reparsed = json.loads(artifact.read_text(encoding="utf-8"))
    assert reparsed["schema"] == "thomas.ci.result"
    assert reparsed["status"] == "passed"
    assert reparsed["exit_code"] == 0
    assert isinstance(reparsed["findings"], list) and reparsed["findings"]
    # A validation records the real engine check that actually ran.
    assert any(v["kind"] == "engine_check" for v in reparsed["report"]["validations"])


# --- (4) CI-NATIVE ANNOTATIONS + OUTPUT VARS — failing AND passing ---------


def test_failing_run_emits_error_annotations_and_output_vars(tmp_path: Path) -> None:
    root, _rel, snap_before = _repo_with_broken_file(tmp_path)
    context = CiFailureContext(command="pytest -q", output=_PYTEST_OUTPUT, exit_code=1, job="ci", step="tests")
    sink: list[str] = []
    gh_output = tmp_path / "gh_output.txt"

    result = CiRunner(max_fix_iters=0).run(
        context,
        cwd=root,
        snap_before=snap_before,
        fix_editor=lambda _p: (1, "no fix"),
        annotate=sink.append,
        output_path=gh_output,
    )
    assert result.status == "failed"
    # An ::error annotation line was emitted through the sink for each finding.
    assert sink and all(line.startswith("::error") for line in sink)
    assert len(sink) == len(result.findings)
    # Output vars appended as GitHub-Actions name=value lines.
    written = gh_output.read_text(encoding="utf-8")
    assert "status=failed" in written
    assert "fixed=false" in written
    assert any(line.startswith("exit_code=") for line in written.splitlines())


def test_passing_run_emits_notice_annotation_and_output_vars(tmp_path: Path) -> None:
    root, rel, snap_before = _repo_with_broken_file(tmp_path)
    context = CiFailureContext(command="pytest -q", output=_PYTEST_OUTPUT, exit_code=1, job="ci", step="tests")
    sink: list[str] = []
    gh_output = tmp_path / "gh_output.txt"

    def fake_editor(_p: str) -> tuple[int, str]:
        (root / rel).write_text(_FIXED_SOURCE, encoding="utf-8")
        return 0, "fixed"

    result = CiRunner(max_fix_iters=2).run(
        context,
        cwd=root,
        snap_before=snap_before,
        fix_editor=fake_editor,
        annotate=sink.append,
        output_path=gh_output,
    )
    assert result.status == "passed"
    assert sink and sink[0].startswith("::notice")
    written = gh_output.read_text(encoding="utf-8")
    assert "status=passed" in written
    assert "fixed=true" in written


# --- workflow-command formatting details -----------------------------------


def test_annotation_escaping_and_output_var_noop() -> None:
    line = format_annotation("error", "bad: a, b\nnext", file="a.py", line=7, title="ci / tests")
    assert line.startswith("::error ")
    assert "file=a.py,line=7" in line
    assert "title=ci / tests" in line  # '/' is not a reserved property char
    assert "%0A" in line  # newline in the message is escaped in the DATA payload
    assert "bad:" in line  # a colon in the message DATA is left intact
    # A colon in a PROPERTY value is escaped to %3A so it can't break parsing.
    colon_line = format_annotation("error", "boom", file="pkg:mod.py", line=1)
    assert "file=pkg%3Amod.py" in colon_line
    # write_output_vars is a safe no-op when no $GITHUB_OUTPUT path exists.
    assert write_output_vars({"a": "b"}, None) is False
