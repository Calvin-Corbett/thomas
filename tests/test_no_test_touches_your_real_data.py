"""No test run can write your real Thomas data.

Measured 2026-09-24: ``load_config()`` copies the data-folder paths into
``os.environ`` whenever they are unset (``apply_runtime_data_env_defaults`` in
thomas/core/config.py). Two tests called it without isolation, the paths outlived
them, and ``test_build_role_models`` then wrote ``build_builder = gpt-5.6-terra``
into your real preferences database. tests/conftest.py now gives the whole run a
data folder of its own before anything imports Thomas, gives every test the
THOMAS_* environment back as it found it, and audits direct real-data opens.
The same isolation holds for your ~/.thomas (Build projects,
chat workspaces, the engines' logs), which Thomas finds from THOMAS_OWNED_ROOT or
your home folder rather than from the data folder.

The tests below read what conftest.py defines through ``getattr``, so on a
conftest without the guard each one fails on its own assertion rather than the
module failing to import.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as guard
from thomas.core.config import load_config, resolve_thomas_data_dir
from thomas.integrations.discord_bridge_runtime_support import _default_shared_secret_root
from thomas.preferences._utils import get_db_path

# What the environment looked like before test_load_config_in_a_test_... ran, and
# the keys that test changed.
_THOMAS_ENV_BEFORE: dict[str, str] = {}
_KEYS_THIS_TEST_CHANGED: list[str] = []


def _thomas_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key.startswith("THOMAS_")}


def _under(path: str | Path, root: str | Path) -> bool:
    candidate, parent = Path(path).resolve(), Path(root).resolve()
    return candidate == parent or parent in candidate.parents


def _real_data_dirs() -> tuple[Path, ...]:
    # Without the guard, the platform default is the real folder.
    return tuple(getattr(guard, "REAL_DATA_DIRS", ())) or (resolve_thomas_data_dir(env={}),)


def _run_root() -> Path:
    root = getattr(guard, "TEST_DATA_ROOT", None)
    assert root is not None, "tests/conftest.py gives the test run no data folder of its own"
    return Path(root)


def test_the_run_has_its_own_data_folder_before_anything_imports_thomas() -> None:
    root = _run_root()
    assert getattr(guard, "THOMAS_MODULES_BEFORE_GUARD", None) == [], (
        "Thomas was imported before tests/conftest.py pointed the run at its own data folder"
    )
    active = resolve_thomas_data_dir()
    assert _under(active, root), f"resolve_thomas_data_dir() is {active}, outside the run's folder {root}"
    for real in _real_data_dirs():
        assert not _under(active, real), f"resolve_thomas_data_dir() is your real data folder {real}"
    for key in ("THOMAS_DATA_DIR", "THOMAS_HOME", "THOMAS_STATE_DIR"):
        assert _under(os.environ[key], root), f"{key}={os.environ[key]}"
    # Found from LOCALAPPDATA rather than THOMAS_DATA_DIR, and loaded by every app.
    shared_secrets = _default_shared_secret_root()
    assert _under(shared_secrets, root), f"the shared secret store is {shared_secrets}"


_REPORT_THE_GUARD = """
import json, os, shutil
import tests.conftest as guard
root = getattr(guard, "TEST_DATA_ROOT", None)
print(json.dumps({
    "db_path": os.environ.get("THOMAS_DB_PATH"),
    "runs_db_path": os.environ.get("THOMAS_RUNS_DB_PATH"),
    "unrelated": os.environ.get("THOMAS_CAGE_TEST_MARKER"),
    "dropped": list(getattr(guard, "DROPPED_REAL_DATA_KEYS", ())),
    "root": str(root) if root else None,
}))
if root:
    shutil.rmtree(root, ignore_errors=True)
"""


def test_a_run_started_from_a_thomas_shell_drops_the_real_data_paths_it_inherited(tmp_path: Path) -> None:
    """A Thomas server puts its data paths in the environment of every command it runs.

    A test run it starts (a self-fix checking its work) inherits THOMAS_DB_PATH and
    the rest, so pointing THOMAS_DATA_DIR elsewhere is not enough: each inherited
    path into the real folder is dropped, and anything else is left alone. Run in a
    child process, because the guard acts once, when conftest.py is imported.
    """
    real = tmp_path / "real-thomas"
    env = {key: value for key, value in os.environ.items() if not key.startswith("THOMAS_")}
    env.update(
        THOMAS_DATA_DIR=str(real),
        THOMAS_DB_PATH=str(real / "thomas.db"),
        THOMAS_RUNS_DB_PATH=str(real / ".thomas" / "runs.sqlite3"),
        THOMAS_CAGE_TEST_MARKER=str(tmp_path / "elsewhere"),
        PYTHONUTF8="1",
    )
    done = subprocess.run(
        [sys.executable, "-c", _REPORT_THE_GUARD],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["dropped"] == ["THOMAS_DB_PATH", "THOMAS_RUNS_DB_PATH"], report
    assert report["db_path"] is None and report["runs_db_path"] is None, report
    assert report["unrelated"] == str(tmp_path / "elsewhere"), report
    assert report["root"] and not _under(report["root"], real), report


def test_load_config_in_a_test_points_its_data_paths_at_the_runs_folder(tmp_path: Path) -> None:
    _THOMAS_ENV_BEFORE.clear()
    _THOMAS_ENV_BEFORE.update(_thomas_env())

    # What test_a_worker_cannot_truncate_a_file did: load_config() with the data
    # paths unset, so it writes all of them into os.environ.
    os.environ.pop("THOMAS_DB_PATH", None)
    os.environ.pop("THOMAS_SQLITE_PATH", None)
    load_config()
    db_path_env, preferences_db = os.environ.get("THOMAS_DB_PATH", ""), get_db_path()

    # Then change the environment every other way a test can: add, change, remove.
    os.environ["THOMAS_ADDED_BY_A_TEST"] = "leaked"
    os.environ["THOMAS_DATA_DIR"] = str(tmp_path / "moved")
    os.environ.pop("THOMAS_HOME", None)
    after = _thomas_env()
    _KEYS_THIS_TEST_CHANGED[:] = sorted(
        key for key in set(after) | set(_THOMAS_ENV_BEFORE) if after.get(key) != _THOMAS_ENV_BEFORE.get(key)
    )

    for real in _real_data_dirs():
        assert not _under(preferences_db, real), f"the preferences database is in your real folder: {preferences_db}"
    root = _run_root()
    assert _under(db_path_env, root), f"THOMAS_DB_PATH={db_path_env}"
    assert _under(preferences_db, root), f"the preferences database is {preferences_db}"


def test_the_next_test_gets_the_thomas_environment_back_as_it_was() -> None:
    if not _KEYS_THIS_TEST_CHANGED:
        pytest.skip("checks what the test above it left behind; run the whole module")
    # load_config() sets every data path that was unset (THOMAS_DB_PATH among them),
    # and the test also added, changed and removed a key. Other autouse fixtures give
    # every test fresh values of their own keys (THOMAS_GREEN_ROOT, ...), so only
    # the keys the previous test changed are compared.
    leaked = {
        key: os.environ.get(key)
        for key in [*_KEYS_THIS_TEST_CHANGED, "THOMAS_DB_PATH"]
        if os.environ.get(key) != _THOMAS_ENV_BEFORE.get(key)
    }
    assert leaked == {}, f"the previous test's environment leaked into this one: {leaked}"
    assert {"THOMAS_ADDED_BY_A_TEST", "THOMAS_DATA_DIR", "THOMAS_HOME"} <= set(_KEYS_THIS_TEST_CHANGED)
    for real in _real_data_dirs():
        assert not _under(get_db_path(), real), f"the preferences database is in your real folder {real}"


def _fake_real_folder(tmp_path: Path) -> dict[str, Path]:
    real = tmp_path / "real"
    (real / ".thomas").mkdir(parents=True)
    (real / "json").mkdir()
    files = {
        "db": real / "thomas.db",
        "ledger": real / ".thomas" / "task_ledger.sqlite3",
        "hooks": real / "json" / "thomas_webhooks.json",
    }
    for path in files.values():
        path.write_bytes(b"x")
    (real / "notes.txt").write_bytes(b"not watched")
    files["root"] = real
    return files


def _tripwire():
    snapshot = getattr(guard, "snapshot_real_data", None)
    changes = getattr(guard, "real_data_changes", None)
    check = getattr(guard, "check_real_data", None)
    assert snapshot and changes and check, "tests/conftest.py has no tripwire for your real data"
    return snapshot, changes, check


def test_the_tripwire_names_each_real_data_file_that_was_written_created_or_deleted(tmp_path: Path) -> None:
    snapshot, changes, _ = _tripwire()
    files = _fake_real_folder(tmp_path)
    before = snapshot([files["root"]])
    assert set(before) == {str(files["db"]), str(files["ledger"]), str(files["hooks"])}
    assert changes(before, snapshot([files["root"]])) == []

    later = before[str(files["db"])] + 5_000_000_000
    os.utime(files["db"], ns=(later, later))
    created = files["root"] / ".thomas" / "runs.sqlite3"
    created.write_bytes(b"x")
    files["hooks"].unlink()

    found = changes(before, snapshot([files["root"]]))
    assert len(found) == 3, found
    assert any(str(files["db"]) in line and "written" in line for line in found), found
    assert any(str(created) in line and "created" in line for line in found), found
    assert any(str(files["hooks"]) in line and "deleted" in line for line in found), found


def test_the_tripwire_fails_a_passing_run_when_your_real_data_changed(tmp_path: Path) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    before = snapshot([files["root"]])

    untouched = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(untouched, before, [files["root"]], in_a_green=False) == []
    assert untouched.exitstatus == pytest.ExitCode.OK

    later = before[str(files["ledger"])] + 5_000_000_000
    os.utime(files["ledger"], ns=(later, later))
    written = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    named = check(written, before, [files["root"]], in_a_green=False)
    assert written.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(files["ledger"]) in line for line in named)

    # An unrelated non-SQLite change remains a failure outside a green.
    files["hooks"].write_bytes(b"changed")
    in_green = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert any(str(files["hooks"]) in line for line in check(in_green, before, [files["root"]], in_a_green=True))
    assert in_green.exitstatus == pytest.ExitCode.OK
    outside = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(outside, before, [files["root"]], in_a_green=False)
    assert outside.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_python_child_read_is_attributed_even_without_a_timestamp_change(tmp_path: Path, monkeypatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    log = tmp_path / "child-access.log"
    monkeypatch.setattr(guard, "_CHILD_AUDIT_LOG", log)
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_LOG", str(log))
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_ROOTS", json.dumps([str(root.resolve())]))
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    child = subprocess.run(
        [sys.executable, "-c", "import sys; open(sys.argv[1], 'rb').read()", str(files["db"])],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=False)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(files["db"]) in line and "opened by this test run" in line for line in found), found


def test_native_child_path_argument_is_attributed_without_python_startup(tmp_path: Path, monkeypatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    # -S disables sitecustomize; a native child also does not load it.
    child = subprocess.run(
        [sys.executable, "-S", "-c", "import sys; open(sys.argv[1], 'rb').read()", str(files["db"])],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(files["db"]) in line and "opened by this test run" in line for line in found), found


def test_native_child_given_real_data_path_fails_a_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    command = ["cmd", "/c", "type", str(files["db"])] if os.name == "nt" else ["cat", str(files["db"])]
    child = subprocess.run(command, capture_output=True, check=False, timeout=30)
    assert child.returncode == 0, child.stderr
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(files["db"]) in line and "opened by this test run" in line for line in found), found


def test_native_shell_command_string_with_real_data_path_is_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    command = f'type "{files["db"]}"' if os.name == "nt" else f'cat "{files["db"]}"'
    child = subprocess.run(command, shell=True, capture_output=True, check=False, timeout=30)
    assert child.returncode == 0, child.stderr
    assert child.stdout == b"x"
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found), found


def test_os_system_native_shell_read_is_attributed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    command = f'type "{files["db"]}" > nul' if os.name == "nt" else f'cat "{files["db"]}" > /dev/null'
    assert os.system(command) == 0
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found), found


def test_os_system_native_shell_read_from_inherited_env_is_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    monkeypatch.setenv("THOMAS_NATIVE_INPUT", str(files["db"]))
    command = "type %THOMAS_NATIVE_INPUT% > nul" if os.name == "nt" else 'cat "$THOMAS_NATIVE_INPUT" > /dev/null'
    assert os.system(command) == 0
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found), found


def test_os_system_ignores_unused_inherited_real_data_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    monkeypatch.setenv("THOMAS_NATIVE_INPUT", str(files["db"]))
    # Inheriting an unused path is not a read of it by a harmless native child.
    assert os.system("echo harmless > nul" if os.name == "nt" else "true") == 0
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(session, before, [root], in_a_green=True) == []
    assert session.exitstatus == pytest.ExitCode.OK


def test_os_system_relative_read_from_real_data_cwd_is_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    monkeypatch.chdir(root)
    command = "type thomas.db > nul" if os.name == "nt" else "cat thomas.db > /dev/null"
    assert os.system(command) == 0
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found), found


def test_native_child_with_real_data_cwd_is_attributed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    # No absolute path appears in argv or env; the child reads relative to cwd.
    command = (
        ["cmd", "/c", "type %THOMAS_NATIVE_INPUT%"] if os.name == "nt" else ["sh", "-c", 'cat "$THOMAS_NATIVE_INPUT"']
    )
    child = subprocess.run(
        command,
        cwd=root,
        env={**os.environ, "THOMAS_NATIVE_INPUT": "thomas.db"},
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0
    assert child.stdout == b"x"
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    changes = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any("was opened by this test run" in change for change in changes)


def test_native_child_with_real_data_env_path_is_attributed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    # The native child gets the absolute filename via env, never argv or cwd.
    command = (
        ["cmd", "/c", "type %THOMAS_NATIVE_INPUT%"] if os.name == "nt" else ["sh", "-c", 'cat "$THOMAS_NATIVE_INPUT"']
    )
    child = subprocess.run(
        command,
        env={**os.environ, "THOMAS_NATIVE_INPUT": str(files["db"])},
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found), found


def test_native_child_ignores_unused_explicit_real_data_env_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    command = ["cmd", "/c", "echo harmless"] if os.name == "nt" else ["sh", "-c", "true"]
    child = subprocess.run(
        command,
        env={**os.environ, "THOMAS_NATIVE_INPUT": str(files["db"])},
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(session, before, [root], in_a_green=True) == []
    assert session.exitstatus == pytest.ExitCode.OK


def test_native_child_with_inherited_env_path_is_attributed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    monkeypatch.setenv("THOMAS_NATIVE_INPUT", str(files["db"]))
    command = (
        ["cmd", "/c", "type %THOMAS_NATIVE_INPUT%"] if os.name == "nt" else ["sh", "-c", 'cat "$THOMAS_NATIVE_INPUT"']
    )
    child = subprocess.run(command, capture_output=True, check=False, timeout=30)
    assert child.returncode == 0, child.stderr
    assert child.stdout == b"x"
    assert snapshot([root]) == before
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root) in line and "opened by this test run" in line for line in found), found


def test_native_child_ignores_unused_inherited_real_data_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    monkeypatch.setattr(guard, "_CHILD_REAL_DATA_TARGETS", set())
    monkeypatch.setenv("THOMAS_NATIVE_INPUT", str(files["db"]))
    command = ["cmd", "/c", "echo harmless"] if os.name == "nt" else ["sh", "-c", "true"]
    child = subprocess.run(command, capture_output=True, check=False, timeout=30)
    assert child.returncode == 0, child.stderr
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(session, before, [root], in_a_green=True) == []
    assert session.exitstatus == pytest.ExitCode.OK


def test_live_sqlite_churn_is_not_a_test_failure_but_test_access_is(tmp_path: Path, monkeypatch) -> None:
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    wal, shm = root / "thomas.db-wal", root / "thomas.db-shm"
    before = snapshot([root])
    wal.write_bytes(b"live application")
    shm.write_bytes(b"live application")
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    clean = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(clean, before, [root], in_a_green=False) == []
    assert clean.exitstatus == pytest.ExitCode.OK
    db_before = snapshot([root])
    os.utime(files["db"], ns=(db_before[str(files["db"])] + 5_000_000_000,) * 2)
    changed_db = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert any(str(files["db"]) in line for line in check(changed_db, db_before, [root], in_a_green=False))
    assert changed_db.exitstatus == pytest.ExitCode.TESTS_FAILED
    sidecars_before_removal = snapshot([root])
    wal.unlink()
    shm.unlink()
    checkpointed = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(checkpointed, sidecars_before_removal, [root], in_a_green=False) == []
    assert checkpointed.exitstatus == pytest.ExitCode.OK

    # A read does not change the mtime; it must still fail the run.
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    with files["db"].open("rb") as handle:
        handle.read(1)
    touched = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(touched, before, [root], in_a_green=False)
    assert touched.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(files["db"]) in line and "opened" in line for line in found)

    # A write that happens to leave the same mtime must also be attributed.
    guard._DIRECT_REAL_DATA_ACCESS.clear()
    with files["db"].open("wb") as handle:
        handle.write(b"test write")
    written = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert any(str(files["db"]) in line for line in check(written, before, [root], in_a_green=True))
    assert written.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_real_data_open_audit_records_reads_and_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "simulated-real-data"
    root.mkdir()
    db = root / "thomas.db"
    db.write_bytes(b"database")
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root,))
    guard._DIRECT_REAL_DATA_ACCESS.discard(str(db))
    try:
        assert db.read_bytes() == b"database"
        assert str(db) in guard._DIRECT_REAL_DATA_ACCESS
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(db))
        db.write_bytes(b"updated")
        assert str(db) in guard._DIRECT_REAL_DATA_ACCESS
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(db))
        fd = os.open(db, os.O_RDONLY)
        os.close(fd)
        assert str(db) in guard._DIRECT_REAL_DATA_ACCESS
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(db))
        os.utime(db, None)
        assert str(db) in guard._DIRECT_REAL_DATA_ACCESS
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(db))
        renamed = root / "renamed.db"
        os.rename(db, renamed)
        assert str(db) in guard._DIRECT_REAL_DATA_ACCESS
        assert str(renamed) in guard._DIRECT_REAL_DATA_ACCESS
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(db))
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(renamed))
        os.remove(renamed)
        assert str(renamed) in guard._DIRECT_REAL_DATA_ACCESS
    finally:
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(db))
        guard._DIRECT_REAL_DATA_ACCESS.discard(str(root / "renamed.db"))


def test_python_child_with_explicit_env_is_attributed_to_the_test_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child with its own environment cannot bypass a read-only access audit."""
    snapshot, _, check = _tripwire()
    files = _fake_real_folder(tmp_path)
    root = files["root"]
    before = snapshot([root])
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_ROOTS", json.dumps([str(root.resolve())]))
    monkeypatch.setattr(guard, "_CHILD_AUDIT_LOG", tmp_path / "child-access.jsonl")
    monkeypatch.setenv("THOMAS_TEST_REAL_DATA_AUDIT_LOG", str(guard._CHILD_AUDIT_LOG))
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    child = subprocess.run(
        [sys.executable, "-c", "import sys; open(sys.argv[1], 'rb').read(1)", str(files["db"])],
        env={"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
        check=True,
        capture_output=True,
        text=True,
    )
    assert guard._CHILD_AUDIT_LOG.exists(), f"{child.stderr}; {child.stdout}; {guard._CHILD_AUDIT_BOOT}"
    assert snapshot([root]) == before
    result = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(result, before, [root], in_a_green=True)
    assert result.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(files["db"]) in line and "opened" in line for line in found)


# --- Your ~/.thomas: Build projects, chat workspaces, the engines' logs ----------
#
# Measured 2026-09-24, with the data folder already closed: 597 writes in a 54-file
# sample went to C:\Users\<you>\.thomas, and test_chat_delegation_worker_contract had
# made 23 projects in your Build list. thomas_owned_root() is found from
# THOMAS_OWNED_ROOT or your home folder, never from THOMAS_DATA_DIR.

_OWNED_ROOT_BEFORE: list[str | None] = []


def test_your_thomas_folder_is_the_runs_own_during_a_test() -> None:
    from thomas.forge.anvil.forge_code_projects import thomas_owned_root

    root = _run_root()
    owned = thomas_owned_root()
    assert _under(owned, root), f"thomas_owned_root() is {owned}, outside the run's folder {root}"
    real_homes = tuple(getattr(guard, "REAL_HOME_THOMAS_DIRS", ()))
    assert real_homes, "the tripwire does not watch your real ~/.thomas"
    assert all(not _under(home, root) for home in real_homes), "the tripwire must watch real homes, not test homes"
    assert all(not _under(home, Path.home()) for home in real_homes), "the tripwire must not watch a test home"
    assert _under(Path.home() / ".thomas", Path(os.environ["USERPROFILE"])), "tests must discover their own ~/.thomas"
    # These modules fix a folder under Path.home() / ".thomas" when imported, with
    # no override: the engines' logs and the updater's state.
    moved = getattr(guard, "HOME_STATE_FOLDERS", None) or {("thomas.cli.commands.updater", "_STATE_DIR"): None}
    for name, attribute in moved:
        module = importlib.import_module(name)
        assert hasattr(module, attribute), f"{name}.{attribute} is gone; update HOME_STATE_FOLDERS in conftest.py"
        folder = getattr(module, attribute)
        assert _under(folder, root), f"{name}.{attribute} is {folder}"


def test_the_memory_root_is_the_runs_own_during_a_test() -> None:
    # A shell that runs Thomas carries THOMAS_MEMORY_ROOT=<checkout>\runtime, and it is no data folder
    # the guard knew: on 2026-09-25 a server booted from such a shell wrote serve.lock and three SQLite
    # side files into your real runtime\.thomas.
    root = _run_root()
    assert _under(os.environ["THOMAS_MEMORY_ROOT"], root), f"THOMAS_MEMORY_ROOT is {os.environ['THOMAS_MEMORY_ROOT']}"
    memory_root = Path(load_config().memory.root)
    assert _under(memory_root, root), f"load_config().memory.root is {memory_root}, outside the run's folder {root}"


def test_a_test_that_moves_thomas_owned_root(tmp_path: Path) -> None:
    from thomas.forge.anvil.forge_code_projects import thomas_owned_root

    _OWNED_ROOT_BEFORE[:] = [os.environ.get("THOMAS_OWNED_ROOT")]
    owned_before = thomas_owned_root()
    os.environ["THOMAS_OWNED_ROOT"] = str(tmp_path / "moved-owned-root")
    assert _under(owned_before, _run_root()), f"before this test moved it, thomas_owned_root() was {owned_before}"


def test_the_next_test_finds_thomas_owned_root_where_it_was() -> None:
    if not _OWNED_ROOT_BEFORE:
        pytest.skip("checks what the test above it left behind; run the whole module")
    from thomas.forge.anvil.forge_code_projects import thomas_owned_root

    assert os.environ.get("THOMAS_OWNED_ROOT") == _OWNED_ROOT_BEFORE[0], (
        f"THOMAS_OWNED_ROOT leaked from the previous test: {os.environ.get('THOMAS_OWNED_ROOT')}"
    )
    assert _under(thomas_owned_root(), _run_root())


def _fake_home_thomas(tmp_path: Path) -> dict[str, Path]:
    home = tmp_path / "home" / ".thomas"
    (home / "projects" / "pokemon").mkdir(parents=True)
    (home / "workspaces" / "exec-1").mkdir(parents=True)
    paths = {
        "home": home,
        "engine_log": home / "local_agent_engine.jsonl",
        "project": home / "projects" / "pokemon",
        "deep": home / "workspaces" / "exec-1" / "report.md",
    }
    for key in ("engine_log", "deep"):
        paths[key].write_bytes(b"x")
    return paths


def test_the_tripwire_fails_a_run_that_touched_your_thomas_folder(tmp_path: Path) -> None:
    snapshot = getattr(guard, "snapshot_home_thomas", None)
    _, _, check = _tripwire()
    assert snapshot, "tests/conftest.py has no tripwire for your ~/.thomas"
    paths = _fake_home_thomas(tmp_path)
    before = snapshot([paths["home"]])
    # Top-level files and project folders are watched; deeper files are not.
    assert set(before) == {str(paths["engine_log"]), str(paths["project"])}, before

    clean = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(clean, before, [paths["home"]], in_a_green=False, snapshot=snapshot) == []
    assert clean.exitstatus == pytest.ExitCode.OK

    for key in ("engine_log", "project"):
        later = before[str(paths[key])] + 5_000_000_000
        os.utime(paths[key], ns=(later, later))
    new_project = paths["home"] / "projects" / "Use browseropen and browserextract then 24"
    new_project.mkdir()

    touched = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(touched, before, [paths["home"]], in_a_green=False, snapshot=snapshot)
    assert touched.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert len(found) == 3, found
    assert any(str(paths["engine_log"]) in line and "written" in line for line in found), found
    assert any(str(paths["project"]) in line and "written" in line for line in found), found
    assert any(str(new_project) in line and "created" in line for line in found), found


def test_chdir_into_real_data_is_attributed_without_a_file_change(tmp_path: Path, monkeypatch) -> None:
    snapshot, _, check = _tripwire()
    root = _fake_real_folder(tmp_path)["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    old_cwd = Path.cwd()
    try:
        os.chdir(root)
    finally:
        os.chdir(old_cwd)
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert any("opened by this test run" in line for line in check(session, before, [root], in_a_green=True))
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_directory_mutations_in_real_data_are_attributed_without_a_file_change(tmp_path: Path, monkeypatch) -> None:
    snapshot, _, check = _tripwire()
    root = _fake_real_folder(tmp_path)["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    (root / "new-dir").mkdir()
    (root / "new-dir").rmdir()
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert any("opened by this test run" in line for line in check(session, before, [root], in_a_green=True))
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_child_chdir_into_real_data_is_attributed_without_a_file_change(tmp_path: Path, monkeypatch) -> None:
    snapshot, _, check = _tripwire()
    root = _fake_real_folder(tmp_path)["root"]
    before = snapshot([root])
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root.resolve(),))
    child = subprocess.run(
        [sys.executable, "-c", "import os, sys; os.chdir(sys.argv[1])", str(root)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert any("opened by this test run" in line for line in check(session, before, [root], in_a_green=True))
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_a_run_started_from_a_thomas_shell_drops_the_thomas_folder_paths_it_inherited(tmp_path: Path) -> None:
    """The caged Thomas is given THOMAS_OWNED_ROOT, your ~/.thomas, to build in.

    A test run started from its shell gets the run's own folder instead, and any
    other inherited THOMAS_* path into that folder is dropped.
    """
    real_home = tmp_path / "home" / ".thomas"
    env = {key: value for key, value in os.environ.items() if not key.startswith("THOMAS_")}
    env.update(
        THOMAS_OWNED_ROOT=str(real_home),
        THOMAS_ALIVENESS_LOG=str(real_home / "aliveness.jsonl"),
        THOMAS_CAGE_TEST_MARKER=str(tmp_path / "elsewhere"),
        PYTHONUTF8="1",
    )
    script = _REPORT_THE_GUARD.replace(
        '"root": str(root) if root else None,',
        '"root": str(root) if root else None, "owned_root": os.environ.get("THOMAS_OWNED_ROOT"), '
        '"real_home": [str(p) for p in getattr(guard, "REAL_HOME_THOMAS_DIRS", ())],',
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["dropped"] == ["THOMAS_ALIVENESS_LOG"], report
    assert report["root"] and report["owned_root"] and _under(report["owned_root"], report["root"]), report
    assert str(real_home.resolve()) in report.get("real_home", []), report
    assert report["unrelated"] == str(tmp_path / "elsewhere"), report
