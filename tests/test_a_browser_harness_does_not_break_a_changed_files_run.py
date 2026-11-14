"""Handing pytest a browser harness must not take the whole run down with it.

Verification runs pytest over every changed path under ``tests/`` (``_is_test_file``
in thomas/forge/anvil/build_verify.py), and the browser harnesses live there: the
``.mjs`` files run the shipped modules under Node and the ``.html`` files drive
them in Chromium. Neither is a Python test module, and pytest handed a path it
has no collector for fails the ENTIRE run with "found no collectors" before a
single test executes -- so touching a fixture reports every test in the run as
not having happened. ``tests/conftest.py`` collects those paths and yields no
tests from them, which keeps such a run about the Python tests beside them.

The runs below are ``--collect-only``: what is being checked is whether pytest
accepts the paths, not what the tests do once they start.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "web_node" / "browser_search_rows.mjs"
PAGE = REPO_ROOT / "tests" / "web_node" / "browser_search_playtest.html"
REAL_TEST = REPO_ROOT / "tests" / "test_the_search_page_answers_in_every_state.py"

NO_TESTS_COLLECTED = 5  # pytest.ExitCode.NO_TESTS_COLLECTED
USAGE_ERROR = 4  # pytest.ExitCode.USAGE_ERROR -- what "found no collectors" exits with


def _collect(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *[str(p) for p in paths]],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        # Well inside the suite's own 300s per-test timeout: collecting three
        # named paths is seconds of work, and a hang here should name itself.
        timeout=120,
    )


def test_a_harness_path_beside_real_tests_leaves_those_tests_collected() -> None:
    """The shape a changed-files run actually has: a fixture and the test that drives it."""
    if not (HARNESS.exists() and REAL_TEST.exists()):
        pytest.skip("the Search harness is not present in this checkout")

    result = _collect(HARNESS, PAGE, REAL_TEST)
    output = result.stdout + result.stderr

    assert "found no collectors" not in output, output
    assert result.returncode != USAGE_ERROR, output
    assert result.returncode == 0, output
    assert "test_the_search_page_answers_in_every_state" in output, output


def test_a_harness_path_on_its_own_is_accepted_rather_than_an_error() -> None:
    """Alone, a harness collects nothing -- which is not the same as failing."""
    if not HARNESS.exists():
        pytest.skip("the Search harness is not present in this checkout")

    result = _collect(HARNESS)
    output = result.stdout + result.stderr

    assert "found no collectors" not in output, output
    # Nothing to run is honest here: the harness is asserted on from a test
    # module that starts it. What must not happen is the usage error that ends
    # the run before the other paths in it are collected.
    assert result.returncode == NO_TESTS_COLLECTED, output
