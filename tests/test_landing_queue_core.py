"""Landing queue core: order, one in flight, no gates while waiting, fairness, presence while waiting."""

from __future__ import annotations

import pytest
from scripts.crew.brief.landing_queue import AttemptCapReached, Config, Outcome

from tests._landing_fakes import World, holder_numbers


def test_turns_are_granted_in_ticket_order(tmp_path):
    w = World(tmp_path)
    a, b, c = w.lane("a", 101), w.lane("b", 102), w.lane("c", 103)
    na, nb, nc = a.enqueue("ka", "s"), b.enqueue("kb", "s"), c.enqueue("kc", "s")
    assert (na, nb, nc) == (1, 2, 3)
    assert a.wait_turn(na) == "granted"
    steps = [lambda: a.hold(na, w.committer("ka")), lambda: (b.wait_turn(nb), b.hold(nb, w.committer("kb")))]

    def sleep(dt: float) -> None:
        w.clock.advance(dt)
        if steps:
            steps.pop(0)()

    c.sleep = sleep
    assert c.wait_turn(nc) == "granted"
    assert [m.split("Landing-Ticket: ")[1] for _, m in w.dev] == ["ka", "kb"]  # a landed before b, c came last


def test_only_one_landing_is_in_flight(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    assert a.wait_turn(na) == "granted"
    seen: list[list[int]] = []
    b.sleep = lambda dt: (w.clock.advance(dt), seen.append(holder_numbers(b)))
    assert b.wait_turn(nb, max_wait=10) == "timeout"  # a keeps the slot, so b never gets it
    assert seen and all(row == [na] for row in seen)
    assert "granted" not in [e["kind"] for e in w.store.events() if e["ticket"] == nb]


def test_waiting_runs_no_commit_and_only_the_holder_commits(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    b.sleep = lambda dt: w.clock.advance(dt)
    assert b.wait_turn(nb, max_wait=6) == "timeout"
    assert w.commit_calls == 0
    assert a.wait_turn(na) == "granted"
    a.hold(na, w.committer("ka"))
    assert w.commit_calls == 1


def test_presence_is_refreshed_on_every_poll_while_waiting(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    a.enqueue("ka", "s")
    nb = b.enqueue("kb", "s")
    before = w.presence_calls
    phases = []
    b.sleep = lambda dt: (w.clock.advance(dt), phases.append(w.store.beats([nb])[nb]["phase"]))
    b.wait_turn(nb, max_wait=20)  # 2 s polls for about 22 s: one heartbeat write per 5 s, not one per poll
    assert 3 <= w.presence_calls - before <= 5
    assert set(phases) == {"waiting"}


def test_waiter_status_line_names_position_and_holder(tmp_path):
    w = World(tmp_path, Config(poll=2.0, say_every=3.0))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na = a.enqueue("ka", "s")
    a.wait_turn(na)
    nb = b.enqueue("kb", "s")
    b.wait_turn(nb, max_wait=7)
    assert any("1 ahead" in line and "holder: a" in line and "est. wait" in line for line in w.said)


def test_a_refused_change_returns_with_its_reason_and_frees_the_slot(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)
    verdict, out = a.hold(na, lambda: Outcome(False, blocker="local_gate_failed", message="gate x failed"))
    assert verdict == "refused" and out.blocker == "local_gate_failed"
    assert b.wait_turn(nb) == "granted"  # the next ticket went straight in; the refused one did not keep the slot
    assert w.dev == []


def test_a_requeue_goes_to_the_tail_with_an_attempt_counter(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    n1 = a.enqueue("ka", "s")
    a.wait_turn(n1)
    a.hold(n1, lambda: Outcome(False, blocker="x", message="no"))
    nb = b.enqueue("kb", "s")
    n2 = a.enqueue("ka", "s")
    assert n2 > nb  # behind b, not back at the head
    assert w.store.tickets()[n1]["attempt"] == 1 and w.store.tickets()[n2]["attempt"] == 2


def _refuse_once(w, lane, key="ka"):
    n = lane.enqueue(key, "s")
    lane.wait_turn(n)
    lane.hold(n, lambda: Outcome(False, blocker="local_gate_failed", message="no"))
    return n


def test_honest_refusals_have_their_own_looser_cap(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    for _ in range(10):
        _refuse_once(w, a)  # ten honest refusals in an hour are allowed: a gate refusal is not abuse
    with pytest.raises(AttemptCapReached) as caught:
        a.enqueue("ka", "s")
    assert "refused-in-slot" in str(caught.value) and 0 < caught.value.retry_in <= 3600
    w.clock.advance(3601)
    assert a.enqueue("ka", "s")  # the oldest attempt aged out of the window


def test_a_hold_that_overran_its_lease_counts_toward_the_strict_cap(tmp_path):
    w = World(tmp_path, Config(poll=2.0, max_hold=30.0, say_every=1e9))
    a, b = w.lane("a", 101), w.lane("b", 102)
    for i in range(3):
        n = a.enqueue(f"k{i}", "s")
        a.wait_turn(n)
        w.clock.advance(31)  # a keeps the slot past its lease while its process is alive
        nb = b.enqueue(f"kb{i}", "s")
        b.wait_turn(nb)
        b.hold(nb, w.committer(f"kb{i}"))
    with pytest.raises(AttemptCapReached) as caught:
        a.enqueue("again", "s")
    assert "slot-wasting" in str(caught.value)


def test_timeouts_withdrawals_and_dead_waiters_never_count(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    for i in range(6):
        n = a.enqueue(f"k{i}", "s")
        a.withdraw(n)
    n = a.enqueue("kt", "s")
    w.alive.discard(101)
    b.reap()  # a's waiter died: the lane drops it
    w.alive.add(101)
    assert a.enqueue("fresh", "s")  # still allowed: none of that cost the shared slot


def test_the_cap_is_keyed_on_the_bound_session_not_the_agent_id(tmp_path):
    w = World(tmp_path)
    one, two = w.lane("shared", 101), w.lane("shared", 102)
    one.session, two.session = "session-one", "session-two"
    for _ in range(10):
        _refuse_once(w, one)
    with pytest.raises(AttemptCapReached):
        one.enqueue("x", "s")
    assert two.enqueue("x", "s")  # another session under the same agent id is not locked out


def test_landings_never_count_against_the_cap(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    for i in range(6):
        n = a.enqueue(f"k{i}", "s")
        a.wait_turn(n)
        assert a.hold(n, w.committer(f"k{i}"))[0] == "landed"
    assert len(w.dev) == 6


def test_a_failing_head_cannot_block_the_line(tmp_path):
    w = World(tmp_path)
    a, b, c = w.lane("a", 101), w.lane("b", 102), w.lane("c", 103)
    na, nb, nc = a.enqueue("ka", "s"), b.enqueue("kb", "s"), c.enqueue("kc", "s")
    a.wait_turn(na)
    a.hold(na, lambda: Outcome(False, blocker="x", message="no"))
    b.wait_turn(nb)
    b.hold(nb, w.committer("kb"))
    assert c.wait_turn(nc) == "granted"


def test_a_commit_that_raises_still_releases_the_slot(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    a.wait_turn(na)

    def boom() -> Outcome:
        raise OSError("disk went away")

    with pytest.raises(OSError):
        a.hold(na, boom)
    assert b.wait_turn(nb) == "granted"
    assert next(e for e in w.store.events() if e["ticket"] == na and e["kind"] == "refused")["blocker"] == "lane_error"


def test_wait_timeout_leaves_the_line_with_a_notice(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    a.enqueue("ka", "s")
    nb = b.enqueue("kb", "s")
    started = w.clock()
    assert b.wait_turn(nb, max_wait=5) == "timeout"
    assert 5 < w.clock() - started <= 8  # it left when its own limit passed, not later
    state = b.states()[nb]
    assert state["state"] == "abandoned" and "run land.py again" in state["notice"]


def test_estimate_uses_recent_hold_times(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    a.wait_turn(n)
    w.clock.advance(20)
    a.hold(n, w.committer("ka"))
    assert a.durations() == [20.0]
    assert a.eta(2) == 60.0
