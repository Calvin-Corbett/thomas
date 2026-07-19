from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from thomas.core.timezones import resolve_timezone


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    txt = str(value or "").strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_hhmm(value: Any) -> tuple[int, int]:
    txt = str(value or "").strip()
    if len(txt) != 5 or txt[2] != ":":
        raise ValueError("schedule.at must be HH:MM")
    hour = int(txt[:2])
    minute = int(txt[3:5])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("schedule.at must be HH:MM")
    return hour, minute


def compute_next_run(schedule: dict[str, Any] | None, now: datetime | None = None) -> datetime | None:
    if not schedule:
        return None
    current = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    stype = str(schedule.get("type") or "").strip().lower()
    if stype == "once":
        run_at = _as_datetime(schedule.get("run_at"))
        if run_at is None:
            raise ValueError("schedule.run_at required for once")
        return run_at.astimezone(timezone.utc)

    if stype == "interval":
        every_seconds = float(schedule.get("every_seconds") or 0)
        if every_seconds <= 0:
            raise ValueError("schedule.every_seconds must be > 0")
        start_at = _as_datetime(schedule.get("start_at")) or current
        start_at = start_at.astimezone(timezone.utc)
        if start_at >= current:
            return start_at
        elapsed = (current - start_at).total_seconds()
        steps = int(elapsed // every_seconds) + 1
        return start_at + timedelta(seconds=steps * every_seconds)

    if stype in {"daily", "weekly"}:
        tz_name = str(schedule.get("tz") or "UTC").strip() or "UTC"
        zone = resolve_timezone(tz_name)
        hour, minute = _parse_hhmm(schedule.get("at"))
        local_now = current.astimezone(zone)
        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if stype == "daily":
            if target <= local_now:
                target = target + timedelta(days=1)
            return target.astimezone(timezone.utc)

        dow_values = schedule.get("dow")
        if not isinstance(dow_values, list) or not dow_values:
            raise ValueError("schedule.dow must include weekday numbers 0..6")
        weekdays = sorted({int(v) for v in dow_values if 0 <= int(v) <= 6})
        if not weekdays:
            raise ValueError("schedule.dow must include weekday numbers 0..6")
        for offset in range(0, 8):
            candidate = target + timedelta(days=offset)
            if candidate.weekday() not in weekdays:
                continue
            if candidate <= local_now:
                continue
            return candidate.astimezone(timezone.utc)
        return None

    raise ValueError(f"unsupported schedule type '{stype}'")
