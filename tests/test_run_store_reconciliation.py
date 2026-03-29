from __future__ import annotations

from thomas.marketplace.observability import run_store


def test_reconcile_orphaned_runs_marks_open_runs_dead(tmp_path) -> None:
    run_store.init_db(tmp_path / "runs.sqlite3")
    run_id = run_store.create_run(
        {
            "run_id": "orphaned-run",
            "started_at": "2026-03-28T14:00:00+00:00",
        }
    )

    reconciled = run_store.reconcile_orphaned_runs(
        started_before="2026-03-28T15:00:00+00:00",
        reason="server startup reconciliation",
        ended_at="2026-03-28T15:00:00+00:00",
    )

    payload = run_store.get_run(run_id)["run"]
    assert reconciled == 1
    assert payload["ended_at"] == "2026-03-28T15:00:00+00:00"
    assert payload["ok"] is False
    assert str(payload["error"] or "").startswith("dead_run:")


def test_reconcile_stale_runs_uses_last_event_activity(tmp_path) -> None:
    run_store.init_db(tmp_path / "runs.sqlite3")
    stale_run_id = run_store.create_run(
        {
            "run_id": "stale-run",
            "started_at": "2026-03-28T14:00:00+00:00",
        }
    )
    fresh_run_id = run_store.create_run(
        {
            "run_id": "fresh-run",
            "started_at": "2026-03-28T14:28:00+00:00",
        }
    )
    run_store.append_event(
        stale_run_id,
        "iteration",
        {"type": "iteration", "iteration": 1},
        t_ms=125000,
        seq=0,
    )
    run_store.append_event(
        fresh_run_id,
        "thinking",
        {"type": "thinking", "text": "still working"},
        t_ms=0,
        seq=0,
    )

    reconciled = run_store.reconcile_stale_runs(
        idle_seconds=300,
        now_iso="2026-03-28T14:30:00+00:00",
        reason="stale run janitor reconciliation",
    )

    stale_payload = run_store.get_run(stale_run_id)["run"]
    fresh_payload = run_store.get_run(fresh_run_id)["run"]
    assert reconciled == 1
    assert stale_payload["ended_at"] == "2026-03-28T14:30:00+00:00"
    assert str(stale_payload["error"] or "").startswith("dead_run:")
    assert fresh_payload["ended_at"] is None
