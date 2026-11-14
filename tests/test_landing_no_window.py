"""Every process the landing tools start is started without a console window (CREATE_NO_WINDOW).

Agents run land.py from parents that have no console. Windows opens a visible console for every child such a parent starts,
so a measurement that spawns dozens of python and git processes flashed dozens of windows on the desktop. One flag on every
spawn prevents it; this test records the flags of every spawn the tools make.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scripts.crew.brief import land_commit, land_git, land_precheck, land_worker, landing_proc
from scripts.crew.brief.landing_queue import Config, Lane
from scripts.crew.brief.landing_store import FileTicketStore, canonical_coordination_dir

from tests._landing_fakes import sp

CREATE_NO_WINDOW = 0x08000000
pytestmark = pytest.mark.skipif(os.name != "nt", reason="console windows are a Windows matter")


@pytest.fixture()
def spawns(monkeypatch):
    seen: list[tuple[str, int]] = []
    real = subprocess.Popen

    class Recorder(real):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
            seen.append((str(args[0] if isinstance(args, (list, tuple)) else args), int(kw.get("creationflags") or 0)))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", Recorder)
    return seen


def repo(tmp_path) -> Path:
    work = tmp_path / "repo"
    work.mkdir()
    sp.run(["git", "init", "-q"], cwd=work, check=True)
    sp.run(
        ["git", "-c", "user.email=t@e.t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"],
        cwd=work,
        check=True,
    )
    return work


def assert_all_hidden(spawns, expect_at_least: int) -> None:
    assert len(spawns) >= expect_at_least, spawns
    bare = [name for name, flags in spawns if not flags & CREATE_NO_WINDOW]
    assert bare == [], f"started with a visible console: {bare}"


def test_the_helper_adds_the_flag_and_keeps_the_callers_own_flags():
    assert landing_proc.hidden({})["creationflags"] == CREATE_NO_WINDOW
    assert landing_proc.hidden({"creationflags": 0x4000})["creationflags"] == CREATE_NO_WINDOW | 0x4000


def test_git_and_taskkill_calls_are_hidden(tmp_path, spawns):
    work = repo(tmp_path)
    land_git.git(work, "status")
    land_git.find_landed(work, "lq-none", [])
    canonical_coordination_dir(work)
    landing_proc.stale_locks(work, now=time.time())
    landing_proc.kill_tree(2_000_000_000)
    assert_all_hidden(spawns, 7)


def test_the_commit_tool_run_and_its_precheck_are_hidden(tmp_path, spawns):
    tool = tmp_path / "tool.py"
    tool.write_text('import json\nprint(json.dumps({"ok": True, "commit_sha": "abc", "message": "ok"}))\n')
    lane = Lane(FileTicketStore(tmp_path / "queue"), agent="a", cfg=Config())
    num = lane.enqueue("key", "s")
    lane.wait_turn(num)
    assert land_commit.run_commit([sys.executable, str(tool)], lane, num, Config(), "key", root=tmp_path).ok
    other = Lane(FileTicketStore(tmp_path / "queue"), agent="b", cfg=Config())
    behind = other.enqueue("kb", "s")  # waits behind the holder, as a pre-check's ticket does: its turn has not come
    assert land_precheck.Precheck(other, behind, [sys.executable, str(tool)], tmp_path).run().ok
    assert_all_hidden(spawns, 2)


def test_the_detached_worker_is_started_without_a_console(tmp_path, spawns):
    script = tmp_path / "worker_stub.py"
    script.write_text("raise SystemExit(0)\n")
    proc = land_worker.spawn_worker(1, script)
    assert proc is not None
    proc.wait(timeout=30)
    assert_all_hidden(spawns, 1)


def test_a_child_the_tests_start_themselves_is_hidden_too(spawns):
    sp.run([sys.executable, "-c", "pass"], check=True)
    assert_all_hidden(spawns, 1)
