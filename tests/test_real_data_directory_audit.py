"""Regressions for attributing real-data directory access to the test run."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as guard
from tests.real_data_child_audit import filesystem_path_text
from tests.test_no_test_touches_your_real_data import _fake_real_folder, _tripwire


def test_real_data_directory_access_is_attributed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    before = snapshot([root])
    with monkeypatch.context() as change_dir:
        change_dir.chdir(root)
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found)


def test_python_child_directory_access_is_attributed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_ROOTS", json.dumps([str(root)]))
    before = snapshot([root])
    child = subprocess.run(
        [sys.executable, "-c", "import os; os.chdir(os.environ['THOMAS_AUDIT_PROBE'])"],
        env={**os.environ, "THOMAS_AUDIT_PROBE": str(root)},
        cwd=guard.ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    assert str(root) in guard._child_real_data_access()
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found)


def test_directory_mutations_in_real_data_are_attributed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    before = snapshot([root])
    empty_dir = root / "empty"
    empty_dir.mkdir()
    empty_dir.rmdir()
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(empty_dir) in line and "opened by this test run" in line for line in found)


def test_child_pytest_uses_its_own_tests_package(tmp_path: Path) -> None:
    """Auditing a Python child must not import this checkout's tests package into it."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "conftest.py").write_text("LOCAL_CONFTEST = True\n", encoding="utf-8")
    (tests / "test_local.py").write_text(
        "from tests.conftest import LOCAL_CONFTEST\n\ndef test_local():\n    assert LOCAL_CONFTEST\n",
        encoding="utf-8",
    )
    child = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_local.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "1 passed" in child.stdout


def test_child_guard_snapshots_are_not_reported_as_test_access(tmp_path: Path) -> None:
    """A child collecting this checkout can inspect watched roots without blaming tests."""
    log = tmp_path / "child-access.jsonl"
    env = {
        **os.environ,
        "THOMAS_TEST_REAL_DATA_AUDIT_LOG": str(log),
        "THOMAS_TEST_REAL_DATA_AUDIT_ROOTS": json.dumps(
            [str(root) for root in guard.REAL_DATA_DIRS + guard.REAL_HOME_THOMAS_DIRS]
        ),
    }
    child = subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        cwd=guard.ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert not log.exists() or not log.read_text(encoding="utf-8"), (
        log.read_text(encoding="utf-8") if log.exists() else ""
    )


def test_popen_remains_a_type_for_gateway_process_checks() -> None:
    assert isinstance(subprocess.Popen, type)
    with subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        assert isinstance(child, subprocess.Popen)
        assert child.wait(timeout=30) == 0


@pytest.mark.skipif(os.name != "nt", reason="new-console startup is Windows-specific")
def test_new_console_child_does_not_inherit_audit_bootstrap_from_python_parent() -> None:
    # The first child receives sitecustomize and an augmented PYTHONPATH. Its
    # new-console descendant must not inherit that startup hook either.
    first = subprocess.run(
        [
            sys.executable,
            "-c",
            "import subprocess, sys; "
            "child = subprocess.run([sys.executable, '-c', "
            '\'import os; print(os.environ.get("PYTHONPATH", ""))\'], '
            "creationflags=subprocess.CREATE_NEW_CONSOLE, "
            "capture_output=True, text=True, timeout=30); "
            "print(child.stdout); sys.exit(child.returncode)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    assert str(guard._CHILD_AUDIT_BOOT) not in first.stdout


@pytest.mark.skipif(os.name != "nt", reason="extended-length paths are Windows-specific")
def test_extended_length_real_data_path_is_audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "fake-real-data"
    root.mkdir()
    db = root / "thomas.db"
    db.write_bytes(b"db")
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    extended = "\\\\?\\" + str(db.resolve())
    assert filesystem_path_text(extended) == str(db.resolve())
    with open(extended, "rb") as handle:
        assert handle.read(1) == b"d"
    assert str(db.resolve()) in guard._DIRECT_REAL_DATA_ACCESS
    assert filesystem_path_text("\\\\?\\UNC\\server\\share\\db") == "\\\\server\\share\\db"
    assert filesystem_path_text("\\\\?\\PIPE\\test") is None


@pytest.mark.skipif(os.name != "nt", reason="extended-length paths are Windows-specific")
def test_python_child_extended_length_real_data_path_is_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fake-real-data"
    root.mkdir()
    db = root / "thomas.db"
    db.write_bytes(b"db")
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_ROOTS", json.dumps([str(root)]))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    child = subprocess.run(
        [sys.executable, "-c", "import os; open(os.environ['THOMAS_AUDIT_PROBE'], 'rb').close()"],
        env={**os.environ, "THOMAS_AUDIT_PROBE": "\\\\?\\" + str(db.resolve())},
        cwd=guard.ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert str(db.resolve()) in guard._child_real_data_access()


@pytest.mark.skipif(os.name != "nt", reason="named pipes are Windows device paths")
def test_device_path_open_does_not_enter_real_data_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # If path resolution maps a device name under a watched folder, its raw
    # namespace still identifies a pipe, not a real-data file.
    real_root = tmp_path / "fake-real-data"
    real_root.mkdir()
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (real_root,))
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    original_path = guard.Path

    class ResolvingDevicePath:
        def __call__(self, value):
            if value == r"\\.\pipe\thomas-audit-probe":
                return real_root / "thomas-audit-probe"
            return original_path(value)

    monkeypatch.setattr(guard, "Path", ResolvingDevicePath())
    guard._audit_real_data_access("open", (r"\\.\pipe\thomas-audit-probe", "rb", 0))
    assert not guard._DIRECT_REAL_DATA_ACCESS
