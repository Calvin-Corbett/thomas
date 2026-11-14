"""A send-back carries each failing test's own error, not just its name.

Measured 2026-11-06: send-backs named the failing tests but never their error, so the repair agent re-ran them to see
it, a median of 6 test runs a repair round (1,687 in all over the conversations looked at). The JUnit report every
shard already writes holds the error; it now travels with the run (``ProofRun.details``) into the findings.
"""

from __future__ import annotations

from pathlib import Path

from thomas.server.precard import report
from thomas.server.precard.lint import LintResult
from thomas.server.proof import junit
from thomas.server.proof.compare import Verdict

CLEAN = LintResult(True, "", (), ())
XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="1">
<testcase classname="tests.test_x" name="test_ok" file="tests/test_x.py"/>
<testcase classname="tests.test_x" name="test_total" file="tests/test_x.py">
<failure message="AssertionError: assert 3 == 4">{trace}</failure></testcase>
</testsuite></testsuites>"""


def _report(tmp_path: Path, trace: str) -> junit.Report:
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_x.py").write_text("", encoding="utf-8")
    path = tmp_path / "report.xml"
    path.write_text(XML.format(trace=trace), encoding="utf-8")
    read = junit.read_report(path, tmp_path)
    assert read is not None
    return read


def test_the_report_keeps_each_failures_last_lines(tmp_path: Path) -> None:
    lines = [f"frame {i}" for i in range(60)] + ["&gt;       assert total(1, 2) == 4", "E       assert 3 == 4"]
    read = _report(tmp_path, "\n".join(lines))
    ((test, said),) = read.details
    assert test == "tests/test_x.py::test_total" and read.failed == (test,)
    assert said.splitlines()[-1] == "E       assert 3 == 4" and "assert total(1, 2) == 4" in said
    assert "frame 0" not in said and len(said.splitlines()) <= junit.DETAIL_LINES + 1


def test_the_findings_show_what_each_failing_test_said(tmp_path: Path) -> None:
    read = _report(tmp_path, "E       assert 3 == 4")
    verdict = Verdict(read.failed, (), (), (), ())
    text = report.findings_text("abc1234", verdict, CLEAN, [], details=dict(read.details))
    assert report.SAID_HEAD in text
    assert "tests/test_x.py::test_total:\n    " in text and "assert 3 == 4" in text


def test_without_details_the_findings_are_as_before(tmp_path: Path) -> None:
    read = _report(tmp_path, "E       assert 3 == 4")
    verdict = Verdict(read.failed, (), (), (), ())
    assert report.SAID_HEAD not in report.findings_text("abc1234", verdict, CLEAN, [])


def test_a_long_list_is_cut_to_keep_the_send_back_short() -> None:
    names = [f"tests/test_{i}.py::test_a" for i in range(40)]
    details = {name: "\n".join(["E   " + "x" * 90] * 20) for name in names}
    said = report._said_block(names, details)
    assert len(said) < report._SAID_CHARS + 500
    assert said.endswith("re-run one on its own to see it)")
