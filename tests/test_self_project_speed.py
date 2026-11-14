"""A Build speed comparison uses landed verdicts, not merely handed-in projects."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from thomas.server.routes.self_project_speed import speed_scoreboard


def _project(outbox: Path, cid: str, request: datetime, landing: datetime | None) -> dict:
    if landing:
        (outbox / f"{cid}.verdict.json").write_text(
            json.dumps({"status": "landed", "ts": landing.timestamp()}), encoding="utf-8"
        )
    return {
        "thomas_project": {"submission": cid, "settled_at": landing.isoformat() if landing else None},
        "turns": [{"role": "user", "ts": request.isoformat()}],
    }


def test_landed_wall_clock_median_step_shares_and_concurrent_teams(tmp_path: Path) -> None:
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    last_week = now - timedelta(days=3)
    today = now.replace(hour=9)
    conversations = {
        "old": _project(tmp_path, "old", last_week, last_week + timedelta(minutes=30)),
        "fast": _project(tmp_path, "fast", today, today + timedelta(minutes=10)),
        "faster": _project(tmp_path, "faster", today + timedelta(minutes=2), today + timedelta(minutes=7)),
        "pending": _project(tmp_path, "pending", today + timedelta(minutes=3), None),
    }
    timings = {
        "old": {"building": 300},
        "fast": {"building": 300, "checks": 100},
        "faster": {"building": 120, "checks": 60},
    }
    score = speed_scoreboard(conversations, timings, tmp_path, now, {"pending", "fast", "faster"})
    assert score["today"]["median_seconds"] == 450
    assert score["today"]["landed"] == 2
    assert score["today"]["steps"]["building"] == 46.7
    assert score["today"]["steps"]["unattributed"] == 35.6
    assert score["today"]["peak_teams"] == 3
    assert score["last_week"]["median_seconds"] == 1800
    assert score["last_week"]["peak_teams"] == 1
    assert score["last_week"]["steps"]["building"] == 16.7
    assert score["last_week"]["steps"]["unattributed"] == 83.3
    assert score["faster_percent"] == 75.0
    # Landing can occur long after hand-in; a handed-in team has already stopped.
    conversations["fast"]["thomas_project"]["settled_at"] = (today + timedelta(minutes=1)).isoformat()
    assert (
        speed_scoreboard(conversations, timings, tmp_path, now, {"pending", "fast", "faster"})["today"]["peak_teams"]
        == 2
    )


def test_pending_and_malformed_verdicts_never_count_as_landed(tmp_path: Path) -> None:
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    project = _project(tmp_path, "waiting", now - timedelta(minutes=1), None)
    assert speed_scoreboard({"waiting": project}, {}, tmp_path, now)["today"]["median_seconds"] is None
    verdict = tmp_path / "waiting.verdict.json"
    verdict.write_text('{"status":"refused","ts":1}', encoding="utf-8")
    assert speed_scoreboard({"waiting": project}, {}, tmp_path, now)["today"]["landed"] == 0
    verdict.write_text('{"status":"landed","ts":"not a timestamp"}', encoding="utf-8")
    assert speed_scoreboard({"waiting": project}, {}, tmp_path, now)["today"]["landed"] == 0


def test_invalid_retirement_and_unmatched_submission_are_ignored(tmp_path: Path) -> None:
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    project = _project(tmp_path, "safe", now - timedelta(minutes=1), None)
    project["thomas_project"] = {"retirement": "not a record"}
    assert speed_scoreboard({"safe": project}, {}, tmp_path, now)["today"]["landed"] == 0
    project["thomas_project"] = {"submission": "../elsewhere"}
    assert speed_scoreboard({"safe": project}, {}, tmp_path, now)["today"]["landed"] == 0
