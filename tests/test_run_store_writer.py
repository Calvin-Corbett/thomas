from pathlib import Path

from thomas.marketplace.observability import run_store


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


def test_threaded_writer_rejects_records_after_close(tmp_path: Path) -> None:
    run_store.init_db(tmp_path / "runs.sqlite3")
    run_id = run_store.create_run({"started_at": "2026-02-21T00:02:00+00:00"})
    writer = run_store.ThreadedRunWriter(run_id)
    writer.close()

    try:
        writer.record({"type": "text", "text": "late"})
        raised = False
    except RuntimeError:
        raised = True
    assert raised is True
    payload = run_store.get_run(run_id)
    assert payload["events"] == []


def test_stream_replay_wraps_scalar_payload(tmp_path: Path) -> None:
    run_store.init_db(tmp_path / "runs.sqlite3")
    run_id = run_store.create_run({"started_at": "2026-02-21T00:03:00+00:00"})
    run_store.append_event(run_id, "notice", "plain-text", t_ms=0, seq=0)

    replay = list(run_store.stream_replay(run_id))
    assert len(replay) == 1
    assert replay[0]["type"] == "notice"
    assert replay[0]["payload"] == "plain-text"
