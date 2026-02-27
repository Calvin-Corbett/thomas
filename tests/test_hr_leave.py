"""Tests for leave management system."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.hr_platform._exceptions import LeaveBalanceError
from thomas.hr_platform._types import Employee, LeaveType
from thomas.hr_platform.leave import LeaveBalance, LeaveManager


class TestLeaveManager:
    """Test leave management functionality."""

    @pytest.fixture
    def manager(self) -> LeaveManager:
        """Create leave manager."""
        return LeaveManager()

    @pytest.fixture
    def employee(self) -> Employee:
        """Create test employee."""
        return Employee(
            id="emp1",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            phone="555-1234",
            ssn="123-45-6789",
            date_of_birth=date(1990, 1, 15),
            gender="M",
            position_id="pos1",
            department_id="dept1",
            salary=Decimal("100000"),
        )

    def test_initialize_employee_leave(self, manager: LeaveManager, employee: Employee) -> None:
        """Test initializing leave for new employee."""
        balance = manager.initialize_employee_leave(
            employee,
            LeaveType.VACATION,
            Decimal("0"),
            Decimal("6.67"),  # 80 hours/year biweekly
        )

        assert balance.employee_id == employee.id
        assert balance.leave_type == LeaveType.VACATION
        assert balance.balance == Decimal("0")
        assert balance.accrual_rate == Decimal("6.67")

    def test_request_leave(self, manager: LeaveManager, employee: Employee) -> None:
        """Test submitting leave request."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))

        request = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 6, 1),
            date(2024, 6, 7),
            "Summer vacation",
        )

        assert request.employee_id == employee.id
        assert request.leave_type == LeaveType.VACATION
        assert request.start_date == date(2024, 6, 1)
        assert request.status == "requested"

    def test_approve_leave(self, manager: LeaveManager, employee: Employee) -> None:
        """Test approving leave request."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))

        request = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 6, 1),
            date(2024, 6, 7),
        )

        approved = manager.approve_leave(request.id, "mgr1")

        assert approved.status == "approved"
        assert approved.approver_id == "mgr1"

    def test_deny_leave(self, manager: LeaveManager, employee: Employee) -> None:
        """Test denying leave request."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))

        request = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 6, 1),
            date(2024, 6, 7),
        )

        denied = manager.deny_leave(request.id, "mgr1")

        assert denied.status == "rejected"
        assert denied.approver_id == "mgr1"

    def test_take_leave(self, manager: LeaveManager, employee: Employee) -> None:
        """Test marking leave as taken."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))

        request = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 6, 1),
            date(2024, 6, 7),
        )

        manager.approve_leave(request.id, "mgr1")
        taken = manager.take_leave(request.id)

        assert taken.status == "taken"

        # Balance should be deducted
        balance = manager.get_balance(employee.id, LeaveType.VACATION)
        assert balance is not None
        assert balance.balance < Decimal("40")

    def test_insufficient_balance(self, manager: LeaveManager, employee: Employee) -> None:
        """Test error when insufficient balance."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("5"), Decimal("6.67"))

        request = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2026, 6, 1),  # Monday
            date(2026, 6, 12),  # 10 business days
        )

        with pytest.raises(LeaveBalanceError):
            manager.approve_leave(request.id, "mgr1")

    def test_accrue_leave(self, manager: LeaveManager, employee: Employee) -> None:
        """Test leave accrual."""
        balance = manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("0"), Decimal("6.67"))

        initial = balance.balance
        manager.accrue_leave(employee.id)

        updated = manager.get_balance(employee.id, LeaveType.VACATION)
        assert updated is not None
        assert updated.balance == initial + Decimal("6.67")

    def test_leave_balance_deduction(self, manager: LeaveManager) -> None:
        """Test deducting from leave balance."""
        balance = LeaveBalance(
            "emp1",
            LeaveType.VACATION,
            Decimal("40"),
            Decimal("6.67"),
        )

        balance.deduct(Decimal("8"))

        assert balance.balance == Decimal("32")

    def test_balance_insufficient_deduction(self) -> None:
        """Test error when deducting more than balance."""
        balance = LeaveBalance(
            "emp1",
            LeaveType.VACATION,
            Decimal("10"),
            Decimal("6.67"),
        )

        with pytest.raises(LeaveBalanceError):
            balance.deduct(Decimal("20"))

    def test_blackout_dates(self, manager: LeaveManager) -> None:
        """Test blackout date functionality."""
        blackout = manager.add_blackout_date(
            "Year End",
            date(2024, 12, 20),
            date(2024, 12, 31),
        )

        conflict = manager.check_blackout_conflict(
            date(2024, 12, 25),
            date(2024, 12, 26),
        )

        assert conflict is not None
        assert conflict.name == "Year End"

    def test_no_blackout_conflict(self, manager: LeaveManager) -> None:
        """Test when no blackout conflict exists."""
        manager.add_blackout_date(
            "Year End",
            date(2024, 12, 20),
            date(2024, 12, 31),
        )

        conflict = manager.check_blackout_conflict(
            date(2024, 6, 1),
            date(2024, 6, 7),
        )

        assert conflict is None

    def test_cancel_leave(self, manager: LeaveManager, employee: Employee) -> None:
        """Test canceling leave request."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))

        request = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 6, 1),
            date(2024, 6, 7),
        )

        cancelled = manager.cancel_leave(request.id)

        assert cancelled.status == "cancelled"

    def test_team_leave_calendar(self, manager: LeaveManager, employee: Employee) -> None:
        """Test team leave calendar."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))

        request = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 6, 1),
            date(2024, 6, 7),
        )

        manager.approve_leave(request.id, "mgr1")
        manager.take_leave(request.id)

        calendar = manager.get_team_leave_calendar(
            ["emp1"],
            date(2024, 6, 1),
            date(2024, 6, 30),
        )

        assert "emp1" in calendar
        assert len(calendar["emp1"]) > 0

    def test_fmla_tracking(self, manager: LeaveManager, employee: Employee) -> None:
        """Test FMLA tracking."""
        manager.initialize_employee_leave(employee, LeaveType.PARENTAL, Decimal("160"), Decimal("0"))

        request = manager.request_leave(
            employee.id,
            LeaveType.PARENTAL,
            date(2024, 6, 1),
            date(2024, 6, 14),
        )

        manager.approve_leave(request.id, "mgr1")
        manager.take_leave(request.id)

        fmla = manager.get_fmla_tracking(employee.id, 2024)

        assert fmla["hours_used"] > Decimal("0")
        assert fmla["hours_available"] < Decimal("480")

    def test_leave_history(self, manager: LeaveManager, employee: Employee) -> None:
        """Test leave history retrieval."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))

        req1 = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 6, 1),
            date(2024, 6, 7),
        )

        req2 = manager.request_leave(
            employee.id,
            LeaveType.VACATION,
            date(2024, 7, 1),
            date(2024, 7, 7),
        )

        history = manager.get_leave_history(employee.id)

        assert len(history) >= 2

    def test_multiple_leave_types(self, manager: LeaveManager, employee: Employee) -> None:
        """Test managing multiple leave types."""
        manager.initialize_employee_leave(employee, LeaveType.VACATION, Decimal("40"), Decimal("6.67"))
        manager.initialize_employee_leave(employee, LeaveType.SICK, Decimal("20"), Decimal("3.33"))

        balances = manager.get_all_balances(employee.id)

        assert len(balances) == 2
        assert LeaveType.VACATION in balances
        assert LeaveType.SICK in balances

    def test_business_days_calculation(self) -> None:
        """Test business day calculation."""
        # Monday to Friday = 5 business days
        days = LeaveManager._calculate_business_days(
            date(2024, 6, 3),  # Monday
            date(2024, 6, 7),  # Friday
        )

        assert days == Decimal("5")

    def test_business_days_with_weekend(self) -> None:
        """Test business days across weekend."""
        # Monday to Monday = 6 business days (skip weekend)
        days = LeaveManager._calculate_business_days(
            date(2024, 6, 3),  # Monday
            date(2024, 6, 10),  # Monday
        )

        assert days == Decimal("6")

    def test_carryover_cap(self) -> None:
        """Test leave carryover cap."""
        balance = LeaveBalance(
            "emp1",
            LeaveType.VACATION,
            Decimal("50"),  # Over cap
            Decimal("6.67"),
            carry_over_cap=Decimal("40"),
        )

        balance.reset_year()

        assert balance.balance == Decimal("40")
