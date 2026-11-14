"""A collected descendant is not evidence that a selected same-stem file ran."""

from pathlib import Path

from thomas.server.proof import junit


def test_unselected_descendant_cannot_stand_in_for_selected_file(tmp_path: Path) -> None:
    for relative in ("tests/test_pkg.py", "tests/test_pkg/test_inner.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok(): pass\n", encoding="utf-8")
    report_path = tmp_path / "report.xml"
    report_path.write_text(
        '<testsuite><testcase classname="tests.test_pkg.test_inner" name="test_ok"/></testsuite>',
        encoding="utf-8",
    )
    report = junit.read_report(report_path, tmp_path)
    assert report is not None
    assert junit.without_cases(report, ["tests/test_pkg.py"]) == ("tests/test_pkg.py",)
    assert junit.unexpected_modules(report, ["tests/test_pkg.py"]) == ("tests.test_pkg.test_inner",)
    assert junit.without_cases(report, ["tests/test_pkg/test_inner.py"]) == ()
    assert junit.unexpected_modules(report, ["tests/test_pkg/test_inner.py"]) == ()
