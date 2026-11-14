"""Regression tests for the independent review of the landing queue (H2, M1, M3, M4, M5, M7 and the lease/orphan rules)."""

from __future__ import annotations

import os

from scripts.crew.brief import landing_status
from scripts.crew.brief.landing_queue import Config

from tests._landing_fakes import World


def _garbage_beat(w, n, age):  # noqa: ANN001, ANN202
    path = w.store.root / "beats" / f"T{n:06d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json")
    stamp = w.clock() - age
    os.utime(path, (stamp, stamp))


def kinds(w: World, ticket: int) -> list[str]:
    return [e["kind"] for e in w.store.events() if e["ticket"] == ticket]


# ---- H2: nobody's own words set the lease
def test_a_forged_max_hold_does_not_extend_the_lease(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=100.0, say_every=1e9))
    evil, good = w.lane("evil", 1), w.lane("good", 2)
    ne = evil.enqueue("ke", "s")
    w.store.append("granted", ne, by="evil", now=w.clock(), max_hold=1e9)  # the holder writes its own lease
    w.alive.add(555)
    w.store.beat(ne, now=w.clock(), pid=1, child=555, child_start=0, phase="holding")  # any live pid as the "child"
    ng = good.enqueue("kg", "s")

    def sleeper(dt):  # noqa: ANN001, ANN202
        w.clock.advance(dt)
        w.store.beat(ne, now=w.clock(), pid=1, child=555, child_start=0, phase="holding")

    good.sleep = sleeper
    t0 = w.clock()
    assert good.wait_turn(ng, max_wait=10_000) == "granted"
    assert w.clock() - t0 < 110  # was: 86,402 simulated seconds
    assert good.states()[ne]["reason"].startswith("lease_expired")


def test_the_lease_is_clamped_to_the_reapers_value_and_the_ceiling_and_junk_is_ignored(tmp_path):
    w = World(tmp_path, Config(max_hold=3000.0, max_hold_ceiling=1800.0))
    a = w.lane("a", 1)
    n = a.enqueue("ka", "s")
    for declared, expected in ((5000, 1800.0), (60, 60.0), ("abc", 1800.0), (None, 1800.0), (-5, -5.0)):
        w.store.append("granted", n, by="a", now=w.clock(), max_hold=declared)
        assert a.states()[n]["max_hold"] == (expected if declared != -5 else -5.0)
        break
    for declared, expected in ((5000, 1800.0), (60, 60.0), ("abc", 1800.0), (None, 1800.0)):
        w2 = World(tmp_path / f"w{declared}", Config(max_hold=3000.0, max_hold_ceiling=1800.0))
        lane = w2.lane("a", 1)
        num = lane.enqueue("ka", "s")
        w2.store.append("granted", num, by="a", now=w2.clock(), max_hold=declared)
        assert lane.states()[num]["max_hold"] == expected


def test_verify_reports_a_lease_the_reaper_had_to_clamp(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 1)
    n = a.enqueue("ka", "s")
    w.store.append("granted", n, by="a", now=w.clock(), max_hold=1e9)
    assert any("granted a lease of 1000000000.0 s" in f and "clamped" in f for f in a.audit())
    status = landing_status.build_status(a, verify=True)
    assert any("clamped" in f for f in status["tamper_findings"])


def test_a_holder_may_ask_for_a_shorter_lease(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 1)
    n = a.enqueue("ka", "s")
    w.store.append("granted", n, by="a", now=w.clock(), max_hold=30)
    assert a.states()[n]["max_hold"] == 30.0


# ---- M1: a wall clock that is set must not reap live tickets
def test_a_one_hour_wall_clock_jump_reaps_nobody_who_is_alive(tmp_path):
    w = World(tmp_path)
    h = w.lane("h", 11)
    nh = h.enqueue("kh", "s")
    h.wait_turn(nh)
    w.alive.add(12)
    w.store.beat(nh, now=w.clock(), pid=11, child=12, child_start=0, phase="holding")
    ws = [w.lane(f"w{i}", 20 + i) for i in range(5)]
    nws = [x.enqueue(f"k{i}", "s") for i, x in enumerate(ws)]
    for x, n in zip(ws, nws, strict=True):
        x.beat(n, "waiting")
    ws[0].reap()  # a poller that has been running: it has watched every beat
    w.clock.jump(3600)  # the laptop slept; every process is alive
    assert ws[0].reap() == []  # was: one poll reaped the holder and all five waiters
    assert all(s["open"] for s in ws[0].states().values())


def test_after_a_clock_jump_a_really_silent_waiter_is_still_reaped_by_observed_time(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 1), w.lane("b", 2)
    nb = b.enqueue("kb", "s")
    b.wait_turn(nb)  # b holds the slot and keeps beating; a waits behind it and goes silent
    na = a.enqueue("ka", "s")
    b.reap()
    w.clock.jump(3600)
    b.beat(nb, "holding")
    assert b.reap() == []
    w.life(130, b, (b, nb, "holding"))  # a has not beaten for 130 s of observed time while b kept beating
    assert b.states()[na]["reason"] == "heartbeat_stale"


def test_a_dead_pid_is_still_reaped_at_once_after_a_clock_jump(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 1), w.lane("b", 2)
    na = a.enqueue("ka", "s")
    b.reap()
    w.clock.jump(-3600)
    w.alive.discard(1)
    assert b.reap() == [na]


# ---- pid reuse: the start time, not just the pid
def test_a_reused_pid_with_a_different_start_time_is_not_the_owner(tmp_path):
    w = World(tmp_path)
    w.starts[101] = 1000.0
    a, b = w.lane("a", 101), w.lane("b", 102)
    na = a.enqueue("ka", "s")
    assert w.store.tickets()[na]["pid_start"] == 1000.0
    w.starts[101] = 5000.0  # the pid now belongs to a different process
    b.beat(b.enqueue("kb", "s"), "waiting")  # taking a ticket reaps first
    assert b.states()[na]["reason"] == "waiter_dead"


# ---- H3: a surviving commit tool and leftover locks
def test_a_dead_holders_surviving_commit_tool_is_killed_at_the_lease_not_run_beside(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=60.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)
    w.alive.add(555)
    w.starts[555] = 777.0
    w.cmds[555] = "python scripts/crew/brief/fake_commit.py --message m"
    a.beat(na, "holding", 555, 777.0, child_script="fake_commit.py")
    w.alive.discard(101)  # land.py died; commit.py (555) lives
    b.sleep = lambda dt: (w.clock.advance(dt), w.store.beat(nb, now=w.clock(), pid=102, phase="waiting"))
    assert b.reap() == []
    assert b.wait_turn(nb, max_wait=500) == "granted"
    assert w.killed == [555]  # killed first, only then granted: two commit tools never run at once
    skipped = next(e for e in w.store.events() if e["kind"] == "skipped")
    assert skipped["child_pid"] == 555 and skipped["killed"] is True


def test_a_commit_tool_that_cannot_be_killed_blocks_the_next_grant(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=60.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)
    w.alive.add(555)
    w.starts[555] = 777.0
    w.cmds[555] = "python fake_commit.py"
    a.beat(na, "holding", 555, 777.0, child_script="fake_commit.py")
    w.alive.discard(101)
    b.kill_child = lambda pid, start: None  # access denied
    b.sleep = lambda dt: (w.clock.advance(dt), w.store.beat(nb, now=w.clock(), pid=102, phase="waiting"))
    assert (
        b.wait_turn(nb, max_wait=100) == "timeout"
    )  # skipped at the lease (60 s); then one more lease it keeps waiting for the orphan
    assert "granted" not in kinds(w, nb)


def test_the_commit_tool_whose_pid_was_reused_is_not_killed(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=60.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)
    w.alive.add(555)
    w.starts[555] = 9999.0  # a different process now has that pid
    w.cmds[555] = "python scripts/fake_commit.py --message m"
    a.beat(na, "holding", 555, 777.0, child_script="fake_commit.py")
    w.alive.discard(101)
    b.beat(nb, "waiting")
    w.clock.advance(5)
    b.reap()
    assert w.killed == [] and b.states()[na]["reason"] == "holder_dead"


def test_abandoned_git_locks_are_cleaned_before_the_next_grant_and_reported(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    w.locks = (["index.lock", "dev.lock"], [])
    assert a.wait_turn(n) == "granted"
    granted = next(e for e in w.store.events() if e["kind"] == "granted")
    assert granted["locks_cleaned"] == ["index.lock", "dev.lock"]
    assert any("index.lock" in line for line in w.said)


def test_locks_that_git_still_holds_delay_the_grant_but_never_for_ever(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    w.locks = ([], ["index.lock"])  # a git process is running: not safe to remove
    t0 = w.clock()
    assert a.wait_turn(n) == "granted"
    assert 8 <= w.clock() - t0 <= 12  # five polls, then it goes ahead anyway


# ---- L1: the commit tool's budget is what is left of the lease
def test_the_commit_budget_is_the_lease_minus_the_time_since_the_grant(tmp_path):
    w = World(tmp_path, Config(max_hold=100.0))
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    a.wait_turn(n)
    w.clock.advance(30)
    assert a.lease_left(n) == 70.0
