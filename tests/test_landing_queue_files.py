"""Landing queue files: unreadable and half-written files, numbered creation, unwritable heartbeats, concurrent replacement."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
from scripts.crew.brief.landing_store import FileTicketStore

from tests._landing_fakes import World


def _garbage_beat(w, n, age):
    path = w.store.root / "beats" / f"T{n:06d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json")
    stamp = w.clock() - age
    os.utime(path, (stamp, stamp))


def test_an_unreadable_heartbeat_is_alive_only_while_its_file_is_fresh(tmp_path):
    w = World(tmp_path)
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    _garbage_beat(w, nb, age=1)  # a writer is mid-replace right now
    w.clock.advance(5)
    a.beat(na, "waiting")
    assert a.reap() == []
    assert w.store.beats([nb])[nb]["unreadable"] is True


def test_a_garbage_heartbeat_with_a_live_pid_does_not_block_the_line_for_ever(tmp_path):
    w = World(tmp_path)
    evil, good = w.lane("evil", 1), w.lane("good", 2)
    ne = evil.enqueue("ke", "s")
    _garbage_beat(w, ne, age=0)
    ng = good.enqueue("kg", "s")
    t0 = w.clock()
    assert good.wait_turn(ng, max_wait=1800) == "granted"  # was: timed out after 1,802 s with the garbage file alive
    assert w.clock() - t0 < 200
    assert good.states()[ne]["state"] == "abandoned"


def test_a_head_waiter_with_a_valid_beat_that_never_takes_the_slot_is_dropped(tmp_path):
    w = World(tmp_path)
    stuck, good = w.lane("stuck", 1), w.lane("good", 2)
    ns = stuck.enqueue("ks", "s")
    ng = good.enqueue("kg", "s")

    def sleeper(dt):  # noqa: ANN001, ANN202
        w.clock.advance(dt)
        stuck.beat(ns, "waiting")  # alive and beating, but never calls wait_turn, so never takes the slot

    good.sleep = sleeper
    assert good.wait_turn(ng, max_wait=1800) == "granted"
    assert good.states()[ns]["reason"] == "never_took_slot"


def test_a_half_written_ledger_file_is_ignored_and_reported_not_blind_for_ever(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s")
    path = w.store.root / "ledger" / "E000001.json"
    path.write_text("")  # a crash or a full disk left it empty
    w.store._seen.clear()
    a.states()
    assert a.blind  # a file this fresh may still be mid-write
    w.life(62, a, (a, n, "waiting"))
    stamp = w.clock() - 30
    os.utime(path, (stamp, stamp))
    a.reap()
    assert (
        not a.states()[n]["open"] and not a.blind
    )  # not blind any more: the lost taken line makes the ticket unledgered
    assert a.states()[n]["reason"] == "unledgered_ticket"
    assert any("E000001" in f and "empty or unreadable" in f for f in w.store.verify(now=w.clock(), grace=60))


def test_a_numbered_file_always_holds_its_content(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.lane("a", 101).enqueue("ka", "s")
    for folder in ("tickets", "ledger"):
        for path in (w.store.root / folder).glob("*.json"):
            assert path.stat().st_size > 0
    real = os.link

    def crash(src, dst):  # noqa: ANN001, ANN202
        raise OSError("disk full")

    monkeypatch.setattr("scripts.crew.brief.landing_files.os.link", crash)
    with pytest.raises(OSError):  # an OS error is raised, never read as "that number is taken"
        w.store.append("x", 1, by="a", now=0.0)
    monkeypatch.setattr("scripts.crew.brief.landing_files.os.link", real)
    assert not [p for p in (w.store.root / "ledger").iterdir() if p.name.endswith(".tmp")]


def test_a_beat_that_cannot_be_written_is_skipped_not_fatal(tmp_path, monkeypatch):
    w = World(tmp_path)
    n = w.lane("a", 101).enqueue("ka", "s")

    def refuse(src, dst):  # noqa: ANN001, ANN202
        raise PermissionError("sharing violation")

    monkeypatch.setattr("scripts.crew.brief.landing_files.os.replace", refuse)
    monkeypatch.setattr("scripts.crew.brief.landing_files.time.sleep", lambda s: None)
    w.store.beat(n, now=1.0, pid=1)  # must not raise
    assert not list((w.store.root / "beats").glob(".*.tmp"))


def test_a_read_that_fails_once_is_retried(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.lane("a", 101).enqueue("ka", "s")
    w.store._seen.clear()
    real = Path.read_text
    calls = []

    def flaky(self, *args, **kwargs):  # noqa: ANN001, ANN202
        if self.name == "T000001.json" and not calls:
            calls.append(1)
            raise PermissionError("replaced right now")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert w.store.tickets()[1]["agent"] == "a" and calls == [1]


def test_a_heartbeat_file_under_concurrent_replacement_is_never_reported_missing(tmp_path):
    store = FileTicketStore(tmp_path / "q")
    store.beat(1, now=1.0, pid=1)
    stop = threading.Event()
    missing = []

    def writer():
        i = 0
        while not stop.is_set():
            store.beat(1, now=float(i), pid=1)
            i += 1

    def reader():
        while not stop.is_set():
            if 1 not in store.beats():
                missing.append(1)

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(1.5)
    stop.set()
    for t in threads:
        t.join()
    assert missing == []
