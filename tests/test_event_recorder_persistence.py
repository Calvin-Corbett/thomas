# tests/test_event_recorder_persistence.py
from __future__ import annotations

import os
from pathlib import Path

from thomas.observability.run_db import ENV_DB_PATH
from thomas.observability.event_recorder import start_run, record_event, end_run
from thomas.observability.run_store_replay import list_events, count_events

def test_event_recorder_writes_and_replays(tmp_path: Path):
    db = tmp_path / "runs.sqlite3"
    os.environ[ENV_DB_PATH] = str(db)

    run_id = start_run(meta={"test": True})
    record_event("prompt", {"text": "hello"})
    record_event("tool.call", {"name": "x", "authorization": "Bearer SECRET"})
    record_event("tool.output", {"result": "ok", "api_key": "sk-SECRET"})
    end_run(ok=True)

    assert count_events(run_id) == 3
    evs = list_events(run_id, start=0, limit=10)
    assert [e.event_type for e in evs] == ["prompt", "tool.call", "tool.output"]
