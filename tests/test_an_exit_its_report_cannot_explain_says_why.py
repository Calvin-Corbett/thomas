"""When pytest's exit and its report disagree, the check says what pytest gave as the reason (2026-10-28).

d79480 was held with "shard 3 of 30: pytest exit 1 contradicts its report" on both copies, and nothing said why: the
same twelve files passed with exit 0 outside the cage. tests/conftest.py prints its reason (a real-data access) in
the run's own output; the hold now carries it, so the cause is on the card's record instead of only in a log no one
can read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.proof import runner

TRIPWIRE = """
20 passed in 31.90s
!!!!!!!!!!!!! REAL THOMAS DATA ACCESS OR UNATTRIBUTED CHANGE DURING THIS TEST RUN !!!!!!!!!!!!!
C:\\Users\\thomas-agent\\AppData\\Local\\Thomas\\settings.json was opened by this test run
C:\\Users\\thomas-agent\\.thomas\\projects was written during the run (a -> b)
Tests ran with THOMAS_DATA_DIR, THOMAS_OWNED_ROOT and THOMAS_SELF_EDIT_HOME under C:\\Temp\\x.
In a green, external changes do not fail the run; direct test access does.
"""


def _run(tmp_path: Path, output: str):
    source = tmp_path / "tests/test_changed.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text("def test_ok(): pass\n", encoding="utf-8")

    def passing_report_exit_1(argv, cwd, env, timeout_s):
        report = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--junit-xml=")))
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            '<testsuite><testcase file="tests/test_changed.py" classname="tests.test_changed" name="test_ok"/></testsuite>',
            encoding="utf-8",
        )
        return 1, output

    return runner.run_tests(
        tmp_path, ["tests/test_changed.py"], python="python", data_dir=tmp_path / "data", run=passing_report_exit_1
    )


def test_the_tripwires_findings_are_carried_into_the_reason(tmp_path: Path) -> None:
    result = _run(tmp_path, TRIPWIRE)
    assert not result.ran and "contradicts its report" in result.why
    assert "settings.json was opened by this test run" in result.why
    assert "projects was written during the run" in result.why
    assert "Tests ran with" not in result.why


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("1 passed\nINTERNALERROR> KeyError: 'x'\n", "INTERNALERROR> KeyError: 'x'"),
        ("1 passed\nERROR: usage: pytest [options]\n", "ERROR: usage: pytest [options]"),
    ],
)
def test_otherwise_the_last_error_line_is_the_reason(tmp_path: Path, output: str, expected: str) -> None:
    assert expected in _run(tmp_path, output).why


def test_with_nothing_to_quote_the_reason_is_as_before(tmp_path: Path) -> None:
    result = _run(tmp_path, "1 passed in 0.1s\n")
    assert result.why.endswith("pytest exit 1 contradicts its report")
