# tests/test_replay_debugger_redaction.py
from __future__ import annotations

import os
from pathlib import Path

from thomas.observability.redaction import redact_obj
from thomas.observability.run_store_replay import list_events
from thomas.observability.run_db import ENV_DB_PATH
from tests._replay_test_db import init_db, seed_run

def test_redaction_scrubs_known_keys_and_patterns(tmp_path: Path):
    db = tmp_path / "runs.sqlite3"
    init_db(db)
    seed_run(db)
    os.environ[ENV_DB_PATH] = str(db)

    evs = list_events("run_test_1", start=0, limit=10)
    assert len(evs) == 3

    red = [redact_obj(e.payload) for e in evs]
    blob = str(red)
    assert "Bearer abcdef" not in blob
    assert "sk-THIS_SHOULD_NOT_LEAK" not in blob
