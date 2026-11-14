"""The lease with REAL processes (H3): an orphaned grandchild, a commit tool that outlives its holder, leftover git locks."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest
from scripts.crew.brief import land_commit, landing_proc
from scripts.crew.brief.landing_queue import Config, Lane
from scripts.crew.brief.landing_store import FileTicketStore

from tests._landing_fakes import sp


def tagged(tag: str) -> list[psutil.Process]:
    """Live processes whose command line carries the tag (the test's marker for 'something it started')."""
    found = []
    for proc in psutil.process_iter(["cmdline"]):
        if any(tag in part for part in proc.info["cmdline"] or []):
            found.append(proc)
    return found


def lane_for(tmp_path, **cfg) -> tuple[Lane, int]:
    lane = Lane(FileTicketStore(tmp_path / "queue"), agent="a", cfg=Config(**cfg))
    num = lane.enqueue("key", "subject")
    lane.wait_turn(num)
    return lane, num


def script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "fake_commit.py"
    path.write_text(body)
    return [sys.executable, str(path)]


def test_an_orphaned_grandchild_that_outlives_its_parent_is_killed_and_the_call_returns_at_once(tmp_path):
    tag = f"orphan-{time.time_ns()}"
    body = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)  # {tag}'])\n"  # its parent exits below: an orphan
        'print(\'{"ok": true, "commit_sha": "abc", "message": "done"}\')\n'
    )
    lane, num = lane_for(tmp_path, max_hold=60.0)
    t0 = time.monotonic()
    out = land_commit.run_commit(script(tmp_path, body), lane, num, Config(max_hold=60.0), "key", root=tmp_path)
    assert out.ok and out.sha == "abc"
    assert (
        time.monotonic() - t0 < 15
    )  # was: 25.5 s on a 2 s lease with a 25 s grandchild, and for ever with a longer one
    time.sleep(0.5)
    assert tagged(tag) == []  # the straggler the commit tool left behind died with the job


def test_the_lease_kills_the_whole_tree_and_bounds_the_return_time(tmp_path):
    tag = f"tree-{time.time_ns()}"
    body = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)  # {tag}'])\n"
        "time.sleep(120)\n"
    )
    lane, num = lane_for(tmp_path, max_hold=3.0)
    t0 = time.monotonic()
    out = land_commit.run_commit(script(tmp_path, body), lane, num, Config(max_hold=3.0), "key", root=tmp_path)
    took = time.monotonic() - t0
    assert not out.ok and out.blocker == "lease_expired"
    assert took < 12, took  # the lease bounds the return, not the grandchild's 120 s
    time.sleep(0.5)
    assert tagged(tag) == []


def test_a_landing_that_completed_just_before_the_kill_is_a_landing_not_a_refusal(tmp_path):
    body = "import time\ntime.sleep(60)\n"
    lane, num = lane_for(tmp_path, max_hold=2.0)
    lane.find_landed = lambda key, includes=(), own=False: "feedbeef"  # dev's tip already carries the key
    out = land_commit.run_commit(script(tmp_path, body), lane, num, Config(max_hold=2.0), "key", root=tmp_path)
    assert out.ok and out.sha == "feedbeef" and "stopped at the lease" in out.message


def test_a_late_failure_after_the_branch_moved_is_still_a_landing(tmp_path):
    body = (
        'print(\'{"ok": false, "blocker_class": "broken_repo_tool", "message": "index.lock"}\')\nraise SystemExit(1)\n'
    )
    lane, num = lane_for(tmp_path)
    lane.find_landed = lambda key, includes=(), own=False: "feedbeef"
    out = land_commit.run_commit(script(tmp_path, body), lane, num, Config(), "key", root=tmp_path)
    assert out.ok and out.sha == "feedbeef" and "late failure" in out.message


def test_a_warning_line_after_the_result_does_not_turn_a_landing_into_an_unparsed_refusal(tmp_path):
    text = '{"ok": true, "commit_sha": "abc", "message": "done"}\nwarning: LF will be replaced by CRLF the next time Git touches it\n'
    out = land_commit.parse_outcome(0, text)
    assert out.ok and out.sha == "abc" and out.blocker is None  # was: blocker "unparsed", counted as a failed attempt
    assert land_commit.parse_outcome(1, "garbage only").blocker == "unparsed"


def test_a_holders_commit_tool_that_survives_the_holder_is_killed_by_the_next_reaper_by_pid_and_start_time(tmp_path):
    tag = f"survivor-{time.time_ns()}"
    child = sp.Popen([sys.executable, "-c", f"import time; time.sleep(120)  # {tag}"])
    try:
        store = FileTicketStore(tmp_path / "queue")
        holder = Lane(store, agent="a", pid=2_000_000_000, cfg=Config(max_hold=2.0))  # land.py is long dead
        num = holder.enqueue("key", "s")
        holder.store.append("granted", num, by="a", now=time.time(), max_hold=2.0)
        holder.store.beat(
            num,
            now=time.time(),
            pid=2_000_000_000,
            child=child.pid,
            child_start=landing_proc.start_time(child.pid),
            child_script=tag,
            phase="holding",
        )
        waiter = Lane(store, agent="b", cfg=Config(max_hold=2.0))
        assert waiter.reap() == []  # the lease is not over: the commit tool may still be landing
        time.sleep(2.6)
        store.beat(
            num,
            now=time.time(),
            pid=2_000_000_000,
            child=child.pid,
            child_start=landing_proc.start_time(child.pid),
            child_script=tag,
            phase="holding",
        )
        assert waiter.reap() == [num]
        child.wait(timeout=10)
        assert child.returncode is not None  # killed
        assert waiter.states()[num]["state"] == "skipped"
    finally:
        child.kill()


def test_a_reused_pid_is_not_killed_by_the_reaper(tmp_path):
    tag = f"innocent-{time.time_ns()}"
    innocent = sp.Popen([sys.executable, "-c", f"import time; time.sleep(30)  # {tag}"])
    try:
        store = FileTicketStore(tmp_path / "queue")
        holder = Lane(store, agent="a", pid=2_000_000_000, cfg=Config(max_hold=1.0))
        num = holder.enqueue("key", "s")
        store.append("granted", num, by="a", now=time.time() - 5, max_hold=1.0)
        store.beat(
            num,
            now=time.time(),
            pid=2_000_000_000,
            child=innocent.pid,
            child_start=landing_proc.start_time(innocent.pid) - 500,
            child_script=tag,
            phase="holding",
        )
        Lane(store, agent="b", cfg=Config(max_hold=1.0)).reap()
        assert innocent.poll() is None  # the recorded start time says it is a different process: left alone
    finally:
        innocent.kill()


def make_repo(tmp_path) -> Path:
    work = tmp_path / "repo"
    work.mkdir()
    sp.run(["git", "init", "-q"], cwd=work, check=True)
    sp.run(
        ["git", "-c", "user.email=t@e.t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"],
        cwd=work,
        check=True,
    )
    return work


def test_abandoned_git_locks_are_removed_only_when_no_git_runs_and_are_reported(tmp_path):
    work = make_repo(tmp_path)
    branch = sp.run(
        ["git", "symbolic-ref", "--short", "HEAD"], cwd=work, capture_output=True, text=True, check=True
    ).stdout.strip()
    locks = [work / ".git" / "index.lock", work / ".git" / "refs" / "heads" / f"{branch}.lock"]
    for lock in locks:
        lock.write_text("")
    future = time.time() + 120  # old enough
    removed, left = landing_proc.clean_stale_locks(work, now=future, running=lambda: True)
    assert removed == [] and sorted(left) == sorted(p.name for p in locks) and all(p.exists() for p in locks)
    removed, left = landing_proc.clean_stale_locks(work, now=future, running=lambda: False)
    assert sorted(removed) == sorted(p.name for p in locks) and left == [] and not any(p.exists() for p in locks)


def test_a_lock_file_younger_than_thirty_seconds_is_left_alone(tmp_path):
    work = make_repo(tmp_path)
    lock = work / ".git" / "index.lock"
    lock.write_text("")
    assert landing_proc.clean_stale_locks(work, running=lambda: False) == ([], [])
    assert lock.exists()


def test_a_timed_out_commit_tool_cleans_its_own_leftover_locks_and_says_so(tmp_path, monkeypatch):
    work = make_repo(tmp_path)
    body = f"import time\nopen(r'{work / '.git' / 'index.lock'}', 'w').close()\ntime.sleep(120)\n"
    lane, num = lane_for(tmp_path, max_hold=3.0)
    monkeypatch.setattr(
        landing_proc, "git_running", lambda root=None: False
    )  # no git elsewhere on this machine can matter
    out = land_commit.run_commit(script(tmp_path, body), lane, num, Config(max_hold=3.0), "key", root=work)
    assert out.blocker == "lease_expired" and "index.lock" in out.message
    assert not (work / ".git" / "index.lock").exists()
