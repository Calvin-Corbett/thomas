"""Calendar operations for email_calendar tools.

Includes calendar listing, freebusy checking, and event creation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

try:
    from thomas.tools.base import Tool, ToolError  # type: ignore
except ImportError:  # pragma: no cover

    class ToolError(RuntimeError):
        pass


def _merge_busy_intervals(busy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Merge overlapping busy intervals."""
    if not busy:
        return []
    sorted_busy = sorted(busy, key=lambda x: x[0])
    merged = [sorted_busy[0]]
    for start, end in sorted_busy[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _invert_to_free(
    window_start: datetime, window_end: datetime, busy: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """Invert busy intervals to free intervals."""
    busy = _merge_busy_intervals(busy)
    free = []

    current = window_start
    for busy_start, busy_end in busy:
        if busy_start > current:
            free.append((current, busy_start))
        current = max(current, busy_end)

    if current < window_end:
        free.append((current, window_end))

    return free


def _round_up(dt: datetime, minutes: int) -> datetime:
    """Round datetime up to nearest N minutes."""
    if minutes <= 0:
        return dt
    delta = timedelta(minutes=minutes)
    return dt + (delta - timedelta(microseconds=dt.microsecond + dt.second * 1_000_000) % delta)


def _parse_freebusy_payload_to_intervals(payload: dict[str, Any], tzinfo_: Any) -> list[tuple[datetime, datetime]]:
    """Parse freebusy response payload into datetime intervals."""
    from .email_calendar import _parse_iso_datetime

    intervals = []
    for cal_id, cal_data in (payload.get("calendars") or {}).items():
        for busy_item in cal_data.get("busy") or []:
            start_str = busy_item.get("start") or ""
            end_str = busy_item.get("end") or ""
            if start_str and end_str:
                start = _parse_iso_datetime(start_str)
                end = _parse_iso_datetime(end_str)
                intervals.append((start, end))
    return intervals


class CalendarTodayTool(Tool):
    """Tool to list today's calendar events."""

    name = "calendar.today"
    description = "List today's calendar events."
    params_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        from .email_calendar import _get_service

        return await _get_service().calendar_list_events(days=1)


class CalendarWeekTool(Tool):
    """Tool to list next 7 days' calendar events."""

    name = "calendar.week"
    description = "List next 7 days of calendar events."
    params_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        from .email_calendar import _get_service

        return await _get_service().calendar_list_events(days=7)


class CalendarCreateEventTool(Tool):
    """Tool to create a calendar event."""

    name = "calendar.create"
    description = "Create a calendar event."
    params_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "ISO 8601 start time"},
            "end": {"type": "string", "description": "ISO 8601 end time"},
            "description": {"type": "string", "description": "Event description (optional)"},
        },
        "required": ["title", "start", "end"],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        from .email_calendar import _get_service

        return await _get_service().calendar_create_event(
            title=str(params.get("title", "")).strip(),
            start=str(params.get("start", "")).strip(),
            end=str(params.get("end", "")).strip(),
            description=str(params.get("description", "")).strip(),
        )


class CalendarSuggestTimesTool(Tool):
    """Tool to suggest available meeting times."""

    name = "calendar.suggest_times"
    description = "Suggest available meeting times based on calendar freebusy."
    params_schema = {
        "type": "object",
        "properties": {
            "calendars": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Calendar IDs (default: primary)",
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Meeting duration in minutes (default: 60)",
                "minimum": 15,
                "maximum": 480,
            },
            "days_ahead": {
                "type": "integer",
                "description": "Number of days to search (default: 14)",
                "minimum": 1,
                "maximum": 90,
            },
            "start_hour": {
                "type": "integer",
                "description": "Start hour of business day (default: 9)",
                "minimum": 0,
                "maximum": 23,
            },
            "end_hour": {
                "type": "integer",
                "description": "End hour of business day (default: 17)",
                "minimum": 0,
                "maximum": 23,
            },
            "timezone": {
                "type": "string",
                "description": "Timezone (default: UTC)",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        from .email_calendar import _get_service

        calendars = params.get("calendars") or ["primary"]
        if isinstance(calendars, str):
            calendars = [calendars]
        calendars = [str(c).strip() for c in calendars]

        duration = max(15, min(480, int(params.get("duration_minutes", 60))))
        days = max(1, min(90, int(params.get("days_ahead", 14))))
        start_hour = max(0, min(23, int(params.get("start_hour", 9))))
        end_hour = max(0, min(23, int(params.get("end_hour", 17))))
        tz = str(params.get("timezone", "UTC")).strip()

        if start_hour >= end_hour:
            raise ToolError("start_hour must be before end_hour")

        suggestions = await _get_service().suggest_times(
            calendars=calendars,
            duration_minutes=duration,
            days_ahead=days,
            start_hour=start_hour,
            end_hour=end_hour,
            timezone=tz,
        )

        return suggestions
