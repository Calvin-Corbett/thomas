"""The ambient capture run belongs to one run store and keeps run-relative times.

Proves thomas.core.capture_context and thomas.server.routes.mission_control_routes.

Two things you would have seen in Mission Control:

* A process remembers one ambient run id. When the run store was pointed at a
  different database, model calls with no run kept writing to the old id, and the
  new database invented a bare run row for it: a "Chat Session" with no session,
  running forever.
* The ambient run's events stored the clock's epoch milliseconds where the run
  store stores the offset from the run's start, so its last activity read as the
  year 2083.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core import capture_context
from thomas.marketplace.observability import run_store


@pytest.fixture(autouse=True)
def _own_capture_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})
    monkeypatch.setattr(capture_context, "_run_t0_ms", {})
    monkeypatch.setattr(run_store, "_DB_PATH", run_store._DB_PATH)


def test_a_second_run_store_gets_its_own_ambient_run(tmp_path: Path) -> None:
    run_store.init_db(tmp_path / "a.sqlite3")
    first = capture_context.ambient_run_id()
    assert capture_context.ambient_run_id() == first

    run_store.init_db(tmp_path / "b.sqlite3")
    second = capture_context.ambient_run_id()
    assert second and second != first

    capture_context.append_capture_event(second, {"type": "model/response", "text": "hi"})
    runs = run_store.list_runs(limit=10, offset=0, filters={})
    assert [r["run_id"] for r in runs] == [second]
    assert runs[0]["mode"] == "ambient-capture"


def test_capture_events_store_the_offset_from_the_run_start(tmp_path: Path) -> None:
    run_store.init_db(tmp_path / "c.sqlite3")
    run_id = capture_context.ambient_run_id()
    capture_context.append_capture_event(run_id, {"type": "model/response", "text": "hi"})
    events = run_store.get_run(run_id)["events"]
    assert events
    assert all(0 <= int(e["t_ms"]) < 60_000 for e in events)
