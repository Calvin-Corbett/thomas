
import sqlite3
from pathlib import Path

from thomas.observability import run_store

def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

def test_retention_deletes_oldest_count(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)

    monkeypatch.setattr(run_store, "MAX_RUNS", 3)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 10**9)

    created = []
    for i in range(5):
        rid = run_store.create_run(
            {
                "session_id": "s1",
                "profile": "p",
                "model_id": "m",
                "mode": "chat",
                "started_at": f"2026-02-10T00:0{i}:00+00:00",
                "thomas_version": "test",
            }
        )
        run_store.append_event(rid, "text", {"type": "text", "text": f"hello {i}"}, t_ms=0, seq=0)
        run_store.finalize_run(rid, ok=True, error=None, iterations=i, tool_calls=0, usage={"tokens": i})
        created.append(rid)

    runs = run_store.list_runs(limit=100, offset=0, filters={})
    remaining = [r["run_id"] for r in runs]
    assert len(remaining) == 3
    assert set(remaining) == set(created[-3:])

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON;")
    run_count = _count(conn, "runs")
    ev_count = _count(conn, "events")
    conn.close()

    assert run_count == 3
    assert ev_count == 3

def test_retention_size_deletes_some(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)

    monkeypatch.setattr(run_store, "MAX_RUNS", 10**9)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 1500)

    big = "X" * 5000
    for i in range(6):
        rid = run_store.create_run({"started_at": f"2026-02-10T00:0{i}:00+00:00"})
        run_store.append_event(rid, "text", {"type": "text", "text": big, "i": i}, t_ms=0, seq=0)
        run_store.finalize_run(rid, ok=True, error=None, iterations=0, tool_calls=0, usage=None)

    runs = run_store.list_runs(limit=100, offset=0, filters={})
    assert len(runs) < 6
