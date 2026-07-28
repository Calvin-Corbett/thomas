"""ruff cannot verify a game, and must not report that it did.

`ruff check` over a folder of HTML and JavaScript prints "No Python files
found", says "All checks passed!", and exits 0. So a web workspace came back
`passed=True` with the evidence "ruff clean" -- a Python linter certifying
output it is structurally incapable of reading. Confirmed against real ruff: a
deliberately broken JavaScript file passes this check.

That is what Thomas mostly builds, so for his actual work the code-family gate
was passing vacuously while reporting the language of a real check.
"""

from __future__ import annotations

import shutil

import pytest

from thomas.marketplace.orchestrator.verification import (
    DEFAULT_CHECKERS,
    run_ruff_check,
    verify_deliverable,
)

_HAS_RUFF = shutil.which("ruff") is not None


@pytest.mark.skipif(not _HAS_RUFF, reason="needs a real ruff on PATH")
def test_a_web_workspace_is_not_reported_as_clean(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<script>const x = 1;</script>", encoding="utf-8")
    (tmp_path / "game.js").write_text("const x = 1;\nx = 2;\n", encoding="utf-8")

    result = run_ruff_check(str(tmp_path))

    assert result.checks == ("ruff_not_applicable",)
    assert "verified nothing" in result.evidence
    assert "clean" not in result.evidence


@pytest.mark.skipif(not _HAS_RUFF, reason="needs a real ruff on PATH")
def test_broken_javascript_is_not_evidence_of_anything(tmp_path) -> None:
    """The case that makes it concrete: ruff exits 0 on this."""
    (tmp_path / "broken.js").write_text("function ( { syntax error", encoding="utf-8")

    result = run_ruff_check(str(tmp_path))

    assert result.checks == ("ruff_not_applicable",)


@pytest.mark.skipif(not _HAS_RUFF, reason="needs a real ruff on PATH")
def test_a_real_python_workspace_is_still_linted(tmp_path) -> None:
    """Fixing the false pass must not disable the check that does work."""
    (tmp_path / "ok.py") .write_text("value = 1\n", encoding="utf-8")

    result = run_ruff_check(str(tmp_path))

    assert result.checks == ("ruff",)
    assert result.passed


@pytest.mark.skipif(not _HAS_RUFF, reason="needs a real ruff on PATH")
def test_a_python_error_still_fails(tmp_path) -> None:
    """A parse error rather than a style rule: which lint rules are enabled
    depends on config discovery walking up from the workspace, but nothing
    accepts source that cannot be parsed."""
    (tmp_path / "bad.py").write_text("def broken(:\n    return\n", encoding="utf-8")

    result = run_ruff_check(str(tmp_path))

    assert result.checks == ("ruff",)
    assert not result.passed


def test_a_missing_workspace_is_still_reported_as_skipped(tmp_path) -> None:
    result = run_ruff_check("")

    assert result.checks == ("skipped",)


def test_nothing_in_the_codebase_injects_richer_checkers() -> None:
    """The dispatch table is what actually runs. The old comment claimed
    production injected pytest; it never did, and a note asserting a safety
    property that is absent stops the next reader from looking.

    `ui` joined `code` on 2026-07-28, when the deterministic web preflight was
    hoisted into `thomas.tools.web_preflight` so this layer could call it. The
    point of the assertion is unchanged: whatever is in this dict is the whole
    truth about what runs, because nothing anywhere passes `checkers=`."""
    assert set(DEFAULT_CHECKERS) == {"code", "ui"}


def test_a_non_code_family_gets_the_structural_check(tmp_path) -> None:
    (tmp_path / "notes.md").write_text("# findings", encoding="utf-8")

    result = verify_deliverable("research", str(tmp_path), "wrote it up")

    assert result.checks == ("files_present",)
    assert "notes.md" in result.evidence
