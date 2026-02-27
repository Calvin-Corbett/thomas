"""Onboarding outcome analytics built from recorded observability events."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from thomas.observability.run_db import connect, ensure_schema, resolve_runs_db_path


@dataclass(frozen=True)
class OnboardingEvent:
    run_id: str
    started_at: datetime | None
    t_ms: int | None
    event_type: str
    payload: dict[str, Any]


def _parse_iso_datetime(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ImportError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_payload(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _parse_int(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except json.JSONDecodeError:
        return None
    return value if value >= 0 else None


def _normalize_onboarding_event_name(full_type: str) -> str:
    prefix = "onboarding.client."
    if full_type.startswith(prefix):
        return full_type[len(prefix) :]
    return full_type


def _fetch_events(db_path: Path) -> list[OnboardingEvent]:
    ensure_schema(db_path)
    con = connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT e.run_id, r.started_at, e.t_ms, e.event_type, e.payload_json
            FROM events e
            LEFT JOIN runs r ON r.run_id = e.run_id
            WHERE e.event_type LIKE 'onboarding.client.%'
            ORDER BY e.id ASC
            """
        ).fetchall()
    finally:
        con.close()

    out: list[OnboardingEvent] = []
    for row in rows:
        out.append(
            OnboardingEvent(
                run_id=str(row["run_id"] or ""),
                started_at=_parse_iso_datetime(row["started_at"]),
                t_ms=_parse_int(row["t_ms"]),
                event_type=_normalize_onboarding_event_name(str(row["event_type"] or "")),
                payload=_load_payload(row["payload_json"]),
            )
        )
    return out


def _stage_bucket(event_name: str) -> str:
    name = str(event_name or "").strip().lower()
    if any(key in name for key in ("wizard.open", "onboarding.open", "opened")):
        return "wizard_opened"
    if any(key in name for key in ("path.select", "path_selected")):
        return "path_selected"
    if any(key in name for key in ("connection.pass", "connection.ok", "connection.success")):
        return "connection_passed"
    if any(key in name for key in ("connection.fail", "connection.error")):
        return "connection_failed"
    if any(
        key in name
        for key in (
            "download_approval_failed",
            "download.approval.failed",
            "repair.failed",
            "recovery.failed",
        )
    ):
        return "recovery_failed"
    if any(
        key in name
        for key in (
            "download_approved",
            "download.approved",
            "repair.completed",
            "repair.success",
            "recovery.success",
        )
    ):
        return "recovery_succeeded"
    if any(key in name for key in ("dependencies.approve", "dependencies.approved")):
        return "dependencies_approved"
    if any(key in name for key in ("dependencies.skip", "dependencies.skipped")):
        return "dependencies_skipped"
    if any(key in name for key in ("interview.start", "interview.started")):
        return "interview_started"
    if any(key in name for key in ("interview.complete", "interview.completed")):
        return "interview_completed"
    if any(key in name for key in ("onboarding.complete", "onboarding.completed", "setup.completed")):
        return "onboarding_completed"
    return "other"


def _extract_failure_reason(event_name: str, payload: dict[str, Any]) -> str:
    raw_payload = dict(payload or {})
    nested_payload = raw_payload.get("payload")
    nested = nested_payload if isinstance(nested_payload, dict) else {}

    for candidate in (
        nested.get("error"),
        nested.get("reason"),
        raw_payload.get("error"),
        raw_payload.get("reason"),
    ):
        text = str(candidate or "").strip()
        if text:
            # Keep reasons bounded and normalize whitespace for stable grouping.
            return " ".join(text.split())[:220]

    fallback = str(event_name or "").strip()
    return fallback[:220]


def _extract_journey_id(payload: dict[str, Any], run_id: str) -> str:
    root = dict(payload or {})
    nested_raw = root.get("payload")
    nested = nested_raw if isinstance(nested_raw, dict) else {}

    for candidate in (
        root.get("onboarding_session_id"),
        nested.get("onboarding_session_id"),
    ):
        sid = str(candidate or "").strip()
        if sid:
            return sid[:120]

    rid = str(run_id or "").strip()
    return rid[:120] if rid else "unknown"


def _filter_by_window(events: Iterable[OnboardingEvent], *, since_days: int) -> list[OnboardingEvent]:
    days = max(1, int(since_days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[OnboardingEvent] = []
    for event in events:
        started = event.started_at
        if started is not None and started < cutoff:
            continue
        out.append(event)
    return out


def build_onboarding_outcome_report(db_path: Path, *, since_days: int = 7) -> dict[str, Any]:
    events = _filter_by_window(_fetch_events(db_path), since_days=since_days)

    event_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    failure_events: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    users: set[str] = set()
    runs: set[str] = set()
    journey_timing: dict[str, dict[str, int]] = {}

    for event in events:
        name = str(event.event_type or "").strip()
        if not name:
            continue
        event_counts[name] += 1
        stage = _stage_bucket(name)
        stage_counts[stage] += 1
        lowered = name.lower()
        if "fail" in lowered or "error" in lowered:
            failure_events[name] += 1
            reason = _extract_failure_reason(name, event.payload)
            if reason:
                failure_reasons[reason] += 1
        payload = dict(event.payload or {})
        user_id = str(payload.get("user_id") or "").strip()
        if user_id:
            users.add(user_id)
        run_id = str(event.run_id or "").strip()
        if run_id:
            runs.add(run_id)

        journey_id = _extract_journey_id(payload, run_id)
        t_ms = event.t_ms
        stage = _stage_bucket(name)
        if t_ms is not None:
            timing = journey_timing.setdefault(journey_id, {})
            if stage == "wizard_opened":
                open_ms = timing.get("opened_ms")
                if open_ms is None or t_ms < open_ms:
                    timing["opened_ms"] = int(t_ms)
            elif stage == "onboarding_completed":
                complete_ms = timing.get("completed_ms")
                if complete_ms is None or t_ms < complete_ms:
                    timing["completed_ms"] = int(t_ms)

    opened = int(stage_counts.get("wizard_opened", 0))
    completed = int(stage_counts.get("onboarding_completed", 0))
    completion_rate = float(completed / opened) if opened > 0 else 0.0
    recovery_failed = int(stage_counts.get("recovery_failed", 0))
    recovery_succeeded = int(stage_counts.get("recovery_succeeded", 0))
    recovery_attempts = int(recovery_failed + recovery_succeeded)
    recovery_success_rate = float(recovery_succeeded / recovery_attempts) if recovery_attempts > 0 else 0.0
    duration_samples_ms: list[int] = []
    for timing in journey_timing.values():
        opened_ms = _parse_int(timing.get("opened_ms"))
        completed_ms = _parse_int(timing.get("completed_ms"))
        if opened_ms is None or completed_ms is None:
            continue
        delta = int(completed_ms - opened_ms)
        if delta < 0 or delta > 86_400_000:
            continue
        duration_samples_ms.append(delta)
    median_time_to_ready_seconds = (
        float(round(float(median(duration_samples_ms)) / 1000.0, 3)) if duration_samples_ms else 0.0
    )

    top_failures = [{"event": name, "count": int(count)} for name, count in failure_events.most_common(10)]
    top_failure_reasons = [{"reason": reason, "count": int(count)} for reason, count in failure_reasons.most_common(10)]

    return {
        "ok": True,
        "window_days": int(max(1, int(since_days))),
        "summary": {
            "events": int(sum(event_counts.values())),
            "runs": int(len(runs)),
            "unique_users": int(len(users)),
            "wizard_opened": opened,
            "onboarding_completed": completed,
            "completion_rate": float(round(completion_rate, 6)),
            "recovery_attempts": recovery_attempts,
            "recovery_succeeded": recovery_succeeded,
            "recovery_success_rate": float(round(recovery_success_rate, 6)),
            "completed_journeys_with_timing": int(len(duration_samples_ms)),
            "median_time_to_ready_seconds": median_time_to_ready_seconds,
        },
        "stage_counts": {key: int(value) for key, value in sorted(stage_counts.items())},
        "event_counts": {key: int(value) for key, value in sorted(event_counts.items())},
        "top_failures": top_failures,
        "top_failure_reasons": top_failure_reasons,
    }


def get_outcomes_report(*, since_days: int = 7) -> dict[str, Any]:
    """Backward-compatible default report loader used by HTTP endpoints."""
    db_path = resolve_runs_db_path()
    return build_onboarding_outcome_report(db_path, since_days=max(1, int(since_days)))
