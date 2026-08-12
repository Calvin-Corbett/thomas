"""Concurrent Code-run cap is configurable, not a hard 3 (Calvin: run many projects at once).

Regression for the "another Code run is still active / all N slots are busy" 409
block: the ceiling is now live-configurable via THOMAS_MAX_CONCURRENT_CODE_RUNS
with a generous default, so different Code projects (distinct conversations) run
concurrently instead of being serialized behind a single slot.
"""

from __future__ import annotations

import importlib

import pytest

routes = importlib.import_module("thomas.server.routes.evolve_agent_routes")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_MAX_CONCURRENT_CODE_RUNS", raising=False)


def test_default_cap_is_generous_and_not_the_old_hard_three() -> None:
    assert routes._max_concurrent_code_runs() == routes.DEFAULT_MAX_CONCURRENT_CODE_RUNS
    assert routes.DEFAULT_MAX_CONCURRENT_CODE_RUNS >= 8  # decisively above the old cap of 3


def test_env_override_raises_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_MAX_CONCURRENT_CODE_RUNS", "25")
    assert routes._max_concurrent_code_runs() == 25


def test_env_override_is_clamped_to_the_safety_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_MAX_CONCURRENT_CODE_RUNS", "100000")
    assert routes._max_concurrent_code_runs() == routes._CODE_RUN_CEILING


@pytest.mark.parametrize("bad", ["", "  ", "abc", "0", "-4", "3.5"])
def test_invalid_or_nonpositive_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("THOMAS_MAX_CONCURRENT_CODE_RUNS", bad)
    assert routes._max_concurrent_code_runs() == routes.DEFAULT_MAX_CONCURRENT_CODE_RUNS


def test_back_compat_constant_matches_default() -> None:
    # Callers/tests importing the old constant name still get the (raised) default.
    assert routes.MAX_CONCURRENT_CODE_RUNS == routes.DEFAULT_MAX_CONCURRENT_CODE_RUNS
