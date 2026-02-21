from pathlib import Path

from thomas.observability import run_store


def test_threaded_writer_falls_back_when_worker_is_unavailable(tmp_path: Path) -> None:
    run_store.init_db(tmp_path / "runs.sqlite3")
    run_id = run_store.create_run({"started_at": "2026-02-21T00:00:00+00:00"})
    writer = run_store.ThreadedRunWriter(run_id)
    writer.start()
    writer._exc = RuntimeError("forced failure for fallback test")

    writer.record({"type": "text", "text": "fallback path"})
    writer.close()

    payload = run_store.get_run(run_id)
    assert len(payload["events"]) == 1
    assert payload["events"][0]["event_type"] == "text"
    assert payload["events"][0]["payload"]["text"] == "fallback path"


def test_threaded_writer_close_drains_pending_queue(tmp_path: Path) -> None:
    run_store.init_db(tmp_path / "runs.sqlite3")
    run_id = run_store.create_run({"started_at": "2026-02-21T00:01:00+00:00"})
    writer = run_store.ThreadedRunWriter(run_id)
    writer.start()

    # Stop worker early, then leave queued events for close() to drain.
    writer._q.put(None)
    writer._thr.join(timeout=2.0)
    assert not writer._thr.is_alive()
    writer._q.put((0, 0, "text", '{"type":"text","text":"from-drain"}', "from-drain"))

    writer.close()

    payload = run_store.get_run(run_id)
    assert len(payload["events"]) == 1
    assert payload["events"][0]["payload"]["text"] == "from-drain"
