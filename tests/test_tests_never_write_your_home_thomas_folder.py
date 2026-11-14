"""A test run never puts self-edit copies or source application locks in your real ~/.thomas.

Measured on dev 144b1954 (2026-10-12), with USERPROFILE pointed at an empty folder:
tests/test_code_never_runs_in_thomas_own_source.py, test_redesign_source_undo.py,
test_redesign_undo_capture_limits.py and test_native_self_edit_routes.py (56 passed) left
a self-edit-<id> copy of a pytest folder, its .baseline.json and 15
source-application-locks/*.lock files in that folder's .thomas, and the run still passed.
The self-edit code took both folders from Path.home() / ".thomas", which nothing in a
test run moved, and the tripwire in tests/conftest.py listed only the top-level files of
~/.thomas and its projects/* folders.

The tests below fake your home folder, so a failure here never writes your real one.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as guard
from thomas.forge.anvil import forge_code_self_edit as isolation
from thomas.server.routes.evolve_agent_self_edit_runs import prepare_run

REPO = Path(__file__).resolve().parents[1]


def _under(path: str | Path, root: str | Path) -> bool:
    candidate, parent = Path(path).resolve(), Path(root).resolve()
    return candidate == parent or parent in candidate.parents


def _run_root() -> Path:
    root = getattr(guard, "TEST_DATA_ROOT", None)
    assert root is not None, "tests/conftest.py gives the test run no data folder of its own"
    return Path(root)


def _fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Path.home() answers an empty folder for this test, so nothing reaches your real one."""
    home = tmp_path / "your-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _under_run(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and Path(text).is_absolute() and _under(text, _run_root())


def _left_in(home: Path) -> list[str]:
    folder = home / ".thomas"
    return sorted(str(path.relative_to(home)) for path in folder.rglob("*")) if folder.exists() else []


def _lock_name(source: Path) -> str:
    # The name source_application_gate gives the lock of one source.
    return hashlib.sha256(os.path.normcase(str(source.resolve())).encode("utf-8")).hexdigest() + ".lock"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


def _thomas_source(root: Path) -> Path:
    """A git folder with what a self-edit run checks: one product file, the policy file and the board."""
    (root / "thomas").mkdir(parents=True)
    (root / "thomas" / "menu.py").write_text("PLUS = True\n", encoding="utf-8")
    (root / "agent_safety.toml").write_text('[protected]\npolicy_files=["agent_safety.toml"]\n', encoding="utf-8")
    (root / "plans" / "thomas").mkdir(parents=True)
    (root / "plans" / "thomas" / "WORKBOARD.md").write_text("## Agent Claims\n", encoding="utf-8")
    _git(root, "init", "-q")
    return root.resolve()


def test_the_source_application_lock_is_made_in_the_runs_own_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _fake_home(tmp_path, monkeypatch)
    source = tmp_path / "source"
    source.mkdir()

    with isolation.source_application_gate(source):
        # The lock still holds: a second application of the same source is refused while this one runs.
        with pytest.raises(isolation.SelfEditSnapshotError):
            with isolation.source_application_gate(source):
                pass

    assert _left_in(home) == [], f"the lock was made in your home folder's .thomas: {_left_in(home)}"
    made = [path for path in _run_root().rglob(_lock_name(source)) if path.parent.name == "source-application-locks"]
    assert len(made) == 1, f"no source-application-locks/{_lock_name(source)} in the run's folder {_run_root()}"


def test_a_self_edit_run_copies_thomas_into_the_runs_own_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What test_a_self_edit_thread_from_redesign_is_let_through_the_guard reaches through /api/evolve/agent/send."""
    home = _fake_home(tmp_path, monkeypatch)
    source = _thomas_source(tmp_path / "thomas-source")
    catalog = tmp_path / "catalog"
    catalog.mkdir()

    record = prepare_run(source, catalog, {"id": "conv-1", "self_edit_scope": ["thomas/menu.py"]}, "run-1")

    assert _left_in(home) == [], f"the self-edit copy was made in your home folder's .thomas: {_left_in(home)}"
    candidate = Path(record["candidate_root"])
    assert _under(candidate, _run_root()), f"the self-edit copy {candidate} is outside the run's folder {_run_root()}"
    assert candidate.parent.name == "self-edit-candidates" and candidate.name.startswith("self-edit-"), candidate
    assert (candidate / "thomas" / "menu.py").read_text(encoding="utf-8") == "PLUS = True\n"
    baseline = json.loads(candidate.with_suffix(".baseline.json").read_text(encoding="utf-8"))
    assert baseline["source_root"] == str(source)
    isolation.discard_candidate(candidate)


_GATE_IN_A_CHILD = """
import sys
from pathlib import Path
from thomas.forge.anvil import forge_code_self_edit as isolation
with isolation.source_application_gate(Path(sys.argv[1])):
    pass
print("locked and released")
"""


def test_a_thomas_process_a_test_starts_stays_out_of_your_home_folder(tmp_path: Path) -> None:
    """A test that starts Thomas in another process cannot patch it, so the run's folder is in the environment."""
    home = tmp_path / "your-home"
    home.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home), "PYTHONUTF8": "1"}
    done = subprocess.run(
        [sys.executable, "-c", _GATE_IN_A_CHILD, str(source)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0 and "locked and released" in done.stdout, done.stderr[-2000:]
    assert _left_in(home) == [], (
        f"a Thomas process started by a test wrote your home folder's .thomas: {_left_in(home)}"
    )


def test_outside_a_test_run_the_copies_and_locks_stay_in_this_accounts_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running Thomas keeps them in its own ~/.thomas, as before.

    Not in THOMAS_OWNED_ROOT: the caged Thomas is handed your ~/.thomas there and may only list it
    (scripts/cage/enable_build_projects.ps1), so a lock or a copy made there would fail.
    """
    home = _fake_home(tmp_path, monkeypatch)
    owned = tmp_path / "owners-thomas"
    monkeypatch.setenv("THOMAS_OWNED_ROOT", str(owned))
    for key in [key for key in os.environ if key.startswith("THOMAS_") and _under_run(os.environ[key])]:
        monkeypatch.delenv(key)
    source = tmp_path / "source"
    source.mkdir()

    with isolation.source_application_gate(source):
        pass

    assert (home / ".thomas" / "source-application-locks" / _lock_name(source)).is_file(), _left_in(home)
    assert not owned.exists(), f"the lock went to THOMAS_OWNED_ROOT: {sorted(owned.rglob('*'))}"


def test_the_tripwire_fails_a_run_that_left_self_edit_material_in_your_thomas_folder(tmp_path: Path) -> None:
    snapshot = getattr(guard, "snapshot_home_thomas", None)
    check = getattr(guard, "check_real_data", None)
    assert snapshot and check, "tests/conftest.py has no tripwire for your ~/.thomas"
    home = tmp_path / "home" / ".thomas"
    candidates, locks = home / "self-edit-candidates", home / "source-application-locks"
    (candidates / "self-edit-earlier").mkdir(parents=True)
    locks.mkdir()
    (locks / ("1" * 64 + ".lock")).write_bytes(b"0")
    before = snapshot([home])

    clean = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(clean, before, [home], in_a_green=False, snapshot=snapshot) == []
    assert clean.exitstatus == pytest.ExitCode.OK

    # What one run of the four self-edit test files left in your ~/.thomas on dev.
    copy = candidates / "self-edit-dnzjsea_"
    (copy / "thomas").mkdir(parents=True)
    baseline = copy.with_suffix(".baseline.json")
    baseline.write_text(json.dumps({"source_root": str(tmp_path / "pytest-of-you" / "thomas-source")}), "utf-8")
    lock = locks / ("2" * 64 + ".lock")
    lock.write_bytes(b"0")

    touched = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(touched, before, [home], in_a_green=False, snapshot=snapshot)
    assert touched.exitstatus == pytest.ExitCode.TESTS_FAILED, found
    for path in (copy, baseline, lock):
        assert any(str(path) in line and "created" in line for line in found), (path, found)
