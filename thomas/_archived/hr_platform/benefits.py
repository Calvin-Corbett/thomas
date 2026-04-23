"""Benefits administration system with enrollment, eligibility, and analytics."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from thomas.hr_platform._exceptions import BenefitEnrollmentError
from thomas.hr_platform._types import (
    Benefit,
    BenefitType,
    Employee,
    EmploymentStatus,
)


class BenefitPlan:
    """Represents a benefit plan available to employees."""

    def __init__(
        self,
        id: str,
        name: str,
        benefit_type: BenefitType,
        employer_cost_monthly: Decimal,
        employee_cost_monthly: Decimal,
        coverage_types: list[str],
        deductible: Decimal = Decimal("0"),
        max_out_of_pocket: Decimal = Decimal("0"),
    ) -> None:
        """Initialize benefit plan.

        Args:
            id: Plan ID
            name: Plan name
            benefit_type: Type of benefit
            employer_cost_monthly: Monthly employer contribution
            employee_cost_monthly: Monthly employee contribution
            coverage_types: Available coverage types (employee, employee+spouse, family)
            deductible: Annual deductible
            max_out_of_pocket: Maximum out-of-pocket annual expense
        """
        self.id = id
        self.name = name
        self.benefit_type = benefit_type
        self.employer_cost_monthly = employer_cost_monthly
        self.employee_cost_monthly = employee_cost_monthly
        self.coverage_types = coverage_types
        self.deductible = deductible
        self.max_out_of_pocket = max_out_of_pocket
        self.created_at = datetime.now()

    def total_cost_monthly(self) -> Decimal:
        """Get total monthly cost (employer + employee)."""
        return self.employer_cost_monthly + self.employee_cost_monthly


class EnrollmentPeriod:
    """Open enrollment window for benefits."""

    def __init__(
        self,
        id: str,
        start_date: date,
        end_date: date,
        plan_year_start: date,
        year: int,
    ) -> None:
        """Initialize enrollment period.

        Args:
            id: Period ID
            start_date: Enrollment window start
            end_date: Enrollment window end
            plan_year_start: When coverage starts
            year: Plan year
        """
        self.id = id
        self.start_date = start_date
        self.end_date = end_date
        self.plan_year_start = plan_year_start
        self.year = year

    def is_open(self, check_date: date = None) -> bool:
        """Check if enrollment period is currently open.

        Args:
            check_date: Date to check (defaults to today)

        Returns:
            True if enrollment period is open
        """
        if check_date is None:
            check_date = date.today()
        return self.start_date <= check_date <= self.end_date


class BenefitsManager:
    """Manages benefits administration and enrollment."""

    def __init__(self) -> None:
        """Initialize benefits manager."""
        self.plans: dict[str, BenefitPlan] = {}
        self.enrollments: dict[str, Benefit] = {}
        self.enrollment_periods: dict[str, EnrollmentPeriod] = {}

    def add_plan(self, plan: BenefitPlan) -> BenefitPlan:
        """Add a benefit plan.

        Args:
            plan: BenefitPlan to add

        Returns:
            The added plan

        Raises:
            ValueError: If plan ID already exists
        """
        if plan.id in self.plans:
            raise ValueError(f"Plan {plan.id} already exists")
        self.plans[plan.id] = plan
        return plan

    def create_enrollment_period(
        self, start_date: date, end_date: date, plan_year_start: date, year: int
    ) -> EnrollmentPeriod:
        """Create an open enrollment period.

        Args:
            start_date: When enrollment opens
            end_date: When enrollment closes
            plan_year_start: When coverage begins
            year: Plan year

        Returns:
            The created EnrollmentPeriod
        """
        period_id = str(uuid.uuid4())
        period = EnrollmentPeriod(period_id, start_date, end_date, plan_year_start, year)
        self.enrollment_periods[period_id] = period
        return period

    def enroll_employee(
        self,
        employee_id: str,
        plan_id: str,
        coverage_level: str = "employee",
        dependents: list[str] | None = None,
        effective_date: date | None = None,
    ) -> Benefit:
        """Enroll employee in a benefit plan.

        Args:
            employee_id: ID of employee
            plan_id: ID of benefit plan
            coverage_level: Coverage type (employee, employee+spouse, family)
            dependents: List of dependent names
            effective_date: When coverage starts (defaults to today)

        Returns:
            The created Benefit enrollment

        Raises:
            BenefitEnrollmentError: If enrollment fails
        """
        if plan_id not in self.plans:
            raise BenefitEnrollmentError(f"Plan {plan_id} not found")

        plan = self.plans[plan_id]

        if coverage_level not in plan.coverage_types:
            raise BenefitEnrollmentError(f"Coverage level {coverage_level} not available for plan {plan_id}")

        if effective_date is None:
            effective_date = date.today()

        if dependents is None:
            dependents = []

        benefit = Benefit(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            benefit_type=plan.benefit_type,
            plan_name=plan.name,
            monthly_cost_employee=plan.employee_cost_monthly,
            monthly_cost_employer=plan.employer_cost_monthly,
            effective_date=effective_date,
            dependents=dependents,
            coverage_level=coverage_level,
        )

        self.enrollments[benefit.id] = benefit
        return benefit

    def terminate_enrollment(
        self,
        benefit_id: str,
        termination_date: date | None = None,
    ) -> Benefit:
        """Terminate a benefit enrollment.

        Args:
            benefit_id: ID of benefit enrollment
            termination_date: When coverage ends (defaults to today)

        Returns:
            The updated Benefit

        Raises:
            BenefitEnrollmentError: If benefit not found
        """
        if benefit_id not in self.enrollments:
            raise BenefitEnrollmentError(f"Benefit {benefit_id} not found")

        if termination_date is None:
            termination_date = date.today()

        benefit = self.enrollments[benefit_id]
        benefit.termination_date = termination_date
        return benefit

    def get_employee_benefits(self, employee_id: str, check_date: date | None = None) -> list[Benefit]:
        """Get all active benefits for an employee.

        Args:
            employee_id: ID of employee
            check_date: Date to check (defaults to today)

        Returns:
            List of active benefit enrollments
        """
        if check_date is None:
            check_date = date.today()

        benefits = []
        for benefit in self.enrollments.values():
            if benefit.employee_id == employee_id and benefit.is_active(check_date):
                benefits.append(benefit)

        return benefits

    def get_employees_by_benefit_type(self, benefit_type: BenefitType) -> dict[str, list[Benefit]]:
        """Get all employees enrolled in a benefit type.

        Args:
            benefit_type: Type of benefit

        Returns:
            Dictionary of employee_id -> benefits
        """
        result: dict[str, list[Benefit]] = {}

        for benefit in self.enrollments.values():
            if benefit.benefit_type == benefit_type and benefit.is_active():
                if benefit.employee_id not in result:
                    result[benefit.employee_id] = []
                result[benefit.employee_id].append(benefit)

        return result

    def calculate_employee_cost(self, employee_id: str, check_date: date | None = None) -> Decimal:
        """Calculate total monthly benefits cost for employee.

        Args:
            employee_id: ID of employee
            check_date: Date to check (defaults to today)

        Returns:
            Total monthly cost
        """
        total = Decimal("0")
        for benefit in self.get_employee_benefits(employee_id, check_date):
            total += benefit.monthly_cost_employee

        return total

    def calculate_employer_cost(self, check_date: date | None = None) -> Decimal:
        """Calculate total monthly benefits cost for all active employees.

        Args:
            check_date: Date to check (defaults to today)

        Returns:
            Total employer monthly cost
        """
        if check_date is None:
            check_date = date.today()

        total = Decimal("0")
        for benefit in self.enrollments.values():
            if benefit.is_active(check_date):
                total += benefit.monthly_cost_employer

        return total

    def get_benefit_eligibility(
        self, employee: Employee, benefit_types: list[BenefitType] | None = None
    ) -> dict[BenefitType, bool]:
        """Determine benefit eligibility for an employee.

        Args:
            employee: Employee object
            benefit_types: Specific types to check (None checks all)

        Returns:
            Dictionary of benefit_type -> is_eligible
        """
        if benefit_types is None:
            benefit_types = list(BenefitType)

        eligibility: dict[BenefitType, bool] = {}

        for btype in benefit_types:
            # Eligibility rules
            is_active = employee.status == EmploymentStatus.ACTIVE
            is_fte = employee.salary >= Decimal("20000")  # FTE minimum
            tenure = employee.years_of_service()

            # Health benefits require 30 days tenure
            if btype in [BenefitType.HEALTH_INSURANCE, BenefitType.DENTAL_INSURANCE]:
                eligible = is_active and is_fte and tenure >= 0.082  # ~30 days
            # Retirement requires 6 months tenure
            elif btype == BenefitType.RETIREMENT_401K:
                eligible = is_active and is_fte and tenure >= 0.5
            # FSA/HSA for active FTE
            elif btype in [BenefitType.FSA, BenefitType.HSA]:
                eligible = is_active and is_fte
            # All benefits for active employees
            else:
                eligible = is_active

            eligibility[btype] = eligible

        return eligibility

    def check_open_enrollment(self, year: int) -> EnrollmentPeriod | None:
        """Find open enrollment period for given year.

        Args:
            year: Plan year to check

        Returns:
            Open EnrollmentPeriod or None if not open
        """
        for period in self.enrollment_periods.values():
            if period.year == year and period.is_open():
                return period
        return None

    def add_dependent(self, benefit_id: str, dependent_name: str) -> Benefit:
        """Add a dependent to a benefit enrollment.

        Args:
            benefit_id: ID of benefit enrollment
            dependent_name: Name of dependent

        Returns:
            Updated Benefit

        Raises:
            BenefitEnrollmentError: If benefit not found
        """
        if benefit_id not in self.enrollments:
            raise BenefitEnrollmentError(f"Benefit {benefit_id} not found")

        benefit = self.enrollments[benefit_id]
        if dependent_name not in benefit.dependents:
            benefit.dependents.append(dependent_name)

        return benefit

    def remove_dependent(self, benefit_id: str, dependent_name: str) -> Benefit:
        """Remove a dependent from benefit enrollment.

        Args:
            benefit_id: ID of benefit enrollment
            dependent_name: Name of dependent

        Returns:
            Updated Benefit

        Raises:
            BenefitEnrollmentError: If benefit not found
        """
        if benefit_id not in self.enrollments:
            raise BenefitEnrollmentError(f"Benefit {benefit_id} not found")

        benefit = self.enrollments[benefit_id]
        if dependent_name in benefit.dependents:
            benefit.dependents.remove(dependent_name)

        return benefit

    def calculate_cobra_premium(self, benefit: Benefit, cobra_months: int = 18) -> Decimal:
        """Calculate COBRA continuation coverage premium (102% of cost).

        Args:
            benefit: The benefit being continued
            cobra_months: Number of months COBRA is available

        Returns:
            Monthly COBRA premium
        """
        monthly_cost = benefit.monthly_cost_employer + benefit.monthly_cost_employee
        cobra_premium = monthly_cost * Decimal("1.02")
        return cobra_premium.quantize(Decimal("0.01"))

    def get_benefits_cost_analysis(self, start_date: date, end_date: date) -> dict[str, Decimal]:
        """Analyze benefits costs over a date range.

        Args:
            start_date: Start of analysis period
            end_date: End of analysis period

        Returns:
            Dictionary with cost breakdown
        """
        months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
        if months <= 0:
            months = 1

        analysis: dict[str, Decimal] = {
            "total_employee_cost": Decimal("0"),
            "total_employer_cost": Decimal("0"),
            "total_cost": Decimal("0"),
            "average_monthly_per_employee": Decimal("0"),
            "enrollment_count": Decimal("0"),
        }

        enrollment_count = 0
        for benefit in self.enrollments.values():
            if benefit.is_active(start_date) or benefit.is_active(end_date):
                analysis["total_employee_cost"] += benefit.monthly_cost_employee * Decimal(str(months))
                analysis["total_employer_cost"] += benefit.monthly_cost_employer * Decimal(str(months))
                enrollment_count += 1

        analysis["total_cost"] = analysis["total_employee_cost"] + analysis["total_employer_cost"]
        analysis["enrollment_count"] = Decimal(str(enrollment_count))

        if enrollment_count > 0:
            analysis["average_monthly_per_employee"] = (
                analysis["total_cost"] / Decimal(str(enrollment_count)) / Decimal(str(months))
            ).quantize(Decimal("0.01"))

        return analysis
