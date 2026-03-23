"""Time and attendance system with timesheet management and analytics."""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from thomas.marketplace.hr_platform._exceptions import TimeTrackingError
from thomas.marketplace.hr_platform._types import TimeEntry


class TimeSheet:
    """Weekly timesheet for employee."""

    def __init__(self, employee_id: str, week_start: date) -> None:
        """Initialize timesheet.

        Args:
            employee_id: ID of employee
            week_start: Monday of week
        """
        self.id = str(uuid.uuid4())
        self.employee_id = employee_id
        self.week_start = week_start
        self.week_end = week_start + timedelta(days=6)
        self.entries: list[TimeEntry] = []
        self.status = "draft"  # draft, submitted, approved, rejected
        self.submitted_at: datetime | None = None
        self.approved_by: str | None = None

    def add_entry(self, entry: TimeEntry) -> TimeEntry:
        """Add time entry to timesheet.

        Args:
            entry: TimeEntry to add

        Returns:
            The added entry

        Raises:
            TimeTrackingError: If entry outside week range
        """
        if not (self.week_start <= entry.date <= self.week_end):
            raise TimeTrackingError("Entry date outside timesheet week")

        self.entries.append(entry)
        return entry

    def total_hours(self) -> Decimal:
        """Calculate total hours for week.

        Returns:
            Total hours worked
        """
        return sum(entry.hours_worked() for entry in self.entries)

    def billable_hours(self) -> Decimal:
        """Calculate billable hours for week.

        Returns:
            Total billable hours
        """
        return sum(entry.hours_worked() for entry in self.entries if entry.billable)

    def submit(self) -> None:
        """Submit timesheet for approval."""
        if self.status != "draft":
            raise TimeTrackingError("Timesheet already submitted")
        self.status = "submitted"
        self.submitted_at = datetime.now()

    def approve(self, approver_id: str) -> None:
        """Approve submitted timesheet.

        Args:
            approver_id: ID of approver
        """
        if self.status != "submitted":
            raise TimeTrackingError("Only submitted timesheets can be approved")
        self.status = "approved"
        self.approved_by = approver_id

    def reject(self) -> None:
        """Reject timesheet, return to draft."""
        self.status = "draft"
        self.submitted_at = None


class AttendanceRecord:
    """Tracks attendance patterns for an employee."""

    def __init__(self, employee_id: str) -> None:
        """Initialize attendance record.

        Args:
            employee_id: ID of employee
        """
        self.employee_id = employee_id
        self.late_arrivals = 0
        self.early_departures = 0
        self.absences = 0
        self.excused_absences = 0

    def record_late_arrival(self, minutes_late: int) -> None:
        """Record late arrival.

        Args:
            minutes_late: Minutes after expected start
        """
        if minutes_late > 0:
            self.late_arrivals += 1

    def record_early_departure(self, minutes_early: int) -> None:
        """Record early departure.

        Args:
            minutes_early: Minutes before expected end
        """
        if minutes_early > 0:
            self.early_departures += 1

    def record_absence(self, excused: bool = False) -> None:
        """Record absence.

        Args:
            excused: Whether absence is excused
        """
        self.absences += 1
        if excused:
            self.excused_absences += 1

    def unexcused_absences(self) -> int:
        """Get count of unexcused absences."""
        return self.absences - self.excused_absences


class ShiftSchedule:
    """Employee shift schedule."""

    def __init__(self, employee_id: str, shift_type: str, start_time: time, end_time: time) -> None:
        """Initialize shift schedule.

        Args:
            employee_id: ID of employee
            shift_type: Shift type (morning, evening, night, custom)
            start_time: Shift start time
            end_time: Shift end time
        """
        self.employee_id = employee_id
        self.shift_type = shift_type
        self.start_time = start_time
        self.end_time = end_time
        self.assignments: dict[date, bool] = {}  # date -> is_scheduled

    def assign_day(self, day: date) -> None:
        """Assign employee to work on date.

        Args:
            day: Date to assign
        """
        self.assignments[day] = True

    def unassign_day(self, day: date) -> None:
        """Remove assignment for date.

        Args:
            day: Date to remove
        """
        self.assignments[day] = False

    def is_scheduled(self, day: date) -> bool:
        """Check if scheduled for date.

        Args:
            day: Date to check

        Returns:
            True if scheduled
        """
        return self.assignments.get(day, False)


class TimeTrackingManager:
    """Manages time entry, timesheets, and attendance."""

    def __init__(self) -> None:
        """Initialize time tracking manager."""
        self.time_entries: dict[str, TimeEntry] = {}
        self.timesheets: dict[str, TimeSheet] = {}
        self.attendance: dict[str, AttendanceRecord] = {}
        self.schedules: dict[str, ShiftSchedule] = {}

    def clock_in(self, employee_id: str, clock_in_time: datetime) -> TimeEntry:
        """Record clock in time.

        Args:
            employee_id: ID of employee
            clock_in_time: Time of clock in

        Returns:
            The created TimeEntry
        """
        entry = TimeEntry(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            date=clock_in_time.date(),
            clock_in=clock_in_time,
        )

        self.time_entries[entry.id] = entry
        return entry

    def clock_out(
        self,
        time_entry_id: str,
        clock_out_time: datetime,
        break_minutes: int = 0,
    ) -> TimeEntry:
        """Record clock out time.

        Args:
            time_entry_id: ID of time entry
            clock_out_time: Time of clock out
            break_minutes: Minutes taken for breaks

        Returns:
            Updated TimeEntry

        Raises:
            TimeTrackingError: If entry not found
        """
        if time_entry_id not in self.time_entries:
            raise TimeTrackingError(f"Time entry {time_entry_id} not found")

        entry = self.time_entries[time_entry_id]
        entry.clock_out = clock_out_time
        entry.break_minutes = break_minutes

        return entry

    def get_day_entries(self, employee_id: str, day: date) -> list[TimeEntry]:
        """Get all time entries for employee on date.

        Args:
            employee_id: ID of employee
            day: Date to query

        Returns:
            List of time entries
        """
        return [e for e in self.time_entries.values() if e.employee_id == employee_id and e.date == day]

    def get_week_entries(self, employee_id: str, week_start: date) -> list[TimeEntry]:
        """Get all time entries for week.

        Args:
            employee_id: ID of employee
            week_start: Monday of week

        Returns:
            List of time entries
        """
        week_end = week_start + timedelta(days=6)
        return [
            e for e in self.time_entries.values() if e.employee_id == employee_id and week_start <= e.date <= week_end
        ]

    def create_timesheet(self, employee_id: str, week_start: date) -> TimeSheet:
        """Create a timesheet for employee/week.

        Args:
            employee_id: ID of employee
            week_start: Monday of week

        Returns:
            The created TimeSheet
        """
        timesheet = TimeSheet(employee_id, week_start)
        self.timesheets[timesheet.id] = timesheet

        # Auto-populate with time entries
        entries = self.get_week_entries(employee_id, week_start)
        for entry in entries:
            timesheet.add_entry(entry)

        return timesheet

    def submit_timesheet(self, timesheet_id: str) -> TimeSheet:
        """Submit timesheet for approval.

        Args:
            timesheet_id: ID of timesheet

        Returns:
            Updated TimeSheet

        Raises:
            TimeTrackingError: If timesheet not found
        """
        if timesheet_id not in self.timesheets:
            raise TimeTrackingError(f"Timesheet {timesheet_id} not found")

        timesheet = self.timesheets[timesheet_id]
        timesheet.submit()
        return timesheet

    def approve_timesheet(self, timesheet_id: str, approver_id: str) -> TimeSheet:
        """Approve timesheet.

        Args:
            timesheet_id: ID of timesheet
            approver_id: ID of approver

        Returns:
            Updated TimeSheet

        Raises:
            TimeTrackingError: If timesheet not found
        """
        if timesheet_id not in self.timesheets:
            raise TimeTrackingError(f"Timesheet {timesheet_id} not found")

        timesheet = self.timesheets[timesheet_id]
        timesheet.approve(approver_id)
        return timesheet

    def detect_overtime(self, employee_id: str, week_start: date) -> tuple[Decimal, bool]:
        """Detect overtime hours in a week.

        Args:
            employee_id: ID of employee
            week_start: Monday of week

        Returns:
            Tuple of (overtime_hours, requires_approval)
        """
        entries = self.get_week_entries(employee_id, week_start)
        total_hours = sum(entry.hours_worked() for entry in entries)
        standard_hours = Decimal("40")

        overtime = max(Decimal("0"), total_hours - standard_hours)
        requires_approval = overtime > Decimal("0")

        return (overtime, requires_approval)

    def get_attendance_pattern(
        self,
        employee_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, any]:
        """Analyze attendance pattern over period.

        Args:
            employee_id: ID of employee
            start_date: Start of period
            end_date: End of period

        Returns:
            Attendance statistics dictionary
        """
        entries = [
            e for e in self.time_entries.values() if e.employee_id == employee_id and start_date <= e.date <= end_date
        ]

        total_days = (end_date - start_date).days + 1
        worked_days = len(set(e.date for e in entries))
        total_hours = sum(e.hours_worked() for e in entries)

        # Calculate average hours per day worked
        avg_hours = total_hours / Decimal(str(worked_days)) if worked_days > 0 else Decimal("0")

        return {
            "total_days": total_days,
            "worked_days": worked_days,
            "absent_days": total_days - worked_days,
            "total_hours": total_hours.quantize(Decimal("0.01")),
            "average_hours_per_day": avg_hours.quantize(Decimal("0.01")),
        }

    def set_shift_schedule(
        self,
        employee_id: str,
        shift_type: str,
        start_time: time,
        end_time: time,
    ) -> ShiftSchedule:
        """Set shift schedule for employee.

        Args:
            employee_id: ID of employee
            shift_type: Shift type
            start_time: Start time
            end_time: End time

        Returns:
            The created ShiftSchedule
        """
        schedule = ShiftSchedule(employee_id, shift_type, start_time, end_time)
        self.schedules[employee_id] = schedule
        return schedule

    def get_schedule(self, employee_id: str) -> ShiftSchedule | None:
        """Get shift schedule for employee.

        Args:
            employee_id: ID of employee

        Returns:
            ShiftSchedule or None if not set
        """
        return self.schedules.get(employee_id)

    def calculate_payroll_hours(self, employee_id: str, pay_period_start: date, pay_period_end: date) -> Decimal:
        """Calculate total hours for payroll.

        Args:
            employee_id: ID of employee
            pay_period_start: Start of period
            pay_period_end: End of period

        Returns:
            Total hours worked
        """
        entries = [
            e
            for e in self.time_entries.values()
            if e.employee_id == employee_id and pay_period_start <= e.date <= pay_period_end
        ]
        return sum(e.hours_worked() for e in entries)

    def get_billable_report(
        self,
        employee_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Decimal]:
        """Generate billable hours report by project.

        Args:
            employee_id: ID of employee
            start_date: Start of period
            end_date: End of period

        Returns:
            Dictionary of project_id -> billable_hours
        """
        entries = [
            e
            for e in self.time_entries.values()
            if (e.employee_id == employee_id and e.billable and start_date <= e.date <= end_date)
        ]

        report: dict[str, Decimal] = {}
        for entry in entries:
            project_id = entry.project_id or "unassigned"
            report[project_id] = report.get(project_id, Decimal("0")) + entry.hours_worked()

        return report

    def get_leave_integration_hours(
        self,
        employee_id: str,
        start_date: date,
        end_date: date,
    ) -> Decimal:
        """Calculate hours that should come from leave balance.

        Args:
            employee_id: ID of employee
            start_date: Start of period
            end_date: End of period

        Returns:
            Hours from leave (absence - actual clock entries)
        """
        # Get scheduled hours
        scheduled_entries = [
            e for e in self.time_entries.values() if e.employee_id == employee_id and start_date <= e.date <= end_date
        ]

        total_scheduled = Decimal("40") * Decimal(str((end_date - start_date).days // 7 + 1))
        actual_hours = sum(e.hours_worked() for e in scheduled_entries)

        # Hours that should be covered by leave
        return max(Decimal("0"), total_scheduled - actual_hours)
