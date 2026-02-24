from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report
from thomas.observability.run_db import connect, ensure_schema


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


def test_build_onboarding_outcome_report_counts_stages_and_failures() -> None:
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
        _seed_event(
            db,
            run_id="r1",
            started_at=started,
            event_type="onboarding.client.connection.failed",
            payload_json='{"user_id":"u1"}',
        )
        _seed_event(
            db,
            run_id="r2",
            started_at=started,
            event_type="onboarding.client.onboarding.completed",
            payload_json='{"user_id":"u2"}',
        )

        report = build_onboarding_outcome_report(db, since_days=7)

    summary = report["summary"]
    assert summary["events"] == 3
    assert summary["runs"] == 2
    assert summary["unique_users"] == 2
    assert summary["wizard_opened"] == 1
    assert summary["onboarding_completed"] == 1
    assert summary["completion_rate"] == 1.0
    assert summary["completed_journeys_with_timing"] == 0
    assert summary["median_time_to_ready_seconds"] == 0.0
    failures = report["top_failures"]
    assert failures
    assert failures[0]["event"] == "connection.failed"
    reasons = report["top_failure_reasons"]
    assert reasons
    assert reasons[0]["reason"] == "connection.failed"


def test_build_onboarding_outcome_report_includes_recovery_and_failure_reasons() -> None:
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
        _seed_event(
            db,
            run_id="r1",
            started_at=started,
            event_type="onboarding.client.wizard.download_approval_failed",
            payload_json='{"user_id":"u1","payload":{"error":"missing ollama runtime"}}',
        )
        _seed_event(
            db,
            run_id="r1",
            started_at=started,
            event_type="onboarding.client.wizard.download_approved",
            payload_json='{"user_id":"u1","payload":{"trigger":"approve_all"}}',
        )

        report = build_onboarding_outcome_report(db, since_days=7)

    summary = report["summary"]
    assert summary["recovery_attempts"] == 2
    assert summary["recovery_succeeded"] == 1
    assert summary["recovery_success_rate"] == 0.5
    assert summary["completed_journeys_with_timing"] == 0
    assert summary["median_time_to_ready_seconds"] == 0.0
    reasons = report["top_failure_reasons"]
    assert reasons
    assert reasons[0]["reason"] == "missing ollama runtime"


def test_build_onboarding_outcome_report_tracks_median_time_to_ready_seconds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runs.sqlite3"
        started = datetime.now(UTC).isoformat()
        _seed_event(
            db,
            run_id="s1",
            started_at=started,
            event_type="onboarding.client.wizard.opened",
            payload_json='{"user_id":"u1","onboarding_session_id":"session-1"}',
            t_ms=1_000,
            seq=1,
        )
        _seed_event(
            db,
            run_id="s1",
            started_at=started,
            event_type="onboarding.client.onboarding.completed",
            payload_json='{"user_id":"u1","onboarding_session_id":"session-1"}',
            t_ms=31_000,
            seq=2,
        )
        _seed_event(
            db,
            run_id="s2",
            started_at=started,
            event_type="onboarding.client.wizard.opened",
            payload_json='{"user_id":"u2","onboarding_session_id":"session-2"}',
            t_ms=500,
            seq=1,
        )
        _seed_event(
            db,
            run_id="s2",
            started_at=started,
            event_type="onboarding.client.onboarding.completed",
            payload_json='{"user_id":"u2","onboarding_session_id":"session-2"}',
            t_ms=90_500,
            seq=2,
        )

        report = build_onboarding_outcome_report(db, since_days=7)

    summary = report["summary"]
    assert summary["completed_journeys_with_timing"] == 2
    # Median of 30s and 90s.
    assert summary["median_time_to_ready_seconds"] == 60.0
