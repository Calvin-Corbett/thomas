"""Landing queue recovery: kill the holder (or waiter) at each step; nothing is lost and nothing lands twice."""

from __future__ import annotations

from scripts.crew.brief.landing_queue import Config, Outcome

from tests._landing_fakes import World


def kinds(w: World, ticket: int) -> list[str]:
    return [e["kind"] for e in w.store.events() if e["ticket"] == ticket]


def test_kill_before_the_slot_drops_the_waiter_and_the_line_moves(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    w.alive.discard(101)  # a dies while still waiting
    assert b.wait_turn(nb) == "granted"
    assert b.states()[na]["state"] == "abandoned" and "waiter_dead" in b.states()[na]["reason"]
    assert w.dev == []  # a's change never landed, and says so


def test_kill_after_the_slot_before_the_commit_loses_nothing_and_lands_once_on_retry(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    assert a.wait_turn(na) == "granted"
    w.alive.discard(101)  # a dies holding the slot, before it ran the commit tool
    assert b.wait_turn(nb) == "granted"
    skipped = b.states()[na]
    assert (
        skipped["state"] == "skipped" and "holder_dead" in skipped["reason"] and "nothing landed" in skipped["notice"]
    )
    b.hold(nb, w.committer("kb"))
    a2 = w.lane("a", 111)  # the agent comes back and re-runs: tail of the line, lands exactly once
    n2 = a2.enqueue("ka", "s")
    assert a2.wait_turn(n2) == "granted"
    assert a2.hold(n2, w.committer("ka"))[0] == "landed"
    assert [m.split("Landing-Ticket: ")[1] for _, m in w.dev] == ["kb", "ka"]


def test_kill_after_the_branch_moved_before_the_ledger_line_is_not_landed_twice(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)
    sha = w.land_on_dev("ka")  # the compare-and-swap happened ...
    w.alive.discard(101)  # ... and the holder died before it wrote anything
    assert b.wait_turn(nb) == "granted"
    state = b.states()[na]
    assert state["state"] == "recovered" and state["sha"] == sha and f"already landed as {sha}" in state["notice"]
    a2 = w.lane("a", 111)
    n2 = a2.enqueue("ka", "s")
    a2.wait_turn(n2)
    verdict, out = a2.hold(n2, w.committer("ka"))
    assert verdict == "already_landed" and out.sha == sha
    assert len([1 for _, m in w.dev if "Landing-Ticket: ka" in m]) == 1 and w.commit_calls == 0


def test_kill_after_the_landed_line_before_the_release_just_releases(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)
    sha = w.land_on_dev("ka")
    w.store.append("landed", na, by="a", now=w.clock(), sha_landed=sha)
    w.alive.discard(101)
    assert b.wait_turn(nb) == "granted"
    assert b.states()[na]["state"] == "recovered" and b.states()[na]["sha"] == sha
    assert len(w.dev) == 1


def test_a_hung_holder_is_skipped_when_its_lease_runs_out(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=100.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)

    def sleep(dt: float) -> None:
        w.clock.advance(dt)
        a.beat(na, "holding")  # a is alive and heartbeating, just not finishing

    b.sleep = sleep
    assert b.wait_turn(nb, max_wait=1000) == "granted"
    assert 100 < w.clock() - b.states()[na]["events"][1]["at"] < 110
    assert b.states()[na]["state"] == "skipped" and b.states()[na]["reason"].startswith("lease_expired")


def test_the_hung_holder_that_lands_late_is_recorded_not_landed_again(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=60.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    z, nz = w.bystander()
    a.wait_turn(na)

    def slow_commit() -> Outcome:
        w.life(
            62, b, (a, na, "holding"), (b, nb, "waiting"), (z, nz, "waiting")
        )  # a hangs past its lease, alive and beating
        return Outcome(
            True, sha=w.land_on_dev("ka")
        )  # ... b took the slot back, and then a's commit tool finishes anyway

    verdict, out = a.hold(na, slow_commit)
    assert verdict == "landed" and b.states()[na]["state"] == "skipped" and b.states()[na]["sha"] == out.sha
    a2 = w.lane("a", 111)
    n2 = a2.enqueue("ka", "s")
    a2.wait_turn(n2)
    assert a2.hold(n2, w.committer("ka"))[0] == "already_landed"
    assert len(w.dev) == 1


def test_a_dead_holder_whose_commit_process_still_runs_keeps_the_slot_until_the_lease_ends(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=100.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    z, nz = w.bystander()
    a.wait_turn(na)
    w.alive.add(555)
    a.beat(na, "holding", child_pid=555)
    w.alive.discard(101)  # land.py died but its commit.py child still runs and may still move the branch
    assert b.reap() == []
    w.life(90, b, (b, nb, "waiting"), (z, nz, "waiting"))
    assert b.states()[na]["open"]  # inside the lease
    w.life(14, b, (b, nb, "waiting"), (z, nz, "waiting"))
    assert not b.states()[na]["open"] and "still running" in b.states()[na]["reason"]


def test_a_holder_with_a_stale_heartbeat_is_skipped_but_a_fresh_one_is_not(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    z, nz = w.bystander()
    a.wait_turn(na)
    w.life(100, b, (b, nb, "waiting"), (z, nz, "waiting"))  # 100 s since a's last beat: inside the 120 s allowance
    assert b.states()[na]["open"]
    w.life(30, b, (b, nb, "waiting"), (z, nz, "waiting"))  # 130 s: frozen or pid reused
    assert b.states()[na]["reason"] == "heartbeat_stale"


def test_a_waiter_that_keeps_beating_is_not_dropped_but_a_silent_one_is(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    for _ in range(4):
        w.clock.advance(80)
        b.beat(nb, "waiting")
    assert na in b.reap() and nb not in b.reap()  # a never beat for 320 s; b beat every 80 s
    assert b.states()[nb]["open"]


def test_a_second_reaper_does_not_write_a_second_verdict(tmp_path):
    w = World(tmp_path)
    a, b, c = w.lane("a", 101), w.lane("b", 102), w.lane("c", 103)
    na = a.enqueue("ka", "s")
    w.alive.discard(101)
    assert b.reap() == [na]
    assert c.reap() == []
    assert kinds(w, na).count("abandoned") == 1


def test_a_closed_ticket_stops_the_old_holder_from_committing(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    z, nz = w.bystander()
    a.wait_turn(na)
    w.life(1000, b, (b, nb, "waiting"), (z, nz, "waiting"))  # lease over, a is skipped
    verdict, out = a.hold(na, w.committer("ka"))
    assert verdict == "lost" and w.commit_calls == 0
    assert "skipped" in out.blocker


def test_the_queue_survives_a_chain_of_deaths(tmp_path):
    w = World(tmp_path)
    lanes = [w.lane(f"x{i}", 200 + i) for i in range(5)]
    nums = [lane.enqueue(f"k{i}", "s") for i, lane in enumerate(lanes)]
    for dead in (200, 201, 202):
        w.alive.discard(dead)
    assert lanes[3].wait_turn(nums[3]) == "granted"
    lanes[3].hold(nums[3], w.committer("k3"))
    assert lanes[4].wait_turn(nums[4]) == "granted"
    lanes[4].hold(nums[4], w.committer("k4"))
    assert [m.split("Landing-Ticket: ")[1] for _, m in w.dev] == ["k3", "k4"]


def test_a_reaper_that_loses_the_race_writes_nothing(tmp_path):
    w = World(tmp_path)
    a, b, c = w.lane("a", 101), w.lane("b", 102), w.lane("c", 103)
    na = a.enqueue("ka", "s")
    w.alive.discard(101)
    raced = []

    def alive(pid):  # noqa: ANN001, ANN202
        if pid == 101 and not raced:
            raced.append(c.reap())  # while b is judging a, c finishes the same verdict
        return pid in w.alive

    b.pid_alive = alive
    assert b.reap() == [] and raced == [[na]]
    assert kinds(w, na).count("abandoned") == 1


def test_a_landed_line_is_trusted_even_when_dev_history_no_longer_shows_the_key(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)
    w.store.append("landed", na, by="a", now=w.clock(), sha_landed="abc123")  # dev was rewritten or the key aged out
    w.alive.discard(101)
    assert b.wait_turn(nb) == "granted"
    assert b.states()[na]["state"] == "recovered" and b.states()[na]["sha"] == "abc123"
    assert "already landed as abc123" in b.states()[na]["notice"]
