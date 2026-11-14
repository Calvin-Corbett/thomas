"""A Build run started on Autopilot starts.

Build's settings accept autonomy 5 (Autopilot) since 5213bb30, but the runner
process a Build launches still allowed only 1 to 4. Every Autopilot Build exited 2
before doing any work ("argument --autonomy: invalid choice: '5'"), observed on
2026-09-23 on a Pokemon build that then worked when Chat handed it over.
"""

from __future__ import annotations

import pytest

from thomas.forge.anvil.forge_code_runner import build_parser
from thomas.forge.anvil.forge_code_settings import AUTONOMY_LEVELS, _autonomy_value

BASE = ["--project-root", "C:/project", "--family", "gpt", "--model", "gpt-5.6-sol"]


@pytest.mark.parametrize("level", AUTONOMY_LEVELS)
def test_the_runner_accepts_every_level_build_settings_accept(level: int) -> None:
    accepted = _autonomy_value(level)
    assert build_parser().parse_args([*BASE, "--autonomy", str(accepted)]).autonomy == level


def test_autopilot_is_one_of_those_levels() -> None:
    assert 5 in AUTONOMY_LEVELS
