"""Only a completed rerun of the requested test can explain a failure away."""

from pathlib import Path

import pytest

from thomas.server.proof import compare, runner
from thomas.server.proof.environment import REFUSED, TIMED_OUT

NODE = "tests/test_changed.py::test_changed"


def rerun(tmp_path: Path, code: int, *, node: str = NODE, failed: bool = False, skipped: str = "") -> str:
    source = tmp_path / NODE.split("::", 1)[0]
    source.parent.mkdir(parents=True, exist_ok=True)
    source.touch()

    def run(argv, *, cwd, timeout_s, env):
        report = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--junit-xml=")))
        report.parent.mkdir(parents=True, exist_ok=True)
        file, name = node.split("::", 1)
        failure = '<failure message="broken"/>' if failed else skipped
        report.write_text(
            f'<testsuite><testcase file="{file}" name="{name}">{failure}</testcase></testsuite>',
            encoding="utf-8",
        )
        return code, "partial report"

    return runner.run_one(tmp_path, NODE, python="python", data_dir=tmp_path / "data", run=run)


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize(
    "code, expected", [(TIMED_OUT, runner.TIMEOUT), (REFUSED, runner.NO_PLACE), (3, runner.UNKNOWN)]
)
def test_partial_report_does_not_override_unfinished_process(tmp_path: Path, code: int, expected: str, failed: bool):
    assert rerun(tmp_path, code, failed=failed) == expected


@pytest.mark.parametrize("code", [0, 1])
def test_completed_report_must_contain_the_requested_test(tmp_path: Path, code: int):
    assert rerun(tmp_path, code, node="tests/test_other.py::test_other") == runner.UNKNOWN


@pytest.mark.parametrize("failed, code, expected", [(False, 0, runner.PASSED), (True, 1, runner.FAILED)])
def test_completed_requested_test_still_supplies_a_verdict(tmp_path: Path, failed: bool, code: int, expected: str):
    assert rerun(tmp_path, code, failed=failed) == expected


@pytest.mark.parametrize("code", [0, 1])
@pytest.mark.parametrize("skipped", ["<skipped/>", '<skipped type="pytest.xfail"/>'])
def test_skipped_requested_node_cannot_excuse_a_failure(tmp_path: Path, code: int, skipped: str):
    status = rerun(tmp_path, code, skipped=skipped)
    assert status == runner.UNKNOWN
    result = compare.confirm([NODE], rerun_on_base=lambda _: status, rerun_with_change=lambda _: status)
    assert result.blocking == (NODE,)
    assert NODE not in result.excused


def test_inherited_confirmation_uses_the_collected_node(tmp_path: Path):
    child = tmp_path / "tests/test_child.py"
    child.parent.mkdir(parents=True)
    child.write_text("class TestChild:\n    def test_changed(self): pass\n", encoding="utf-8")
    node = "tests/test_child.py::TestChild::test_changed"

    def run(argv, **kwargs):
        report = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--junit-xml=")))
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            '<testsuite><testcase file="tests/support.py" classname="tests.test_child.TestChild" '
            'name="test_changed"/></testsuite>',
            encoding="utf-8",
        )
        return 0, "completed inherited case"

    assert runner.run_one(tmp_path, node, python="python", data_dir=tmp_path / "data", run=run) == runner.PASSED


def test_unfinished_baseline_cannot_excuse_a_regression(tmp_path: Path):
    status = rerun(tmp_path, TIMED_OUT, failed=True)
    result = compare.confirm([NODE], rerun_on_base=lambda _: status, rerun_with_change=lambda _: runner.FAILED)
    assert result.blocking == (NODE,)
    assert NODE not in result.excused
