"""
Activity tracking for the CRM system.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.crm._types import Activity, ActivityType


class ActivityManager:
    """Manages activities in the CRM system.

    Handles activity logging, scheduling, reminders, feed generation,
    statistics, alerts, and templates.
    """

    def __init__(self) -> None:
        """Initialize the activity manager."""
        self._activities: dict[str, Activity] = {}
        self._activity_templates: dict[str, dict[str, Any]] = {}
        self._scheduled_activities: dict[str, dict[str, Any]] = {}
        self._reminders: dict[str, list[dict[str, Any]]] = {}

    def log_activity(
        self,
        activity_type: ActivityType,
        contact_id: str,
        notes: str,
        timestamp: datetime | None = None,
        deal_id: str | None = None,
        duration: int | None = None,
        user: str | None = None,
    ) -> Activity:
        """Log a new activity.

        Args:
            activity_type: Type of activity
            contact_id: Associated contact ID
            notes: Activity notes/description
            timestamp: When the activity occurred (defaults to now)
            deal_id: Associated deal ID
            duration: Duration in minutes
            user: User who logged the activity

        Returns:
            Created Activity object
        """
        activity_id = str(uuid.uuid4())

        activity = Activity(
            id=activity_id,
            type=activity_type,
            contact_id=contact_id,
            deal_id=deal_id,
            timestamp=timestamp or datetime.utcnow(),
            notes=notes,
            duration=duration,
            user=user,
        )

        self._activities[activity_id] = activity
        return activity

    def get_activity(self, activity_id: str) -> Activity:
        """Get an activity by ID.

        Args:
            activity_id: Activity identifier

        Returns:
            Activity object
        """
        return self._activities.get(activity_id)

    def list_activities(self) -> list[Activity]:
        """Get all activities.

        Returns:
            List of Activity objects
        """
        return list(self._activities.values())

    def delete_activity(self, activity_id: str) -> None:
        """Delete an activity.

        Args:
            activity_id: Activity identifier
        """
        if activity_id in self._activities:
            del self._activities[activity_id]

    def schedule_activity(
        self,
        activity_type: ActivityType,
        contact_id: str,
        notes: str,
        scheduled_for: datetime,
        deal_id: str | None = None,
        user: str | None = None,
    ) -> str:
        """Schedule an activity for a future time.

        Args:
            activity_type: Type of activity
            contact_id: Associated contact ID
            notes: Activity notes
            scheduled_for: When the activity should occur
            deal_id: Associated deal ID
            user: User who scheduled the activity

        Returns:
            Scheduled activity ID
        """
        scheduled_id = str(uuid.uuid4())

        scheduled = {
            "id": scheduled_id,
            "type": activity_type.value,
            "contact_id": contact_id,
            "deal_id": deal_id,
            "notes": notes,
            "scheduled_for": scheduled_for.isoformat(),
            "user": user,
            "created_at": datetime.utcnow().isoformat(),
            "completed": False,
        }

        self._scheduled_activities[scheduled_id] = scheduled

        return scheduled_id

    def complete_scheduled_activity(self, scheduled_id: str) -> Activity:
        """Complete a scheduled activity and log it.

        Args:
            scheduled_id: Scheduled activity ID

        Returns:
            Logged Activity object
        """
        if scheduled_id not in self._scheduled_activities:
            return None

        scheduled = self._scheduled_activities[scheduled_id]

        activity = self.log_activity(
            activity_type=ActivityType(scheduled["type"]),
            contact_id=scheduled["contact_id"],
            notes=scheduled["notes"],
            timestamp=datetime.utcnow(),
            deal_id=scheduled["deal_id"],
            user=scheduled["user"],
        )

        scheduled["completed"] = True
        del self._scheduled_activities[scheduled_id]

        return activity

    def get_scheduled_activities(self) -> list[dict[str, Any]]:
        """Get all scheduled activities.

        Returns:
            List of scheduled activities, sorted by scheduled_for
        """
        activities = list(self._scheduled_activities.values())
        return sorted(activities, key=lambda a: a["scheduled_for"])

    def get_overdue_activities(self) -> list[dict[str, Any]]:
        """Get all overdue scheduled activities.

        Returns:
            List of overdue scheduled activities
        """
        overdue = []
        now = datetime.utcnow()

        for activity in self._scheduled_activities.values():
            scheduled_time = datetime.fromisoformat(activity["scheduled_for"])

            if scheduled_time < now and not activity["completed"]:
                overdue.append(activity)

        return sorted(overdue, key=lambda a: a["scheduled_for"])

    def set_reminder(
        self,
        scheduled_id: str,
        remind_before_minutes: int = 15,
    ) -> None:
        """Set a reminder for a scheduled activity.

        Args:
            scheduled_id: Scheduled activity ID
            remind_before_minutes: Minutes before the activity to remind
        """
        if scheduled_id not in self._scheduled_activities:
            return

        scheduled = self._scheduled_activities[scheduled_id]

        reminder = {
            "id": str(uuid.uuid4()),
            "scheduled_id": scheduled_id,
            "contact_id": scheduled["contact_id"],
            "remind_at": (
                datetime.fromisoformat(scheduled["scheduled_for"]) - timedelta(minutes=remind_before_minutes)
            ).isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "sent": False,
        }

        if scheduled_id not in self._reminders:
            self._reminders[scheduled_id] = []

        self._reminders[scheduled_id].append(reminder)

    def get_pending_reminders(self) -> list[dict[str, Any]]:
        """Get all pending reminders.

        Returns:
            List of pending reminders
        """
        pending = []
        now = datetime.utcnow()

        for scheduled_id, reminders in self._reminders.items():
            for reminder in reminders:
                remind_time = datetime.fromisoformat(reminder["remind_at"])

                if remind_time <= now and not reminder["sent"]:
                    pending.append(reminder)

        return pending

    def mark_reminder_sent(self, reminder_id: str) -> None:
        """Mark a reminder as sent.

        Args:
            reminder_id: Reminder ID
        """
        for reminders in self._reminders.values():
            for reminder in reminders:
                if reminder["id"] == reminder_id:
                    reminder["sent"] = True
                    return

    def get_activity_feed(
        self,
        contact_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Activity]:
        """Get an activity feed, optionally filtered by contact.

        Activities are returned in reverse chronological order (newest first).

        Args:
            contact_id: Optional contact ID to filter by
            limit: Maximum number of activities to return
            offset: Offset for pagination

        Returns:
            List of Activity objects
        """
        activities = list(self._activities.values())

        if contact_id:
            activities = [a for a in activities if a.contact_id == contact_id]

        # Sort by timestamp, newest first
        sorted_activities = sorted(activities, key=lambda a: a.timestamp, reverse=True)

        return sorted_activities[offset : offset + limit]

    def get_activity_statistics(
        self,
        user: str | None = None,
        activity_type: ActivityType | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get activity statistics for a time period.

        Args:
            user: Optional user to filter by
            activity_type: Optional activity type to filter by
            days: Number of days to look back

        Returns:
            Dictionary with activity statistics
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        activities = [a for a in self._activities.values() if a.timestamp >= cutoff]

        if user:
            activities = [a for a in activities if a.user == user]

        if activity_type:
            activities = [a for a in activities if a.type == activity_type]

        # Count by type
        by_type: dict[str, int] = defaultdict(int)
        for activity in activities:
            by_type[activity.type.value] += 1

        # Count by user
        by_user: dict[str, int] = defaultdict(int)
        for activity in activities:
            if activity.user:
                by_user[activity.user] += 1

        # Calculate total duration
        total_duration = sum(a.duration for a in activities if a.duration) or 0

        return {
            "total_activities": len(activities),
            "by_type": dict(by_type),
            "by_user": dict(by_user),
            "total_duration_minutes": total_duration,
            "average_duration_minutes": (
                total_duration / len([a for a in activities if a.duration])
                if any(a.duration for a in activities)
                else 0
            ),
        }

    def create_activity_template(
        self,
        template_name: str,
        activity_type: ActivityType,
        notes_template: str,
        duration: int | None = None,
    ) -> str:
        """Create a reusable activity template.

        Args:
            template_name: Name of the template
            activity_type: Type of activity
            notes_template: Template for notes (can contain variables)
            duration: Default duration

        Returns:
            Template ID
        """
        template_id = str(uuid.uuid4())

        self._activity_templates[template_id] = {
            "id": template_id,
            "name": template_name,
            "type": activity_type.value,
            "notes_template": notes_template,
            "duration": duration,
            "created_at": datetime.utcnow().isoformat(),
        }

        return template_id

    def get_activity_template(self, template_id: str) -> dict[str, Any]:
        """Get an activity template.

        Args:
            template_id: Template ID

        Returns:
            Template dictionary
        """
        return self._activity_templates.get(template_id)

    def list_activity_templates(self) -> list[dict[str, Any]]:
        """Get all activity templates.

        Returns:
            List of template dictionaries
        """
        return list(self._activity_templates.values())

    def create_activity_from_template(
        self,
        template_id: str,
        contact_id: str,
        variable_substitutions: dict[str, str] | None = None,
        deal_id: str | None = None,
        user: str | None = None,
    ) -> Activity:
        """Create an activity from a template.

        Args:
            template_id: Template ID
            contact_id: Contact ID
            variable_substitutions: Variables to substitute in template
            deal_id: Associated deal ID
            user: User logging the activity

        Returns:
            Created Activity object
        """
        template = self.get_activity_template(template_id)

        if not template:
            return None

        notes = template["notes_template"]

        if variable_substitutions:
            for var, value in variable_substitutions.items():
                notes = notes.replace(f"{{{{{var}}}}}", str(value))

        activity = self.log_activity(
            activity_type=ActivityType(template["type"]),
            contact_id=contact_id,
            notes=notes,
            deal_id=deal_id,
            duration=template.get("duration"),
            user=user,
        )

        return activity

    def get_contact_activity_summary(self, contact_id: str) -> dict[str, Any]:
        """Get an activity summary for a contact.

        Args:
            contact_id: Contact ID

        Returns:
            Dictionary with contact activity summary
        """
        activities = [a for a in self._activities.values() if a.contact_id == contact_id]

        if not activities:
            return {
                "contact_id": contact_id,
                "total_activities": 0,
                "last_activity": None,
                "by_type": {},
            }

        sorted_activities = sorted(activities, key=lambda a: a.timestamp, reverse=True)

        by_type: dict[str, int] = defaultdict(int)
        for activity in activities:
            by_type[activity.type.value] += 1

        return {
            "contact_id": contact_id,
            "total_activities": len(activities),
            "last_activity": sorted_activities[0].timestamp.isoformat(),
            "first_activity": sorted_activities[-1].timestamp.isoformat(),
            "by_type": dict(by_type),
            "total_duration_minutes": sum(a.duration for a in activities if a.duration) or 0,
        }
