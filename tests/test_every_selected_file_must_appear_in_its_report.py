"""A passing neighbour cannot stand in for a selected file that never ran."""

from pathlib import Path

import pytest

from thomas.server.proof import runner


@pytest.mark.parametrize("folder, strict_report", [(True, True), (False, False), (False, True)])
def test_a_missing_selected_module_holds_a_passing_shard(tmp_path: Path, folder: bool, strict_report: bool) -> None:
    files = ["tests/test_seen.py", "tests/test_missing.py"]
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(exist_ok=True)
        target.write_text("def test_ok():\n    pass\n", encoding="utf-8")

    def report_only_the_neighbour(argv, cwd, env, timeout_s):
        report = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--junit-xml=")))
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            '<testsuite><testcase file="tests/test_seen.py" classname="tests.test_seen" name="test_ok"/></testsuite>',
            encoding="utf-8",
        )
        return 0, "one selected file never collected"

    result = runner.run_tests(
        tmp_path,
        files,
        python="python",
        data_dir=tmp_path / "data",
        shard_files=2,
        folder=folder,
        strict_report=strict_report,
        run=report_only_the_neighbour,
    )

    assert not result.ran
    assert result.unrun == ("tests/test_missing.py",)
    assert "tests/test_missing.py" in result.why
    assert result.seen == 1


def test_a_file_only_collection_error_accounts_for_its_module(tmp_path: Path) -> None:
    from thomas.server.proof import junit

    report = tmp_path / "report.xml"
    report.write_text(
        '<testsuite><testcase file="tests/test_broken.py"><error>collection failed</error></testcase></testsuite>',
        encoding="utf-8",
    )
    read = junit.read_report(report, tmp_path)
    assert read is not None
    assert read.failed == ("tests/test_broken.py",)
    assert junit.without_cases(read, ["tests/test_broken.py"]) == ()
