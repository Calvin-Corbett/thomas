"""Real landings, real workers, a bare repository as GitHub: what the push after a landing does and says.

Proves: scripts.crew.brief.land_worker, scripts.crew.brief.push_after_land, scripts.crew.brief.push_dev,
thomas.core.github_push_status.

Each test lands through ``land.py`` with a stand-in commit tool in a throwaway repository, with ``dev-origin`` a bare
repository in tmp_path and the data folder and the settings store files in tmp_path. Nothing touches a real remote.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from scripts.crew.brief import push_dev

from tests.test_land_e2e import (  # noqa: F401 - the throwaway repo and the real worker harness
    lane_of,
    run,
    start,
    world,
)
from thomas.core import github_push_status as gps
from thomas.preferences.store import PreferencesPatch, PreferencesStore


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def github(world, tmp_path):  # noqa: F811
    """The throwaway repo with a bare ``dev-origin``, a pre-push hook that counts its runs, and its own data folder."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(world.repo, "branch", "-M", "dev")
    git(world.repo, "remote", "add", "dev-origin", str(remote))
    runs = tmp_path / "hook_runs.txt"
    hook = world.repo / ".git" / "hooks" / "pre-push"
    hook.write_text(f'#!/bin/sh\necho run >> "{runs.as_posix()}"\n', encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    world.env["THOMAS_DB_PATH"] = str(tmp_path / "settings.db")
    world.env["THOMAS_DATA_DIR"] = str(tmp_path / "data")
    return type("G", (), {"world": world, "remote": remote, "runs": runs, "data": tmp_path / "data"})()


def remote_tip(remote: Path) -> str:
    done = subprocess.run(["git", "rev-parse", "--verify", "-q", "dev"], cwd=remote, capture_output=True, text=True)
    return done.stdout.strip()


def wait_for(check, seconds: float = 90.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.4)
    return False


def finished(g) -> bool:
    return gps.read_state(g.data).get("status") not in (None, "pushing", "waiting", "deferred")


def hook_runs(g) -> int:
    return len(g.runs.read_text().split()) if g.runs.exists() else 0


def test_two_landings_back_to_back_send_one_push_that_covers_both(github) -> None:
    w = github.world
    for i in range(2):
        (w.repo / f"f{i}.txt").write_text(f"change {i}\n")
    procs = [
        start(w, f"agent-{i}", "--message", f"feat: change {i}", "--include", f"f{i}.txt", seconds="4")
        for i in range(2)
    ]
    for proc in procs:
        out, err = proc.communicate(timeout=180)
        assert proc.returncode == 0, (out, err)
    assert wait_for(lambda: remote_tip(github.remote) == git(w.repo, "rev-parse", "dev"))
    assert wait_for(lambda: finished(github))
    assert hook_runs(github) == 1
    assert git(github.remote, "rev-list", "--count", "dev") == git(w.repo, "rev-list", "--count", "dev")
    assert gps.collect_github_push(w.repo, github.data)["sentence"].startswith("Last pushed to GitHub: today ")


def test_a_hook_that_stops_the_push_is_shown_and_the_landing_stays_landed(github) -> None:
    w = github.world
    hook = w.repo / ".git" / "hooks" / "pre-push"
    hook.write_text('#!/bin/sh\necho "core overhead guard: over by 4" >&2\nexit 1\n', encoding="utf-8", newline="\n")
    (w.repo / "f0.txt").write_text("change\n")
    code, answer = run(w, "agent-0", "--message", "feat: change", "--include", "f0.txt")
    assert code == 0 and answer["status"] == "landed"
    assert wait_for(lambda: finished(github))
    assert remote_tip(github.remote) == ""
    assert git(w.repo, "log", "-1", "--format=%s", "dev").startswith("feat: change")
    lane = lane_of(w)
    assert [s["state"] for _n, s in sorted(lane.states().items())] == ["released"]
    reading = gps.collect_github_push(w.repo, github.data)
    assert reading["level"] == "act"
    assert reading["sentence"].endswith("a check stopped the push: core overhead guard: over by 4")
    assert json.loads((github.data / gps.STATE_NAME).read_text())["status"] == "blocked"


def test_turned_off_in_the_settings_store_a_landing_pushes_nothing_and_says_so(github, tmp_path) -> None:
    w = github.world
    PreferencesStore(db_path=str(tmp_path / "settings.db")).patch(
        PreferencesPatch(advanced={"runtime": {"push_dev_after_landing": False}})
    )
    (w.repo / "f0.txt").write_text("change\n")
    code, answer = run(w, "agent-0", "--message", "feat: change", "--include", "f0.txt")
    assert code == 0 and answer["status"] == "landed"
    assert wait_for(lambda: finished(github))
    assert remote_tip(github.remote) == "" and hook_runs(github) == 0
    assert gps.collect_github_push(w.repo, github.data)["sentence"].startswith(
        "Pushing to GitHub after a landing is turned off in your settings."
    )


def test_a_push_already_running_makes_the_next_wait_instead_of_starting_another(github) -> None:
    w = github.world
    lock = push_dev._take_lock(w.repo)
    assert lock is not None
    (w.repo / "f0.txt").write_text("change\n")
    code, answer = run(w, "agent-0", "--message", "feat: change", "--include", "f0.txt")
    assert code == 0 and answer["status"] == "landed"
    assert wait_for(lambda: gps.read_state(github.data).get("status") == "waiting", 60)
    assert remote_tip(github.remote) == "" and hook_runs(github) == 0
    lock.unlink()
    assert wait_for(lambda: remote_tip(github.remote) == git(w.repo, "rev-parse", "dev"))
    assert wait_for(lambda: finished(github))
    assert hook_runs(github) == 1
