from __future__ import annotations

from pathlib import Path

from thomas.observability.focus_scorecard import build_focus_scorecard
from thomas.observability.run_db import connect, ensure_schema


def _seed_event(db: Path, *, run_id: str, event_type: str, payload_json: str) -> None:
    ensure_schema(db)
    con = connect(db)
    try:
        con.execute(
            "INSERT OR REPLACE INTO runs(run_id, started_at, ok, meta_json, last_seq) VALUES (?, datetime('now'), ?, ?, ?)",
            (run_id, 1, "{}", 1),
        )
        con.execute(
            "INSERT INTO events(run_id, t_ms, seq, event_type, payload_json) VALUES (?, ?, ?, ?, ?)",
            (run_id, 1, 1, event_type, payload_json),
        )
        con.commit()
    finally:
        con.close()


def test_focus_scorecard_flags_low_onboarding_completion(tmp_path: Path) -> None:
    db = tmp_path / "runs.sqlite3"
    # 6 opens, 1 completion -> low completion rate should trigger high-priority onboarding item.
    for idx in range(6):
        _seed_event(
            db,
            run_id=f"open-{idx}",
            event_type="onboarding.client.wizard.opened",
            payload_json='{"user_id":"u-open"}',
        )
    _seed_event(
        db,
        run_id="done-1",
        event_type="onboarding.client.onboarding.completed",
        payload_json='{"user_id":"u-done"}',
    )

    report = build_focus_scorecard(runs_db_path=db, window_days=7)
    actions = list(report.get("priority_actions") or [])
    ids = {str(item.get("id")) for item in actions}
    assert "onboarding_conversion_drop" in ids


def test_focus_scorecard_reports_maintain_course_when_clean(tmp_path: Path) -> None:
    db = tmp_path / "runs.sqlite3"
    report = build_focus_scorecard(runs_db_path=db, window_days=7)
    actions = list(report.get("priority_actions") or [])
    assert actions
    assert actions[0]["id"] in {"maintain_course", "config_warning_backlog"}
    assert 0 <= int(report.get("health_score", 0)) <= 100


def test_focus_scorecard_flags_low_recovery_success(tmp_path: Path) -> None:
    db = tmp_path / "runs.sqlite3"
    # 4 failures + 1 success -> 20% recovery success, should trigger recovery priority.
    for idx in range(4):
        _seed_event(
            db,
            run_id=f"recovery-fail-{idx}",
            event_type="onboarding.client.wizard.download_approval_failed",
            payload_json='{"user_id":"u1","payload":{"error":"installer denied"}}',
        )
    _seed_event(
        db,
        run_id="recovery-ok-1",
        event_type="onboarding.client.wizard.download_approved",
        payload_json='{"user_id":"u1","payload":{"trigger":"approve_all"}}',
    )

    report = build_focus_scorecard(runs_db_path=db, window_days=7)
    actions = list(report.get("priority_actions") or [])
    ids = {str(item.get("id")) for item in actions}
    assert "recovery_flow_low_success" in ids
