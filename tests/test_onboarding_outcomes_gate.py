from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from thomas.marketplace.observability.onboarding_outcomes import build_onboarding_outcome_report
from thomas.marketplace.observability.onboarding_outcomes_gate import evaluate_onboarding_outcomes_gate
from thomas.marketplace.observability.run_db import connect, ensure_schema


def _seed_event(
    db: Path,
    *,
    run_id: str,
    started_at: str,
    event_type: str,
    payload_json: str,
    t_ms: int = 10,
    seq: int = 1,
) -> None:
    ensure_schema(db)
    con = connect(db)
    try:
        con.execute(
            "INSERT OR REPLACE INTO runs(run_id, started_at, ok, meta_json, last_seq) VALUES (?, ?, ?, ?, ?)",
            (run_id, started_at, 1, "{}", 0),
        )
        con.execute(
            "INSERT INTO events(run_id, t_ms, seq, event_type, payload_json) VALUES (?, ?, ?, ?, ?)",
            (run_id, int(t_ms), int(seq), event_type, payload_json),
        )
        con.commit()
    finally:
        con.close()


def test_onboarding_outcomes_gate_warns_on_low_sample_size() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runs.sqlite3"
        started = datetime.now(UTC).isoformat()
        _seed_event(
            db,
            run_id="r1",
            started_at=started,
            event_type="onboarding.client.wizard.opened",
            payload_json='{"user_id":"u1"}',
        )
        report = build_onboarding_outcome_report(db, since_days=7)

    gate = evaluate_onboarding_outcomes_gate(
        report,
        min_events_for_quality_thresholds=10,
        min_completion_rate=0.9,
        min_recovery_success_rate=0.8,
        max_median_time_to_ready_seconds=480.0,
    )
    assert gate["ok"] is True
    assert gate["warnings"]
    assert "insufficient onboarding telemetry sample" in gate["warnings"][0]


def test_onboarding_outcomes_gate_fails_when_thresholds_missed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runs.sqlite3"
        started = datetime.now(UTC).isoformat()
        for idx in range(5):
            _seed_event(
                db,
                run_id=f"o-{idx}",
                started_at=started,
                event_type="onboarding.client.wizard.opened",
                payload_json='{"user_id":"u1"}',
            )
        _seed_event(
            db,
            run_id="done-1",
            started_at=started,
            event_type="onboarding.client.onboarding.completed",
            payload_json='{"user_id":"u1"}',
        )
        _seed_event(
            db,
            run_id="rf-1",
            started_at=started,
            event_type="onboarding.client.wizard.download_approval_failed",
            payload_json='{"user_id":"u1","payload":{"error":"repair failed"}}',
        )
        report = build_onboarding_outcome_report(db, since_days=7)

    gate = evaluate_onboarding_outcomes_gate(
        report,
        min_events_for_quality_thresholds=3,
        min_completion_rate=0.9,
        min_recovery_success_rate=0.8,
        max_median_time_to_ready_seconds=480.0,
    )
    assert gate["ok"] is False
    errors = " | ".join(gate["errors"])
    assert "completion rate below target" in errors
    assert "recovery success rate below target" in errors


def test_onboarding_outcomes_gate_fails_when_median_time_to_ready_is_too_high() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runs.sqlite3"
        started = datetime.now(UTC).isoformat()
        _seed_event(
            db,
            run_id="r1",
            started_at=started,
            event_type="onboarding.client.wizard.opened",
            payload_json='{"user_id":"u1","onboarding_session_id":"session-1"}',
            t_ms=0,
            seq=1,
        )
        _seed_event(
            db,
            run_id="r1",
            started_at=started,
            event_type="onboarding.client.onboarding.completed",
            payload_json='{"user_id":"u1","onboarding_session_id":"session-1"}',
            t_ms=900_000,
            seq=2,
        )
        report = build_onboarding_outcome_report(db, since_days=7)

    gate = evaluate_onboarding_outcomes_gate(
        report,
        min_events_for_quality_thresholds=1,
        min_completion_rate=0.5,
        min_recovery_success_rate=0.0,
        max_median_time_to_ready_seconds=480.0,
    )
    assert gate["ok"] is False
    errors = " | ".join(gate["errors"])
    assert "median time-to-ready above target" in errors


def test_onboarding_outcomes_gate_warns_when_completion_sample_is_too_small() -> None:
    report = {
        "ok": True,
        "window_days": 7,
        "summary": {
            "events": 25,
            "runs": 1,
            "unique_users": 0,
            "wizard_opened": 1,
            "onboarding_completed": 0,
            "completion_rate": 0.0,
            "recovery_attempts": 0,
            "recovery_succeeded": 0,
            "recovery_success_rate": 0.0,
            "completed_journeys_with_timing": 0,
            "median_time_to_ready_seconds": 0.0,
        },
        "stage_counts": {},
        "event_counts": {},
        "top_failures": [],
        "top_failure_reasons": [],
    }

    gate = evaluate_onboarding_outcomes_gate(
        report,
        min_events_for_quality_thresholds=20,
        min_started_journeys_for_completion_rate=3,
        min_completion_rate=0.9,
        min_recovery_success_rate=0.8,
        max_median_time_to_ready_seconds=480.0,
    )

    assert gate["ok"] is True
    assert gate["errors"] == []
    assert any("insufficient completed onboarding-start sample" in msg for msg in gate["warnings"])
