"""A test starts without the tasks and projects an earlier test on its worker left.

Each test here says this on its own. Which tests share a worker changes from run to run, which is how these leaks
stayed hidden and then surfaced one at a time, so a pair of tests here would pass or fail by the same luck.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.between_tests import forget_other_tests_work
from thomas.core import task_bot_runtime


def test_the_fixture_that_empties_them_runs_for_every_test(request: pytest.FixtureRequest) -> None:
    assert "_no_test_reads_another_tests_work" in request.fixturenames


def test_a_task_left_on_the_shared_ledger_is_gone_for_the_next_test(tmp_path: Path) -> None:
    left = str(task_bot_runtime.create_execution(session_id="left-behind", summary="unfinished")["execution_id"])
    assert task_bot_runtime.get_execution(left) is not None

    forget_other_tests_work(tmp_path / "owned")

    assert task_bot_runtime.get_execution(left) is None


def test_a_project_left_in_the_owned_root_is_gone_for_the_next_test(tmp_path: Path) -> None:
    project = tmp_path / "owned" / "projects" / "left behind"
    project.mkdir(parents=True)

    forget_other_tests_work(tmp_path / "owned")

    assert not project.exists()
