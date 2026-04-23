"""Google Calendar API operations for Google Workspace integration.

Provides functions to list, create, update, and delete calendar events
through Google Calendar API v3.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class CalendarError(Exception):
    """Raised when Google Calendar API operations fail."""

    pass


class CalendarAPI:
    """Wrapper for Google Calendar API v3 operations using raw REST endpoints."""

    BASE_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(self, access_token: str) -> None:
        """Initialize Google Calendar API client.

        Args:
            access_token: OAuth2 access token with Calendar scope
        """
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        """Get authorization headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def list_calendars(self, session: Any) -> dict[str, Any]:
        """Get list of all calendars accessible to the user.

        Args:
            session: aiohttp ClientSession

        Returns:
            Dict with calendars list
        """
        url = f"{self.BASE_URL}/users/me/calendarList"
        try:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise CalendarError(f"List calendars failed: {resp.status} - {error}")
                data = await resp.json()
                calendars = data.get("items", [])
                return {
                    "calendars": [
                        {
                            "id": cal.get("id"),
                            "summary": cal.get("summary"),
                            "description": cal.get("description", ""),
                            "timezone": cal.get("timeZone"),
                            "primary": cal.get("primary", False),
                        }
                        for cal in calendars
                    ]
                }
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Failed to list calendars: {e}") from e

    async def list_events(
        self,
        session: Any,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 25,
        order_by: str = "startTime",
    ) -> dict[str, Any]:
        """List events in a calendar.

        Args:
            session: aiohttp ClientSession
            calendar_id: Calendar ID (default "primary")
            time_min: Lower bound for event start time (RFC 3339)
            time_max: Upper bound for event start time (RFC 3339)
            max_results: Maximum events to return
            order_by: Order results by "startTime" or "updated"

        Returns:
            Dict with events list
        """
        params = {
            "maxResults": min(2500, max(1, max_results)),
            "orderBy": order_by,
            "showDeleted": False,
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max

        url = f"{self.BASE_URL}/calendars/{calendar_id}/events"
        try:
            async with session.get(url, headers=self._headers(), params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise CalendarError(f"List events failed: {resp.status} - {error}")
                data = await resp.json()
                events = data.get("items", [])
                return {
                    "events": [self._normalize_event(ev) for ev in events],
                    "nextPageToken": data.get("nextPageToken"),
                }
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Failed to list events: {e}") from e

    async def get_event(
        self,
        session: Any,
        calendar_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        """Get details of a specific event.

        Args:
            session: aiohttp ClientSession
            calendar_id: Calendar ID
            event_id: Event ID

        Returns:
            Normalized event object
        """
        url = f"{self.BASE_URL}/calendars/{calendar_id}/events/{event_id}"
        try:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise CalendarError(f"Get event failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_event(data)
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Failed to get event {event_id}: {e}") from e

    async def create_event(
        self,
        session: Any,
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        attendees: list[str] | None = None,
        location: str = "",
    ) -> dict[str, Any]:
        """Create a new calendar event.

        Args:
            session: aiohttp ClientSession
            calendar_id: Calendar ID
            summary: Event title
            start: Start time (RFC 3339, e.g., "2024-02-26T10:00:00")
            end: End time (RFC 3339)
            description: Event description
            attendees: List of attendee email addresses
            location: Event location

        Returns:
            Created event object
        """
        payload = {
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if description:
            payload["description"] = description
        if location:
            payload["location"] = location
        if attendees:
            payload["attendees"] = [{"email": email} for email in attendees]

        url = f"{self.BASE_URL}/calendars/{calendar_id}/events"
        try:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                if resp.status != 201:
                    error = await resp.text()
                    raise CalendarError(f"Create event failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_event(data)
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Failed to create event: {e}") from e

    async def update_event(
        self,
        session: Any,
        calendar_id: str,
        event_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing calendar event.

        Args:
            session: aiohttp ClientSession
            calendar_id: Calendar ID
            event_id: Event ID
            updates: Dict with fields to update (summary, start, end, description, location, etc.)

        Returns:
            Updated event object
        """
        # First get the current event
        url = f"{self.BASE_URL}/calendars/{calendar_id}/events/{event_id}"
        try:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise CalendarError(f"Get event failed: {resp.status} - {error}")
                current = await resp.json()

            # Apply updates
            if "summary" in updates:
                current["summary"] = updates["summary"]
            if "start" in updates:
                current["start"] = updates["start"]
            if "end" in updates:
                current["end"] = updates["end"]
            if "description" in updates:
                current["description"] = updates["description"]
            if "location" in updates:
                current["location"] = updates["location"]

            # Send updated event
            async with session.patch(url, headers=self._headers(), json=current) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise CalendarError(f"Update event failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_event(data)
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Failed to update event {event_id}: {e}") from e

    async def delete_event(
        self,
        session: Any,
        calendar_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        """Delete a calendar event.

        Args:
            session: aiohttp ClientSession
            calendar_id: Calendar ID
            event_id: Event ID

        Returns:
            Dict with success status
        """
        url = f"{self.BASE_URL}/calendars/{calendar_id}/events/{event_id}"
        try:
            async with session.delete(url, headers=self._headers()) as resp:
                if resp.status not in (204, 200):
                    error = await resp.text()
                    raise CalendarError(f"Delete event failed: {resp.status} - {error}")
                return {"success": True, "eventId": event_id}
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Failed to delete event {event_id}: {e}") from e

    async def check_freebusy(
        self,
        session: Any,
        calendar_ids: list[str],
        time_min: str,
        time_max: str,
    ) -> dict[str, Any]:
        """Check free/busy status for calendars.

        Args:
            session: aiohttp ClientSession
            calendar_ids: List of calendar IDs
            time_min: Start of time period (RFC 3339)
            time_max: End of time period (RFC 3339)

        Returns:
            Dict with freebusy info per calendar
        """
        payload = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cal_id} for cal_id in calendar_ids],
        }

        url = f"{self.BASE_URL}/freeBusy"
        try:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise CalendarError(f"Check freebusy failed: {resp.status} - {error}")
                data = await resp.json()

                # Normalize response
                calendars_freebusy = data.get("calendars", {})
                result = {
                    "calendars": {
                        cal_id: {
                            "busy": [
                                {"start": slot.get("start"), "end": slot.get("end")}
                                for slot in freebusy.get("busy", [])
                            ]
                        }
                        for cal_id, freebusy in calendars_freebusy.items()
                    }
                }
                return result
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Failed to check freebusy: {e}") from e

    @staticmethod
    def _normalize_event(raw_event: dict[str, Any]) -> dict[str, Any]:
        """Normalize Google Calendar API event response."""
        start = raw_event.get("start", {})
        end = raw_event.get("end", {})

        return {
            "eventId": raw_event.get("id"),
            "summary": raw_event.get("summary", ""),
            "description": raw_event.get("description", ""),
            "location": raw_event.get("location", ""),
            "startTime": start.get("dateTime") or start.get("date"),
            "endTime": end.get("dateTime") or end.get("date"),
            "organizer": raw_event.get("organizer", {}).get("email", ""),
            "attendees": [
                {"email": att.get("email"), "responseStatus": att.get("responseStatus")}
                for att in raw_event.get("attendees", [])
            ],
            "htmlLink": raw_event.get("htmlLink", ""),
            "status": raw_event.get("status", ""),
            "transparency": raw_event.get("transparency", "opaque"),
            "visibility": raw_event.get("visibility", "default"),
            "reminders": raw_event.get("reminders", {}).get("overrides", []),
        }
