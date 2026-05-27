"""Tests for the xfail-debt enforcement infrastructure.

Covers:
- scripts/xfail_inventory.py: AST-based xfail discovery, classification,
  arc-id extraction from commit subjects.
- scripts/forge/gates/xfail_growth_gate.py: BASE/HEAD count comparison,
  xfail-justified: trailer detection, FAIL message clarity.

The tests use synthetic Python source strings (no real test files) and
synthetic commit-message lists (no real git repo) so they're fast and
hermetic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.forge.gates.xfail_growth_gate import _has_justification  # noqa: E402
from scripts.xfail_inventory import (  # noqa: E402
    _arc_id_from_subject,
    _classify,
    _find_xfails_in_file,
)

# ---------------------------------------------------------------------------
# AST scanner (xfail_inventory.find_xfails)
# ---------------------------------------------------------------------------


def _write_test_file(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test_synth.py"
    p.write_text(content, encoding="utf-8")
    return p


def test_module_level_xfail_detected(tmp_path: Path) -> None:
    content = '''"""synth"""
import pytest
pytestmark = pytest.mark.xfail(reason="domain skeleton")
'''
    # Need REPO_ROOT resolution to work — patch the path to be repo-relative.
    # We approximate by writing INTO the repo's tests dir? No — _find_xfails_in_file
    # uses path.relative_to(REPO_ROOT). Use a path that IS under REPO_ROOT.
    target = REPO_ROOT / "tests" / "_synth_test_must_not_exist.py"
    target.write_text(content, encoding="utf-8")
    try:
        entries = _find_xfails_in_file(target)
        assert len(entries) == 1
        assert entries[0].scope == "module"
        assert entries[0].reason == "domain skeleton"
        assert entries[0].line == 3
    finally:
        target.unlink(missing_ok=True)


def test_function_level_xfail_detected() -> None:
    content = """import pytest

@pytest.mark.xfail(reason="flake on CI")
def test_thing():
    pass
"""
    target = REPO_ROOT / "tests" / "_synth_test_must_not_exist.py"
    target.write_text(content, encoding="utf-8")
    try:
        entries = _find_xfails_in_file(target)
        assert len(entries) == 1
        assert entries[0].scope == "function"
        assert "flake" in entries[0].reason
    finally:
        target.unlink(missing_ok=True)


def test_parametrize_xfail_detected() -> None:
    content = """import pytest

@pytest.mark.parametrize("x", [
    pytest.param(1, marks=pytest.mark.xfail(reason="bug A")),
    2,
])
def test_thing(x):
    pass
"""
    target = REPO_ROOT / "tests" / "_synth_test_must_not_exist.py"
    target.write_text(content, encoding="utf-8")
    try:
        entries = _find_xfails_in_file(target)
        assert len(entries) == 1
        assert entries[0].scope == "param"
        assert entries[0].reason == "bug A"
    finally:
        target.unlink(missing_ok=True)


def test_xfail_in_docstring_not_counted() -> None:
    """Regression guard: my earlier grep-based count caught xfail mentions
    in docstrings/comments. The AST walker must not."""
    content = '''"""This module talks about pytest.mark.xfail for educational reasons.

The reason="..." pattern is documented in pytest docs as xfail behavior.
"""

def test_real_test():
    pass
'''
    target = REPO_ROOT / "tests" / "_synth_test_must_not_exist.py"
    target.write_text(content, encoding="utf-8")
    try:
        entries = _find_xfails_in_file(target)
        assert len(entries) == 0
    finally:
        target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Reason classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("Domain skeleton pending implementation", "domain-stub"),
        ("Placeholder; raises NotImplementedError", "domain-stub"),
        ("Pre-existing bug surfaced by step-up runner", "step-up"),
        ("mixed-19 batch xfail", "step-up"),
        ("TestRRTConnect RNG flake on CI", "flake"),
        ("Race condition between worker A and B", "flake"),
        ("Windows-only feature; skipif equivalent", "platform-specific"),
        ("Tracked in docs/ops/remediation/STUB_TRACKING.md", "tracked"),
        ("Tracked separately per Pattern 19", "tracked"),
        ("", "other"),
        ("just because", "other"),
    ],
)
def test_classify_reason(reason: str, expected: str) -> None:
    assert _classify(reason) == expected


# ---------------------------------------------------------------------------
# Arc-id extraction from commit subjects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("test(mixed-19): xfail search domain", "mixed-19"),
        ("test(pathfinding): xfail RRTConnect flake", "pathfinding"),
        ("test(webhooks): xfail 3 pre-existing bugs", "webhooks"),
        ("fix(autonomy)+test(mixed-20): reconcile smoke + xfail", "mixed-20"),
        # Extractor is scoped to `test(...)` / `fix(...)+test(...)` patterns.
        # Other commit types return empty (they're not in the xfail arc taxonomy).
        ("chore(cleanup): not an xfail commit", ""),
        ("safety: unrelated work", ""),  # no parenthesized scope
    ],
)
def test_arc_id_extraction(subject: str, expected: str) -> None:
    assert _arc_id_from_subject(subject) == expected


# ---------------------------------------------------------------------------
# Justification-trailer detection
# ---------------------------------------------------------------------------


def test_trailer_detected_in_single_commit() -> None:
    messages = [
        "fix(memory): some change\n\nxfail-justified: telecom skeleton, tracked in STUB_TRACKING.md\n",
    ]
    found, reason = _has_justification(messages)
    assert found is True
    assert "telecom skeleton" in reason


def test_trailer_detected_in_one_of_many_commits() -> None:
    messages = [
        "fix(memory): unrelated",
        "chore: another",
        "test(siem): expansion\n\nxfail-justified: siem batch; tracked in mixed-19 arc\n",
        "docs: yet another",
    ]
    found, reason = _has_justification(messages)
    assert found is True


def test_empty_trailer_rejected() -> None:
    """`xfail-justified:` alone (no reason) doesn't pass."""
    messages = ["fix: thing\n\nxfail-justified: \n"]
    found, reason = _has_justification(messages)
    assert found is False
    assert reason == ""


def test_no_trailer_anywhere() -> None:
    messages = [
        "fix(memory): some change\n\nThomas-Agent: claude\n",
        "chore: cleanup",
    ]
    found, _ = _has_justification(messages)
    assert found is False


def test_trailer_case_insensitive() -> None:
    """xfail-justified, Xfail-Justified, XFAIL-JUSTIFIED — all accepted."""
    messages = ["fix: thing\n\nXFAIL-JUSTIFIED: legit reason\n"]
    found, reason = _has_justification(messages)
    assert found is True
    assert reason == "legit reason"


def test_trailer_must_be_at_line_start() -> None:
    """Reject false-positives where 'xfail-justified:' is mid-sentence."""
    messages = ["fix: thing\n\nThis is xfail-justified: but not as a trailer\n"]
    found, _ = _has_justification(messages)
    # Current implementation uses `stripped.lower().startswith` so leading
    # whitespace is OK but mid-line text is not.
    assert found is False
