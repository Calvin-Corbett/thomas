"""Damage is local to a run; retention and replay stay bounded."""

from __future__ import annotations

import os
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from thomas.core import run_journal as journal
from thomas.core import run_journal_retention as retention
from thomas.core import run_journal_summary as summaries
from thomas.core.journal_lent import JournalDamaged

DAY = 86400.0
LIMIT = 4 * 1024 * 1024
WHEN = "2026-11-04T12:00:00+00:00"


def aged(path, seconds, now):
    os.utime(path, (now - seconds, now - seconds))


def test_damage_stops_only_its_run_and_next_open_starts_fresh(tmp_path):
    reports = []
    runs = journal.RunJournals(on_damage=lambda *args: reports.append(args))
    bad = runs.open(tmp_path, "bad")
    bad.start(1, {})
    bad.path.write_bytes(b"broken\n")
    aged(bad.path, 40 * DAY, time.time())
    with pytest.raises(JournalDamaged, match="kept as"):
        runs.open(tmp_path, "bad")
    backups = list(tmp_path.glob("bad.journal.damaged-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"broken\n"
    assert time.time() - backups[0].stat().st_mtime < 10
    assert not bad.summary_path.exists() and not bad.path.exists()
    assert reports[0][0] == "bad" and "kept as" in reports[0][1]
    assert runs.open(tmp_path, "good").run_step(1, {}, lambda _: 9) == 9
    assert runs.open(tmp_path, "bad").state.latest == {}


@pytest.mark.parametrize("error", [OSError, RuntimeError, ValueError, TypeError])
def test_damage_report_failure_does_not_hide_damage(tmp_path, error):
    def report(*_):
        raise error("report failed")

    runs = journal.RunJournals(on_damage=report)
    runs.open(tmp_path, "bad").path.write_bytes(b"broken\n")
    with pytest.raises(JournalDamaged):
        runs.open(tmp_path, "bad")
    assert runs.open(tmp_path, "good").state.latest == {}


def test_quarantine_failure_keeps_original_and_reports_damage(tmp_path, monkeypatch):
    reports = []
    runs = journal.RunJournals(on_damage=lambda *args: reports.append(args))
    bad = runs.open(tmp_path, "bad")
    bad.path.write_bytes(b"broken\n")

    def fail(*_):
        raise PermissionError("locked")

    monkeypatch.setattr(journal.os, "replace", fail)
    with pytest.raises(JournalDamaged, match="could not be set aside"):
        runs.open(tmp_path, "bad")
    assert bad.path.read_bytes() == b"broken\n" and reports


@pytest.mark.parametrize("operation", ["start", "finish", "close", "cached", "run_step", "unknown"])
def test_failed_quarantine_invalidates_existing_owner_before_work_or_writes(tmp_path, monkeypatch, operation):
    runs = journal.RunJournals()
    owner = runs.open(tmp_path, "bad")
    owner.run_step(1, {}, lambda _: "saved result")
    owner.start(2, {"saved": True})
    with owner.path.open("ab") as handle:
        handle.write(b"broken\n")
    damaged = owner.path.read_bytes()
    summary = owner.summary_path.read_bytes()
    unrelated = runs.open(tmp_path, "good")

    def fail(*_):
        raise PermissionError("locked")

    with monkeypatch.context() as patch:
        patch.setattr(journal.os, "replace", fail)
        with pytest.raises(JournalDamaged, match="could not be set aside"):
            runs.open(tmp_path, "bad")
    # The permission failure is gone, but this owner must remain invalidated.
    worked = []
    operations = {
        "start": lambda: owner.start(3, {}),
        "finish": lambda: owner.finish(2, "stale"),
        "close": lambda: owner.close("ended"),
        "cached": lambda: owner.run_step(1, {}, lambda _: worked.append(True)),
        "run_step": lambda: owner.run_step(2, {}, lambda _: worked.append(True)),
        "unknown": lambda: owner.mark_unknown(2),
    }
    with pytest.raises(OSError, match="reopen"):
        operations[operation]()
    assert not worked
    assert owner.path.read_bytes() == damaged
    assert owner.summary_path.read_bytes() == summary
    assert unrelated.run_step(1, {}, lambda _: "unaffected") == "unaffected"
    with pytest.raises(JournalDamaged, match="kept as"):
        runs.open(tmp_path, "bad")
    assert next(tmp_path.glob("bad.journal.damaged-*")).read_bytes() == damaged
    assert runs.open(tmp_path, "bad").state.latest == {}
    assert runs.open(tmp_path, "good").state.finished[1].result == "unaffected"


def test_a_listing_reads_only_the_summaries(tmp_path, monkeypatch):
    runs = journal.RunJournals()
    item = journal.Journal(tmp_path, "listed", meta={"kind": "check"})
    item.start(1, {})

    def no_replay(*_):
        pytest.fail("listing replayed a journal")

    monkeypatch.setattr(journal, "replay", no_replay)
    assert runs.summaries(tmp_path)[0]["run_id"] == "listed"
    assert runs.summary(tmp_path, "listed")["steps"] == {"1": "started"}
    assert runs.folders() == [tmp_path]
    assert str(tmp_path) in runs.sweep()
    with pytest.raises(ValueError):
        runs.summary(tmp_path, "../escape")


def test_a_huge_journal_is_read_one_line_at_a_time(tmp_path):
    path = tmp_path / "huge.journal"
    pad = "x" * 240
    with path.open("wb") as handle:
        for number in range(150_000):
            state = journal.STARTED if number % 2 == 0 else journal.FINISHED
            handle.write(
                journal.Record("huge", number % 4 + 1, state, {"pad": pad, "n": number}, None, WHEN, "").line()
            )
    assert path.stat().st_size > 40 * 1024 * 1024
    tracemalloc.start()
    try:
        result = journal.replay(path, "huge")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert sorted(result.latest) == [1, 2, 3, 4]
    assert result.latest[4].input["n"] == 149_999
    assert peak < LIMIT, f"replay peak: {peak} bytes"


def test_a_line_longer_than_a_record_is_damage_and_never_read_whole(tmp_path):
    path = tmp_path / "long.journal"
    path.write_bytes(b"x" * (20 * 1024 * 1024) + b"\n")
    tracemalloc.start()
    try:
        with pytest.raises(JournalDamaged, match="longer than a record"):
            journal.replay(path, "long")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < LIMIT, f"oversized line peak: {peak} bytes"


@pytest.mark.parametrize(
    "closed,days,expected",
    [
        ("ended", 7, ""),
        ("ended", 7.001, "removed"),
        ("", 30, ""),
        ("", 30.001, "abandoned"),
    ],
)
def test_retention_boundaries(tmp_path, closed, days, expected):
    item = journal.Journal(tmp_path, "run")
    item.start(1, {})
    if closed:
        item.close(closed)
    now = time.time()
    aged(item.summary_path, days * DAY, now)
    done = retention.sweep(tmp_path, now=now)
    assert [key for key, values in done.items() if values] == ([expected] if expected else [])
    if expected == "removed":
        assert not item.path.exists() and not item.summary_path.exists()
    elif expected == "abandoned":
        assert summaries.read_summary(item.summary_path)["closed"] == "abandoned"
        assert retention.sweep(tmp_path, now=now + 6 * DAY)["removed"] == []
        assert retention.sweep(tmp_path, now=now + 8 * DAY)["removed"] == ["run"]
    else:
        assert item.path.exists()
        assert summaries.read_summary(item.summary_path)["closed"] == closed


def test_damage_backup_expiry_and_unrelated_files(tmp_path):
    now = time.time()
    names = ["old.journal.damaged-1", "new.journal.damaged-2", "notes.damaged-1", "x.journal.damaged-no"]
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"x")
        aged(path, (7 if name.startswith("new") else 8) * DAY, now)
    done = retention.sweep(tmp_path, now=now)
    assert done["damaged_removed"] == [names[0]]
    assert all((tmp_path / name).exists() for name in names[1:])


def test_large_closed_compacts_but_active_is_untouched(tmp_path):
    for run_id in ("closed", "active"):
        path = tmp_path / f"{run_id}.journal"
        with path.open("wb") as handle:
            for number in range(3000):
                handle.write(journal.Record(run_id, 2, journal.FINISHED, {"try": number}, number, WHEN, WHEN).line())
        item = journal.Journal(tmp_path, run_id)
        if run_id == "closed":
            item.close("ended")
        assert path.stat().st_size > retention.COMPACT_BYTES
    before = journal.replay(tmp_path / "closed.journal", "closed").latest
    active = (tmp_path / "active.journal").read_bytes()
    assert retention.sweep(tmp_path)["compacted"] == ["closed"]
    assert journal.replay(tmp_path / "closed.journal", "closed").latest == before
    assert (tmp_path / "closed.journal").read_bytes().count(b"\n") == 1
    assert (tmp_path / "active.journal").read_bytes() == active


def test_compaction_preserves_all_latest_states_and_discards_torn_tail(tmp_path):
    item = journal.Journal(tmp_path, "mixed")
    item.start(3, {})
    item.start(1, {"old": True})
    item.finish(1, "done")
    item.start(2, {})
    item.mark_unknown(2)
    before = journal.replay(item.path, "mixed").latest
    with item.path.open("ab") as handle:
        handle.write(b'{"torn":')
    size = retention.compact(item.path, "mixed")
    assert size == item.path.stat().st_size
    assert list(journal.replay(item.path, "mixed").latest) == [1, 2, 3]
    assert journal.replay(item.path, "mixed").latest == before
    assert not journal.replay(item.path, "mixed").torn


@pytest.mark.parametrize("operation", ["finish", "start", "close", "run_step"])
def test_expired_owner_cannot_recreate_a_journal_without_its_history(tmp_path, operation):
    owner = journal.RunJournals().open(tmp_path, "expired")
    owner.start(1, {"saved": True})
    owner.start(2, {})
    owner.close("abandoned")
    aged(owner.summary_path, 8 * DAY, time.time())
    assert retention.sweep(tmp_path)["removed"] == ["expired"]
    worked = []
    operations = {
        "finish": lambda: owner.finish(2, "result"),
        "start": lambda: owner.start(3, {}),
        "close": lambda: owner.close("done"),
        "run_step": lambda: owner.run_step(2, {}, lambda _: worked.append(True)),
    }
    with pytest.raises(OSError, match="reopen"):
        operations[operation]()
    assert not worked
    assert not owner.path.exists()
    assert not owner.summary_path.exists()
    fresh = journal.RunJournals().open(tmp_path, "expired")
    assert fresh.state.latest == {}
    assert fresh.run_step(1, {}, lambda _: "fresh") == "fresh"


@pytest.mark.parametrize("removal", ["expiry", "quarantine"])
@pytest.mark.parametrize("operation", ["start", "finish", "close", "cached", "run_step", "unknown"])
def test_removed_owner_cannot_use_a_new_journal_with_the_same_run_id(tmp_path, operation, removal):
    owner = journal.Journal(tmp_path, "reused")
    owner.run_step(1, {}, lambda _: "old result")
    owner.start(2, {"old": True})
    owner.close("abandoned")
    now = time.time()
    aged(owner.summary_path, 8 * DAY, now)
    if removal == "expiry":
        assert retention.sweep(tmp_path, now=now)["removed"] == ["reused"]
    else:
        owner.path.write_bytes(b"broken\n")
        with pytest.raises(journal.JournalDamaged):
            journal.RunJournals().open(tmp_path, "reused")
    fresh = journal.Journal(tmp_path, "reused")
    fresh.run_step(1, {}, lambda _: "new result")
    before = fresh.path.read_bytes()

    def no_work(_):
        pytest.fail("a stale owner executed work on a different journal generation")

    operations = {
        "start": lambda: owner.start(3, {}),
        "finish": lambda: owner.finish(2, "stale"),
        "close": lambda: owner.close("ended"),
        "cached": lambda: owner.run_step(1, {}, no_work),
        "run_step": lambda: owner.run_step(2, {}, no_work),
        "unknown": lambda: owner.mark_unknown(2),
    }
    with pytest.raises(OSError, match="history was removed"):
        operations[operation]()
    assert fresh.path.read_bytes() == before
    assert journal.Journal(tmp_path, "reused").state.finished[1].result == "new result"


def test_waiting_compaction_cannot_recreate_an_expired_journal(tmp_path, monkeypatch):
    owner = journal.RunJournals().open(tmp_path, "expired")
    owner.run_step(1, {}, lambda _: "saved result")
    owner.start(2, {"saved input": True})
    owner.close("abandoned")
    aged(owner.summary_path, 8 * DAY, time.time())
    lock = journal._run_lock(owner.path)
    attempting = threading.Event()
    real_lock = journal._run_lock

    def observed_lock(path):
        result = real_lock(path)
        attempting.set()
        return result

    monkeypatch.setattr(journal, "_run_lock", observed_lock)
    with ThreadPoolExecutor(1) as pool:
        with lock:
            pending = pool.submit(retention.compact, owner.path, owner.run_id)
            assert attempting.wait(5), "compaction did not attempt the held run lock"
            assert not pending.done(), "compaction bypassed the held run lock"
            assert retention.sweep(tmp_path)["removed"] == ["expired"]
            assert not owner.path.exists() and not owner.summary_path.exists()
            assert not pending.done(), "compaction must wait until expiry releases the lock"
        with pytest.raises(FileNotFoundError):
            pending.result(timeout=5)
    assert not owner.path.exists() and not owner.summary_path.exists()
    assert not list(tmp_path.iterdir()), "compaction left replacement files behind"
    worked = []
    with pytest.raises(OSError, match="reopen"):
        owner.run_step(2, {}, lambda _: worked.append(True))
    assert not worked
    assert not owner.path.exists() and not owner.summary_path.exists()


@pytest.mark.parametrize("reopen", [False, True], ids=["existing-owner", "resumed-owner"])
@pytest.mark.parametrize("maintenance", ["compact", "sweep"])
def test_compaction_cannot_discard_an_acknowledged_resumed_write(tmp_path, monkeypatch, reopen, maintenance):
    owner = journal.RunJournals().open(tmp_path, "run")
    owner.start(1, {"saved": True})
    aged(owner.summary_path, 31 * DAY, time.time())
    assert retention.sweep(tmp_path)["abandoned"] == ["run"]
    replayed = threading.Event()
    release = threading.Event()
    attempting = threading.Event()
    acknowledged = threading.Event()
    real_replay = journal.replay

    def pause_after_replay(path, run_id):
        state = real_replay(path, run_id)
        if threading.current_thread().name.startswith("maintenance"):
            replayed.set()
            assert release.wait(5), "compaction was not released"
        return state

    def maintain():
        if maintenance == "sweep":
            assert retention.sweep(tmp_path, compact_bytes=0)["compacted"] == ["run"]
        else:
            retention.compact(owner.path, "run")

    def resume():
        attempting.set()
        item = journal.RunJournals().open(tmp_path, "run") if reopen else owner
        item.finish(1, {"persisted": True})
        acknowledged.set()

    monkeypatch.setattr(journal, "replay", pause_after_replay)
    with ThreadPoolExecutor(1, thread_name_prefix="maintenance") as maintenance_pool:
        with ThreadPoolExecutor(1, thread_name_prefix="owner") as owner_pool:
            compacting = maintenance_pool.submit(maintain)
            try:
                assert replayed.wait(5), "compaction never reached replay"
                other = journal.RunJournals().open(tmp_path, "unrelated")
                other.start(1, {})
                other.finish(1, "not blocked")
                writing = owner_pool.submit(resume)
                assert attempting.wait(5), "owner did not attempt its write"
                assert not acknowledged.wait(0.3), "write bypassed maintenance exclusion"
            finally:
                release.set()
            compacting.result(timeout=5)
            writing.result(timeout=5)
    assert acknowledged.is_set()
    restored = journal.RunJournals().open(tmp_path, "run")
    assert restored.state.latest[1].result == {"persisted": True}
    assert restored.run_step(1, None, lambda _: pytest.fail("saved step repeated")) == {"persisted": True}


@pytest.mark.parametrize("same_thread", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_retention_preserves_admitted_resumed_work(tmp_path, same_thread, fails):
    now = time.time()
    owner = journal.Journal(tmp_path, "resumed")
    owner.run_step(1, {}, lambda _: "prior result")
    owner.start(2, {"saved": True})
    owner.close("abandoned")
    aged(owner.summary_path, 8 * DAY, now)
    resumed = journal.RunJournals().open(tmp_path, "resumed")
    assert now - resumed.summary_path.stat().st_mtime > 7 * DAY
    unrelated = journal.Journal(tmp_path, "unrelated")
    unrelated.run_step(1, {}, lambda _: "old")
    unrelated.close("ended")
    aged(unrelated.summary_path, 8 * DAY, now)
    admitted = threading.Event()
    release = threading.Event()

    def sweep():
        done = retention.sweep(tmp_path, now=now)
        assert done["removed"] == ["unrelated"]
        assert resumed.path.exists() and resumed.summary_path.exists()

    def work(value):
        assert value == {"saved": True}
        admitted.set()
        if same_thread:
            sweep()
        else:
            assert release.wait(5), "resumed work was not released"
        if fails:
            raise ValueError("work failed")
        return "new result"

    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(resumed.run_step, 2, {"wrong": True}, work)
        try:
            assert admitted.wait(5), "resumed work was not admitted"
            if not same_thread:
                sweep()
        finally:
            release.set()
        if fails:
            with pytest.raises(ValueError, match="work failed"):
                running.result(timeout=5)
        else:
            assert running.result(timeout=5) == "new result"
    restored = journal.RunJournals().open(tmp_path, "resumed")
    assert restored.run_step(1, None, lambda _: pytest.fail("saved step repeated")) == "prior result"
    if fails:
        assert restored.state.latest[2].state == journal.STARTED
    else:
        assert restored.run_step(2, None, lambda _: pytest.fail("new step repeated")) == "new result"
    aged(restored.summary_path, 8 * DAY, now)
    assert retention.sweep(tmp_path, now=now)["removed"] == ["resumed"], "execution pin leaked"


def test_failed_compaction_preserves_original_and_cleans_temporary(tmp_path, monkeypatch):
    item = journal.Journal(tmp_path, "run")
    item.start(1, {})
    original = item.path.read_bytes()

    def fail(*_):
        raise OSError("locked")

    monkeypatch.setattr(summaries, "replace_with_retry", fail)
    with pytest.raises(OSError):
        retention.compact(item.path, "run")
    assert item.path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run.journal", "run.summary.json"]


def test_one_unsweepable_run_does_not_stop_others(tmp_path, monkeypatch):
    for run_id in ("locked", "removed"):
        item = journal.Journal(tmp_path, run_id)
        item.close("ended")
        aged(item.summary_path, 8 * DAY, time.time())
    unlink = Path.unlink

    def sometimes_locked(path, *args, **kwargs):
        if path.name == "locked.journal":
            raise PermissionError("locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", sometimes_locked)
    done = retention.sweep(tmp_path)
    assert done["removed"] == ["removed"]
    assert (tmp_path / "locked.summary.json").exists()


def test_abandoned_run_gets_a_fresh_week_before_removal(tmp_path):
    item = journal.Journal(tmp_path, "stale")
    item.start(1, "keep input")
    os.utime(item.summary_path, (1, 1))
    assert retention.sweep(tmp_path)["abandoned"] == ["stale"]
    marked = item.summary_path.stat().st_mtime
    assert summaries.read_summary(item.summary_path)["closed"] == "abandoned"
    assert retention.sweep(tmp_path, now=marked + 7 * DAY)["removed"] == []
    assert retention.sweep(tmp_path, now=marked + 7 * DAY + 1)["removed"] == ["stale"]
    assert not item.path.exists() and not item.summary_path.exists()


def test_facade_tracks_folders_from_reads_and_sweeps_each(tmp_path):
    folder = tmp_path / "from-summary"
    other = tmp_path / "from-listing"
    for place in (folder, other):
        item = journal.Journal(place, "old")
        item.start(1)
        item.close("ended")
        os.utime(item.summary_path, (1, 1))
    facade = journal.RunJournals()
    assert facade.summary(folder, "old")["closed"] == "ended"
    assert facade.summaries(other)[0]["run_id"] == "old"
    assert {path: done["removed"] for path, done in facade.sweep().items()} == {
        str(folder): ["old"],
        str(other): ["old"],
    }


def test_torn_tail_resumes_instead_of_quarantining(tmp_path):
    item = journal.Journal(tmp_path, "torn")
    item.start(1, {"saved": True})
    with item.path.open("ab") as handle:
        handle.write(b'{"unfinished":')
    facade = journal.RunJournals()
    reopened = facade.open(tmp_path, "torn")
    assert reopened.run_step(1, {}, lambda value: value) == {"saved": True}
    assert not list(tmp_path.glob("*.damaged-*"))


def test_compaction_damage_preserves_original_and_does_not_block_others(tmp_path):
    broken = journal.Journal(tmp_path, "broken")
    broken.close("ended")
    broken.path.write_bytes(b"invalid\n")
    healthy = journal.Journal(tmp_path, "healthy")
    healthy.start(1)
    healthy.finish(1, "saved")
    healthy.close("ended")
    done = retention.sweep(tmp_path, compact_bytes=0)
    assert done["compacted"] == ["healthy"]
    assert broken.path.read_bytes() == b"invalid\n"
    assert not list(tmp_path.glob("*.compact-*"))
    assert journal.replay(healthy.path, "healthy").latest[1].result == "saved"


@pytest.mark.parametrize("failure", ["timestamp", "summary"])
def test_quarantine_cleanup_failure_restores_original(tmp_path, monkeypatch, failure):
    item = journal.Journal(tmp_path, "damaged")
    item.start(1)
    item.close("ended")
    item.path.write_bytes(b"bad\n")
    unlink = Path.unlink

    def locked_summary(path, *args, **kwargs):
        if path == item.summary_path:
            raise PermissionError("locked summary")
        return unlink(path, *args, **kwargs)

    if failure == "timestamp":
        monkeypatch.setattr(os, "utime", lambda *args: (_ for _ in ()).throw(OSError("clock")))
    else:
        monkeypatch.setattr(Path, "unlink", locked_summary)
    with pytest.raises(JournalDamaged):
        journal.RunJournals().open(tmp_path, "damaged")
    assert item.path.read_bytes() == b"bad\n"
    assert item.summary_path.exists()
    assert not list(tmp_path.glob("*.damaged-*"))


def test_expiry_waits_for_quarantine_to_refresh_backup_age(tmp_path, monkeypatch):
    now = time.time()
    item = journal.Journal(tmp_path, "damaged")
    item.start(1)
    item.path.write_bytes(b"damaged bytes\n")
    aged(item.path, 9 * DAY, now)
    renamed = threading.Event()
    release = threading.Event()
    sweep_progress = threading.Event()
    real_utime = os.utime
    real_lock = journal._run_lock

    def pause_timestamp(path, *args, **kwargs):
        if journal.DAMAGED_MARK in Path(path).name:
            renamed.set()
            assert release.wait(5), "quarantine was not released"
        return real_utime(path, *args, **kwargs)

    def observed_lock(path):
        lock = real_lock(path)
        if renamed.is_set():
            sweep_progress.set()
        return lock

    def quarantine():
        with pytest.raises(JournalDamaged, match="kept as"):
            journal.RunJournals().open(tmp_path, "damaged")

    def sweep():
        try:
            return retention.sweep(tmp_path, now=now)
        finally:
            sweep_progress.set()

    monkeypatch.setattr(os, "utime", pause_timestamp)
    monkeypatch.setattr(journal, "_run_lock", observed_lock)
    with ThreadPoolExecutor(2) as pool:
        opening = pool.submit(quarantine)
        try:
            assert renamed.wait(5), "quarantine did not rename the journal"
            sweeping = pool.submit(sweep)
            assert sweep_progress.wait(5), "sweep did not reach quarantine"
            assert not sweeping.done(), "sweep bypassed quarantine's run lock"
        finally:
            release.set()
        opening.result(timeout=5)
        assert sweeping.result(timeout=5)["damaged_removed"] == []
    backups = list(tmp_path.glob("*.damaged-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"damaged bytes\n"
    assert backups[0].stat().st_mtime >= now
    assert not item.path.exists() and not item.summary_path.exists()
    assert retention.sweep(tmp_path, now=now + 8 * DAY)["damaged_removed"] == [backups[0].name]


def test_compaction_syncs_replacement_before_returning(tmp_path, monkeypatch):
    owner = journal.Journal(tmp_path, "durable")
    owner.run_step(1, {}, lambda _: "saved")
    owner.start(2, {"resume": True})
    events = []
    real_sync = os.fsync
    real_replace = summaries.replace_with_retry

    def sync_file(descriptor):
        real_sync(descriptor)
        events.append("file")

    def replace(source, target):
        assert events == ["file"]
        real_replace(source, target)
        events.append("replace")

    def sync_directory(folder):
        assert folder == tmp_path
        assert events == ["file", "replace"]
        assert journal.replay(owner.path, "durable").finished[1].result == "saved"
        events.append("directory")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", sync_file)
        patch.setattr(summaries, "replace_with_retry", replace)
        patch.setattr(journal, "_sync_directory", sync_directory)
        retention.compact(owner.path, "durable")
    assert events == ["file", "replace", "directory"]
    assert owner.run_step(2, None, lambda value: value) == {"resume": True}
    assert journal.Journal(tmp_path, "durable").state.finished[1].result == "saved"


def test_failed_compaction_directory_sync_requires_owner_to_reopen(tmp_path, monkeypatch):
    owner = journal.Journal(tmp_path, "uncertain")
    owner.run_step(1, {}, lambda _: "saved")
    owner.start(2, {"resume": True})

    def fail_sync(_):
        raise OSError("directory sync failed")

    with monkeypatch.context() as patch:
        patch.setattr(journal, "_sync_directory", fail_sync)
        with pytest.raises(OSError, match="directory sync failed"):
            retention.compact(owner.path, "uncertain")
    with pytest.raises(OSError, match="reopen"):
        owner.run_step(2, None, lambda _: pytest.fail("uncertain owner executed work"))
    assert not list(tmp_path.glob("*.compact-*"))
    resumed = journal.Journal(tmp_path, "uncertain")
    assert resumed.run_step(1, None, lambda _: pytest.fail("saved step repeated")) == "saved"
    assert resumed.run_step(2, None, lambda value: value) == {"resume": True}


def test_deeply_nested_damage_is_quarantined_and_reported(tmp_path):
    reports = []
    runs = journal.RunJournals(on_damage=lambda *args: reports.append(args))
    item = runs.open(tmp_path, "nested")
    item.start(1)
    damaged = b"[" * 10000 + b"0" + b"]" * 10000 + b"\n"
    item.path.write_bytes(damaged)
    with pytest.raises(JournalDamaged, match="RecursionError"):
        runs.open(tmp_path, "nested")
    assert len(reports) == 1 and reports[0][0] == "nested"
    assert next(tmp_path.glob("nested.journal.damaged-*")).read_bytes() == damaged
    assert runs.open(tmp_path, "healthy").run_step(1, {}, lambda _: "saved") == "saved"
    assert runs.open(tmp_path, "nested").state.latest == {}


@pytest.mark.parametrize("damaged_file", ["journal", "summary"])
def test_nested_damage_does_not_stop_other_runs_retention(tmp_path, damaged_file):
    broken = journal.Journal(tmp_path, "a-broken")
    broken.close("ended")
    damaged_path = broken.path if damaged_file == "journal" else broken.summary_path
    damaged = b"[" * 10000 + b"0" + b"]" * 10000 + b"\n"
    damaged_path.write_bytes(damaged)
    healthy = journal.Journal(tmp_path, "z-healthy")
    healthy.run_step(1, {}, lambda _: "saved")
    healthy.close("ended")
    assert retention.sweep(tmp_path, compact_bytes=0)["compacted"] == ["z-healthy"]
    assert damaged_path.read_bytes() == damaged
    assert journal.replay(healthy.path, "z-healthy").finished[1].result == "saved"
    if damaged_file == "summary":
        assert summaries.read_summary(damaged_path) is None
        assert journal.RunJournals().summaries(tmp_path) == [summaries.read_summary(healthy.summary_path)]


def test_retention_defaults_match_the_policy():
    assert "RunJournals" in journal.__all__
    assert retention.KEEP_CLOSED_S == 7 * DAY
    assert retention.ABANDON_AFTER_S == 30 * DAY
    assert retention.COMPACT_BYTES == 256 * 1024


def test_missing_folder_and_mismatched_summary_are_ignored(tmp_path):
    assert not any(retention.sweep(tmp_path / "absent").values())
    item = journal.Journal(tmp_path, "safe")
    item.start(1)
    item.close("ended")
    item.summary_path.rename(tmp_path / "wrong.summary.json")
    assert not any(retention.sweep(tmp_path, now=time.time() + 9 * DAY).values())
    assert item.path.exists()
