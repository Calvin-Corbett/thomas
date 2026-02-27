"""Tests for deadline management module."""

from datetime import date, timedelta

import pytest

from thomas.legal._exceptions import DeadlineCalculationError
from thomas.legal.deadlines import DeadlineManager


class TestDeadlineManager:
    """Test suite for DeadlineManager."""

    @pytest.fixture
    def manager(self) -> DeadlineManager:
        """Create a DeadlineManager instance."""
        return DeadlineManager()

    def test_create_deadline(self, manager: DeadlineManager) -> None:
        """Test creating a custom deadline."""
        due_date = date.today() + timedelta(days=30)

        deadline = manager.create_deadline(
            case_id="case_001",
            description="Respond to interrogatories",
            due_date=due_date,
            deadline_type="discovery_response",
            importance=4,
        )

        assert deadline.deadline_id in manager.deadlines
        assert deadline.due_date == due_date
        assert deadline.case_id == "case_001"

    def test_deadline_from_court_rule(self, manager: DeadlineManager) -> None:
        """Test creating deadline from court rules."""
        triggering_date = date.today()

        # Federal: response to complaint is 21 days
        deadline = manager.create_deadline_from_rule(
            case_id="case_001",
            description="Answer complaint",
            deadline_type="response_to_complaint",
            triggering_event_date=triggering_date,
            jurisdiction="federal",
        )

        # Should be 21 business days later
        expected_date = manager._add_business_days(triggering_date, 21)
        assert deadline.due_date == expected_date

    def test_court_rule_validation(self, manager: DeadlineManager) -> None:
        """Test validation of court rules."""
        # Invalid jurisdiction
        with pytest.raises(DeadlineCalculationError):
            manager.create_deadline_from_rule(
                case_id="case_001",
                description="Test",
                deadline_type="response_to_complaint",
                triggering_event_date=date.today(),
                jurisdiction="invalid",
            )

        # Invalid deadline type
        with pytest.raises(DeadlineCalculationError):
            manager.create_deadline_from_rule(
                case_id="case_001",
                description="Test",
                deadline_type="invalid_type",
                triggering_event_date=date.today(),
                jurisdiction="federal",
            )

    def test_business_day_calculation(self, manager: DeadlineManager) -> None:
        """Test business day calculation skipping weekends."""
        start = date(2024, 1, 1)  # Monday

        # Add 1 business day (should be Tuesday)
        result = manager._add_business_days(start, 1)
        assert result == date(2024, 1, 2)

        # Add 5 business days from Monday (should skip weekend)
        result = manager._add_business_days(start, 5)
        assert result.weekday() <= 4  # Monday-Friday

    def test_add_dependent_deadline(self, manager: DeadlineManager) -> None:
        """Test linking dependent deadlines."""
        due_date = date.today() + timedelta(days=30)

        parent = manager.create_deadline(
            case_id="case_001",
            description="Discovery responses due",
            due_date=due_date,
            deadline_type="discovery_response",
            importance=4,
        )

        due_date_2 = due_date + timedelta(days=14)

        child = manager.create_deadline(
            case_id="case_001",
            description="Expert reports due",
            due_date=due_date_2,
            deadline_type="expert_report",
            importance=4,
        )

        manager.add_dependent_deadline(parent.deadline_id, child.deadline_id)

        assert child.deadline_id in parent.dependent_deadlines

    def test_get_overdue_deadlines(self, manager: DeadlineManager) -> None:
        """Test retrieving overdue deadlines."""
        # Create past deadline
        past_date = date.today() - timedelta(days=5)
        past_deadline = manager.create_deadline(
            case_id="case_001",
            description="Overdue deadline",
            due_date=past_date,
            deadline_type="filing",
            importance=5,
        )

        # Create future deadline
        future_date = date.today() + timedelta(days=5)
        future_deadline = manager.create_deadline(
            case_id="case_001",
            description="Future deadline",
            due_date=future_date,
            deadline_type="filing",
            importance=3,
        )

        overdue = manager.get_overdue_deadlines()

        assert len(overdue) == 1
        assert overdue[0].deadline_id == past_deadline.deadline_id

    def test_get_deadlines_for_case(self, manager: DeadlineManager) -> None:
        """Test retrieving deadlines for a specific case."""
        case1_deadline = manager.create_deadline(
            case_id="case_001",
            description="Case 1 deadline",
            due_date=date.today() + timedelta(days=10),
            deadline_type="filing",
            importance=3,
        )

        case2_deadline = manager.create_deadline(
            case_id="case_002",
            description="Case 2 deadline",
            due_date=date.today() + timedelta(days=20),
            deadline_type="filing",
            importance=3,
        )

        case1_deadlines = manager.get_deadlines_for_case("case_001")

        assert len(case1_deadlines) == 1
        assert case1_deadlines[0].deadline_id == case1_deadline.deadline_id

    def test_get_upcoming_deadlines(self, manager: DeadlineManager) -> None:
        """Test retrieving upcoming deadlines within threshold."""
        # Create deadline 15 days away
        deadline_15 = manager.create_deadline(
            case_id="case_001",
            description="15 days away",
            due_date=date.today() + timedelta(days=15),
            deadline_type="filing",
            importance=3,
        )

        # Create deadline 60 days away
        deadline_60 = manager.create_deadline(
            case_id="case_001",
            description="60 days away",
            due_date=date.today() + timedelta(days=60),
            deadline_type="filing",
            importance=3,
        )

        # Get deadlines within 30 days
        upcoming = manager.get_upcoming_deadlines(days=30)

        assert len(upcoming) == 1
        assert upcoming[0].deadline_id == deadline_15.deadline_id

    def test_deadline_risk_scoring(self, manager: DeadlineManager) -> None:
        """Test deadline risk score calculation."""
        deadline = manager.create_deadline(
            case_id="case_001",
            description="Test deadline",
            due_date=date.today() + timedelta(days=3),
            deadline_type="filing",
            importance=5,
        )

        risk = manager.calculate_deadline_risk(deadline.deadline_id)

        # Risk = (5 - days_remaining) * importance
        # = (5 - 3) * 5 = 10
        assert risk == 10

    def test_get_reminders_due(self, manager: DeadlineManager) -> None:
        """Test retrieving reminders due today."""
        today = date.today()

        deadline = manager.create_deadline(
            case_id="case_001",
            description="Test deadline",
            due_date=today + timedelta(days=1),
            deadline_type="filing",
            importance=3,
        )

        reminders = manager.get_reminders_due()

        # Should have reminders scheduled
        assert isinstance(reminders, list)

    def test_mark_deadline_complete(self, manager: DeadlineManager) -> None:
        """Test marking deadline as completed."""
        deadline = manager.create_deadline(
            case_id="case_001",
            description="Test deadline",
            due_date=date.today() + timedelta(days=10),
            deadline_type="filing",
            importance=3,
        )

        updated = manager.mark_deadline_complete(deadline.deadline_id)

        assert updated.marked_complete is True

    def test_export_to_ical(self, manager: DeadlineManager) -> None:
        """Test exporting deadlines to iCalendar format."""
        manager.create_deadline(
            case_id="case_001",
            description="Filing deadline",
            due_date=date.today() + timedelta(days=30),
            deadline_type="filing",
            importance=4,
        )

        ical = manager.export_to_ical(case_id="case_001")

        assert "BEGIN:VCALENDAR" in ical
        assert "END:VCALENDAR" in ical
        assert "BEGIN:VEVENT" in ical
        assert "Filing deadline" in ical

    def test_jurisdiction_court_rules(self, manager: DeadlineManager) -> None:
        """Test different court rule sets by jurisdiction."""
        start_date = date.today()

        # Federal: 21 days for response
        fed_deadline = manager.create_deadline_from_rule(
            case_id="case_001",
            description="Federal response",
            deadline_type="response_to_complaint",
            triggering_event_date=start_date,
            jurisdiction="federal",
        )

        # State civil: 30 days for response
        state_deadline = manager.create_deadline_from_rule(
            case_id="case_001",
            description="State response",
            deadline_type="response_to_complaint",
            triggering_event_date=start_date,
            jurisdiction="state_civil",
        )

        # State deadline should be later
        assert state_deadline.due_date > fed_deadline.due_date

    def test_reminder_schedule(self, manager: DeadlineManager) -> None:
        """Test reminder scheduling."""
        due_date = date.today() + timedelta(days=30)

        deadline = manager.create_deadline(
            case_id="case_001",
            description="Test deadline",
            due_date=due_date,
            deadline_type="filing",
            importance=3,
        )

        reminder = manager.reminders[deadline.deadline_id]

        # Should have reminders at multiple intervals
        assert len(reminder.reminder_dates) > 0
        assert 30 in reminder.reminder_dates
        assert 1 in reminder.reminder_dates
