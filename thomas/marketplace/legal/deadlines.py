"""Deadline management and calendar integration module."""

import logging
from datetime import date, datetime, timedelta
from uuid import uuid4

from thomas.marketplace.legal._exceptions import DeadlineCalculationError

logger = logging.getLogger(__name__)


# Court rule-based deadlines by jurisdiction
COURT_RULES = {
    "federal": {
        "response_to_complaint": 21,  # days
        "response_to_motion": 14,
        "discovery_response": 30,
        "trial_readiness": 30,
    },
    "state_civil": {
        "response_to_complaint": 30,
        "response_to_motion": 21,
        "discovery_response": 35,
        "trial_readiness": 45,
    },
    "state_criminal": {
        "preliminary_hearing": 10,
        "arraignment": 72,
        "trial_readiness": 60,
    },
}

# Holidays (simplified - typically jurisdiction-specific)
FEDERAL_HOLIDAYS = {
    (1, 1): "New Year's Day",
    (7, 4): "Independence Day",
    (12, 25): "Christmas",
}


class Deadline:
    """Represents a court or statutory deadline."""

    def __init__(
        self,
        deadline_id: str,
        case_id: str,
        description: str,
        due_date: date,
        deadline_type: str,
        importance: int,
    ) -> None:
        """Initialize a deadline."""
        self.deadline_id = deadline_id
        self.case_id = case_id
        self.description = description
        self.due_date = due_date
        self.deadline_type = deadline_type
        self.importance = importance
        self.created_at = datetime.now()
        self.triggered_by: str | None = None
        self.dependent_deadlines: list[str] = []
        self.reminders_sent: list[datetime] = []
        self.marked_complete: bool = False


class ReminderSchedule:
    """Represents scheduled reminders for a deadline."""

    def __init__(
        self,
        deadline_id: str,
        due_date: date,
    ) -> None:
        """Initialize reminder schedule."""
        self.deadline_id = deadline_id
        self.due_date = due_date
        self.reminder_dates = self._calculate_reminders(due_date)
        self.reminders_sent: dict[int, datetime] = {}

    def _calculate_reminders(self, due_date: date) -> dict[int, date]:
        """Calculate reminder dates: at filing, 30/14/7/3/1 days before."""
        reminders = {}

        # Reminder schedule
        for days_before in [30, 14, 7, 3, 1]:
            reminder_date = due_date - timedelta(days=days_before)
            reminders[days_before] = reminder_date

        # Also add reminder on filing (filing assumed to be today)
        today = date.today()
        if today < due_date:
            reminders[0] = today

        return reminders


class DeadlineManager:
    """Manages deadline calculation, tracking, and reminders."""

    def __init__(self) -> None:
        """Initialize the deadline manager."""
        self.deadlines: dict[str, Deadline] = {}
        self.reminders: dict[str, ReminderSchedule] = {}
        self.triggered_deadlines: list[tuple[str, datetime]] = []
        self.calendar_events: list[dict] = []

    def create_deadline_from_rule(
        self,
        case_id: str,
        description: str,
        deadline_type: str,
        triggering_event_date: date,
        jurisdiction: str = "federal",
        importance: int = 3,
    ) -> Deadline:
        """Create a deadline based on court rules.

        Uses jurisdiction-specific rules to calculate due date.
        """
        if jurisdiction not in COURT_RULES:
            raise DeadlineCalculationError(f"Unknown jurisdiction: {jurisdiction}")

        rules = COURT_RULES[jurisdiction]
        if deadline_type not in rules:
            raise DeadlineCalculationError(f"Unknown deadline type: {deadline_type}")

        days = rules[deadline_type]
        due_date = self._add_business_days(triggering_event_date, days)

        return self.create_deadline(
            case_id=case_id,
            description=description,
            due_date=due_date,
            deadline_type=deadline_type,
            importance=importance,
            triggered_by=f"rule_{jurisdiction}_{deadline_type}",
        )

    def create_deadline(
        self,
        case_id: str,
        description: str,
        due_date: date,
        deadline_type: str,
        importance: int,
        triggered_by: str | None = None,
    ) -> Deadline:
        """Create a statutory or custom deadline."""
        if importance < 1 or importance > 5:
            raise ValueError("Importance must be 1-5")

        deadline_id = str(uuid4())
        deadline = Deadline(
            deadline_id=deadline_id,
            case_id=case_id,
            description=description,
            due_date=due_date,
            deadline_type=deadline_type,
            importance=importance,
        )

        if triggered_by:
            deadline.triggered_by = triggered_by

        self.deadlines[deadline_id] = deadline

        # Create reminder schedule
        reminder = ReminderSchedule(deadline_id, due_date)
        self.reminders[deadline_id] = reminder

        # Create calendar event
        self._create_calendar_event(deadline)

        logger.info(f"Created deadline {deadline_id}: {description}")
        return deadline

    def add_dependent_deadline(
        self,
        parent_deadline_id: str,
        child_deadline_id: str,
    ) -> Deadline:
        """Link a deadline as dependent on another (event-triggered)."""
        if parent_deadline_id not in self.deadlines:
            raise ValueError(f"Parent deadline {parent_deadline_id} not found")
        if child_deadline_id not in self.deadlines:
            raise ValueError(f"Child deadline {child_deadline_id} not found")

        parent = self.deadlines[parent_deadline_id]
        if child_deadline_id not in parent.dependent_deadlines:
            parent.dependent_deadlines.append(child_deadline_id)

        logger.info(f"Linked deadline {child_deadline_id} as dependent on " f"{parent_deadline_id}")

        return parent

    def get_overdue_deadlines(self) -> list[Deadline]:
        """Get all overdue deadlines."""
        today = date.today()
        return [d for d in self.deadlines.values() if d.due_date < today and not d.marked_complete]

    def get_deadlines_for_case(
        self,
        case_id: str,
        include_complete: bool = False,
    ) -> list[Deadline]:
        """Get all deadlines for a case."""
        deadlines = [d for d in self.deadlines.values() if d.case_id == case_id]

        if not include_complete:
            deadlines = [d for d in deadlines if not d.marked_complete]

        return sorted(deadlines, key=lambda d: d.due_date)

    def get_upcoming_deadlines(
        self,
        days: int = 30,
        include_complete: bool = False,
    ) -> list[Deadline]:
        """Get deadlines due within N days."""
        today = date.today()
        threshold = today + timedelta(days=days)

        deadlines = [
            d
            for d in self.deadlines.values()
            if today <= d.due_date <= threshold and (include_complete or not d.marked_complete)
        ]

        return sorted(deadlines, key=lambda d: d.due_date)

    def calculate_deadline_risk(self, deadline_id: str) -> int:
        """Calculate risk score for a deadline: (5 - days_remaining) × importance.

        Higher score = higher risk.
        """
        if deadline_id not in self.deadlines:
            raise ValueError(f"Deadline {deadline_id} not found")

        deadline = self.deadlines[deadline_id]
        days_remaining = (deadline.due_date - date.today()).days

        if days_remaining <= 0:
            return 25  # Max score for overdue

        risk = (5 - min(5, days_remaining)) * deadline.importance
        return max(0, min(25, risk))

    def get_reminders_due(self) -> list[dict]:
        """Get reminders due today."""
        today = date.today()
        reminders_due = []

        for deadline_id, reminder in self.reminders.items():
            if deadline_id not in self.deadlines:
                continue

            deadline = self.deadlines[deadline_id]
            if deadline.marked_complete:
                continue

            # Check which reminders are due
            for days_before, reminder_date in reminder.reminder_dates.items():
                if reminder_date == today and days_before not in reminder.reminders_sent:
                    reminders_due.append(
                        {
                            "deadline_id": deadline_id,
                            "deadline_description": deadline.description,
                            "due_date": deadline.due_date,
                            "days_before": days_before,
                            "importance": deadline.importance,
                        }
                    )

        return reminders_due

    def mark_deadline_complete(self, deadline_id: str) -> Deadline:
        """Mark a deadline as completed."""
        if deadline_id not in self.deadlines:
            raise ValueError(f"Deadline {deadline_id} not found")

        deadline = self.deadlines[deadline_id]
        deadline.marked_complete = True

        logger.info(f"Marked deadline {deadline_id} complete")
        return deadline

    def export_to_ical(self, case_id: str | None = None) -> str:
        """Export deadlines as iCalendar format."""
        deadlines = self.get_deadlines_for_case(case_id, include_complete=True) if case_id else self.deadlines.values()

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Legal Practice//Deadlines//EN",
        ]

        for deadline in deadlines:
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{deadline.deadline_id}",
                    f"DTSTAMP:{datetime.now().isoformat()}",
                    f"DTSTART:{deadline.due_date.isoformat()}",
                    f"SUMMARY:{deadline.description}",
                    f"DESCRIPTION:Deadline Type: {deadline.deadline_type}, " f"Importance: {deadline.importance}/5",
                    "END:VEVENT",
                ]
            )

        lines.append("END:VCALENDAR")
        return "\n".join(lines)

    def _add_business_days(
        self,
        start_date: date,
        num_days: int,
    ) -> date:
        """Add business days, excluding weekends and federal holidays."""
        current = start_date
        added = 0

        while added < num_days:
            current += timedelta(days=1)

            # Skip weekends (5=Saturday, 6=Sunday)
            if current.weekday() >= 5:
                continue

            # Skip federal holidays
            if (current.month, current.day) in FEDERAL_HOLIDAYS:
                continue

            added += 1

        return current

    def _create_calendar_event(self, deadline: Deadline) -> None:
        """Internal: create calendar event for deadline."""
        event = {
            "event_id": str(uuid4()),
            "deadline_id": deadline.deadline_id,
            "case_id": deadline.case_id,
            "title": f"[{deadline.importance}/5] {deadline.description}",
            "date": deadline.due_date,
            "type": deadline.deadline_type,
            "created_at": datetime.now(),
        }

        self.calendar_events.append(event)
