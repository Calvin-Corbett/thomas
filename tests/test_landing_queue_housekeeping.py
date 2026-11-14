"""Regression tests for the independent review of the landing queue, part two: identity, forged lines, number reuse,
pruning, the heartbeat write rate, submitted tickets and orphaned waits (M3, M4, M5, M7, H4)."""

from __future__ import annotations

import os

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


# ---- M3: identity and the cap
def test_attaching_to_your_own_open_ticket_never_makes_a_second_one(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    a.session = "s1"
    n = a.enqueue("ka", "s")
    assert a.enqueue("ka", "s") == n
    other = w.lane("a", 102)
    other.session = "s2"
    assert other.enqueue("ka", "s") != n  # another session is another identity, even under the same agent id


# ---- M4: forged lane lines and number reuse
def test_an_abandoned_line_written_by_someone_else_is_ignored_and_reported(tmp_path):
    w = World(tmp_path)
    a, mallory = w.lane("a", 101), w.lane("mallory", 102)
    n = a.enqueue("ka", "s")
    w.store.append("abandoned", n, by="mallory", now=w.clock(), reason="waiter_dead", notice="gone")
    assert mallory.states()[n]["open"] and mallory.states()[n]["ignored"]
    assert any("written by mallory, not a or a lane" in f for f in mallory.audit())


def test_a_lane_verdict_that_the_owner_is_dead_is_not_honoured_while_it_lives(tmp_path):
    w = World(tmp_path)
    w.starts[101] = 1000.0
    a, b = w.lane("a", 101), w.lane("b", 102)
    n = a.enqueue("ka", "s")
    w.store.append("abandoned", n, by="lane:b", now=w.clock(), reason="waiter_dead", notice="forged")
    assert b.states()[n]["open"]  # pid 101 is alive and is the same process
    assert any("is alive and is the same process" in f for f in b.audit())
    w.alive.discard(101)
    assert not b.states()[n]["open"]  # once it really is dead the same line stands


def test_a_deleted_ticket_file_does_not_hand_its_number_to_the_next_ticket(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    a.enqueue("ka", "s")
    n2 = a.enqueue("kb", "s")
    (w.store.root / "tickets" / f"T{n2:06d}.json").unlink()
    n3 = b.enqueue("kc", "s")
    assert n3 == n2 + 1  # was: the number was reused and the new ticket was born "abandoned"
    assert b.states()[n3]["open"]
    assert any(f"T{n2:06d} is missing" in f for f in b.audit())


def test_a_taken_line_for_a_number_that_is_used_twice_is_reported(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    w.store.append("taken", n, by="a", now=w.clock(), ticket_sha="x")
    assert any("was taken twice" in f for f in a.audit())


# ---- M5: pruning, and what a poll reads
def test_the_lane_prunes_old_finished_tickets_and_nothing_else_notices(tmp_path):
    w = World(tmp_path, Config(poll=2.0, say_every=1e9, keep_closed=20))
    a, b = w.lane("a", 101), w.lane("b", 102)
    for i in range(70):
        n = a.enqueue(f"k{i}", "s")
        a.withdraw(n)
    waiting = b.enqueue("keep-me-open", "s")
    a.enqueue("trigger", "s")
    tickets = list((w.store.root / "tickets").glob("T*.json"))
    assert len(tickets) < 50  # bounded, not 72
    assert waiting in a.states() and a.states()[waiting]["open"]  # an open ticket is never pruned
    newest = a.enqueue("fresh", "s")
    assert newest > 72  # numbers never go backwards
    assert a.audit() == []  # a prune is not mistaken for tampering
    assert not (w.store.root / "prune.lock").exists()


def test_a_prune_never_removes_a_finished_ticket_that_is_newer_than_an_open_one(tmp_path):
    w = World(tmp_path, Config(keep_closed=5))
    a, b = w.lane("a", 101), w.lane("b", 102)
    old_open = a.enqueue("old", "s")
    for i in range(30):
        n = b.enqueue(f"k{i}", "s")
        b.withdraw(n)
    assert (w.store.root / "tickets" / f"T{old_open:06d}.json").exists()
    assert len(a.states()) >= 6


def test_beats_are_dropped_when_a_ticket_finishes_and_read_only_for_open_ones(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    a.wait_turn(n)
    a.hold(n, w.committer("ka"))
    assert not (w.store.root / "beats" / f"T{n:06d}.json").exists()
    n2 = a.enqueue("kb", "s")
    a.beat(n2, "waiting")
    assert list(w.store.beats([n2])) == [n2] and w.store.beats([n]) == {}


def test_heartbeat_writes_are_at_most_one_per_waiter_per_five_seconds(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    a.enqueue("ka", "s")
    nb = b.enqueue("kb", "s")
    writes = []
    real = w.store.beat
    w.store.beat = lambda *args, **kw: (writes.append(w.clock()), real(*args, **kw))
    b.wait_turn(nb, max_wait=58)
    gaps = [y - x for x, y in zip(writes, writes[1:], strict=False)]
    assert gaps and min(gaps) >= 5.0 and len(writes) <= 12


# ---- detached tickets
def test_a_submitted_ticket_survives_a_gap_between_calls_and_expires_after_the_grace(tmp_path):
    w = World(tmp_path, Config(resume_grace=600.0))
    a, b = w.lane("a", 101), w.lane("b", 102)
    nb = b.enqueue("kb", "s")  # b is the head and is the one that reaps; a's submitted ticket waits behind it
    n = a.enqueue("ka", "s", mode="detached")
    beaters = ((a, n, "waiting"), (b, nb, "waiting"))
    w.life(480, b, *beaters)  # nobody asks for 480 s: inside the grace
    assert b.states()[n]["open"]
    a.touch(n, throttle=False)
    w.life(540, b, *beaters)  # 540 s after the last ask
    assert b.states()[n]["open"]
    w.life(120, b, *beaters)
    assert b.states()[n]["reason"] == "nobody_resumed"


def test_a_ticket_dropped_for_lack_of_a_resume_does_not_count_against_the_cap(tmp_path):
    w = World(tmp_path, Config(resume_grace=100.0))
    a, b = w.lane("a", 101), w.lane("b", 102)
    nb = b.enqueue("kb", "s")
    b.wait_turn(nb)  # b holds the slot; a's submitted tickets queue behind it
    for i in range(8):
        n = a.enqueue(f"k{i}", "s", mode="detached")
        w.life(104, b, (a, n, "waiting"), (b, nb, "holding"))
        assert b.states()[n]["reason"] == "nobody_resumed"
    assert a.enqueue("again", "s")


def test_a_workers_liveness_follows_its_adoption_not_the_submitting_process(tmp_path):
    w = World(tmp_path)
    front = w.lane("a", 101)
    n = front.enqueue("ka", "s", mode="detached")
    worker = w.lane("a", 202)
    worker.adopt(n)
    w.alive.discard(101)  # the submitting land.py exited
    w.lane("b", 102).beat(0, "x")
    b = w.lane("b", 103)
    b.beat(b.enqueue("kb", "s"), "waiting")
    worker.beat(n, "waiting")
    assert b.reap() == []
    w.alive.discard(202)
    assert b.reap() == [n]


def test_a_wait_stops_when_the_process_that_started_it_is_gone(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    a.enqueue("ka", "s")
    nb = b.enqueue("kb", "s")
    b.stop_if = lambda: "parent_gone" if 999 not in w.alive else None
    assert b.wait_turn(nb) == "lost"
    assert b.states()[nb]["reason"] == "parent_gone"
    assert os.name  # keep the import honest


def test_an_event_older_than_its_ticket_means_the_number_was_reused_and_is_reported(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    w.store.append("granted", n, by="a", now=w.clock() - 3600, max_hold=60)  # a line from before this ticket existed
    assert any("is older than the ticket" in f for f in a.audit())


def test_a_garbage_heartbeat_behind_a_live_holder_is_dropped_by_age_not_kept_alive(tmp_path):
    w = World(tmp_path)
    holder, bad, watcher = w.lane("h", 1), w.lane("bad", 2), w.lane("w", 3)
    nh = holder.enqueue("kh", "s")
    holder.wait_turn(nh)
    nbad = bad.enqueue("kb", "s")
    _garbage_beat(w, nbad, age=0)
    nw = watcher.enqueue("kw", "s")
    w.life(240, watcher, (holder, nh, "holding"), (watcher, nw, "waiting"))
    assert watcher.states()[nbad]["state"] == "abandoned" and watcher.states()[nbad]["reason"] == "heartbeat_stale"
    assert watcher.states()[nh]["open"]
