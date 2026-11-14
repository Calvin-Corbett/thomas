"""A successful-looking XML report cannot override pytest's unsuccessful exit."""

from pathlib import Path

import pytest

from thomas.server.proof import runner

NODE = "tests/test_changed.py::test_ok"


@pytest.mark.parametrize("code", [1, 5])
@pytest.mark.parametrize("confirmation", [False, True])
def test_unsuccessful_exit_cannot_turn_a_passing_report_into_proof(tmp_path: Path, code: int, confirmation: bool):
    source = tmp_path / "tests/test_changed.py"
    source.parent.mkdir()
    source.write_text("def test_ok(): pass\n", encoding="utf-8")

    def contradictory_report(argv, cwd, env, timeout_s):
        report = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--junit-xml=")))
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            '<testsuite><testcase file="tests/test_changed.py" classname="tests.test_changed" name="test_ok"/></testsuite>',
            encoding="utf-8",
        )
        return code, "pytest did not succeed"

    if confirmation:
        result = runner.run_one(tmp_path, NODE, python="python", data_dir=tmp_path / "data", run=contradictory_report)
        assert result == runner.UNKNOWN
    else:
        result = runner.run_tests(
            tmp_path, ["tests/test_changed.py"], python="python", data_dir=tmp_path / "data", run=contradictory_report
        )
        assert not result.ran
        assert "contradicts" in result.why
