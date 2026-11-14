"""Verifier follow-ups: prune under a reader, only the first grant counts, the oldest ticket in --status, --wait touches."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.crew.brief import land, land_worker, landing_files
from scripts.crew.brief.landing_queue import Config, Lane
from scripts.crew.brief.landing_store import FileTicketStore

from tests._landing_fakes import World, sp


def fill(w: World, lane: Lane, count: int) -> None:
    for i in range(count):
        lane.withdraw(lane.enqueue(f"k{i}", "s"))


# ---- N1: a reader holding a file open must never crash the prune or leave ghost tickets
def test_a_prune_that_cannot_delete_a_file_a_reader_holds_is_skipped_not_fatal_and_leaves_no_ghosts(
    tmp_path, monkeypatch
):
    w = World(tmp_path, Config(keep_closed=20))
    a = w.lane("a", 101)
    fill(w, a, 30)
    real = Path.unlink

    def held(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if self.name in {"E000003.json", "E000004.json", "T000002.json"}:  # a reader has these open (WinError 32)
            raise PermissionError(32, "being used by another process")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", held)
    fresh = a.enqueue("fresh", "s")  # was: PermissionError escaped enqueue and land.py died with a traceback
    monkeypatch.setattr(Path, "unlink", real)
    states = a.states()
    assert [n for n, s in states.items() if s["open"]] == [fresh]  # no finished ticket reads as open again (no ghosts)
    assert not [e for e in w.store.events() if e.get("reason") == "unledgered_ticket"]
    a.enqueue("more", "s")  # and the next prune finishes the job without complaint
    assert a.audit() == []


# ---- N2: the first grant counts; a holder cannot restart its own lease by writing another
def test_a_repeated_granted_line_never_restarts_the_lease(tmp_path):
    w = World(tmp_path, Config(max_hold=60.0))
    a, b = w.lane("a", 101), w.lane("b", 102)
    na, nb = a.enqueue("ka", "s"), b.enqueue("kb", "s")
    z, nz = w.bystander()
    a.wait_turn(na)
    first = b.states()[na]["granted_at"]
    for _ in range(7):  # the holder appends a fresh grant every 10 s, hoping to keep the slot for ever
        w.life(10, b, (a, na, "holding"), (b, nb, "waiting"), (z, nz, "waiting"))
        w.store.append("granted", na, by="a", now=w.clock(), max_hold=60.0)
    assert b.states()[na]["granted_at"] == first
    assert b.states()[na]["reason"].startswith("lease_expired")  # was: still holding after 4 re-appends over 2400 s


def test_a_granted_line_written_by_a_stranger_does_not_grant_anything(tmp_path):
    w = World(tmp_path)
    a, evil = w.lane("a", 101), w.lane("evil", 102)
    n = a.enqueue("ka", "s")
    w.store.append("granted", n, by="evil", now=w.clock(), max_hold=60.0)
    assert a.states()[n]["state"] == "waiting" and a.states()[n]["ignored"]
    assert any("written by evil" in f for f in evil.audit())


# ---- N4: --status counts commits that bypassed the queue since the OLDEST ticket
def test_status_counts_bypass_commits_since_the_oldest_open_ticket(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (
        ["init", "-q"],
        ["config", "user.email", "t@e.t"],
        ["config", "user.name", "t"],
        ["config", "commit.gpgsign", "false"],
    ):
        sp.run(["git", *cmd], cwd=repo, check=True)
    hour_ago = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3600)) + "+0000"
    old_env = {**os.environ, "GIT_COMMITTER_DATE": hour_ago, "GIT_AUTHOR_DATE": hour_ago}
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "base"], cwd=repo, env=old_env, check=True)
    long_ago = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 50)) + "+0000"
    env = {**os.environ, "GIT_COMMITTER_DATE": long_ago, "GIT_AUTHOR_DATE": long_ago}
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "direct, no ticket"], cwd=repo, env=env, check=True)
    store = FileTicketStore(tmp_path / "queue")
    now = time.time()
    for age in (100, 10):  # tickets 100 s and 10 s old; the direct commit (50 s ago) came while the OLD one waited
        store.take(now=now - age, agent="a", session="", pid=os.getpid(), key=f"k{age}", subject="s", attempt=1)
    lane = Lane(store, agent="a", cfg=Config())
    land.show_status(SimpleNamespace(verify=False, json=True), lane, repo)
    assert (
        json.loads(capsys.readouterr().out)["dev_commits_outside_queue"] == 1
    )  # was: 0, counted from the youngest ticket


# ---- --wait touches the ticket: that is what keeps a submitted ticket alive
def test_every_wait_call_touches_the_ticket(tmp_path):
    w = World(tmp_path)
    a = w.lane("a", 101)
    n = a.enqueue("ka", "s", mode="detached")
    assert w.store.touches() == {}
    code, status, _text, _extra = land_worker.wait_for(a, n, 0.0, lambda text: None)
    assert (code, status) == (5, "waiting")
    assert w.store.touches()[n] == pytest.approx(w.clock(), abs=1.0)


# ---- any OS error other than "that file exists" is an error, never "that number is taken"
def test_a_permission_error_creating_a_numbered_file_is_raised_not_read_as_taken(tmp_path, monkeypatch):
    calls = []

    def refuse(src, dst):  # noqa: ANN001, ANN202
        calls.append(dst)
        raise PermissionError("access denied")

    monkeypatch.setattr(landing_files.os, "link", refuse)
    with pytest.raises(PermissionError):
        landing_files.create_numbered(tmp_path / "ledger", "E", lambda n: b"{}", 1)
    assert len(calls) == 1  # was: spun through 5000 numbers and then reported "no free slot"
    assert not [p for p in (tmp_path / "ledger").iterdir()]  # and no temporary file is left behind


def test_the_prune_itself_skips_a_file_it_cannot_delete(tmp_path, monkeypatch):
    w = World(tmp_path, Config(keep_closed=20))
    a = w.lane("a", 101)
    fill(w, a, 10)
    real = Path.unlink

    def held(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if self.name == "E000003.json":
            raise PermissionError(32, "being used by another process")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", held)
    assert w.store.prune(6, now=w.clock()) >= 1  # the prune finishes; the held file waits for the next one


def test_a_housekeeping_failure_never_stops_a_landing(tmp_path, monkeypatch):
    w = World(tmp_path, Config(keep_closed=20))
    a = w.lane("a", 101)

    def broken(below, *, now):  # noqa: ANN001, ANN202
        raise OSError("the folder is busy")

    monkeypatch.setattr(w.store, "prune", broken)
    fill(w, a, 45)  # past the prune threshold, so every later ticket meets the broken prune
    assert a.enqueue("fresh", "s")  # and the ticket is still taken
