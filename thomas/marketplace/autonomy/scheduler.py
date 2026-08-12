from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from thomas.core.timezones import resolve_timezone

# Scheduling spec (JSON):
# - {"type":"once","run_at":"2026-02-10T12:34:56-06:00"}
# - {"type":"interval","every_seconds":3600,"start_at": "...optional..."}
# - {"type":"daily","at":"08:00","tz":"America/Chicago"}
# - {"type":"weekly","dow":[1,3,5],"at":"09:00","tz":"America/Chicago"}  # 0=Mon
#
# All schedule computations are deterministic and timezone-aware.


def _parse_dt(val: str) -> datetime:
    # datetime.fromisoformat supports offsets (e.g. -06:00)
    return datetime.fromisoformat(val)


def _parse_hhmm(val: str) -> time:
    parts = val.strip().split(":")
    if len(parts) != 2:
        raise ValueError("time must be HH:MM")
    hh, mm = int(parts[0]), int(parts[1])
    return time(hour=hh, minute=mm, second=0)


def compute_next_run(schedule: dict[str, Any] | None, now: datetime) -> datetime | None:
    if not schedule:
        return None
    stype = schedule.get("type")
    if stype == "once":
        run_at = schedule.get("run_at")
        if not run_at:
            return None
        dt = _parse_dt(run_at)
        return dt if dt > now else None

    if stype == "interval":
        every = float(schedule.get("every_seconds", 0))
        if every <= 0:
            return None
        start_at = schedule.get("start_at")
        if start_at:
            base = _parse_dt(start_at)
            if base > now:
                return base
            # align to next multiple
            elapsed = (now - base).total_seconds()
            k = int(elapsed // every) + 1
            return base + timedelta(seconds=k * every)
        return now + timedelta(seconds=every)

    if stype in ("daily", "weekly"):
        tz_name = schedule.get("tz") or "UTC"
        tz = resolve_timezone(tz_name)
        at = _parse_hhmm(schedule.get("at", "00:00"))
        # Convert "now" into target tz for calendar logic
        local_now = now.astimezone(tz)
        candidate = local_now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate = candidate + timedelta(days=1)
        if stype == "weekly":
            dows = schedule.get("dow") or []
            if not isinstance(dows, list) or not dows:
                return candidate.astimezone(now.tzinfo or tz)
            # Find next day whose weekday is in dows (0=Mon)
            for i in range(0, 14):
                cand = candidate + timedelta(days=i)
                if cand.weekday() in set(int(x) for x in dows):
                    if cand > local_now:
                        candidate = cand
                        break
        return candidate.astimezone(now.tzinfo or tz)

    # Unknown schedule type
    return None


@dataclass(frozen=True)
class EngineTiming:
    scheduler_tick_s: float = 1.5
    lock_ttl_s: float = 300.0
    max_concurrency: int = 4
    claim_batch: int = 8
