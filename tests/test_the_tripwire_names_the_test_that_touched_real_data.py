"""The real-data tripwire names the test and the action, not only the folder (2026-10-28).

d79480's checks failed in the cage on "C:\\Users\\thomas-agent\\AppData\\Local\\Thomas\\green was opened by this test
run", and the same files passed outside the cage, so the folder alone could not say which test to look at. Each
"was opened" line now ends with the first event and test that touched the path, for the test process itself, for a
command it started, and for a Python child with its own audit hook.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as guard
from tests.real_data_child_audit import Remembering, remember_access

THIS_TEST_FILE = "tests/test_the_tripwire_names_the_test_that_touched_real_data.py"


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "LocalAppData" / "Thomas").resolve()
    (root / "green").mkdir(parents=True)
    by: dict[str, str] = {}
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root,))
    monkeypatch.setattr(guard, "REAL_HOME_THOMAS_DIRS", ())
    monkeypatch.setattr(guard, "_REAL_DATA_ACCESS_BY", by)
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", Remembering(by, "a child command"))
    monkeypatch.setattr(guard, "_CHILD_AUDIT_LOG", tmp_path / "child-access.jsonl")
    return root


def _opened(root: Path) -> list[str]:
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    lines = guard.check_real_data(session, {}, [root], in_a_green=True, snapshot=lambda roots: {})
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    return [line for line in lines if " was opened by this test run" in line]


def test_the_runs_own_child_targets_remember_into_the_runs_record() -> None:
    assert isinstance(guard._CHILD_REAL_DATA_TARGETS, Remembering)
    assert guard._CHILD_REAL_DATA_TARGETS.by is guard._REAL_DATA_ACCESS_BY


def test_a_direct_access_names_its_event_and_test(real: Path) -> None:
    guard._audit_real_data_access("os.scandir", (str(real / "green"),))
    (line,) = _opened(real)
    assert line.startswith(f"{real / 'green'} was opened by this test run (os.scandir at {THIS_TEST_FILE}:")
    assert line.endswith(f", {THIS_TEST_FILE}::test_a_direct_access_names_its_event_and_test)")


def test_a_command_naming_the_path_is_named_as_a_child_command(real: Path) -> None:
    child = subprocess.run([sys.executable, "-c", "pass", str(real / "green")], check=False, timeout=60)
    assert child.returncode == 0
    (line,) = _opened(real)
    assert "(a child command at " in line
    assert f", {THIS_TEST_FILE}::test_a_command_naming_the_path" in line


def test_the_first_test_to_touch_a_path_is_the_one_named(monkeypatch: pytest.MonkeyPatch) -> None:
    by: dict[str, str] = {}
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_first.py::test_one (call)")
    remember_access(by, "C:/x", "open")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_second.py::test_two (call)")
    remember_access(by, "C:/x", "os.listdir")
    assert list(by) == ["C:/x"]
    assert by["C:/x"].startswith(f"open at {THIS_TEST_FILE}:")
    assert by["C:/x"].endswith(", tests/test_first.py::test_one")


def test_a_touch_from_a_background_thread_names_the_thread() -> None:
    by: dict[str, str] = {}
    worker = threading.Thread(target=remember_access, args=(by, "C:/y", "os.listdir"), name="green-sweep")
    worker.start()
    worker.join(10)
    assert " in thread green-sweep, " in by["C:/y"], "a thread an earlier test left running is named as itself"


def test_a_touch_while_importing_code_outside_the_checkout_names_that_code_then_the_checkout_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tripwire_outside_helper.py").write_text(
        "from tests.real_data_child_audit import remember_access\n\nBY = {}\nremember_access(BY, 'C:/z', 'os.listdir')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        how = importlib.import_module("tripwire_outside_helper").BY["C:/z"]
    finally:
        sys.modules.pop("tripwire_outside_helper", None)
    assert how.startswith("os.listdir at ")
    assert f"/{tmp_path.name}/tripwire_outside_helper.py:4 <module> via {THIS_TEST_FILE}:" in how
    assert "<frozen" not in how, "the import machinery's frames are no file, so never the place named"


def test_a_python_childs_record_names_it_and_older_bare_records_still_count(real: Path) -> None:
    named = str(real / "green")
    guard._CHILD_AUDIT_LOG.write_text(
        json.dumps(str(real)) + "\n" + json.dumps([named, "os.listdir in a Python child, tests/test_b.py::u"]) + "\n",
        encoding="utf-8",
    )
    assert guard._child_real_data_access() == {str(real), named}
    assert {
        str(real): "a Python child",
        named: "os.listdir in a Python child, tests/test_b.py::u",
    } == guard._REAL_DATA_ACCESS_BY


def test_a_real_python_child_reports_its_event_and_the_test_that_started_it(
    real: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = real / "settings.json"
    target.write_text("{}", encoding="utf-8")
    guard._DIRECT_REAL_DATA_ACCESS.clear()  # writing it here was this test's own first touch; the child's is wanted
    guard._REAL_DATA_ACCESS_BY.clear()
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_LOG", str(guard._CHILD_AUDIT_LOG))
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_ROOTS", json.dumps([str(real)]))
    # Through the environment, not the command line: a path in the command is the parent's to name ("a child
    # command"), and the first to touch a path is the one named.
    monkeypatch.setenv("TRIPWIRE_TARGET", str(target))
    child = subprocess.run(
        [sys.executable, "-c", "import os; open(os.environ['TRIPWIRE_TARGET'], 'rb').read()"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert child.returncode == 0, child.stderr
    (line,) = [line for line in _opened(real) if "settings.json" in line]
    assert f"(open in a Python child, {THIS_TEST_FILE}::test_a_real_python_child" in line


def test_a_python_child_says_which_of_its_lines_touched_real_data(
    real: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test named is only the one running at that moment. On 2026-11-01 a run failed on a file a Python child opened
    under one test's name, the next run of the same tests did not, and that name was all there was to go on."""
    target = real / "settings.json"
    target.write_text("{}", encoding="utf-8")
    guard._DIRECT_REAL_DATA_ACCESS.clear()
    guard._REAL_DATA_ACCESS_BY.clear()
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_LOG", str(guard._CHILD_AUDIT_LOG))
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_ROOTS", json.dumps([str(real)]))
    monkeypatch.setenv("TRIPWIRE_TARGET", str(target))
    script = tmp_path / "reads_real_data.py"
    script.write_text(
        "import os\n\n\ndef read_it():\n    open(os.environ['TRIPWIRE_TARGET'], 'rb').read()\n\n\nread_it()\n",
        encoding="utf-8",
    )
    child = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False, timeout=60)
    assert child.returncode == 0, child.stderr
    (line,) = [line for line in _opened(real) if "settings.json" in line]
    assert "reads_real_data.py:5 read_it" in line
