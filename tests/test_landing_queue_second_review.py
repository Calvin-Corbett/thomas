"""Regression tests for the second review of the landing queue: sleep, stray ledger files, forged lines, forged heartbeats."""

from __future__ import annotations

import time

from scripts.crew.brief import land_worker, landing_status
from scripts.crew.brief.landing_queue import Config

from tests._landing_fakes import World


def kinds(w: World, ticket: int) -> list[str]:
    return [e["kind"] for e in w.store.events() if e["ticket"] == ticket]


# ---- H1: the machine sleeps. Windows counts suspend in the monotonic clock, so BOTH clocks jump together.
def sleeping_queue(tmp_path):
    w = World(tmp_path)
    h = w.lane("h", 11)
    nh = h.enqueue("kh", "s")
    h.wait_turn(nh)
    w.alive.add(12)
    h.beat(nh, "holding", 12)
    ws = [w.lane(f"w{i}", 20 + i) for i in range(5)]
    nws = [x.enqueue(f"k{i}", "s") for i, x in enumerate(ws)]
    for x, n in zip(ws, nws, strict=True):
        x.beat(n, "waiting")
    ws[0].reap()  # a poller that has been running: it has a baseline
    return w, h, nh, ws, nws


def test_a_sleep_where_both_clocks_jump_reaps_nobody_who_is_alive(tmp_path):
    w, h, nh, ws, nws = sleeping_queue(tmp_path)
    w.clock.advance(3600)  # the lid closes for an hour: wall AND monotonic both move
    assert ws[0].reap() == []  # was: the first poller to wake reaped the holder and every other waiter
    assert all(s["open"] for s in ws[0].states().values())
    fresh = w.lane("fresh", 99)  # a process started after the wake has no gap of its own to notice
    assert fresh.reap() == []
    assert all(s["open"] for s in fresh.states().values())


def test_after_a_sleep_a_dead_pid_is_reaped_at_once_and_a_silent_one_after_the_normal_allowance(tmp_path):
    w, h, nh, ws, nws = sleeping_queue(tmp_path)
    w.clock.advance(3600)
    fresh = w.lane("fresh", 99)
    w.alive.discard(20)  # this one really died
    assert fresh.reap() == [nws[0]]
    beaters = [(h, nh, "holding"), *[(x, n, "waiting") for x, n in zip(ws[2:], nws[2:], strict=True)]]
    w.life(130, fresh, *beaters)  # ws[1] stays silent for 130 s of awake time
    assert fresh.states()[nws[1]]["reason"] == "heartbeat_stale"
    assert all(fresh.states()[n]["open"] for n in nws[2:]) and fresh.states()[nh]["open"]


def test_a_holder_that_slept_through_its_lease_gets_the_lease_again_from_the_wake(tmp_path):
    w, h, nh, ws, nws = sleeping_queue(tmp_path)
    w.clock.advance(3600)
    fresh = w.lane("fresh", 99)
    beaters = [(h, nh, "holding", {"ran": 12.0}), *[(x, n, "waiting") for x, n in zip(ws, nws, strict=True)]]
    w.life(120, fresh, *beaters)
    assert fresh.states()[nh][
        "open"
    ]  # alive and beating, 12 s of RUN time: not "lease_expired" for the hour it was asleep


def test_a_holder_whose_own_run_time_passed_the_lease_is_skipped_at_once(tmp_path):
    w = World(tmp_path, Config(max_hold=60.0))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    z, nz = w.bystander()
    a.wait_turn(na)
    w.life(10, b, (a, na, "holding", {"ran": 61.0}), (b, nb, "waiting"), (z, nz, "waiting"))
    assert b.states()[na]["reason"].startswith("lease_expired")


def test_a_waiter_who_woke_first_does_not_make_the_slow_ones_look_dead(tmp_path):
    w = World(tmp_path)
    a, early, slow = w.lane("a", 1), w.lane("early", 2), w.lane("slow", 3)
    na, ne, ns = a.enqueue("ka", "s"), early.enqueue("ke", "s"), slow.enqueue("ks", "s")
    for x, n in ((a, na), (early, ne), (slow, ns)):
        x.beat(n, "waiting")
    a.reap()  # a poller with a baseline, then everything sleeps
    w.clock.advance(3600)
    early.beat(
        ne, "waiting"
    )  # one process woke before a did: the queue is not silent, only a's own gap shows the sleep
    assert a.reap() == []  # was: `slow` was reaped, its beat being an hour old
    assert a.states()[ns]["open"]


# ---- H2: a stray numbered file must not hide later events
def test_a_stray_ledger_file_with_six_nines_does_not_blind_the_queue(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 1)
    n = a.enqueue("ka", "s")
    ledger = w.store.root / "ledger"
    (ledger / "E999999.json").write_text("{}")  # the reviewer's file
    (ledger / "E888888.json").write_text("")
    (ledger / "Eabc.json").write_text("x")
    assert a.wait_turn(n) == "granted"
    assert "E1000000.json" in {p.name for p in ledger.iterdir()}
    assert a.states()[n]["state"] == "holding"  # the later events are read, not skipped past
    a.hold(n, w.committer("ka"))
    assert a.states()[n]["state"] == "released"
    m = a.enqueue("kb", "s")
    assert a.wait_turn(m) == "granted"  # and the next ticket still gets its turn


def test_verify_names_every_bad_ledger_file_and_never_stops_at_the_first(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 1)
    a.enqueue("ka", "s")
    ledger = w.store.root / "ledger"
    (ledger / "E999999.json").write_text("{}")
    (ledger / "E777777.json").write_text('{"kind": 5, "seq": "x"}')
    found = a.audit()
    assert any("E999999.json is not a valid event file" in f for f in found)
    assert any("E777777.json is not a valid event file" in f for f in found)
    assert a.states()  # and the lane reads on


# ---- H3: what S1 cannot stop, and what it can
def test_a_second_worker_cannot_take_a_ticket_that_is_already_held(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    a.wait_turn(n)
    twin = w.lane("a", 102)  # a second `land.py --worker N` for the same ticket
    assert twin.wait_turn(n) == "lost"
    assert kinds(w, n).count("granted") == 1  # was: a second granted line and a second commit tool beside the first


def test_a_lane_verdict_with_a_made_up_reason_about_a_live_holder_is_ignored_and_reported(tmp_path):
    w = World(tmp_path)
    w.starts[101] = 1000.0
    holder, other = w.lane("a", 101), w.lane("b", 102)
    n = holder.enqueue("ka", "s")
    holder.wait_turn(n)
    w.store.append("skipped", n, by="lane:evil", now=w.clock(), reason="because", notice="x")
    assert other.states()[n]["state"] == "holding"
    assert any("is alive and is the same process" in f for f in other.audit())


def test_a_lease_verdict_before_the_lease_was_over_is_ignored(tmp_path):
    w = World(tmp_path, Config(max_hold=300.0))
    holder, other = w.lane("a", 101), w.lane("b", 102)
    n = holder.enqueue("ka", "s")
    holder.wait_turn(n)
    w.store.append("skipped", n, by="lane:evil", now=w.clock() + 5, reason="lease_expired", notice="x")
    assert other.states()[n]["state"] == "holding"


def test_status_says_plainly_that_events_are_unauthenticated_and_what_the_ten_minute_rule_is(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    n = a.enqueue("ka", "s")
    w.alive.discard(101)
    b.reap()
    text = landing_status.render(landing_status.build_status(b, verify=True))
    assert "Tamper-evident, not tamper-proof" in text and "forging a `by` field evicts a ticket" in text
    assert "1 lane verdict(s) on record are attributed only by their own `by` text" in text
    assert "at least every 8 minutes" in text and "45 minutes" in text and n == 1


# ---- M3: a pid named by a heartbeat file is never killed unless it is the commit tool the holder recorded
def forged_holder(tmp_path, *, start, script, cmd):
    w = World(tmp_path, Config(poll=2.0, max_hold=60.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    z, nz = w.bystander()
    a.wait_turn(na)
    w.alive.add(555)  # a victim: any live process
    if start:
        w.starts[555] = start
    if cmd:
        w.cmds[555] = cmd
    a.beat(na, "holding", 555, start, child_script=script)
    w.alive.discard(101)
    w.life(70, b, (b, nb, "waiting"), (z, nz, "waiting"))
    return w, b, na


def test_a_heartbeat_naming_a_pid_without_a_start_time_or_commit_tool_kills_nothing(tmp_path):
    w, b, na = forged_holder(tmp_path, start=0, script="", cmd="")
    assert w.killed == []  # was: the victim process was killed by another agent's reaper
    skipped = next(e for e in w.store.events() if e["kind"] == "skipped")
    assert "without a recorded start time and commit tool" in skipped["child_ignored"] and "child_pid" not in skipped
    assert any("a forged or damaged heartbeat" in f for f in b.audit())


def test_a_heartbeat_with_a_real_start_time_but_another_program_kills_nothing(tmp_path):
    w, b, na = forged_holder(tmp_path, start=5.0, script="fake_commit.py", cmd="notepad.exe C:/x.txt")
    assert w.killed == []
    assert (
        "is not running the commit tool" in next(e for e in w.store.events() if e["kind"] == "skipped")["child_ignored"]
    )


def test_only_the_recorded_commit_tool_with_its_start_time_is_killed_and_only_after_the_lease(tmp_path):
    w, b, na = forged_holder(
        tmp_path, start=5.0, script="fake_commit.py", cmd="python scripts/fake_commit.py --message m"
    )
    assert w.killed == [555]
    assert next(e for e in w.store.events() if e["kind"] == "skipped")["killed"] is True


def test_the_request_carries_the_wait_limit_the_worker_will_honour():
    args = type(
        "A",
        (),
        {
            "agent": "",
            "include": [],
            "allow_scope_fallback": False,
            "fallback_reason": "",
            "max_hold": 900.0,
            "wait_timeout": 123.0,
        },
    )()
    assert land_worker.request_for(args, "m")["wait_timeout"] == 123.0
    assert time.time() > 0
