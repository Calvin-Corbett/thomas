"""Landing queue store and status: atomic numbering, the queue root setting, tamper evidence, the status view."""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
from pathlib import Path

import pytest
from scripts.crew.brief import landing_status
from scripts.crew.brief.landing_store import ENV_ROOT, FileTicketStore, resolve_queue_root

from tests._landing_fakes import World


def _take_one(root: str, i: int, barrier) -> None:  # noqa: ANN001
    store = FileTicketStore(root)
    barrier.wait()
    store.take(
        agent=f"agent{i}", session=f"s{i}", pid=os.getpid(), now=time.time(), key=f"k{i}", subject="s", attempt=1
    )


def test_twenty_real_processes_get_twenty_distinct_consecutive_tickets(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(20)
    procs = [ctx.Process(target=_take_one, args=(str(tmp_path / "q"), i, barrier)) for i in range(20)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
    assert all(p.exitcode == 0 for p in procs)
    store = FileTicketStore(tmp_path / "q")
    assert sorted(store.tickets()) == list(range(1, 21))  # no duplicate, no gap, whatever the interleaving
    assert sorted(e["seq"] for e in store.events()) == list(range(1, 21))
    assert sorted(t["agent"] for t in store.tickets().values()) == sorted(f"agent{i}" for i in range(20))
    assert store.verify(now=time.time(), grace=60) == []


def test_numbers_do_not_depend_on_the_clock(tmp_path):
    store = FileTicketStore(tmp_path / "q")
    nums = [
        store.take(agent="a", session="s", pid=1, now=t, key="k", subject="s", attempt=1)
        for t in (500.0, 100.0, 100.0, 9e9)
    ]
    assert nums == [1, 2, 3, 4]  # the clock stepped backwards and sat still; order is still arrival order


def test_the_queue_root_is_one_setting_with_a_shared_default(tmp_path):
    assert resolve_queue_root({ENV_ROOT: str(tmp_path / "cage")}) == tmp_path / "cage"
    default = resolve_queue_root({}, start=tmp_path)  # not a git checkout: falls back to its own runtime folder
    assert default == tmp_path / "runtime" / "coordination" / "landing_queue"


def test_a_deleted_ticket_is_reported(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    a.enqueue("kb", "s")
    (w.store.root / "tickets" / f"T{n:06d}.json").unlink()
    found = w.store.verify(now=w.clock(), grace=60)
    assert any(f"T{n:06d} is missing" in f for f in found)
    assert any(f"ticket T{n:06d} was taken but its file is gone" in f for f in found)


def test_a_rewritten_ticket_is_reported(tmp_path):
    w = World(tmp_path)
    n = w.lane("a", 101).enqueue("ka", "s")
    path = w.store.root / "tickets" / f"T{n:06d}.json"
    body = json.loads(path.read_text())
    path.write_text(json.dumps({**body, "agent": "mallory"}))
    assert any("no longer matches its ledger hash" in f for f in w.store.verify(now=w.clock(), grace=60))


def test_a_deleted_or_edited_ledger_line_is_reported(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    a.wait_turn(n)
    a.hold(n, w.committer("ka"))
    ledger = w.store.root / "ledger"
    (ledger / "E000002.json").unlink()
    edited = ledger / "E000003.json"
    edited.write_text(edited.read_text().replace('"a"', '"b"', 1))
    found = w.store.verify(now=w.clock(), grace=60)
    assert any("E000002 is missing" in f for f in found) and any("E000003" in f and "own hash" in f for f in found)


def test_an_event_written_for_someone_elses_ticket_is_reported(tmp_path):
    w = World(tmp_path)
    n = w.lane("a", 101).enqueue("ka", "s")
    w.store.append("landed", n, by="mallory", now=w.clock(), sha_landed="deadbeef")
    assert any("written by mallory, not a" in f for f in w.store.verify(now=w.clock(), grace=60))


def test_a_ticket_written_by_hand_is_reported_then_dropped_and_never_trusted(tmp_path):
    w = World(tmp_path)
    b = w.lane("b", 102)
    w.alive.add(666)
    tickets = w.store.root / "tickets"
    tickets.mkdir(parents=True)
    (tickets / "T000001.json").write_text(
        json.dumps({"num": 1, "agent": "forger", "pid": 666, "created": w.clock(), "key": "kx"})
    )
    nb = b.enqueue("kb", "s")
    z, nz = w.bystander()
    assert nb == 2 and b.states()[1]["open"]  # inside the grace it still counts
    w.life(62, b, (b, nb, "waiting"), (z, nz, "waiting"))
    assert not b.states()[1]["open"] and b.states()[1]["reason"] == "unledgered_ticket"
    assert any("has no ledger line" in f for f in w.store.verify(now=w.clock(), grace=60))


def test_a_torn_ticket_from_a_crash_is_dropped(tmp_path):
    w = World(tmp_path)
    tickets = w.store.root / "tickets"
    tickets.mkdir(parents=True)
    os.close(os.open(tickets / "T000001.json", os.O_CREAT | os.O_WRONLY))  # numbered, never filled in
    b = w.lane("b", 102)
    nb = b.enqueue("kb", "s")
    z, nz = w.bystander()
    assert b.states()[1]["open"]
    w.life(32, b, (b, nb, "waiting"), (z, nz, "waiting"))
    assert not b.states()[1]["open"] and b.states()[1]["reason"] == "torn_ticket"
    assert any("empty or unreadable" in f for f in w.store.verify(now=w.clock(), grace=60))


def test_status_shows_queue_holder_ages_attempts_and_the_last_landings(tmp_path):
    w = World(tmp_path)
    a, b, c = w.lane("a", 101), w.lane("b", 102), w.lane("c", 103)
    na = a.enqueue("ka", "fix one")
    a.wait_turn(na)
    w.clock.advance(12)
    a.hold(na, w.committer("ka"))
    nb, nc = b.enqueue("kb", "fix two"), c.enqueue("kc", "fix three")
    b.wait_turn(nb)
    w.clock.advance(5)
    status = landing_status.build_status(c, agent="c")
    assert status["queue_length"] == 2
    assert (
        status["holder"]["agent"] == "b"
        and status["holder"]["held_s"] == 5.0
        and status["holder"]["lease_left_s"] == 895.0
    )
    waiting = [q for q in status["queue"] if q["state"] == "waiting"][0]
    assert waiting["position"] == 1 and waiting["attempt"] == 1 and waiting["age_s"] == 5.0 and waiting["eta_s"] == 24.0
    last = status["recent_landings"][0]
    assert last["agent"] == "a" and last["hold_s"] == 12.0 and last["sha"].startswith("sha")
    text = landing_status.render(status)
    assert "holder: b" in text and "est wait" in text and "commit.py directly" in text


def test_status_is_read_only_and_surfaces_notices_and_bypassers(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    w.alive.discard(101)
    b.reap()
    before = len(w.store.events())
    status = landing_status.build_status(b, agent="a", untagged_since_oldest=3)
    assert len(w.store.events()) == before
    assert status["notices"][0]["ticket"] == na
    b.enqueue("kc", "s")
    text = landing_status.render(landing_status.build_status(b, untagged_since_oldest=3))
    assert "3 commit(s) reached dev while the queue was open without a landing ticket" in text and "slower" in text
    refused = w.lane("r", 103)
    nr = refused.enqueue("kr", "s")
    w.store.append("refused", nr, by="r", now=w.clock(), blocker="local_gate_failed", message="x")
    assert "local_gate_failed" in landing_status.render(landing_status.build_status(b))


def test_asking_for_status_never_reaps(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    a.enqueue("ka", "s")
    w.alive.discard(101)  # a is dead and nobody has noticed yet
    before = len(w.store.events())
    status = landing_status.build_status(b)
    assert len(w.store.events()) == before and status["queue_length"] == 1
