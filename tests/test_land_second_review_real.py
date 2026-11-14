"""Second review, with REAL processes and real git: job object, forged heartbeats, suspend, pre-check bound, git locks."""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from pathlib import Path

import psutil
import pytest
from scripts.crew.brief import land_commit, land_precheck, land_worker, landing_proc
from scripts.crew.brief.landing_queue import Config, Lane
from scripts.crew.brief.landing_store import ENV_ROOT, FileTicketStore

from tests._landing_fakes import sp


def tagged(tag: str) -> list[psutil.Process]:
    return [p for p in psutil.process_iter(["cmdline"]) if any(tag in part for part in p.info["cmdline"] or [])]


def tool(tmp_path: Path, body: str, name: str = "fake_commit.py") -> list[str]:
    path = tmp_path / name
    path.write_text(body)
    return [sys.executable, str(path)]


def granted_lane(tmp_path, **cfg):
    said: list[str] = []
    lane = Lane(FileTicketStore(tmp_path / "queue"), agent="a", cfg=Config(**cfg), say=said.append)
    num = lane.enqueue("key", "s")
    lane.wait_turn(num)
    return lane, num, said


OK = 'import json,time\ntime.sleep({s})\nprint(json.dumps({{"ok": True, "commit_sha": "abc", "message": "done"}}))\n'


def test_a_sleep_during_the_commit_tool_is_not_charged_against_its_lease(tmp_path, monkeypatch):
    lane, num, _ = granted_lane(tmp_path, max_hold=8.0)
    jumps = [0]

    def asleep_clock() -> float:  # every reading says an hour passed, as after a suspend
        jumps[0] += 1
        return time.time() + 3600.0 * jumps[0]

    clock = types.SimpleNamespace(time=asleep_clock, sleep=time.sleep, monotonic=time.monotonic)
    monkeypatch.setattr(land_commit, "time", clock)
    out = land_commit.run_commit(tool(tmp_path, OK.format(s=7)), lane, num, Config(max_hold=8.0), "key", root=tmp_path)
    assert out.ok and out.sha == "abc"  # was: the first slice charged the whole hour and the live landing was killed


def test_a_landing_that_holds_the_slot_past_the_warning_is_reported_once_and_finishes(tmp_path):
    lane, num, said = granted_lane(tmp_path, max_hold=60.0, warn_hold=2.0)
    out = land_commit.run_commit(
        tool(tmp_path, OK.format(s=13)), lane, num, Config(max_hold=60.0, warn_hold=2.0), "key", root=tmp_path
    )
    assert out.ok
    assert [e["kind"] for e in lane.store.events()].count("overran") == 1
    assert sum("hold overran" in line for line in said) == 1


def test_a_job_object_is_assigned_and_dies_with_its_owner(tmp_path):
    tag = f"jobclose-{time.time_ns()}"
    inner = f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)  # {tag}'])\ntime.sleep(120)\n"
    proc = sp.Popen([sys.executable, "-c", inner])
    tree = landing_proc.JobTree(proc)
    try:
        assert tree.assigned
        time.sleep(1.5)
        tree.close()  # nobody called kill: closing the job's last handle must take the whole tree down
        proc.wait(timeout=15)
        time.sleep(0.5)
        assert tagged(tag) == []  # KILL_ON_JOB_CLOSE
    finally:
        proc.kill()


def test_when_the_os_refuses_the_job_the_ticket_says_unbounded_and_the_tree_kill_still_runs(tmp_path, monkeypatch):
    def refuse(self) -> None:  # noqa: ANN001
        self.why_not = "AssignProcessToJobObject refused (5; a parent job may forbid nesting)"

    monkeypatch.setattr(landing_proc.JobTree, "_assign_windows", refuse)
    tag = f"nojob-{time.time_ns()}"
    lane, num, said = granted_lane(tmp_path, max_hold=3.0)
    child = "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)', sys.argv[1]])"
    body = f"import subprocess, sys, time\n{child}\ntime.sleep(120)\n"
    seen: list[int] = []
    timer = threading.Timer(1.5, lambda: seen.append(len(tagged(tag))))
    timer.start()
    t0 = time.monotonic()
    try:
        out = land_commit.run_commit(
            tool(tmp_path, body) + [tag], lane, num, Config(max_hold=3.0), "key", root=tmp_path
        )
        assert out.blocker == "lease_expired" and time.monotonic() - t0 < 20
        assert lane.states()[num]["unbounded"]
        assert any("WARNING: the commit tool is not in a job object" in line for line in said)  # loud, not silent
        time.sleep(0.5)
        assert seen and seen[0] >= 2  # the tag is on both command lines, so the check below can see them at all
        assert tagged(tag) == []  # the fallback tree kill reached the commit tool AND its linked child
    finally:
        timer.cancel()
        for proc in tagged(tag):
            proc.kill()


def test_a_precheck_that_hangs_is_stopped_at_its_deadline_with_a_clear_advisory_message(tmp_path):
    store = FileTicketStore(tmp_path / "queue")
    Lane(store, agent="h", cfg=Config()).enqueue("someone-else", "s")  # someone is ahead: the turn does not come
    said: list[str] = []
    lane = Lane(store, agent="a", cfg=Config(precheck_timeout=2.0), say=said.append)
    num = lane.enqueue("key", "s")
    t0 = time.monotonic()
    land_precheck.Precheck(lane, num, tool(tmp_path, "import time\ntime.sleep(120)\n"), tmp_path)(num, 1)
    assert time.monotonic() - t0 < 20  # was: no timeout, for ever
    assert lane.states()[num]["state"] == "waiting"  # a timeout is advisory: the ticket stays in line
    assert any("did not finish in 2 s" in line and "real run still runs every gate" in line for line in said)


def holder_with_forged_beat(tmp_path, helper, *, start, script):
    store = FileTicketStore(tmp_path / "queue")
    holder = Lane(store, agent="a", pid=2_000_000_000, cfg=Config(max_hold=2.0))
    num = holder.enqueue("key", "s")
    store.append("granted", num, by="a", now=time.time(), max_hold=2.0)
    store.beat(
        num,
        now=time.time(),
        pid=2_000_000_000,
        child=helper.pid,
        child_start=start,
        child_script=script,
        phase="holding",
    )
    time.sleep(2.6)
    store.beat(
        num,
        now=time.time(),
        pid=2_000_000_000,
        child=helper.pid,
        child_start=start,
        child_script=script,
        phase="holding",
    )
    waiter = Lane(store, agent="b", cfg=Config(max_hold=2.0))
    waiter.reap()
    return waiter, num


def test_a_forged_heartbeat_naming_a_real_unrelated_process_does_not_kill_it(tmp_path):
    tag = f"victim-{time.time_ns()}"
    victim = sp.Popen([sys.executable, "-c", f"import time; time.sleep(60)  # {tag}"])
    try:
        for start, script in ((0, ""), (landing_proc.start_time(victim.pid), "fake_commit.py")):
            waiter, num = holder_with_forged_beat(tmp_path / f"c{start}", victim, start=start, script=script)
            assert victim.poll() is None  # was: the reviewer killed a helper this way
            skipped = waiter.states()[num]
            assert skipped["state"] == "skipped"
            assert any(e.get("child_ignored") for e in skipped["events"])
            assert any("forged or damaged heartbeat" in f for f in waiter.audit())
    finally:
        victim.kill()


def test_a_second_worker_for_a_ticket_with_a_live_owner_exits_without_touching_it(tmp_path, monkeypatch):
    sleeper = sp.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        monkeypatch.setenv(ENV_ROOT, str(tmp_path / "queue"))
        monkeypatch.setenv("THOMAS_LAND_ROOT", str(tmp_path))
        first = Lane(FileTicketStore(tmp_path / "queue"), agent="a", pid=sleeper.pid, cfg=Config())
        num = first.enqueue("key", "s", request={"message": "m"})
        first.adopt(num)  # the first worker owns it, and it is alive
        assert land_worker.worker_main(num) == 3
        assert [e["kind"] for e in first.store.events()].count("adopted") == 1  # the second one did not adopt it
    finally:
        sleeper.kill()


def test_git_running_sees_a_git_in_a_linked_worktree_and_one_started_with_dash_c(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    sp.run(["git", "init", "-q"], cwd=main, check=True)
    sp.run(
        ["git", "-c", "user.email=t@e.t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"],
        cwd=main,
        check=True,
    )
    tree = tmp_path / "linked"
    sp.run(["git", "worktree", "add", "-q", str(tree)], cwd=main, check=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    holder = sp.Popen(
        ["git", "-C", str(tree), "cat-file", "--batch"], cwd=elsewhere, stdin=-1, stdout=-1
    )  # waits on stdin
    try:
        time.sleep(1.0)
        assert landing_proc.git_running(main)  # its cwd is outside the repo, but -C names a worktree of it
    finally:
        holder.kill()
    inside = sp.Popen(["git", "cat-file", "--batch"], cwd=tree, stdin=-1, stdout=-1)
    try:
        time.sleep(1.0)
        assert landing_proc.git_running(main)  # cwd in a linked worktree
    finally:
        inside.kill()
    assert os.path.isdir(tree) and pytest is not None


def test_git_running_reads_dash_c_and_worktree_arguments_even_when_the_cwd_is_elsewhere(tmp_path, monkeypatch):
    main, tree, elsewhere = tmp_path / "main", tmp_path / "linked", tmp_path / "elsewhere"
    for d in (main, elsewhere):
        d.mkdir()
    sp.run(["git", "init", "-q"], cwd=main, check=True)
    sp.run(
        ["git", "-c", "user.email=t@e.t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "b"],
        cwd=main,
        check=True,
    )
    sp.run(["git", "worktree", "add", "-q", str(tree)], cwd=main, check=True)

    class Fake:
        def __init__(self, cwd, args):
            self.info, self._cwd, self._args = {"name": "git.exe"}, cwd, args

        def cwd(self):
            return str(self._cwd)

        def cmdline(self):
            return self._args

    def only(proc):  # noqa: ANN001, ANN202
        monkeypatch.setattr(landing_proc.psutil, "process_iter", lambda attrs=None: [proc])
        return landing_proc.git_running(main)

    assert only(Fake(elsewhere, ["git", "-C", str(tree), "status"]))  # named by -C, a linked worktree of the repo
    assert only(Fake(tree, ["git", "status"]))  # cwd in a linked worktree
    assert not only(Fake(elsewhere, ["git", "status"]))  # a git elsewhere that never touches the repo
