"""The browser E2E gate must not claim to enforce while nothing calls it.

Measured on dev ``6f16ff21`` over 3139 non-test ``.py`` files under ``thomas/``
+ ``scripts/``.  The import graph is the same BEFORE and AFTER -- only the
claim changed::

    thomas.browser.e2e_gate       0 production importer(s) -> []
    thomas.agent.completion_gate  1 -> thomas/agent/loop_completion.py:11
    production constructors of E2EFlow(...)                -> NONE

BEFORE, the module docstring opened "Real-browser click-type-assert E2E as a
required done gate" and said a missing or failed run "*blocks* completion".
Zero importers means nothing was ever blocked, so those sentences were false.
AFTER, it carries the dormancy notice and the numbers agree.  These tests give
4 failed / 2 passed against the old text, 6 passed against the new, and
1 failed / 2 passed / 3 skipped once a production importer exists -- that last
failure demanding the notice be *deleted*.

``thomas.agent.completion_gate`` is the CONTROL: a gate of the same shape that
*is* wired in.  If the probe below could not see that one, a zero for the E2E
gate would prove nothing.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import pytest

from thomas.browser import e2e_gate

REPO_ROOT = Path(__file__).resolve().parents[1]

# The exact sentence the docstring must carry while the module is unreachable.
DORMANCY_NOTICE = "DORMANT: nothing in production imports this module"

# Sentences that claimed enforcement this module does not perform.
ENFORCEMENT_CLAIMS = (
    "E2E as a required done gate",
    "promotes browser validation to a *required* completion",
    "the result is promoted to a REQUIRED gate",
)


def _is_test_path(rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return rel.startswith("tests/") or base.startswith("test_") or "/test_" in rel


@lru_cache(maxsize=1)
def _production_sources() -> tuple[tuple[str, str], ...]:
    """(relative path, text) for every non-test .py file under thomas/ and scripts/."""
    rows: list[tuple[str, str]] = []
    for top in ("thomas", "scripts"):
        for path in (REPO_ROOT / top).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if _is_test_path(rel) or any(part.startswith(".") for part in rel.split("/")):
                continue
            try:
                rows.append((rel, path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return tuple(rows)


@lru_cache(maxsize=4)
def _production_importers(module: str) -> tuple[str, ...]:
    """Every non-test .py file under thomas/ or scripts/ that imports ``module``."""
    tail = module.rsplit(".", 1)[-1]
    parent = module.rsplit(".", 1)[0]
    self_path = module.replace(".", "/") + ".py"
    found: set[str] = set()
    for rel, text in _production_sources():
        # Cheap pre-filter: an import of the module must name its last segment.
        if rel == self_path or tail not in text:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == module or (mod == parent and any(a.name == tail for a in node.names)):
                    found.add(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Import):
                if any(a.name == module or a.name.startswith(module + ".") for a in node.names):
                    found.add(f"{rel}:{node.lineno}")
    return tuple(sorted(found))


def test_the_probe_can_see_a_gate_that_is_actually_wired_up() -> None:
    """CONTROL: the same probe reports the live completion gate as reachable."""
    control = _production_importers("thomas.agent.completion_gate")
    assert control, "probe found no importer of a gate that IS wired in; it cannot measure reachability"
    assert any(item.startswith("thomas/agent/loop_completion.py:") for item in control), control


def test_the_docstring_agrees_with_whether_production_calls_the_gate() -> None:
    """The dormancy notice and the import graph must agree, in both directions."""
    doc = e2e_gate.__doc__ or ""
    callers = _production_importers("thomas.browser.e2e_gate")
    claims_dormant = DORMANCY_NOTICE in doc

    if callers:
        assert not claims_dormant, f"e2e_gate is now imported by {callers} -- delete the DORMANT notice."
    else:
        assert claims_dormant, f"nothing imports e2e_gate, so it blocks nothing; docstring needs {DORMANCY_NOTICE!r}."


@pytest.mark.parametrize("phrase", ENFORCEMENT_CLAIMS)
def test_the_docstring_does_not_claim_enforcement_it_never_performs(phrase: str) -> None:
    """These exact sentences claimed enforcement; none may return while importers is 0."""
    if _production_importers("thomas.browser.e2e_gate"):
        pytest.skip("the gate has a production caller; enforcement language is now earned")
    assert phrase not in (e2e_gate.__doc__ or ""), f"docstring still claims enforcement: {phrase!r}"


def test_production_still_builds_no_e2e_flow_for_the_gate_to_run() -> None:
    """The blocker is a missing input: E2EFlow is built only under tests/.

    If this fails, a flow producer exists and wiring the gate is a real option.
    """
    producers = [
        rel for rel, text in _production_sources() if rel != "thomas/browser/e2e_gate.py" and "E2EFlow(" in text
    ]
    assert not producers, f"E2EFlow is now built in production ({producers}); the gate may be wirable"
