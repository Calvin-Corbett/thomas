"""Tests for employee management system."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from thomas.hr_platform._exceptions import EmployeeNotFoundError
from thomas.hr_platform._types import (
    Department,
    Employee,
    EmploymentStatus,
    Position,
)
from thomas.hr_platform.employees import EmployeeManager


class TestEmployeeManager:
    """Test employee management functionality."""

    @pytest.fixture
    def manager(self) -> EmployeeManager:
        """Create manager instance."""
        return EmployeeManager()

    @pytest.fixture
    def department(self) -> Department:
        """Create test department."""
        return Department(
            id="dept1",
            name="Engineering",
            code="ENG",
            budget_annual=Decimal("500000"),
        )

    @pytest.fixture
    def position(self, department: Department) -> Position:
        """Create test position."""
        return Position(
            id="pos1",
            title="Software Engineer",
            department_id=department.id,
            level="Senior",
            salary_min=Decimal("100000"),
            salary_max=Decimal("150000"),
            salary_mid=Decimal("125000"),
        )

    @pytest.fixture
    def employee(self, position: Position, department: Department) -> Employee:
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
            position_id=position.id,
            department_id=department.id,
            salary=Decimal("125000"),
        )

    def test_add_department(self, manager: EmployeeManager, department: Department) -> None:
        """Test adding department."""
        result = manager.add_department(department)
        assert result.id == department.id
        assert manager.departments[department.id] == department

    def test_add_position(
        self,
        manager: EmployeeManager,
        department: Department,
        position: Position,
    ) -> None:
        """Test adding position."""
        manager.add_department(department)
        result = manager.add_position(position)
        assert result.id == position.id

    def test_hire_employee(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test hiring employee."""
        manager.add_department(department)
        manager.add_position(position)
        result = manager.hire_employee(employee)

        assert result.status == EmploymentStatus.HIRED
        assert manager.employees[employee.id] == result

    def test_activate_employee(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test activating employee."""
        manager.add_department(department)
        manager.add_position(position)
        manager.hire_employee(employee)
        result = manager.activate_employee(employee.id)

        assert result.status == EmploymentStatus.ACTIVE

    def test_activate_nonexistent_employee(self, manager: EmployeeManager) -> None:
        """Test activating nonexistent employee."""
        with pytest.raises(EmployeeNotFoundError):
            manager.activate_employee("nonexistent")

    def test_terminate_employee(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test terminating employee."""
        manager.add_department(department)
        manager.add_position(position)
        manager.hire_employee(employee)
        manager.activate_employee(employee.id)

        result = manager.terminate_employee(employee.id)
        assert result.status == EmploymentStatus.TERMINATED
        assert result.termination_date is not None

    def test_transfer_employee(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test transferring employee."""
        dept2 = Department(id="dept2", name="Sales", code="SAL")
        pos2 = Position(
            id="pos2",
            title="Sales Rep",
            department_id=dept2.id,
            level="Mid",
            salary_min=Decimal("60000"),
            salary_max=Decimal("90000"),
            salary_mid=Decimal("75000"),
        )

        manager.add_department(department)
        manager.add_department(dept2)
        manager.add_position(position)
        manager.add_position(pos2)
        manager.hire_employee(employee)

        result = manager.transfer_employee(employee.id, dept2.id, pos2.id)
        assert result.department_id == dept2.id
        assert result.position_id == pos2.id

    def test_get_employees_by_department(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test getting employees by department."""
        manager.add_department(department)
        manager.add_position(position)
        manager.hire_employee(employee)

        results = manager.get_employees_by_department(department.id)
        assert len(results) == 1
        assert results[0].id == employee.id

    def test_search_employees(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test searching employees by name."""
        manager.add_department(department)
        manager.add_position(position)
        manager.hire_employee(employee)

        results = manager.search_employees("John")
        assert len(results) > 0
        assert results[0][0].id == employee.id

    def test_headcount_by_status(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test headcount by employment status."""
        manager.add_department(department)
        manager.add_position(position)
        manager.hire_employee(employee)
        manager.activate_employee(employee.id)

        counts = manager.get_headcount_by_status()
        assert counts[EmploymentStatus.ACTIVE.value] == 1

    def test_seniority_calculation(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test seniority calculation."""
        manager.add_department(department)
        manager.add_position(position)

        emp = employee
        emp.hire_date = date.today() - timedelta(days=365)
        manager.hire_employee(emp)

        seniority = manager.calculate_seniority(emp.id)
        assert seniority >= 0.99  # Approximately 1 year

    def test_work_anniversaries(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test getting work anniversaries."""
        manager.add_department(department)
        manager.add_position(position)

        emp = employee
        emp.hire_date = date(2020, 2, 15)
        manager.hire_employee(emp)

        start = date(2024, 2, 1)
        end = date(2024, 2, 29)
        anniversaries = manager.get_work_anniversaries(start, end)

        assert len(anniversaries) == 1
        assert anniversaries[0][0].id == emp.id
        assert anniversaries[0][1] == 4

    def test_org_chart(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test organizational chart generation."""
        manager.add_department(department)
        manager.add_position(position)

        emp1 = employee
        emp1.manager_id = None
        manager.hire_employee(emp1)
        manager.activate_employee(emp1.id)

        emp2 = Employee(
            id="emp2",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            phone="555-5678",
            ssn="987-65-4321",
            date_of_birth=date(1992, 6, 20),
            gender="F",
            position_id=position.id,
            department_id=department.id,
            salary=Decimal("100000"),
            manager_id=emp1.id,
        )
        manager.hire_employee(emp2)
        manager.activate_employee(emp2.id)

        tree = manager.get_org_chart_tree()
        assert "root" in tree
        assert len(tree["root"]) >= 1

    def test_reporting_hierarchy(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test reporting hierarchy chain."""
        manager.add_department(department)
        manager.add_position(position)

        emp1 = employee
        emp1.manager_id = None
        manager.hire_employee(emp1)

        emp2 = Employee(
            id="emp2",
            first_name="Manager",
            last_name="Person",
            email="mgr@example.com",
            phone="555-9999",
            ssn="555-55-5555",
            date_of_birth=date(1985, 1, 1),
            gender="M",
            position_id=position.id,
            department_id=department.id,
            salary=Decimal("150000"),
            manager_id=emp1.id,
        )
        manager.hire_employee(emp2)

        hierarchy = manager.get_reporting_hierarchy(emp2.id)
        assert hierarchy[0] == emp2.id
        assert hierarchy[1] == emp1.id

    def test_full_name(self, employee: Employee) -> None:
        """Test full name generation."""
        assert employee.full_name() == "John Doe"

    def test_is_active(
        self,
        manager: EmployeeManager,
        employee: Employee,
        department: Department,
        position: Position,
    ) -> None:
        """Test is_active method."""
        manager.add_department(department)
        manager.add_position(position)
        manager.hire_employee(employee)

        assert not employee.is_active()
        manager.activate_employee(employee.id)
        assert manager.get_employee(employee.id).is_active()

    def test_age_calculation(self, employee: Employee) -> None:
        """Test age calculation."""
        age = employee.age()
        assert age >= 33  # Born in 1990
        assert age <= 36
