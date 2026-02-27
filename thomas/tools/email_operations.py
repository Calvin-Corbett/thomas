"""Email operations and service for email/calendar tools.

Contains the EmailCalendarService class and email operation methods.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

try:
    from thomas.tools.base import Tool, ToolError  # type: ignore
except ImportError:  # pragma: no cover

    class ToolError(RuntimeError):
        pass


from .email_providers import _Provider


class _EmailCalendarService:
    """Service for email and calendar operations."""

    def __init__(self, provider: _Provider, config: Any) -> None:
        self.provider = provider
        self.config = config

    async def email_read(self, count: int, filter: str | None, folder: str) -> list[dict[str, Any]]:
        """Read recent email messages."""
        return await self.provider.email_read(count=count, filter=filter, folder=folder)

    async def email_get(self, message_id: str) -> dict[str, Any]:
        """Get a single email by ID."""
        if not message_id:
            raise ToolError("message_id is required.")
        return await self.provider.email_get(message_id=message_id)

    async def email_send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        """Send an email."""
        if not to or not subject:
            raise ToolError("to and subject are required.")
        return await self.provider.email_send(to=to, subject=subject, body=body)

    async def email_reply(self, message_id: str, body: str) -> dict[str, Any]:
        """Reply to an email."""
        if not message_id or not body:
            raise ToolError("message_id and body are required.")
        return await self.provider.email_reply(message_id=message_id, body=body)

    async def calendar_list_events(self, days: int = 7) -> list[dict[str, Any]]:
        """List calendar events for the next N days."""
        from .email_calendar import _get_tz

        tz = _get_tz(self.config.timezone)
        return await self.provider.calendar_list_events(days=days, tz=self.config.timezone)

    async def calendar_freebusy(self, calendars: list[str], start: str, end: str) -> list[tuple[str, str]]:
        """Get busy intervals for calendars."""
        return await self.provider.calendar_freebusy(
            calendars=calendars,
            start=start,
            end=end,
            tz=self.config.timezone,
        )

    async def calendar_create_event(self, title: str, start: str, end: str, description: str = "") -> dict[str, Any]:
        """Create a calendar event."""
        return await self.provider.calendar_create_event(
            title=title,
            start=start,
            end=end,
            description=description,
            tz=self.config.timezone,
        )

    async def suggest_times(
        self,
        calendars: list[str],
        duration_minutes: int = 60,
        days_ahead: int = 14,
        start_hour: int = 9,
        end_hour: int = 17,
        timezone: str = "UTC",
    ) -> list[dict[str, Any]]:
        """Suggest available meeting times based on freebusy."""
        from datetime import datetime as dt

        from .calendar_operations import _invert_to_free, _round_up
        from .email_calendar import _get_tz

        if not calendars:
            calendars = ["primary"]

        tz_info = _get_tz(timezone)
        now = dt.now(tz_info)
        now_rounded = _round_up(now, 30)

        suggestions = []

        for day_offset in range(days_ahead):
            day_start = now_rounded + timedelta(days=day_offset)
            day_start = day_start.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            day_end = day_start.replace(hour=end_hour, minute=0, second=0, microsecond=0)

            if day_start < now_rounded:
                day_start = now_rounded

            if day_start >= day_end:
                continue

            window_start_iso = day_start.isoformat()
            window_end_iso = day_end.isoformat()

            busy = await self.calendar_freebusy(calendars, window_start_iso, window_end_iso)

            if isinstance(busy, list) and busy and isinstance(busy[0], tuple):
                pass
            else:
                busy = []

            free = _invert_to_free(day_start, day_end, busy)

            for free_start, free_end in free:
                free_duration = (free_end - free_start).total_seconds() / 60
                if free_duration >= duration_minutes:
                    suggestions.append(
                        {
                            "start": free_start.isoformat(),
                            "end": (free_start + timedelta(minutes=duration_minutes)).isoformat(),
                            "duration_minutes": duration_minutes,
                        }
                    )

                if len(suggestions) >= 5:
                    return suggestions

        return suggestions
