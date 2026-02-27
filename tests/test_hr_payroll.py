"""Tests for payroll engine."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.hr_platform._exceptions import PayrollCalculationError
from thomas.hr_platform._types import Employee, EmploymentStatus
from thomas.hr_platform.payroll import PayrollEngine


class TestPayrollEngine:
    """Test payroll calculation functionality."""

    @pytest.fixture
    def engine(self) -> PayrollEngine:
        """Create payroll engine."""
        return PayrollEngine()

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
            pay_frequency="biweekly",
            status=EmploymentStatus.ACTIVE,
        )

    def test_federal_tax_calculation(self, engine: PayrollEngine) -> None:
        """Test federal income tax calculation."""
        # $100,000 annual salary
        tax = engine.calculate_federal_tax(Decimal("100000"))

        # Should be in reasonable range
        assert tax > Decimal("10000")
        assert tax < Decimal("25000")

    def test_state_tax_calculation(self, engine: PayrollEngine) -> None:
        """Test state income tax calculation."""
        tax = engine.calculate_state_tax(Decimal("100000"))

        # California tax
        assert tax > Decimal("5000")
        assert tax < Decimal("10000")

    def test_social_security_tax(self, engine: PayrollEngine) -> None:
        """Test Social Security tax calculation."""
        tax = engine.calculate_social_security_tax(Decimal("100000"))

        # 6.2% of $100,000 = $6,200
        expected = Decimal("100000") * PayrollEngine.SOCIAL_SECURITY_RATE
        assert tax == expected

    def test_medicare_tax(self, engine: PayrollEngine) -> None:
        """Test Medicare tax calculation."""
        tax = engine.calculate_medicare_tax(Decimal("100000"))

        # 1.45% of $100,000 = $1,450
        expected = Decimal("100000") * PayrollEngine.MEDICARE_RATE
        assert tax == expected

    def test_pre_tax_deductions(self, engine: PayrollEngine) -> None:
        """Test pre-tax deduction calculation."""
        deductions = engine.calculate_pre_tax_deductions(Decimal("100000"), Decimal("5"))

        # 5% of $100,000 = $5,000
        assert deductions == Decimal("5000.00")

    def test_post_tax_deductions(self, engine: PayrollEngine) -> None:
        """Test post-tax deduction calculation."""
        deductions = engine.calculate_post_tax_deductions(Decimal("100000"))

        # Default 1% = $1,000
        assert deductions == Decimal("1000.00")

    def test_overtime_calculation(self, engine: PayrollEngine) -> None:
        """Test overtime pay calculation."""
        # 50 hours at $25/hour
        overtime_hours, overtime_pay = engine.calculate_overtime(Decimal("50"), Decimal("25"))

        # 10 hours at 1.5x = 10 * 25 * 1.5 = $375
        assert overtime_hours == Decimal("10.00")
        assert overtime_pay == Decimal("375.00")

    def test_overtime_2x(self, engine: PayrollEngine) -> None:
        """Test 2x overtime calculation."""
        # 70 hours at $20/hour
        overtime_hours, overtime_pay = engine.calculate_overtime(Decimal("70"), Decimal("20"))

        # 20 hours at 1.5x (40-60) + 10 hours at 2x (60-70)
        # (20 * 20 * 1.5) + (10 * 20 * 2) = 600 + 400 = 1000
        assert overtime_hours == Decimal("30.00")
        assert overtime_pay == Decimal("1000.00")

    def test_salary_conversion_biweekly(self, engine: PayrollEngine) -> None:
        """Test salary conversion to biweekly."""
        period_salary = engine.calculate_salary_for_period(Decimal("100000"), "biweekly")

        # $100,000 / 26 = $3,846.15
        assert period_salary == Decimal("3846.15")

    def test_salary_conversion_monthly(self, engine: PayrollEngine) -> None:
        """Test salary conversion to monthly."""
        period_salary = engine.calculate_salary_for_period(Decimal("100000"), "monthly")

        # $100,000 / 12 = $8,333.33
        assert period_salary == Decimal("8333.33")

    def test_salary_conversion_hourly(self, engine: PayrollEngine) -> None:
        """Test salary conversion to hourly."""
        period_salary = engine.calculate_salary_for_period(Decimal("52000"), "hourly")

        # $52,000 / 2080 = $25.00
        assert period_salary == Decimal("25.00")

    def test_payroll_record_calculation(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test complete payroll record calculation."""
        record = engine.calculate_payroll_record(
            employee,
            date(2024, 1, 1),
            date(2024, 1, 14),
        )

        assert record.employee_id == employee.id
        assert record.gross_salary > Decimal("0")
        assert record.federal_tax > Decimal("0")
        assert record.social_security_tax > Decimal("0")
        assert record.medicare_tax > Decimal("0")
        assert record.net_salary > Decimal("0")

    def test_payroll_record_with_bonus(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test payroll with bonus."""
        record = engine.calculate_payroll_record(
            employee,
            date(2024, 1, 1),
            date(2024, 1, 14),
            bonus=Decimal("5000"),
        )

        assert record.bonus == Decimal("5000")
        assert record.year_to_date > record.gross_salary

    def test_payroll_with_ytd_earnings(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test Social Security tax cap with YTD earnings."""
        # YTD near wage base limit
        ytd = Decimal("168000")

        record = engine.calculate_payroll_record(
            employee,
            date(2024, 1, 1),
            date(2024, 1, 14),
            ytd_earnings=ytd,
        )

        # Social Security should be minimal (near wage base)
        assert record.social_security_tax < Decimal("100")

    def test_payroll_batch_processing(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test batch payroll processing."""
        employees = [employee]
        ytd_map = {"emp1": Decimal("0")}

        records = engine.process_payroll_batch(
            employees,
            date(2024, 1, 1),
            date(2024, 1, 14),
            ytd_map,
        )

        assert len(records) == 1
        assert records[0].employee_id == "emp1"

    def test_pay_stub_generation(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test pay stub text generation."""
        record = engine.calculate_payroll_record(
            employee,
            date(2024, 1, 1),
            date(2024, 1, 14),
        )

        stub = engine.generate_pay_stub(record)

        assert "PAY STUB" in stub
        assert "EARNINGS" in stub
        assert "TAXES" in stub
        assert "NET PAY" in stub
        assert f"{record.net_salary:.2f}" in stub

    def test_payroll_summary(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test payroll summary calculation."""
        record = engine.calculate_payroll_record(
            employee,
            date(2024, 1, 1),
            date(2024, 1, 14),
        )
        engine.payroll_records[record.id] = record

        summary = engine.get_payroll_summary(date(2024, 1, 1), date(2024, 1, 31))

        assert summary["total_gross"] > Decimal("0")
        assert summary["total_net"] > Decimal("0")
        assert summary["record_count"] > Decimal("0")

    def test_invalid_salary(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test error handling for invalid salary."""
        emp = employee
        emp.salary = Decimal("0")

        with pytest.raises(PayrollCalculationError):
            engine.calculate_payroll_record(
                emp,
                date(2024, 1, 1),
                date(2024, 1, 14),
            )

    def test_tax_bracket_progressive(self, engine: PayrollEngine) -> None:
        """Test progressive tax calculation."""
        tax_low = engine.calculate_federal_tax(Decimal("50000"))
        tax_high = engine.calculate_federal_tax(Decimal("150000"))

        # Higher income should have higher tax
        assert tax_high > tax_low

        # Progressive: higher earner pays higher effective rate on higher bracket
        # But marginal rates are progressive

    def test_deductions_reduce_net(self, engine: PayrollEngine, employee: Employee) -> None:
        """Test that deductions reduce net pay."""
        record = engine.calculate_payroll_record(
            employee,
            date(2024, 1, 1),
            date(2024, 1, 14),
        )

        gross = record.gross_salary
        deductions = record.total_deductions()

        # Net should be gross minus deductions
        assert record.net_salary < gross
        assert record.net_salary > Decimal("0")

    def test_overtime_hourly_employee(self, engine: PayrollEngine) -> None:
        """Test overtime for hourly employee."""
        hourly_emp = Employee(
            id="emp2",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            phone="555-5678",
            ssn="987-65-4321",
            date_of_birth=date(1992, 6, 20),
            gender="F",
            position_id="pos1",
            department_id="dept1",
            salary=Decimal("50000"),  # $50k annual = ~$24/hour
            pay_frequency="hourly",
            status=EmploymentStatus.ACTIVE,
        )

        # 50 hours worked in period
        record = engine.calculate_payroll_record(
            hourly_emp,
            date(2024, 1, 1),
            date(2024, 1, 14),
            hours_worked=Decimal("50"),
        )

        # Should have overtime pay
        assert record.overtime_pay > Decimal("0")
        assert record.overtime_hours == Decimal("10.00")
