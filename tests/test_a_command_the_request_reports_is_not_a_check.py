"""A command the request only reports on is not a command that must pass.

A size-rule request said: "`python scripts/forge/gates/monolith_guard.py` (the whole-repo run) prints "Monolith guard
FAILED: 6 violation(s)" on dev today", and later told the team to leave three of those violations. The contract made
the whole-repository guard a command that had to exit 0, which it never could, so the team finished the work and still
could not hand it in (2026-09-27). Mood decides, as it does for requirements: a command that is the subject of a report
in a sentence that asks for nothing is what the request saw, not a check. A report that also asks ("... fails; fix it")
still makes the command a check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core.acceptance_contract import KIND_COMMAND, build_contract


def _commands(text: str, ws: Path) -> list[str]:
    return [item.target for item in build_contract(text, ws) if item.kind == KIND_COMMAND]


def test_a_command_the_request_reports_on_is_not_a_check(tmp_path: Path) -> None:
    text = (
        '`python scripts/forge/gates/monolith_guard.py` (the whole-repo run) prints "Monolith guard FAILED: 6 '
        'violation(s)" on dev today. Split the three web files under the limit.'
    )
    assert _commands(text, tmp_path) == []


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("`pytest tests/test_x.py` fails with an ImportError; fix it.", "pytest tests/test_x.py"),
        ("Run `pytest tests/test_x.py` before you finish.", "pytest tests/test_x.py"),
        ("`npm test` must pass.", "npm test"),
        ("`make check` reports three errors and should report none.", "make check"),
    ],
)
def test_a_command_the_request_asks_for_is_still_a_check(tmp_path: Path, text: str, command: str) -> None:
    assert _commands(text, tmp_path) == [command]
