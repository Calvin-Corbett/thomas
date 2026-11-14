"""Two acknowledged writers on one execution record must both survive, and one update must not read every record.

Replays the forced schedule from the 2026-09-11 runtime lab (both writers read the same record, A writes, then B writes) and the
1,000-record read count. Red on the unlocked runtime (A's claimed_owner is lost; 1,001 reads per update), green once
update_execution holds a per-record lock with a revision check and the summary is updated incrementally.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from thomas.core import task_bot_runtime as rt


def _forced_two_writer_schedule(root):
    eid = rt.create_execution(session_id="fixture", summary="original", repo_root=root)["execution_id"]
    original_get = rt.get_execution
    both_read = threading.Barrier(2, timeout=5)
    a_finished = threading.Event()
    returned: dict[str, dict] = {}

    def synchronized_read(execution_id, repo_root=None):
        row = original_get(execution_id, repo_root)
        name = threading.current_thread().name
        if execution_id == eid and name in {"writer-A", "writer-B"}:
            try:
                both_read.wait()
            except threading.BrokenBarrierError:
                pass
            if name == "writer-B":
                a_finished.wait(5)
        return row

    def writer(name, **fields):
        threading.current_thread().name = name
        try:
            returned[name] = rt.update_execution(eid, repo_root=root, **fields)
        finally:
            if name == "writer-A":
                a_finished.set()

    rt.get_execution = synchronized_read
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(writer, "writer-A", claimed_owner="worker-A")
            b = pool.submit(writer, "writer-B", visibility="foreground")
            a.result(timeout=15)
            b.result(timeout=15)
    finally:
        rt.get_execution = original_get
        both_read.abort()
    return returned, original_get(eid, root)


def test_two_acknowledged_writers_both_survive(tmp_path):
    returned, final = _forced_two_writer_schedule(tmp_path)
    assert returned["writer-A"]["claimed_owner"] == "worker-A"
    assert final["visibility"] == "foreground"
    assert final["claimed_owner"] == "worker-A", "the second writer overwrote the first writer's acknowledged field"


@pytest.mark.parametrize("records", [10, 1000])
def test_one_update_does_not_read_every_record(tmp_path, records):
    when = rt._to_iso(rt._now())
    for index in range(records):
        eid = f"exec-fixture-{index:04d}"
        payload = rt._new_record(
            execution_id=eid,
            task_id="",
            session_id="fixture",
            summary="fixture",
            intent="task",
            scope=[],
            visibility="background",
            parent_execution_id="",
            bot_id="",
            backend_type="provider_native",
            runtime_profile={},
            actor="fixture",
            created_at=when,
        )
        rt._write_json(rt.execution_path(eid, tmp_path), payload)
    target = "exec-fixture-0000"
    rt.update_execution(target, progress_summary="warmup", repo_root=tmp_path)
    reads = {"n": 0}
    original_read = rt._read_json

    def counted(*args, **kwargs):
        reads["n"] += 1
        return original_read(*args, **kwargs)

    rt._read_json = counted
    try:
        rt.update_execution(target, progress_summary="probe", repo_root=tmp_path)
    finally:
        rt._read_json = original_read
    assert reads["n"] <= 3, f"one update read {reads['n']} files for {records} records"
    cached = rt.read_summary(tmp_path, refresh=False)
    assert cached["execution_count"] == records
    row = next(r for r in cached["executions"] if r["execution_id"] == target)
    assert row["progress_summary"] == "probe"
    assert rt.read_summary(tmp_path, refresh=True)["execution_count"] == records
