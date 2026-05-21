"""Leave management system with accrual, requests, and balance tracking."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from thomas.marketplace.hr_platform._exceptions import LeaveBalanceError
from thomas.marketplace.hr_platform._types import Employee, LeaveRequest, LeaveType


class LeaveBalance:
    """Tracks leave balance for an employee."""

    def __init__(
        self,
        employee_id: str,
        leave_type: LeaveType,
        balance: Decimal,
        accrual_rate: Decimal,
        carry_over_cap: Decimal = Decimal("40"),
        use_it_or_lose_it: bool = False,
    ) -> None:
        """Initialize leave balance.

        Args:
            employee_id: ID of employee
            leave_type: Type of leave
            balance: Current leave balance
            accrual_rate: Hours accrued per pay period
            carry_over_cap: Maximum carryover hours (remaining forfeit)
            use_it_or_lose_it: If True, unused balance is lost at year end
        """
        self.employee_id = employee_id
        self.leave_type = leave_type
        self.balance = balance
        self.accrual_rate = accrual_rate
        self.carry_over_cap = carry_over_cap
        self.use_it_or_lose_it = use_it_or_lose_it
        self.year = date.today().year

    def accrue(self) -> None:
        """Accrue one pay period of leave."""
        self.balance += self.accrual_rate

    def deduct(self, hours: Decimal) -> None:
        """Deduct hours from balance.

        Raises:
            LeaveBalanceError: If insufficient balance
        """
        if hours > self.balance:
            raise LeaveBalanceError(f"Insufficient balance: {self.balance} available, {hours} requested")
        self.balance -= hours

    def reset_year(self) -> None:
        """Reset balance at year end with carryover rules."""
        if self.use_it_or_lose_it:
            self.balance = Decimal("0")
        else:
            # Cap carryover
            if self.balance > self.carry_over_cap:
                self.balance = self.carry_over_cap
        self.year = date.today().year


class BlackoutDate:
    """Blackout dates when leave cannot be taken."""

    def __init__(self, name: str, start_date: date, end_date: date) -> None:
        """Initialize blackout date.

        Args:
            name: Name of blackout period
            start_date: Start of blackout
            end_date: End of blackout
        """
        self.name = name
        self.start_date = start_date
        self.end_date = end_date

    def is_blackout(self, check_date: date) -> bool:
        """Check if date falls within blackout period."""
        return self.start_date <= check_date <= self.end_date


class LeaveManager:
    """Manages leave requests, accrual, and balance tracking."""

    def __init__(self) -> None:
        """Initialize leave manager."""
        self.balances: dict[tuple[str, LeaveType], LeaveBalance] = {}
        self.requests: dict[str, LeaveRequest] = {}
        self.blackout_dates: dict[str, BlackoutDate] = {}

    def initialize_employee_leave(
        self,
        employee: Employee,
        leave_type: LeaveType,
        initial_balance: Decimal,
        accrual_rate: Decimal,
    ) -> LeaveBalance:
        """Initialize leave balance for new employee.

        Args:
            employee: Employee object
            leave_type: Type of leave
            initial_balance: Starting balance (usually 0)
            accrual_rate: Hours accrued per pay period

        Returns:
            The created LeaveBalance
        """
        key = (employee.id, leave_type)
        balance = LeaveBalance(employee.id, leave_type, initial_balance, accrual_rate)
        self.balances[key] = balance
        return balance

    def get_balance(self, employee_id: str, leave_type: LeaveType) -> LeaveBalance | None:
        """Get leave balance for employee and type.

        Args:
            employee_id: ID of employee
            leave_type: Type of leave

        Returns:
            LeaveBalance or None if not initialized
        """
        return self.balances.get((employee_id, leave_type))

    def get_all_balances(self, employee_id: str) -> dict[LeaveType, LeaveBalance]:
        """Get all leave balances for an employee.

        Args:
            employee_id: ID of employee

        Returns:
            Dictionary of leave_type -> balance
        """
        return {leave_type: balance for (emp_id, leave_type), balance in self.balances.items() if emp_id == employee_id}

    def request_leave(
        self,
        employee_id: str,
        leave_type: LeaveType,
        start_date: date,
        end_date: date,
        reason: str = "",
    ) -> LeaveRequest:
        """Submit a leave request.

        Args:
            employee_id: ID of requesting employee
            leave_type: Type of leave
            start_date: First day of leave
            end_date: Last day of leave
            reason: Reason for leave

        Returns:
            The created LeaveRequest

        Raises:
            LeaveBalanceError: If no balance initialized for this type
        """
        key = (employee_id, leave_type)
        if key not in self.balances:
            raise LeaveBalanceError(f"No {leave_type.value} balance for employee {employee_id}")

        # Calculate business days requested
        days_requested = self._calculate_business_days(start_date, end_date)

        request = LeaveRequest(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            days_requested=days_requested,
            reason=reason,
        )

        self.requests[request.id] = request
        return request

    def approve_leave(self, request_id: str, approver_id: str) -> LeaveRequest:
        """Approve a leave request.

        Args:
            request_id: ID of leave request
            approver_id: ID of approver

        Returns:
            Updated LeaveRequest

        Raises:
            LeaveBalanceError: If request not found or insufficient balance
        """
        if request_id not in self.requests:
            raise LeaveBalanceError(f"Leave request {request_id} not found")

        request = self.requests[request_id]
        balance = self.get_balance(request.employee_id, request.leave_type)

        if balance is None:
            raise LeaveBalanceError("No leave balance for this type")

        if request.days_requested > balance.balance:
            raise LeaveBalanceError(
                f"Insufficient balance: {balance.balance} available, {request.days_requested} requested"
            )

        request.status = "approved"
        request.approver_id = approver_id
        return request

    def deny_leave(self, request_id: str, approver_id: str) -> LeaveRequest:
        """Deny a leave request.

        Args:
            request_id: ID of leave request
            approver_id: ID of approver

        Returns:
            Updated LeaveRequest

        Raises:
            LeaveBalanceError: If request not found
        """
        if request_id not in self.requests:
            raise LeaveBalanceError(f"Leave request {request_id} not found")

        request = self.requests[request_id]
        request.status = "rejected"
        request.approver_id = approver_id
        return request

    def take_leave(self, request_id: str) -> LeaveRequest:
        """Mark approved leave as taken (deduct from balance).

        Args:
            request_id: ID of leave request

        Returns:
            Updated LeaveRequest

        Raises:
            LeaveBalanceError: If request not found or not approved
        """
        if request_id not in self.requests:
            raise LeaveBalanceError(f"Leave request {request_id} not found")

        request = self.requests[request_id]
        if request.status != "approved":
            raise LeaveBalanceError(f"Leave request must be approved before taking (current: {request.status})")

        balance = self.get_balance(request.employee_id, request.leave_type)
        if balance:
            balance.deduct(request.days_requested)

        request.status = "taken"
        return request

    def cancel_leave(self, request_id: str) -> LeaveRequest:
        """Cancel a leave request.

        Args:
            request_id: ID of leave request

        Returns:
            Updated LeaveRequest

        Raises:
            LeaveBalanceError: If request not found
        """
        if request_id not in self.requests:
            raise LeaveBalanceError(f"Leave request {request_id} not found")

        request = self.requests[request_id]
        request.status = "cancelled"
        return request

    def accrue_leave(self, employee_id: str) -> dict[LeaveType, Decimal]:
        """Process one pay period's leave accrual for employee.

        Args:
            employee_id: ID of employee

        Returns:
            Dictionary of leave_type -> new_balance
        """
        accrued: dict[LeaveType, Decimal] = {}

        for (emp_id, leave_type), balance in self.balances.items():
            if emp_id == employee_id:
                balance.accrue()
                accrued[leave_type] = balance.balance

        return accrued

    def check_blackout_conflict(self, start_date: date, end_date: date) -> BlackoutDate | None:
        """Check if leave dates conflict with blackout dates.

        Args:
            start_date: Start of requested leave
            end_date: End of requested leave

        Returns:
            Conflicting BlackoutDate or None
        """
        for blackout in self.blackout_dates.values():
            # Check for overlap
            if not (end_date < blackout.start_date or start_date > blackout.end_date):
                return blackout
        return None

    def add_blackout_date(self, name: str, start_date: date, end_date: date) -> BlackoutDate:
        """Add a blackout date when leave cannot be taken.

        Args:
            name: Name of blackout period
            start_date: Start date
            end_date: End date

        Returns:
            The created BlackoutDate
        """
        blackout_id = str(uuid.uuid4())
        blackout = BlackoutDate(name, start_date, end_date)
        self.blackout_dates[blackout_id] = blackout
        return blackout

    def get_team_leave_calendar(
        self,
        team_member_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, list[tuple[date, date]]]:
        """Get leave calendar for team showing who's out when.

        Args:
            team_member_ids: IDs of team members
            start_date: Start of calendar period
            end_date: End of calendar period

        Returns:
            Dictionary of employee_id -> list of (start, end) leave periods
        """
        calendar: dict[str, list[tuple[date, date]]] = {emp_id: [] for emp_id in team_member_ids}

        for request in self.requests.values():
            if (
                request.employee_id in team_member_ids
                and request.status == "taken"
                and not (request.end_date < start_date or request.start_date > end_date)
            ):
                calendar[request.employee_id].append((request.start_date, request.end_date))

        return calendar

    def get_fmla_tracking(self, employee_id: str, year: int) -> dict[str, any]:
        """Track FMLA (Family Medical Leave Act) usage.

        Args:
            employee_id: ID of employee
            year: Year to check (FMLA resets annually)

        Returns:
            Dictionary with FMLA usage info
        """
        fmla_types = [LeaveType.PARENTAL, LeaveType.MEDICAL]
        fmla_hours = Decimal("0")
        fmla_limit = Decimal("480")  # 12 weeks * 40 hours

        for request in self.requests.values():
            if (
                request.employee_id == employee_id
                and request.leave_type in fmla_types
                and request.status == "taken"
                and request.start_date.year == year
            ):
                fmla_hours += request.days_requested * Decimal("8")  # Assume 8-hour days

        return {
            "hours_used": fmla_hours,
            "hours_available": max(Decimal("0"), fmla_limit - fmla_hours),
            "percent_used": (fmla_hours / fmla_limit * Decimal("100")).quantize(Decimal("0.01")),
            "year": year,
        }

    @staticmethod
    def _calculate_business_days(start_date: date, end_date: date) -> Decimal:
        """Calculate business days between two dates.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            Number of business days
        """
        business_days = 0
        current = start_date

        while current <= end_date:
            # Monday = 0, Sunday = 6
            if current.weekday() < 5:  # Monday-Friday
                business_days += 1
            current += timedelta(days=1)

        return Decimal(str(business_days))

    def get_leave_history(self, employee_id: str, start_date: date | None = None) -> list[LeaveRequest]:
        """Get historical leave requests for employee.

        Args:
            employee_id: ID of employee
            start_date: Optional start date for filtering

        Returns:
            Sorted list of leave requests
        """
        requests = [
            r
            for r in self.requests.values()
            if r.employee_id == employee_id and (start_date is None or r.start_date >= start_date)
        ]
        requests.sort(key=lambda x: x.start_date)
        return requests
