"""The check a Build run closes with gets the time a team's own test run gets (2026-10-28).

``verify_python_changes`` reran a team's changed tests with a 120 s limit, while ``check.run`` gives the same tests
540 s. On a busy PC four test files took longer than 120 s: 7de85f and f01e9d each had "verification could not run:
... timed out after 120 seconds" three times in a row, and each time went back for a fix pass with nothing to fix.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil import build_verify
from thomas.tools import check_run


def test_the_closing_check_waits_as_long_as_check_run(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    given: list[float] = []

    def run_check(cmd, cwd, timeout):
        given.append(timeout)
        return 0, "1 passed"

    ok, rc, _summary = build_verify.verify_python_changes(
        tmp_path, ["tests/test_x.py"], lambda _e: None, run_check=run_check
    )

    assert (ok, rc) == (True, 0)
    assert given == [check_run.DEFAULT_TIMEOUT_S]
