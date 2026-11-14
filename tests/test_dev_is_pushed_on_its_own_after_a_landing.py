"""A landing is followed by a push of dev to GitHub: on unless the saved setting says no, one at a time, one for a run.

Proves: scripts.crew.brief.push_after_land, scripts.crew.brief.land_worker, scripts.crew.brief.push_dev,
thomas.preferences._prefs, thomas.preferences._patches.

Every remote is a bare repository in tmp_path and every settings store is a file in tmp_path.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from scripts.crew.brief import land_worker, push_after_land, push_dev

from tests.test_land_e2e import start, world  # noqa: F401 - the throwaway repo and the real worker harness
from thomas.core import github_push_status
from thomas.preferences.store import PreferencesPatch, PreferencesStore


@pytest.fixture(autouse=True)
def own_data_folder(tmp_path, monkeypatch):
    """The push saves its outcome in the data folder: this test's, never yours."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def pair(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(tmp_path, "init", "-q", "-b", "dev", str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    git(work, "remote", "add", "dev-origin", str(remote))
    (work / "a.txt").write_text("1\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "first")
    return work, remote


def tip_on_remote(remote: Path) -> str:
    done = subprocess.run(["git", "rev-parse", "--verify", "-q", "dev"], cwd=remote, capture_output=True, text=True)
    return done.stdout.strip()


def settings(tmp_path: Path, **runtime: bool) -> Path:
    db = tmp_path / "settings.db"
    store = PreferencesStore(db_path=str(db))
    if runtime:
        store.patch(PreferencesPatch(advanced={"runtime": runtime}))
    return db


def after(work: Path, db: Path, **kw):
    return push_after_land.push_after_landing(work, agent="claude", db_path=db, **kw)


def test_a_push_follows_a_landing_when_nothing_was_set(pair, tmp_path) -> None:
    work, remote = pair
    out = after(work, tmp_path / "no-settings-yet.db")
    assert out.status == "pushed"
    assert tip_on_remote(remote) == git(work, "rev-parse", "dev")


def test_a_saved_store_that_never_mentioned_it_means_on(pair, tmp_path) -> None:
    work, remote = pair
    db = settings(tmp_path)
    assert PreferencesStore(db_path=str(db)).get().advanced.runtime.push_dev_after_landing is True
    assert after(work, db).status == "pushed"
    assert tip_on_remote(remote)


def test_turned_off_in_the_settings_store_nothing_is_pushed_and_it_says_so(pair, tmp_path) -> None:
    work, remote = pair
    db = settings(tmp_path, push_dev_after_landing=False)
    said: list[str] = []
    out = after(work, db, say=said.append)
    assert out.status == "off" and "turned off in your settings" in out.message
    assert said == [out.message]
    assert tip_on_remote(remote) == ""
    PreferencesStore(db_path=str(db)).patch(PreferencesPatch(advanced={"runtime": {"push_dev_after_landing": True}}))
    assert after(work, db).status == "pushed"


@pytest.mark.parametrize("value", ["0", "1", "false", "off"])
def test_no_environment_variable_changes_it(pair, tmp_path, monkeypatch, value) -> None:
    work, remote = pair
    for name in ("THOMAS_PUSH_AFTER_LAND", "THOMAS_PUSH_DEV_AFTER_LANDING"):
        monkeypatch.setenv(name, value)
    assert after(work, settings(tmp_path)).status == "pushed"
    assert tip_on_remote(remote)


def test_a_landing_with_another_in_line_pushes_nothing(pair, tmp_path) -> None:
    work, remote = pair
    out = after(work, settings(tmp_path), others_waiting=True)
    assert out.status == "deferred" and tip_on_remote(remote) == ""


def test_a_push_already_running_makes_the_next_one_wait_then_send_the_tip(pair, tmp_path) -> None:
    work, remote = pair
    lock = push_dev._take_lock(work)
    assert lock is not None
    calls: list[str] = []

    def real(root, **kw):
        result = push_dev.push_landed(root, **kw)
        calls.append(result.status)
        return result

    def free_the_lock(_seconds: float) -> None:
        lock.unlink()

    out = after(work, settings(tmp_path), push=real, sleep=free_the_lock)
    assert calls == ["busy", "pushed"] and out.status == "pushed"
    assert tip_on_remote(remote) == git(work, "rev-parse", "dev")


def test_a_push_that_cannot_run_comes_back_as_a_stop_not_an_error(pair, tmp_path) -> None:
    work, _remote = pair

    def broken(_root, **_kw):
        raise OSError("disk went away")

    out = after(work, settings(tmp_path), push=broken)
    assert out.status == "blocked" and "disk went away" in out.message


def test_a_repository_with_no_github_remote_is_left_alone(tmp_path) -> None:
    lone = tmp_path / "lone"
    git(tmp_path, "init", "-q", "-b", "dev", str(lone))
    recorded: list[object] = []
    out = push_after_land.push_after_landing(lone, agent="claude", record=recorded.append)
    assert out.status == "no_remote" and recorded == []


class FakeLane:
    def __init__(self, open_others: int) -> None:
        self.rows = {1: {"open": False}, **{n + 2: {"open": True} for n in range(open_others)}}

    def states(self):
        return self.rows


def test_the_worker_pushes_after_a_landing_and_counts_the_tickets_still_open(monkeypatch, tmp_path) -> None:
    seen: list[bool] = []
    monkeypatch.setattr(
        push_after_land, "push_after_landing", lambda root, **kw: seen.append(kw["others_waiting"]) or None
    )
    for verdict, lane in (("landed", FakeLane(0)), ("landed", FakeLane(2)), ("already_landed", FakeLane(0))):
        land_worker.push_after(tmp_path, lane, 1, "claude", lambda _t: None, verdict)
    assert seen == [False, True, False]
    land_worker.push_after(tmp_path, FakeLane(0), 1, "claude", lambda _t: None, "refused")
    land_worker.push_after(tmp_path, FakeLane(0), 1, "claude", lambda _t: None, "lost")
    assert len(seen) == 3


def test_the_last_ticket_ending_without_a_landing_sends_the_push_an_earlier_one_put_off(monkeypatch, tmp_path) -> None:
    seen: list[bool] = []
    monkeypatch.setattr(
        push_after_land, "push_after_landing", lambda root, **kw: seen.append(kw["others_waiting"]) or None
    )
    land_worker.push_after(tmp_path, FakeLane(0), 1, "claude", lambda _t: None, "refused")
    assert seen == []
    github_push_status.record("deferred", "put off")
    land_worker.push_after(tmp_path, FakeLane(0), 1, "claude", lambda _t: None, "refused")
    assert seen == [False]


def test_a_push_that_blows_up_cannot_change_a_finished_landing(monkeypatch, tmp_path) -> None:
    def boom(*_a, **_kw):
        raise RuntimeError("the push exploded")

    monkeypatch.setattr(push_after_land, "push_after_landing", boom)
    said: list[str] = []
    land_worker.push_after(tmp_path, FakeLane(0), 1, "claude", said.append, "landed")
    assert said and "the push exploded" in said[0]


def wait_for_tip(remote: Path, want: str, seconds: float = 90.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if tip_on_remote(remote) == want:
            return True
        time.sleep(0.5)
    return False


def test_the_real_worker_pushes_dev_after_it_lands(world, tmp_path) -> None:  # noqa: F811
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(world.repo, "branch", "-M", "dev")
    git(world.repo, "remote", "add", "dev-origin", str(remote))
    world.env["THOMAS_DB_PATH"] = str(tmp_path / "no-settings.db")
    world.env["THOMAS_DATA_DIR"] = str(tmp_path / "data")
    (world.repo / "f0.txt").write_text("change\n")
    proc = start(world, "agent-0", "--message", "feat: change", "--include", "f0.txt")
    out, err = proc.communicate(timeout=180)
    assert proc.returncode == 0, (out, err)
    assert wait_for_tip(remote, git(world.repo, "rev-parse", "dev"))
