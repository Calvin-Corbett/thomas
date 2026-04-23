"""Employee management system with lifecycle, org chart, and analytics."""

import difflib
from datetime import date, datetime, timedelta

from thomas.marketplace.hr_platform._exceptions import EmployeeNotFoundError
from thomas.marketplace.hr_platform._types import (
    Department,
    Employee,
    EmploymentStatus,
    Position,
)


class EmployeeManager:
    """Manages employee lifecycle, org structure, and directory."""

    def __init__(self) -> None:
        """Initialize employee manager."""
        self.employees: dict[str, Employee] = {}
        self.departments: dict[str, Department] = {}
        self.positions: dict[str, Position] = {}

    def add_department(self, department: Department) -> Department:
        """Add a new department.

        Args:
            department: Department object to add

        Returns:
            The added department

        Raises:
            ValueError: If department ID already exists
        """
        if department.id in self.departments:
            raise ValueError(f"Department {department.id} already exists")
        self.departments[department.id] = department
        return department

    def add_position(self, position: Position) -> Position:
        """Add a new position.

        Args:
            position: Position object to add

        Returns:
            The added position

        Raises:
            ValueError: If position ID already exists or department doesn't exist
        """
        if position.id in self.positions:
            raise ValueError(f"Position {position.id} already exists")
        if position.department_id not in self.departments:
            raise ValueError(f"Department {position.department_id} not found")
        self.positions[position.id] = position
        return position

    def hire_employee(self, employee: Employee) -> Employee:
        """Hire a new employee (set status to HIRED).

        Args:
            employee: Employee to hire

        Returns:
            The hired employee

        Raises:
            ValueError: If employee already exists or position doesn't exist
        """
        if employee.id in self.employees:
            raise ValueError(f"Employee {employee.id} already exists")
        if employee.position_id not in self.positions:
            raise ValueError(f"Position {employee.position_id} not found")
        if employee.department_id not in self.departments:
            raise ValueError(f"Department {employee.department_id} not found")

        employee.status = EmploymentStatus.HIRED
        self.employees[employee.id] = employee
        return employee

    def activate_employee(self, employee_id: str) -> Employee:
        """Activate hired employee to ACTIVE status.

        Args:
            employee_id: ID of employee to activate

        Returns:
            The activated employee

        Raises:
            EmployeeNotFoundError: If employee not found
        """
        if employee_id not in self.employees:
            raise EmployeeNotFoundError(employee_id)

        employee = self.employees[employee_id]
        employee.status = EmploymentStatus.ACTIVE
        employee.updated_at = datetime.now()
        return employee

    def terminate_employee(self, employee_id: str, termination_date: date | None = None) -> Employee:
        """Terminate an employee.

        Args:
            employee_id: ID of employee to terminate
            termination_date: Date of termination (defaults to today)

        Returns:
            The terminated employee

        Raises:
            EmployeeNotFoundError: If employee not found
        """
        if employee_id not in self.employees:
            raise EmployeeNotFoundError(employee_id)

        employee = self.employees[employee_id]
        if termination_date is None:
            termination_date = date.today()

        employee.status = EmploymentStatus.TERMINATED
        employee.termination_date = termination_date
        employee.updated_at = datetime.now()
        return employee

    def set_on_leave(self, employee_id: str) -> Employee:
        """Set employee status to ON_LEAVE.

        Args:
            employee_id: ID of employee

        Returns:
            The employee with updated status

        Raises:
            EmployeeNotFoundError: If employee not found
        """
        if employee_id not in self.employees:
            raise EmployeeNotFoundError(employee_id)

        employee = self.employees[employee_id]
        employee.status = EmploymentStatus.ON_LEAVE
        employee.updated_at = datetime.now()
        return employee

    def return_from_leave(self, employee_id: str) -> Employee:
        """Return employee from leave to ACTIVE status.

        Args:
            employee_id: ID of employee

        Returns:
            The employee with updated status

        Raises:
            EmployeeNotFoundError: If employee not found
        """
        if employee_id not in self.employees:
            raise EmployeeNotFoundError(employee_id)

        employee = self.employees[employee_id]
        employee.status = EmploymentStatus.ACTIVE
        employee.updated_at = datetime.now()
        return employee

    def move_to_alumni(self, employee_id: str) -> Employee:
        """Move terminated employee to ALUMNI status.

        Args:
            employee_id: ID of employee

        Returns:
            The employee with updated status

        Raises:
            EmployeeNotFoundError: If employee not found
        """
        if employee_id not in self.employees:
            raise EmployeeNotFoundError(employee_id)

        employee = self.employees[employee_id]
        employee.status = EmploymentStatus.ALUMNI
        employee.updated_at = datetime.now()
        return employee

    def transfer_employee(self, employee_id: str, new_department_id: str, new_position_id: str) -> Employee:
        """Transfer employee to different department and position.

        Args:
            employee_id: ID of employee to transfer
            new_department_id: Target department ID
            new_position_id: Target position ID

        Returns:
            The transferred employee

        Raises:
            EmployeeNotFoundError: If employee not found
            ValueError: If department or position not found
        """
        if employee_id not in self.employees:
            raise EmployeeNotFoundError(employee_id)
        if new_department_id not in self.departments:
            raise ValueError(f"Department {new_department_id} not found")
        if new_position_id not in self.positions:
            raise ValueError(f"Position {new_position_id} not found")

        employee = self.employees[employee_id]
        employee.department_id = new_department_id
        employee.position_id = new_position_id
        employee.updated_at = datetime.now()
        return employee

    def get_employee(self, employee_id: str) -> Employee:
        """Get employee by ID.

        Args:
            employee_id: ID of employee

        Returns:
            The employee

        Raises:
            EmployeeNotFoundError: If employee not found
        """
        if employee_id not in self.employees:
            raise EmployeeNotFoundError(employee_id)
        return self.employees[employee_id]

    def get_employees_by_department(self, department_id: str) -> list[Employee]:
        """Get all employees in a department.

        Args:
            department_id: ID of department

        Returns:
            List of employees in the department
        """
        return [emp for emp in self.employees.values() if emp.department_id == department_id]

    def get_employees_by_manager(self, manager_id: str) -> list[Employee]:
        """Get all direct reports for a manager.

        Args:
            manager_id: ID of manager

        Returns:
            List of direct reports
        """
        return [emp for emp in self.employees.values() if emp.manager_id == manager_id]

    def get_reporting_hierarchy(self, employee_id: str) -> list[str]:
        """Get reporting chain from employee to CEO.

        Args:
            employee_id: ID of employee

        Returns:
            List of manager IDs in chain (including self)
        """
        chain = [employee_id]
        current_id = employee_id

        while current_id in self.employees:
            emp = self.employees[current_id]
            if not emp.manager_id:
                break
            chain.append(emp.manager_id)
            current_id = emp.manager_id

        return chain

    def get_org_chart_tree(self, root_manager_id: str | None = None) -> dict:
        """Build organizational chart as tree structure.

        Args:
            root_manager_id: ID of root manager (None for all roots)

        Returns:
            Tree dictionary with structure: {manager_id: [direct_reports]}
        """
        tree: dict[str, list[dict]] = {}

        for emp in self.employees.values():
            if emp.status == EmploymentStatus.ACTIVE:
                manager_id = emp.manager_id or "root"
                if manager_id not in tree:
                    tree[manager_id] = []
                tree[manager_id].append({"id": emp.id, "name": emp.full_name(), "position": emp.position_id})

        if root_manager_id:
            return self._filter_org_tree(tree, root_manager_id)
        return tree

    def _filter_org_tree(self, tree: dict, root_id: str, depth: int = 0, max_depth: int = 20) -> dict:
        """Recursively filter org tree to include only subtree.

        Args:
            tree: Full organization tree
            root_id: Root node ID to filter
            depth: Current recursion depth
            max_depth: Maximum recursion depth

        Returns:
            Filtered subtree
        """
        if depth > max_depth:
            return {}
        result = {}
        if root_id in tree:
            result[root_id] = tree[root_id]
            for report in tree.get(root_id, []):
                subtree = self._filter_org_tree(tree, report["id"], depth + 1, max_depth)
                result.update(subtree)
        return result

    def search_employees(self, query: str, fuzzy: bool = True, limit: int = 10) -> list[tuple[Employee, float]]:
        """Search employees by name with fuzzy matching.

        Args:
            query: Search query (name)
            fuzzy: Use fuzzy matching if True
            limit: Maximum results to return

        Returns:
            List of (Employee, match_score) tuples sorted by score
        """
        results: list[tuple[Employee, float]] = []

        for emp in self.employees.values():
            name = emp.full_name().lower()
            query_lower = query.lower()

            if fuzzy:
                score = difflib.SequenceMatcher(None, name, query_lower).ratio()
            else:
                score = 1.0 if query_lower in name else 0.0

            if score > 0:
                results.append((emp, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_headcount_by_status(self) -> dict[str, int]:
        """Get employee count by employment status.

        Returns:
            Dictionary of status -> count
        """
        counts: dict[str, int] = {status.value: 0 for status in EmploymentStatus}
        for emp in self.employees.values():
            counts[emp.status.value] += 1
        return counts

    def get_headcount_by_department(self) -> dict[str, int]:
        """Get active employee count by department.

        Returns:
            Dictionary of department_id -> count
        """
        counts: dict[str, int] = {}
        for emp in self.employees.values():
            if emp.status == EmploymentStatus.ACTIVE:
                counts[emp.department_id] = counts.get(emp.department_id, 0) + 1
        return counts

    def get_headcount_trend(self, days: int = 365) -> list[tuple[date, int, int, int]]:
        """Get headcount trend (snapshot, hires, terminations).

        Args:
            days: Number of days to look back

        Returns:
            List of (date, headcount, hires_that_day, terminations_that_day)
        """
        cutoff = date.today() - timedelta(days=days)
        trend: dict[date, tuple[int, int, int]] = {}

        for emp in self.employees.values():
            if emp.hire_date >= cutoff:
                trend.setdefault(emp.hire_date, (0, 0, 0))
                hires, terms = trend[emp.hire_date][1:3]
                trend[emp.hire_date] = (0, hires + 1, terms)

            if emp.termination_date and emp.termination_date >= cutoff:
                trend.setdefault(emp.termination_date, (0, 0, 0))
                hires, terms = trend[emp.termination_date][1:3]
                trend[emp.termination_date] = (0, hires, terms + 1)

        return sorted(trend.items(), key=lambda x: x[0])

    def get_birthdays_this_month(self) -> list[tuple[Employee, int]]:
        """Get employees with birthdays this month.

        Returns:
            List of (Employee, days_until_birthday) tuples
        """
        today = date.today()
        birthdays: list[tuple[Employee, int]] = []

        for emp in self.employees.values():
            dob = emp.date_of_birth
            birthday_this_year = dob.replace(year=today.year)

            if birthday_this_year < today:
                birthday_this_year = dob.replace(year=today.year + 1)

            if birthday_this_year.month == today.month:
                days_until = (birthday_this_year - today).days
                birthdays.append((emp, days_until))

        birthdays.sort(key=lambda x: x[1])
        return birthdays

    def get_work_anniversaries(self, start_date: date, end_date: date) -> list[tuple[Employee, int]]:
        """Get employees with work anniversaries in date range.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of (Employee, years_of_service) tuples
        """
        anniversaries: list[tuple[Employee, int]] = []

        for emp in self.employees.values():
            hire_month = emp.hire_date.month
            hire_day = emp.hire_date.day

            for year in range(start_date.year, end_date.year + 1):
                anniversary = date(year, hire_month, hire_day)
                if start_date <= anniversary <= end_date:
                    years = year - emp.hire_date.year
                    anniversaries.append((emp, years))

        anniversaries.sort(key=lambda x: x[0].hire_date)
        return anniversaries

    def get_span_of_control(self, manager_id: str) -> int:
        """Get direct report count for a manager.

        Args:
            manager_id: ID of manager

        Returns:
            Number of direct reports
        """
        return len(self.get_employees_by_manager(manager_id))

    def calculate_seniority(self, employee_id: str) -> float:
        """Calculate employee seniority in years.

        Args:
            employee_id: ID of employee

        Returns:
            Years of service from hire date

        Raises:
            EmployeeNotFoundError: If employee not found
        """
        emp = self.get_employee(employee_id)
        return emp.years_of_service()

    def get_seniority_ranking(self) -> list[tuple[Employee, float]]:
        """Rank employees by years of service.

        Returns:
            List of (Employee, years_of_service) sorted by seniority
        """
        ranking = []
        for emp in self.employees.values():
            if emp.status in [EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE]:
                ranking.append((emp, emp.years_of_service()))

        ranking.sort(key=lambda x: x[1], reverse=True)
        return ranking

    def get_new_hires(self, days: int = 30) -> list[Employee]:
        """Get employees hired in the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of recently hired employees
        """
        cutoff = date.today() - timedelta(days=days)
        return [emp for emp in self.employees.values() if emp.hire_date >= cutoff]

    def get_employees_by_age_range(self, min_age: int, max_age: int) -> list[Employee]:
        """Get employees within age range.

        Args:
            min_age: Minimum age
            max_age: Maximum age

        Returns:
            List of employees in age range
        """
        return [emp for emp in self.employees.values() if min_age <= emp.age() <= max_age]
