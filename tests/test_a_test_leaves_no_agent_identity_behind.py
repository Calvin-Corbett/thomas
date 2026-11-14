"""A test leaves no agent identity behind for the next one.

``scripts/active_folders.py`` exports a live session into ``os.environ`` and ``scripts/auto_checks.py`` fills ``AGENT_ID``
with the account name. Tests run both, and only ``THOMAS_`` keys were put back, so every commit-tool test that came later
on the same worker failed with ``session_identity``: 71 tests failed in a full run and passed alone, on a commit from
before the plugin work as well as after it.
"""

from __future__ import annotations

import os

import pytest

KEYS = ("AGENT_ID", "AGENT_SESSION_ID")


@pytest.fixture(scope="module")
def as_found() -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in KEYS}


def test_a_test_writes_the_identity_of_a_session_into_the_environment(as_found) -> None:
    os.environ.update(dict.fromkeys(KEYS, "left-behind"))


def test_the_next_test_finds_the_environment_as_it_was(as_found) -> None:
    assert {key: os.environ.get(key) for key in KEYS} == as_found
