"""Payroll engine with tax calculation, deductions, and pay stub generation."""

import uuid
from datetime import date
from decimal import Decimal

from thomas.marketplace.hr_platform._exceptions import PayrollCalculationError
from thomas.marketplace.hr_platform._types import Employee, EmploymentStatus, PayrollRecord


class TaxBracket:
    """Federal tax bracket for progressive tax calculation."""

    def __init__(
        self,
        min_income: Decimal,
        max_income: Decimal | None,
        rate: Decimal,
        year: int = 2024,
    ) -> None:
        """Initialize tax bracket.

        Args:
            min_income: Minimum income for bracket
            max_income: Maximum income for bracket (None for unlimited)
            rate: Tax rate as decimal (0.12 for 12%)
            year: Tax year
        """
        self.min_income = min_income
        self.max_income = max_income
        self.rate = rate
        self.year = year


class PayrollEngine:
    """Calculates payroll, taxes, and deductions."""

    # 2024 Federal tax brackets (single filer, married filing jointly)
    FEDERAL_TAX_BRACKETS_SINGLE = [
        TaxBracket(Decimal("0"), Decimal("11600"), Decimal("0.10")),
        TaxBracket(Decimal("11600"), Decimal("47150"), Decimal("0.12")),
        TaxBracket(Decimal("47150"), Decimal("100525"), Decimal("0.22")),
        TaxBracket(Decimal("100525"), Decimal("191950"), Decimal("0.24")),
        TaxBracket(Decimal("191950"), Decimal("243725"), Decimal("0.32")),
        TaxBracket(Decimal("243725"), Decimal("609350"), Decimal("0.35")),
        TaxBracket(Decimal("609350"), None, Decimal("0.37")),
    ]

    # Fixed rates
    SOCIAL_SECURITY_RATE = Decimal("0.062")
    MEDICARE_RATE = Decimal("0.0145")
    ADDITIONAL_MEDICARE_RATE = Decimal("0.009")  # Above $200k
    ADDITIONAL_MEDICARE_THRESHOLD = Decimal("200000")

    def __init__(self) -> None:
        """Initialize payroll engine."""
        self.payroll_records: dict[str, PayrollRecord] = {}

    def calculate_federal_tax(self, annual_salary: Decimal) -> Decimal:
        """Calculate federal income tax using progressive brackets.

        Args:
            annual_salary: Annual gross salary

        Returns:
            Federal tax amount
        """
        if annual_salary <= Decimal("0"):
            return Decimal("0.00")

        tax = Decimal("0.00")
        previous_max = Decimal("0")

        for bracket in self.FEDERAL_TAX_BRACKETS_SINGLE:
            if annual_salary <= bracket.min_income:
                break

            bracket_min = max(bracket.min_income, previous_max)
            bracket_max = bracket.max_income or annual_salary

            taxable_in_bracket = min(annual_salary, bracket_max) - bracket_min
            tax += taxable_in_bracket * bracket.rate

            previous_max = bracket_max

        return tax.quantize(Decimal("0.01"))

    def calculate_state_tax(self, annual_salary: Decimal, state: str = "CA") -> Decimal:
        """Calculate state income tax (simplified CA rate).

        Args:
            annual_salary: Annual gross salary
            state: State code (currently supports CA)

        Returns:
            State tax amount
        """
        if state == "CA":
            # Simplified CA tax (typical 5-10% range)
            if annual_salary < Decimal("10000"):
                rate = Decimal("0.01")
            elif annual_salary < Decimal("50000"):
                rate = Decimal("0.05")
            else:
                rate = Decimal("0.09")
            return (annual_salary * rate).quantize(Decimal("0.01"))
        return Decimal("0.00")

    def calculate_social_security_tax(self, annual_salary: Decimal, ytd_earnings: Decimal = Decimal("0")) -> Decimal:
        """Calculate Social Security tax (capped at wage base).

        Args:
            annual_salary: Annual gross salary
            ytd_earnings: Year-to-date earnings so far

        Returns:
            Social Security tax amount
        """
        wage_base = Decimal("168600")  # 2024 limit
        remaining_wages = max(Decimal("0"), wage_base - ytd_earnings)
        taxable_wages = min(annual_salary, remaining_wages)
        return (taxable_wages * self.SOCIAL_SECURITY_RATE).quantize(Decimal("0.01"))

    def calculate_medicare_tax(self, annual_salary: Decimal, ytd_earnings: Decimal = Decimal("0")) -> Decimal:
        """Calculate Medicare tax with additional tax above threshold.

        Args:
            annual_salary: Annual gross salary
            ytd_earnings: Year-to-date earnings

        Returns:
            Medicare tax amount
        """
        medicare = (annual_salary * self.MEDICARE_RATE).quantize(Decimal("0.01"))

        # Additional 0.9% Medicare tax on earnings over $200k
        if ytd_earnings + annual_salary > self.ADDITIONAL_MEDICARE_THRESHOLD:
            excess = ytd_earnings + annual_salary - self.ADDITIONAL_MEDICARE_THRESHOLD
            additional = (excess * self.ADDITIONAL_MEDICARE_RATE).quantize(Decimal("0.01"))
            medicare += additional

        return medicare.quantize(Decimal("0.01"))

    def calculate_pre_tax_deductions(self, salary: Decimal, deduction_percent: Decimal = Decimal("3")) -> Decimal:
        """Calculate pre-tax deductions (401k, health insurance).

        Args:
            salary: Gross salary
            deduction_percent: Percentage of salary to deduct

        Returns:
            Pre-tax deduction amount
        """
        return (salary * deduction_percent / Decimal("100")).quantize(Decimal("0.01"))

    def calculate_post_tax_deductions(self, salary: Decimal, deduction_amount: Decimal | None = None) -> Decimal:
        """Calculate post-tax deductions (garnishments, court orders).

        Args:
            salary: Gross salary
            deduction_amount: Fixed deduction amount (if None, calculates 1%)

        Returns:
            Post-tax deduction amount
        """
        if deduction_amount is None:
            return (salary * Decimal("0.01")).quantize(Decimal("0.01"))
        return min(deduction_amount, salary).quantize(Decimal("0.01"))

    def calculate_overtime(
        self,
        hours_worked: Decimal,
        hourly_rate: Decimal,
        standard_hours: Decimal = Decimal("40"),
        standard_threshold_2x: Decimal = Decimal("60"),
    ) -> tuple[Decimal, Decimal]:
        """Calculate overtime pay (1.5x after 40hrs, 2x after 60hrs).

        Args:
            hours_worked: Total hours worked in period
            hourly_rate: Base hourly rate
            standard_hours: Standard hours before 1.5x overtime
            standard_threshold_2x: Hours before 2x overtime

        Returns:
            Tuple of (overtime_hours, overtime_pay)
        """
        overtime_hours = Decimal("0")
        overtime_pay = Decimal("0")

        if hours_worked > standard_threshold_2x:
            # 2x overtime
            hours_at_2x = hours_worked - standard_threshold_2x
            overtime_hours += hours_at_2x
            overtime_pay += hours_at_2x * hourly_rate * Decimal("2")

        if hours_worked > standard_hours:
            # 1.5x overtime (between 40 and 60 hours)
            hours_at_1_5x = min(
                hours_worked - standard_hours,
                standard_threshold_2x - standard_hours,
            )
            overtime_hours += hours_at_1_5x
            overtime_pay += hours_at_1_5x * hourly_rate * Decimal("1.5")

        return (
            overtime_hours.quantize(Decimal("0.01")),
            overtime_pay.quantize(Decimal("0.01")),
        )

    def calculate_salary_for_period(
        self,
        annual_salary: Decimal,
        frequency: str = "biweekly",
    ) -> Decimal:
        """Convert annual salary to period amount.

        Args:
            annual_salary: Annual salary
            frequency: 'annual', 'monthly', 'biweekly', or 'hourly'

        Returns:
            Salary amount for period
        """
        if frequency == "annual":
            return annual_salary.quantize(Decimal("0.01"))
        elif frequency == "monthly":
            return (annual_salary / Decimal("12")).quantize(Decimal("0.01"))
        elif frequency == "biweekly":
            return (annual_salary / Decimal("26")).quantize(Decimal("0.01"))
        elif frequency == "hourly":
            # Calculate based on 2080 hours/year (40 hours/week * 52 weeks)
            return (annual_salary / Decimal("2080")).quantize(Decimal("0.01"))
        else:
            raise PayrollCalculationError(f"Unknown frequency: {frequency}")

    def calculate_payroll_record(
        self,
        employee: Employee,
        pay_period_start: date,
        pay_period_end: date,
        ytd_earnings: Decimal = Decimal("0"),
        bonus: Decimal = Decimal("0"),
        hours_worked: Decimal | None = None,
    ) -> PayrollRecord:
        """Calculate complete payroll for an employee for a period.

        Args:
            employee: Employee object
            pay_period_start: Start date of pay period
            pay_period_end: End date of pay period
            ytd_earnings: Year-to-date earnings before this period
            bonus: Bonus amount for this period
            hours_worked: Hours worked (for hourly employees)

        Returns:
            Complete PayrollRecord

        Raises:
            PayrollCalculationError: If calculation fails
        """
        if not employee.salary or employee.salary <= Decimal("0"):
            raise PayrollCalculationError(f"Invalid salary for {employee.id}")

        # Calculate gross salary for period
        gross_salary = self.calculate_salary_for_period(employee.salary, employee.pay_frequency)

        # Handle overtime for hourly employees
        overtime_hours = Decimal("0")
        overtime_pay = Decimal("0")

        if employee.pay_frequency == "hourly" and hours_worked:
            overtime_hours, overtime_pay = self.calculate_overtime(hours_worked, gross_salary)
            gross_salary = gross_salary * hours_worked + overtime_pay

        # Calculate taxes
        federal_tax = self.calculate_federal_tax(gross_salary)
        state_tax = self.calculate_state_tax(gross_salary)
        social_security = self.calculate_social_security_tax(gross_salary, ytd_earnings)
        medicare = self.calculate_medicare_tax(gross_salary, ytd_earnings)

        # Calculate deductions
        pre_tax_deductions = self.calculate_pre_tax_deductions(gross_salary)
        post_tax_deductions = self.calculate_post_tax_deductions(gross_salary)

        # Calculate net salary
        total_taxes = federal_tax + state_tax + social_security + medicare
        net_salary = (gross_salary + bonus - total_taxes - pre_tax_deductions - post_tax_deductions).quantize(
            Decimal("0.01")
        )

        year_to_date = ytd_earnings + gross_salary + bonus

        return PayrollRecord(
            id=str(uuid.uuid4()),
            employee_id=employee.id,
            pay_period_start=pay_period_start,
            pay_period_end=pay_period_end,
            gross_salary=gross_salary.quantize(Decimal("0.01")),
            federal_tax=federal_tax,
            state_tax=state_tax,
            social_security_tax=social_security,
            medicare_tax=medicare,
            pre_tax_deductions=pre_tax_deductions,
            post_tax_deductions=post_tax_deductions,
            net_salary=net_salary,
            overtime_hours=overtime_hours,
            overtime_pay=overtime_pay,
            bonus=bonus,
            year_to_date=year_to_date.quantize(Decimal("0.01")),
        )

    def process_payroll_batch(
        self,
        employees: list[Employee],
        pay_period_start: date,
        pay_period_end: date,
        ytd_earnings_map: dict[str, Decimal],
    ) -> list[PayrollRecord]:
        """Process payroll for multiple employees in a batch.

        Args:
            employees: List of employees to process
            pay_period_start: Start of pay period
            pay_period_end: End of pay period
            ytd_earnings_map: Map of employee_id -> year-to-date earnings

        Returns:
            List of PayrollRecords for all employees
        """
        records = []
        for emp in employees:
            if emp.status == EmploymentStatus.ACTIVE:
                ytd = ytd_earnings_map.get(emp.id, Decimal("0"))
                record = self.calculate_payroll_record(emp, pay_period_start, pay_period_end, ytd_earnings=ytd)
                records.append(record)
                self.payroll_records[record.id] = record

        return records

    def generate_pay_stub(self, payroll_record: PayrollRecord) -> str:
        """Generate pay stub text representation.

        Args:
            payroll_record: PayrollRecord to generate stub for

        Returns:
            Formatted pay stub string
        """
        stub = f"""
PAY STUB
{'='*60}
Employee ID: {payroll_record.employee_id}
Pay Period: {payroll_record.pay_period_start} to {payroll_record.pay_period_end}

EARNINGS:
  Gross Salary:               ${payroll_record.gross_salary:>12.2f}
  Bonus:                      ${payroll_record.bonus:>12.2f}
  Overtime Hours:             {payroll_record.overtime_hours:>12.2f}
  Overtime Pay:               ${payroll_record.overtime_pay:>12.2f}
  {'─'*55}
  TOTAL EARNINGS:             ${payroll_record.gross_salary + payroll_record.bonus + payroll_record.overtime_pay:>12.2f}

TAXES:
  Federal Income Tax:         ${payroll_record.federal_tax:>12.2f}
  State Income Tax:           ${payroll_record.state_tax:>12.2f}
  Social Security:            ${payroll_record.social_security_tax:>12.2f}
  Medicare:                   ${payroll_record.medicare_tax:>12.2f}
  {'─'*55}
  TOTAL TAXES:                ${payroll_record.federal_tax + payroll_record.social_security_tax + payroll_record.medicare_tax + payroll_record.state_tax:>12.2f}

DEDUCTIONS:
  Pre-Tax Deductions (401k):  ${payroll_record.pre_tax_deductions:>12.2f}
  Post-Tax Deductions:        ${payroll_record.post_tax_deductions:>12.2f}
  {'─'*55}
  TOTAL DEDUCTIONS:           ${payroll_record.pre_tax_deductions + payroll_record.post_tax_deductions:>12.2f}

{'='*60}
NET PAY:                        ${payroll_record.net_salary:>12.2f}
Year-to-Date:                   ${payroll_record.year_to_date:>12.2f}
{'='*60}
"""
        return stub

    def get_payroll_summary(self, start_date: date, end_date: date) -> dict[str, Decimal]:
        """Get summary of payroll for date range.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dictionary with total salaries, taxes, and deductions
        """
        summary: dict[str, Decimal] = {
            "total_gross": Decimal("0"),
            "total_federal_tax": Decimal("0"),
            "total_state_tax": Decimal("0"),
            "total_social_security": Decimal("0"),
            "total_medicare": Decimal("0"),
            "total_pre_tax_deductions": Decimal("0"),
            "total_post_tax_deductions": Decimal("0"),
            "total_net": Decimal("0"),
            "total_overtime_pay": Decimal("0"),
            "record_count": Decimal("0"),
        }

        for record in self.payroll_records.values():
            if start_date <= record.pay_period_start <= end_date:
                summary["total_gross"] += record.gross_salary
                summary["total_federal_tax"] += record.federal_tax
                summary["total_state_tax"] += record.state_tax
                summary["total_social_security"] += record.social_security_tax
                summary["total_medicare"] += record.medicare_tax
                summary["total_pre_tax_deductions"] += record.pre_tax_deductions
                summary["total_post_tax_deductions"] += record.post_tax_deductions
                summary["total_net"] += record.net_salary
                summary["total_overtime_pay"] += record.overtime_pay
                summary["record_count"] += Decimal("1")

        return summary
