"""A run that names test files collects those files, without building every other file in tests/ (2026-10-29).

See tests/collect_only_named.py: each named file made pytest build a node for all ~1,900 files in tests/ again.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest
from tests.collect_only_named import named_files, pytest_ignore_collect

CHECKOUT = Path(__file__).resolve().parents[1]
GIT = "tests/test_check_run_starts_the_real_git.py"
CLOSING = "tests/test_the_closing_check_gets_check_runs_time.py"


def _config(*args: str) -> SimpleNamespace:
    return SimpleNamespace(args=list(args), invocation_params=SimpleNamespace(dir=CHECKOUT), stash=pytest.Stash())


def _ignored(config: SimpleNamespace, rel: str) -> bool | None:
    return pytest_ignore_collect(CHECKOUT / rel, config)


def test_the_hook_is_the_one_the_test_folder_runs_with() -> None:
    assert conftest.pytest_ignore_collect is pytest_ignore_collect


def test_named_files_are_kept_and_the_rest_passed_over() -> None:
    config = _config(GIT, f"{CLOSING}::test_the_closing_check_waits_as_long_as_check_run")
    assert _ignored(config, GIT) is None
    assert _ignored(config, CLOSING) is None, "a test named by its id keeps its file"
    assert _ignored(config, "tests/test_thomas_folders_are_not_indexed.py") is True
    assert _ignored(config, "tests/conftest.py") is None and _ignored(config, "tests/__init__.py") is None


def test_a_folder_or_a_missing_file_turns_it_off() -> None:
    for args in (("tests",), (GIT, "tests/web_node"), (GIT, "tests/test_no_such_file.py")):
        config = _config(*args)
        assert named_files(config) == frozenset()
        assert _ignored(config, "tests/test_thomas_folders_are_not_indexed.py") is None, args


def test_a_named_browser_harness_counts_as_a_named_file() -> None:
    config = _config("tests/web_node/branch_from_here.mjs", GIT)
    assert len(named_files(config)) == 2
    assert _ignored(config, CLOSING) is True


def test_a_real_run_collects_exactly_the_tests_it_named() -> None:
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", GIT, CLOSING],
        cwd=CHECKOUT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    collected = sorted(line for line in run.stdout.splitlines() if "::" in line)
    assert collected == sorted(
        [
            f"{GIT}::test_a_team_test_run_finds_the_real_git_before_the_launcher",
            f"{GIT}::test_off_windows_the_path_is_left_as_it_was",
            f"{CLOSING}::test_the_closing_check_waits_as_long_as_check_run",
        ]
    )
