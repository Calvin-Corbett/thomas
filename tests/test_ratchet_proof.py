"""A proof is read from pytest's JUnit report, and a proof that cannot run is never a pass."""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from thomas.server.green_checkout import Green
from thomas.server.ratchet import proof
from thomas.server.ratchet.proof import SideResult, boot_check, compare, parse_junit, run_side
from thomas.tools.cage_shell import CagedResult

# What pytest 9.1 writes with -o junit_family=xunit1 on Windows (measured 2026-09-24):
# a collection error has an empty classname, and file paths use backslashes.
REPORT = (
    '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
    '<testcase classname="" name="tests.test_two" file="tests/test_two.py" time="0.000">'
    '<error message="collection failure">ImportError</error></testcase>'
    '<testcase classname="tests.test_one" name="test_ok" file="tests\\test_one.py" line="0" time="0.001" />'
    '<testcase classname="tests.test_one.TestK" name="test_bad" file="tests\\test_one.py" line="4" time="0.001">'
    '<failure message="assert 0">E   assert 0</failure></testcase>'
    '<testcase classname="tests.test_one" name="test_skip" file="tests\\test_one.py" line="9" time="0.0">'
    '<skipped message="x" /></testcase>'
    "</testsuite></testsuites>"
)
A, B, OLD = "tests/test_one.py::test_a", "tests/test_one.py::test_b", "tests/test_one.py::test_old"


def _side(
    failing=None, passing=None, files=("tests/test_one.py",), ran=None, unrunnable=(), skipped=(), confirmed=None
) -> SideResult:
    failing, passing = dict(failing or {}), dict(passing or {})
    count = len(failing) + len(passing) if ran is None else ran
    return SideResult(tuple(files), failing, passing, count, tuple(unrunnable), frozenset(skipped), confirmed)


def _green(tmp_path: Path) -> Green:
    work = tmp_path / "green" / "work" / "ratchet-cand-aaaaaaa-bbbbbbb"
    work.mkdir(parents=True)
    return Green(work.name, work, tmp_path / "green" / "git" / work.name, "0" * 40, tmp_path / "blue")


def _local(command: str, *, cwd: str, timeout_s: float, **_: object) -> CagedResult:
    """The caged runner's way of running a line -- a shell, the whole line as typed -- with this venv's Python
    and without the cage (scripts/cage/shell_runner.py:375-390): for the one test that runs pytest itself."""
    python = f'"{sys.executable}"'
    line = command.replace("python -m pytest", f"{python} -m pytest", 1).replace("python -c", f"{python} -c", 1)
    argv = line if os.name == "nt" else ["bash", "-c", line]
    done = subprocess.run(argv, shell=os.name == "nt", cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
    return CagedResult("ok", done.returncode, done.stdout + done.stderr, "local")


def test_the_report_names_each_failure_and_a_collection_error_is_one() -> None:
    failing, passing, skipped = parse_junit(REPORT)

    assert failing == {
        "tests/test_two.py": "<collection> tests/test_two.py",
        "tests/test_one.py::TestK::test_bad": "TestK::test_bad",
    }
    assert passing == {"tests/test_one.py::test_ok": "test_ok"}
    assert skipped == {"tests/test_one.py::test_skip"}  # a skip or an xfail is not a pass


def test_a_missing_file_does_not_disappear_when_another_selected_file_runs(tmp_path: Path) -> None:
    green = _green(tmp_path)
    test = green.work / "tests" / "test_one.py"
    test.parent.mkdir()
    test.write_text("def test_ok(): pass\n", encoding="utf-8")

    result = run_side(green, ["tests/test_one.py", "tests/test_missing.py"], "cand", _local)

    assert result.unrunnable
    assert "tests/test_missing.py" in " ".join(result.unrunnable)


def test_shared_runner_refuses_an_unchanged_stale_report(tmp_path: Path) -> None:
    green = _green(tmp_path)
    test = green.work / "tests" / "test_one.py"
    test.parent.mkdir()
    test.write_text("def test_ok(): pass\n", encoding="utf-8")
    stale = proof.proof_folder(green) / "cand-1.xml"
    stale.parent.mkdir(parents=True)
    stale.write_text(REPORT, encoding="utf-8")

    def no_report(command: str, *, cwd: str, timeout_s: float, **_: object) -> CagedResult:
        return CagedResult("ok", 0, "pytest ran without a report", "local")

    result = run_side(green, ["tests/test_one.py"], "cand", no_report)
    assert result.unrunnable
    assert not result.passing
    assert not stale.exists()


def test_a_report_declaring_entities_is_refused_not_parsed() -> None:
    hostile = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><testsuites>&a;</testsuites>'

    with pytest.raises(ET.ParseError):
        parse_junit(hostile)


def test_only_a_failure_dev_does_not_already_have_blocks() -> None:
    base = _side({OLD: "test_old"}, {A: "test_a"})
    assert compare(base, _side({OLD: "test_old"}, {A: "test_a"})).ok
    # tests/test_one.py was deleted and its tests moved into a file the candidate added, failing as before
    moved = _side(
        {"tests/test_one_b.py::test_old": "test_old"},
        {"tests/test_one_b.py::test_a": "test_a"},
        files=("tests/test_one_b.py",),
    )
    assert compare(base, moved, changed=["tests/test_one.py", "tests/test_one_b.py"]).ok
    # the same bare name failing in a file the candidate did not touch is new, not moved
    elsewhere = _side(
        {OLD: "test_old", "tests/test_other.py::test_old": "test_old"},
        {A: "test_a"},
        files=("tests/test_one.py", "tests/test_other.py"),
    )
    assert compare(base, elsewhere).new_failures == ("tests/test_other.py::test_old",)

    verdict = compare(base, _side({OLD: "test_old", A: "test_a"}))

    assert not verdict.ok and verdict.new_failures == (A,)
    assert verdict.reason.startswith("1 new failure(s)")


def test_a_failure_dev_has_only_sometimes_excuses_nothing() -> None:
    base = _side({OLD: "test_old"}, confirmed=frozenset())  # it passed when run alone on dev

    assert compare(base, _side({OLD: "test_old"})).new_failures == (OLD,)


def test_a_test_that_disappears_or_a_proof_that_cannot_run_is_not_a_pass() -> None:
    base = _side({}, {A: "test_a", B: "test_b"})

    assert compare(base, _side({}, {A: "test_a"})).missing == (B,)
    assert compare(base, _side({}, {A: "test_a"}, skipped={B})).missing == (B,)  # skipped or xfailed with it
    assert not compare(base, _side({}, {}, unrunnable=("cand shard 1 could not run",))).ok
    assert "could not run on dev itself" in compare(_side(unrunnable=("x",)), _side({}, {A: "test_a"})).reason
    assert compare(base, _side({}, {}, ran=0)).reason == "the proof ran no tests"
    assert compare(base, base, left_out=2).reason.startswith("2 test file(s) that prove it were not run")


def test_a_failure_that_passes_alone_is_recorded_and_still_blocks() -> None:
    verdict = compare(_side({}, {A: "test_a"}), _side({A: "test_a"}), flaky={A})

    assert not verdict.ok and verdict.flaky == (A,)
    assert "pass when run alone" in verdict.reason


def test_shards_run_in_the_cage_with_reports_beside_the_green_not_in_it(tmp_path: Path) -> None:
    green = _green(tmp_path)
    (green.work / "tests").mkdir()
    for number in range(31):
        (green.work / "tests" / f"test_{number}.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    calls = []

    def run(command: str, *, cwd: str, timeout_s: float) -> CagedResult:
        calls.append((command, cwd))
        report = Path(command.split("--junitxml=")[1].split('"')[0])
        if report.name.endswith("-2.xml"):  # the second shard hangs; pytest never writes its report
            return CagedResult("timeout", -1, "the caged runner did not answer")
        cases = "".join(
            f'<testcase classname="tests.test_{number}" name="test_ok">'
            + ('<failure message="broken"/>' if number == 0 else "")
            + "</testcase>"
            for number in range(30)
        )
        report.write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")
        return CagedResult("ok", 1, "", "thomas-agent")

    result = run_side(green, [f"tests/test_{n}.py" for n in range(31)], "cand", run)

    assert len(calls) == 2 and all(cwd == str(green.work) for _, cwd in calls)
    assert all("THOMAS_DATA_DIR" in command for command, _ in calls)  # a data folder of the proof's own
    assert proof.proof_folder(green).parent == green.work.parent
    assert not list(green.work.rglob("*.xml"))
    assert result.failing
    assert result.unrunnable[0].startswith("cand shard 2 (1 files) could not run: timeout")


def test_the_boot_check_catches_tests_that_would_import_the_running_thomas(tmp_path: Path) -> None:
    green = _green(tmp_path)

    def inside(command: str, *, cwd: str, timeout_s: float) -> CagedResult:
        return CagedResult("ok", 0, f"{green.work / 'thomas' / '__init__.py'}\n", "thomas-agent")

    def outside(command: str, *, cwd: str, timeout_s: float) -> CagedResult:
        return CagedResult("ok", 0, "C:\\Users\\someone\\Thomas\\thomas\\__init__.py\n", "thomas-agent")

    assert boot_check(green, inside) == ""
    assert "not the green" in boot_check(green, outside)


def test_real_pytest_is_read_the_way_the_proof_reads_it(tmp_path: Path) -> None:
    """The one proof test that runs pytest itself: the argument file, the report path, xunit1, a skip, a
    collection error, and the boot check against the venv's editable install of the running Thomas."""
    green = _green(tmp_path)
    (green.work / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")  # the rootdir, as pyproject.toml is
    for package in ("thomas", "thomas/core"):
        (green.work / package).mkdir(parents=True, exist_ok=True)
        (green.work / package / "__init__.py").write_text("", encoding="utf-8")
    (green.work / "tests").mkdir()
    (green.work / "tests" / "test_a.py").write_text(
        "import pytest\n\n\ndef test_ok():\n    pass\n\n\ndef test_bad():\n    assert 0\n\n\n"
        "@pytest.mark.skip\ndef test_skip():\n    pass\n",
        encoding="utf-8",
    )
    (green.work / "tests" / "test_b.py").write_text("import no_such_module_anywhere\n", encoding="utf-8")

    result = run_side(green, ["tests/test_a.py", "tests/test_b.py"], "cand", _local)

    assert result.unrunnable == ()
    assert set(result.failing) == {"tests/test_a.py::test_bad", "tests/test_b.py"}
    assert set(result.passing) == {"tests/test_a.py::test_ok"}
    assert result.skipped == frozenset({"tests/test_a.py::test_skip"})
    # Measured 2026-09-24: the editable install's finder is appended to sys.meta_path, so the green's own
    # thomas, first on sys.path, wins. If this fails, every proof would test the running Thomas: stop.
    assert boot_check(green, _local, modules=("thomas", "thomas.core")) == ""


def test_a_base_result_is_cached_per_dev_tip_and_file_list(tmp_path: Path) -> None:
    path, known = proof.cached(tmp_path, "d" * 40, ["tests/b.py", "tests/a.py"])
    assert known is None

    proof.remember(path, _side({"x::t": "t"}, {"x::u": "u"}, confirmed=frozenset({"x::t"})))
    again, known = proof.cached(tmp_path, "d" * 40, ["tests/a.py", "tests/b.py"])

    assert again == path and known == _side({"x::t": "t"}, {"x::u": "u"}, confirmed=frozenset({"x::t"}))
