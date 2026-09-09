"""HR analytics engine for workforce insights and metrics."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from thomas.hr_platform._exceptions import HRException
from thomas.hr_platform._types import Employee, PayrollRecord


class TurnoverAnalysis:
    """Analyzes employee turnover patterns."""

    def __init__(self) -> None:
        """Initialize turnover analysis."""
        self.terminations: list[Employee] = []

    def add_termination(self, employee: Employee) -> None:
        """Record an employee termination.

        Args:
            employee: Terminated employee
        """
        if employee.termination_date:
            self.terminations.append(employee)

    def calculate_turnover_rate(
        self,
        start_date: date,
        end_date: date,
        average_headcount: Decimal,
    ) -> Decimal:
        """Calculate annual turnover rate.

        Args:
            start_date: Period start
            end_date: Period end
            average_headcount: Average headcount during period

        Returns:
            Turnover rate as percentage
        """
        terminations = sum(
            1 for emp in self.terminations if emp.termination_date and start_date <= emp.termination_date <= end_date
        )

        if average_headcount <= 0:
            return Decimal("0")

        rate = (Decimal(str(terminations)) / average_headcount) * Decimal("100")
        return rate.quantize(Decimal("0.01"))

    def voluntary_vs_involuntary(self, start_date: date, end_date: date) -> tuple[int, int]:
        """Categorize terminations as voluntary or involuntary.

        Args:
            start_date: Period start
            end_date: Period end

        Returns:
            Tuple of (voluntary_count, involuntary_count)
        """
        period_terminations = [
            emp for emp in self.terminations if emp.termination_date and start_date <= emp.termination_date <= end_date
        ]

        # Simple heuristic: tenure < 2 years often indicates voluntary
        voluntary = sum(1 for e in period_terminations if e.years_of_service() < 2)
        involuntary = len(period_terminations) - voluntary

        return (voluntary, involuntary)

    def turnover_by_department(self, start_date: date, end_date: date) -> dict[str, int]:
        """Get terminations by department.

        Args:
            start_date: Period start
            end_date: Period end

        Returns:
            Dictionary of department_id -> termination count
        """
        by_dept: dict[str, int] = {}

        for emp in self.terminations:
            if emp.termination_date and start_date <= emp.termination_date <= end_date:
                dept = emp.department_id
                by_dept[dept] = by_dept.get(dept, 0) + 1

        return by_dept

    def turnover_by_tenure(self, start_date: date, end_date: date) -> dict[str, int]:
        """Get terminations by tenure bucket.

        Args:
            start_date: Period start
            end_date: Period end

        Returns:
            Dictionary of tenure_range -> count
        """
        by_tenure: dict[str, int] = {
            "0-6 months": 0,
            "6-12 months": 0,
            "1-2 years": 0,
            "2-5 years": 0,
            "5+ years": 0,
        }

        for emp in self.terminations:
            if emp.termination_date and start_date <= emp.termination_date <= end_date:
                tenure = emp.years_of_service()

                if tenure < 0.5:
                    by_tenure["0-6 months"] += 1
                elif tenure < 1:
                    by_tenure["6-12 months"] += 1
                elif tenure < 2:
                    by_tenure["1-2 years"] += 1
                elif tenure < 5:
                    by_tenure["2-5 years"] += 1
                else:
                    by_tenure["5+ years"] += 1

        return by_tenure


class DiversityMetrics:
    """Tracks diversity and EEO metrics."""

    CATEGORIES = {
        "White": 0,
        "Black/African American": 0,
        "Hispanic/Latino": 0,
        "Asian": 0,
        "Native American": 0,
        "Pacific Islander": 0,
        "Two or more races": 0,
    }

    def __init__(self) -> None:
        """Initialize diversity metrics."""
        self.employee_categories: dict[str, str] = {}  # employee_id -> category

    def record_employee_eeo_category(self, employee_id: str, category: str) -> None:
        """Record EEO category for employee.

        Args:
            employee_id: ID of employee
            category: EEO category
        """
        if category not in self.CATEGORIES:
            raise HRException(f"Invalid EEO category: {category}")
        self.employee_categories[employee_id] = category

    def get_diversity_distribution(self, active_employees: list[Employee]) -> dict[str, Decimal]:
        """Get percentage distribution by EEO category.

        Args:
            active_employees: List of active employees

        Returns:
            Dictionary of category -> percentage
        """
        if not active_employees:
            return {}

        distribution: dict[str, int] = {cat: 0 for cat in self.CATEGORIES}

        for emp in active_employees:
            category = self.employee_categories.get(emp.id, "Unknown")
            if category in distribution:
                distribution[category] += 1

        total = len(active_employees)
        return {
            cat: (Decimal(str(count)) / Decimal(str(total)) * Decimal("100")).quantize(Decimal("0.01"))
            for cat, count in distribution.items()
        }

    def get_representation_index(
        self,
        category: str,
        employee_count: int,
        workforce_percent: Decimal,
        population_percent: Decimal,
    ) -> Decimal:
        """Calculate representation index (80% rule).

        Args:
            category: EEO category
            employee_count: Count in category
            workforce_percent: Percentage of workforce
            population_percent: Percentage of population

        Returns:
            Representation index (should be >= 80%)
        """
        if population_percent <= 0:
            return Decimal("100")

        index = (workforce_percent / population_percent) * Decimal("100")
        return index.quantize(Decimal("0.01"))


class CompensationAnalytics:
    """Analyzes compensation equity and ranges."""

    def __init__(self) -> None:
        """Initialize compensation analytics."""
        self.payroll_records: list[PayrollRecord] = []

    def add_payroll_record(self, record: PayrollRecord) -> None:
        """Add payroll record for analysis.

        Args:
            record: PayrollRecord to analyze
        """
        self.payroll_records.append(record)

    def calculate_compa_ratio(
        self,
        employee_salary: Decimal,
        salary_midpoint: Decimal,
    ) -> Decimal:
        """Calculate compa ratio (actual vs midpoint).

        Args:
            employee_salary: Employee salary
            salary_midpoint: Salary range midpoint

        Returns:
            Compa ratio (100 = at midpoint, <100 = below)
        """
        if salary_midpoint <= 0:
            return Decimal("100")

        ratio = (employee_salary / salary_midpoint) * Decimal("100")
        return ratio.quantize(Decimal("0.01"))

    def calculate_range_penetration(
        self,
        employee_salary: Decimal,
        salary_min: Decimal,
        salary_max: Decimal,
    ) -> Decimal:
        """Calculate range penetration (position within range).

        Args:
            employee_salary: Employee salary
            salary_min: Range minimum
            salary_max: Range maximum

        Returns:
            Percentage through range (0-100)
        """
        if salary_max <= salary_min:
            return Decimal("0")

        penetration = ((employee_salary - salary_min) / (salary_max - salary_min)) * Decimal("100")
        return penetration.quantize(Decimal("0.01"))

    def pay_equity_analysis(
        self,
        employees_by_group: dict[str, list[tuple[str, Decimal]]],
    ) -> dict[str, Decimal]:
        """Analyze pay equity between demographic groups.

        Args:
            employees_by_group: Dictionary of group -> [(employee_id, salary)]

        Returns:
            Dictionary of group -> average_salary
        """
        analysis: dict[str, Decimal] = {}

        for group, employees in employees_by_group.items():
            if employees:
                total = sum(sal for _, sal in employees)
                avg = (total / Decimal(str(len(employees)))).quantize(Decimal("0.01"))
                analysis[group] = avg

        return analysis


class EngagementMetrics:
    """Tracks employee engagement and satisfaction."""

    def __init__(self) -> None:
        """Initialize engagement metrics."""
        self.survey_responses: dict[str, dict] = {}

    def record_survey_response(
        self,
        survey_id: str,
        employee_id: str,
        overall_score: Decimal,
        dimensions: dict[str, Decimal],
    ) -> None:
        """Record engagement survey response.

        Args:
            survey_id: ID of survey
            employee_id: ID of respondent
            overall_score: Overall engagement score (1-5)
            dimensions: Dimension scores (engagement, culture, growth, etc.)
        """
        self.survey_responses[employee_id] = {
            "survey_id": survey_id,
            "overall_score": overall_score,
            "dimensions": dimensions,
            "timestamp": datetime.now(),
        }

    def calculate_engagement_index(self) -> Decimal:
        """Calculate overall engagement index.

        Returns:
            Average engagement score (1-5)
        """
        if not self.survey_responses:
            return Decimal("0")

        total = sum(r["overall_score"] for r in self.survey_responses.values())
        avg = total / Decimal(str(len(self.survey_responses)))
        return avg.quantize(Decimal("0.01"))

    def get_dimension_scores(self) -> dict[str, Decimal]:
        """Get average scores by dimension.

        Returns:
            Dictionary of dimension -> average_score
        """
        if not self.survey_responses:
            return {}

        all_dimensions: dict[str, list[Decimal]] = defaultdict(list)

        for response in self.survey_responses.values():
            for dimension, score in response["dimensions"].items():
                all_dimensions[dimension].append(score)

        return {
            dim: (sum(scores) / Decimal(str(len(scores)))).quantize(Decimal("0.01"))
            for dim, scores in all_dimensions.items()
        }


class HRAnalytics:
    """Main HR analytics engine."""

    def __init__(self) -> None:
        """Initialize HR analytics."""
        self.turnover = TurnoverAnalysis()
        self.diversity = DiversityMetrics()
        self.compensation = CompensationAnalytics()
        self.engagement = EngagementMetrics()

    def calculate_cost_per_hire(
        self,
        total_recruitment_cost: Decimal,
        hires_count: int,
    ) -> Decimal:
        """Calculate cost-per-hire metric.

        Args:
            total_recruitment_cost: Total recruiting expenses
            hires_count: Number of people hired

        Returns:
            Cost per hire
        """
        if hires_count <= 0:
            return Decimal("0")

        cost = (total_recruitment_cost / Decimal(str(hires_count))).quantize(Decimal("0.01"))
        return cost

    def calculate_headcount_trend(
        self,
        active_employees_by_date: list[tuple[date, int]],
    ) -> Decimal:
        """Calculate headcount trend (growth rate).

        Args:
            active_employees_by_date: List of (date, headcount) tuples

        Returns:
            Growth rate as percentage
        """
        if len(active_employees_by_date) < 2:
            return Decimal("0")

        first_date, first_count = active_employees_by_date[0]
        last_date, last_count = active_employees_by_date[-1]

        if first_count <= 0:
            return Decimal("0")

        days = (last_date - first_date).days
        if days <= 0:
            return Decimal("0")

        growth = ((Decimal(str(last_count)) - Decimal(str(first_count))) / Decimal(str(first_count))) * Decimal("100")
        annualized = (growth / Decimal(str(days))) * Decimal("365")

        return annualized.quantize(Decimal("0.01"))

    def calculate_span_of_control_analysis(
        self,
        manager_direct_reports: dict[str, int],
    ) -> dict[str, any]:
        """Analyze span of control metrics.

        Args:
            manager_direct_reports: Dictionary of manager_id -> report_count

        Returns:
            Span of control statistics
        """
        if not manager_direct_reports:
            return {}

        counts = list(manager_direct_reports.values())
        total = sum(counts)
        avg = Decimal(str(total)) / Decimal(str(len(counts)))

        return {
            "average_span": avg.quantize(Decimal("0.01")),
            "min_span": min(counts),
            "max_span": max(counts),
            "manager_count": len(counts),
        }

    def flight_risk_prediction(
        self,
        employee: Employee,
        performance_rating: Decimal,
        market_salary: Decimal,
    ) -> Decimal:
        """Predict flight risk (propensity to leave).

        Args:
            employee: Employee object
            performance_rating: Recent performance rating (1-5)
            market_salary: Market rate for role

        Returns:
            Flight risk score (0-100, higher = higher risk)
        """
        risk = Decimal("0")

        # Tenure factor: Low tenure = higher risk
        tenure_years = Decimal(str(employee.years_of_service()))
        if tenure_years < 2:
            risk += Decimal("40")
        elif tenure_years < 5:
            risk += Decimal("20")

        # Performance factor: Low performance = higher risk
        if performance_rating < Decimal("3"):
            risk += Decimal("30")
        elif performance_rating >= Decimal("4.5"):
            risk -= Decimal("20")

        # Compensation factor: Underpaid = higher risk
        if employee.salary < market_salary * Decimal("0.9"):
            risk += Decimal("30")
        elif employee.salary > market_salary * Decimal("1.1"):
            risk -= Decimal("15")

        # Age/career stage: Early career = higher mobility
        if employee.age() < 35:
            risk += Decimal("10")

        return max(Decimal("0"), min(Decimal("100"), risk)).quantize(Decimal("0.01"))

    def generate_executive_summary(
        self,
        total_employees: int,
        turnover_rate: Decimal,
        engagement_index: Decimal,
        cost_per_hire: Decimal,
    ) -> dict[str, any]:
        """Generate executive summary dashboard metrics.

        Args:
            total_employees: Total headcount
            turnover_rate: Annual turnover rate
            engagement_index: Employee engagement score
            cost_per_hire: Average cost per hire

        Returns:
            Executive summary dictionary
        """
        return {
            "total_headcount": total_employees,
            "annualized_turnover_rate": turnover_rate,
            "employee_engagement_score": engagement_index,
            "cost_per_hire": cost_per_hire,
            "health_status": self._assess_health(turnover_rate, engagement_index),
            "generated_at": datetime.now(),
        }

    @staticmethod
    def _assess_health(turnover_rate: Decimal, engagement_index: Decimal) -> str:
        """Assess overall HR health.

        Args:
            turnover_rate: Annual turnover rate
            engagement_index: Engagement score (1-5)

        Returns:
            Health status (Excellent, Good, Fair, Poor)
        """
        if turnover_rate > Decimal("30") or engagement_index < Decimal("2.5"):
            return "Poor"
        elif turnover_rate > Decimal("20") or engagement_index < Decimal("3"):
            return "Fair"
        elif turnover_rate > Decimal("10") or engagement_index < Decimal("3.5"):
            return "Good"
        return "Excellent"
