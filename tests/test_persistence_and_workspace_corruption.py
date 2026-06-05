from __future__ import annotations

import json

from thomas.core.persistence import PersistenceEngine


def test_persistence_save_is_atomic_and_leaves_no_tmp_file(tmp_path):
    state_file = tmp_path / "thomas_state.json"
    engine = PersistenceEngine(state_file=state_file, report_dir=tmp_path, auto_save=False)
    engine.record_turn("chat", "hello", "world")

    assert engine.save() is True
    assert state_file.exists()
    assert not state_file.with_suffix(state_file.suffix + ".tmp").exists()

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert isinstance(payload.get("turn_history"), list)
    assert len(payload["turn_history"]) == 1
