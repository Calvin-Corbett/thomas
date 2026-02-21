# tests/test_replay_debugger_determinism.py
from __future__ import annotations

import os
from pathlib import Path

from thomas.observability.run_store_replay import list_events
from thomas.observability.run_db import ENV_DB_PATH
from tests._replay_test_db import init_db, seed_run

def test_list_events_is_deterministic_sorted_by_seq_then_id(tmp_path: Path):
    db = tmp_path / "runs.sqlite3"
    init_db(db)
    seed_run(db)
    os.environ[ENV_DB_PATH] = str(db)

    evs = list_events("run_test_1", start=0, limit=10)
    assert [e.seq for e in evs] == [1, 2, 3]
    assert [e.event_type for e in evs] == ["tool.call", "prompt", "tool.output"]
