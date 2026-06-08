"""Blast-radius verification: a promotion is gated on the change's OWN tests.

Before this, the evolve loop verified a change with only py_compile (does it
parse?) + test_architecture (is layering intact?). Neither runs the changed
code's behavioural tests, so a change could break a feature yet still promote.
These tests pin the upgrade: the changed module's importing test files are
pulled into verification.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil.evolve import (
    DEFAULT_VERIFY_COMMANDS,
    EvolveCharter,
    _blast_radius_tests,
    _build_verify_commands,
)

REPO = Path(__file__).resolve().parents[1]


def test_blast_radius_finds_the_modules_own_tests():
    # Editing the planner should pull its own test file into verification.
    hits = _blast_radius_tests(["thomas/forge/anvil/evolve_planner.py"], REPO)
    assert any("test_evolve_planner" in h for h in hits), hits


def test_blast_radius_finds_tests_for_the_autonomy_gate():
    hits = _blast_radius_tests(["thomas/forge/anvil/evolve_autonomy.py"], REPO)
    assert any("test_evolve_autonomy" in h for h in hits), hits


def test_blast_radius_is_empty_for_non_thomas_changes():
    # Docs / non-python changes have no behavioural blast radius.
    assert _blast_radius_tests(["README.md", "CHANGELOG.md"], REPO) == []
    assert _blast_radius_tests([], REPO) == []


def test_build_verify_commands_adds_blast_radius_AND_keeps_architecture():
    charter = EvolveCharter()  # default verify ladder = test_architecture
    delta = {"changed_files": ["thomas/forge/anvil/evolve_autonomy.py"]}
    cmds = _build_verify_commands(charter, delta, REPO)
    flat = " ".join(str(c) for c in cmds)
    # 1) it still compiles the change
    assert "py_compile" in flat
    # 2) NEW: it runs the change's own blast-radius tests
    assert "pytest" in flat and "test_evolve_autonomy" in flat, cmds
    # 3) and it still runs the architecture ladder (no regression)
    assert "test_architecture" in flat


def test_evolve_charter_migrates_legacy_default_verify_ladder():
    charter = EvolveCharter.from_dict(
        {"verify_commands": ['python -m pytest tests/test_architecture.py -q -k "not test_no_new_legacy_files"']}
    )
    assert charter.verify_commands == DEFAULT_VERIFY_COMMANDS
    assert "not test_debt_trending" in charter.verify_commands[0]


def test_evolve_charter_preserves_custom_verify_ladder():
    command = "python -m pytest tests/test_evolve_blast_radius.py -q"
    charter = EvolveCharter.from_dict({"verify_commands": [command]})
    assert charter.verify_commands == [command]
