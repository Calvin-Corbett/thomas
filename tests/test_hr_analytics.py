"""Tests for HR analytics system."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.hr_platform._exceptions import HRException
from thomas.marketplace.hr_platform._types import Employee, EmploymentStatus
from thomas.marketplace.hr_platform.analytics import (
    CompensationAnalytics,
    DiversityMetrics,
    EngagementMetrics,
    HRAnalytics,
    TurnoverAnalysis,
)


class TestTurnoverAnalysis:
    """Test turnover analysis functionality."""

    @pytest.fixture
    def analysis(self) -> TurnoverAnalysis:
        """Create turnover analysis."""
        return TurnoverAnalysis()

    def test_add_termination(self, analysis: TurnoverAnalysis) -> None:
        """Test recording termination."""
        emp = Employee(
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
            status=EmploymentStatus.TERMINATED,
            termination_date=date(2024, 6, 1),
        )

        analysis.add_termination(emp)

        assert len(analysis.terminations) == 1

    def test_turnover_rate(self, analysis: TurnoverAnalysis) -> None:
        """Test turnover rate calculation."""
        emp1 = Employee(
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
            status=EmploymentStatus.TERMINATED,
            termination_date=date(2024, 6, 1),
        )

        emp2 = Employee(
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
            salary=Decimal("100000"),
            status=EmploymentStatus.TERMINATED,
            termination_date=date(2024, 6, 15),
        )

        analysis.add_termination(emp1)
        analysis.add_termination(emp2)

        rate = analysis.calculate_turnover_rate(
            date(2024, 1, 1),
            date(2024, 12, 31),
            Decimal("100"),  # avg 100 employees
        )

        assert rate == Decimal("2.00")  # 2/100

    def test_voluntary_vs_involuntary(self, analysis: TurnoverAnalysis) -> None:
        """Test categorizing terminations."""
        emp = Employee(
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
            hire_date=date(2023, 6, 1),
            status=EmploymentStatus.TERMINATED,
            termination_date=date(2024, 6, 1),
        )

        analysis.add_termination(emp)

        voluntary, involuntary = analysis.voluntary_vs_involuntary(
            date(2024, 1, 1),
            date(2024, 12, 31),
        )

        assert voluntary + involuntary == 1

    def test_turnover_by_department(self, analysis: TurnoverAnalysis) -> None:
        """Test turnover by department."""
        emp1 = Employee(
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
            status=EmploymentStatus.TERMINATED,
            termination_date=date(2024, 6, 1),
        )

        emp2 = Employee(
            id="emp2",
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            phone="555-5678",
            ssn="987-65-4321",
            date_of_birth=date(1992, 6, 20),
            gender="F",
            position_id="pos1",
            department_id="dept2",
            salary=Decimal("100000"),
            status=EmploymentStatus.TERMINATED,
            termination_date=date(2024, 6, 15),
        )

        analysis.add_termination(emp1)
        analysis.add_termination(emp2)

        by_dept = analysis.turnover_by_department(
            date(2024, 1, 1),
            date(2024, 12, 31),
        )

        assert by_dept["dept1"] == 1
        assert by_dept["dept2"] == 1

    def test_turnover_by_tenure(self, analysis: TurnoverAnalysis) -> None:
        """Test turnover by tenure."""
        emp = Employee(
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
            hire_date=date(2024, 7, 1),  # ~1.7 years tenure
            status=EmploymentStatus.TERMINATED,
            termination_date=date(2026, 6, 1),
        )

        analysis.add_termination(emp)

        by_tenure = analysis.turnover_by_tenure(
            date(2026, 1, 1),
            date(2026, 12, 31),
        )

        assert by_tenure["1-2 years"] == 1


class TestDiversityMetrics:
    """Test diversity tracking."""

    @pytest.fixture
    def metrics(self) -> DiversityMetrics:
        """Create diversity metrics."""
        return DiversityMetrics()

    def test_record_eeo_category(self, metrics: DiversityMetrics) -> None:
        """Test recording EEO category."""
        metrics.record_employee_eeo_category("emp1", "Hispanic/Latino")

        assert metrics.employee_categories["emp1"] == "Hispanic/Latino"

    def test_invalid_eeo_category(self, metrics: DiversityMetrics) -> None:
        """Test error for invalid category."""
        with pytest.raises(HRException):
            metrics.record_employee_eeo_category("emp1", "Invalid")

    def test_diversity_distribution(self, metrics: DiversityMetrics) -> None:
        """Test diversity distribution calculation."""
        emp1 = Employee(
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
            status=EmploymentStatus.ACTIVE,
        )

        emp2 = Employee(
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
            salary=Decimal("100000"),
            status=EmploymentStatus.ACTIVE,
        )

        metrics.record_employee_eeo_category(emp1.id, "White")
        metrics.record_employee_eeo_category(emp2.id, "Asian")

        distribution = metrics.get_diversity_distribution([emp1, emp2])

        assert "White" in distribution
        assert "Asian" in distribution
        assert distribution["White"] == Decimal("50.00")

    def test_representation_index(self, metrics: DiversityMetrics) -> None:
        """Test representation index calculation."""
        index = metrics.get_representation_index(
            "White",
            100,
            Decimal("80"),
            Decimal("100"),
        )

        assert index == Decimal("80.00")


class TestCompensationAnalytics:
    """Test compensation analysis."""

    @pytest.fixture
    def analytics(self) -> CompensationAnalytics:
        """Create compensation analytics."""
        return CompensationAnalytics()

    def test_compa_ratio(self, analytics: CompensationAnalytics) -> None:
        """Test compa ratio calculation."""
        ratio = analytics.calculate_compa_ratio(
            Decimal("125000"),
            Decimal("125000"),
        )

        assert ratio == Decimal("100.00")

    def test_compa_ratio_above_midpoint(self, analytics: CompensationAnalytics) -> None:
        """Test compa ratio above midpoint."""
        ratio = analytics.calculate_compa_ratio(
            Decimal("150000"),
            Decimal("125000"),
        )

        assert ratio == Decimal("120.00")

    def test_range_penetration(self, analytics: CompensationAnalytics) -> None:
        """Test range penetration calculation."""
        penetration = analytics.calculate_range_penetration(
            Decimal("125000"),
            Decimal("100000"),
            Decimal("150000"),
        )

        assert penetration == Decimal("50.00")

    def test_pay_equity_analysis(self, analytics: CompensationAnalytics) -> None:
        """Test pay equity analysis."""
        employees_by_group = {
            "Men": [("emp1", Decimal("100000")), ("emp2", Decimal("110000"))],
            "Women": [("emp3", Decimal("95000")), ("emp4", Decimal("105000"))],
        }

        equity = analytics.pay_equity_analysis(employees_by_group)

        assert "Men" in equity
        assert "Women" in equity
        assert equity["Men"] == Decimal("105000.00")
        assert equity["Women"] == Decimal("100000.00")


class TestEngagementMetrics:
    """Test engagement metrics."""

    @pytest.fixture
    def metrics(self) -> EngagementMetrics:
        """Create engagement metrics."""
        return EngagementMetrics()

    def test_record_survey_response(self, metrics: EngagementMetrics) -> None:
        """Test recording survey response."""
        metrics.record_survey_response(
            "survey1",
            "emp1",
            Decimal("4.0"),
            {"engagement": Decimal("4.0"), "culture": Decimal("4.5")},
        )

        assert "emp1" in metrics.survey_responses

    def test_engagement_index(self, metrics: EngagementMetrics) -> None:
        """Test engagement index calculation."""
        metrics.record_survey_response(
            "survey1",
            "emp1",
            Decimal("4.0"),
            {"engagement": Decimal("4.0")},
        )

        metrics.record_survey_response(
            "survey1",
            "emp2",
            Decimal("3.0"),
            {"engagement": Decimal("3.0")},
        )

        index = metrics.calculate_engagement_index()

        assert index == Decimal("3.50")

    def test_dimension_scores(self, metrics: EngagementMetrics) -> None:
        """Test dimension score aggregation."""
        metrics.record_survey_response(
            "survey1",
            "emp1",
            Decimal("4.0"),
            {"engagement": Decimal("4.0"), "culture": Decimal("5.0")},
        )

        dimensions = metrics.get_dimension_scores()

        assert "engagement" in dimensions
        assert "culture" in dimensions


class TestHRAnalytics:
    """Test main analytics engine."""

    @pytest.fixture
    def analytics(self) -> HRAnalytics:
        """Create HR analytics."""
        return HRAnalytics()

    def test_cost_per_hire(self, analytics: HRAnalytics) -> None:
        """Test cost-per-hire calculation."""
        cost = analytics.calculate_cost_per_hire(
            Decimal("50000"),
            10,
        )

        assert cost == Decimal("5000.00")

    def test_headcount_trend(self, analytics: HRAnalytics) -> None:
        """Test headcount trend calculation."""
        trend_data = [
            (date(2024, 1, 1), 100),
            (date(2024, 12, 31), 110),
        ]

        growth = analytics.calculate_headcount_trend(trend_data)

        # 10% growth over 365 days
        assert growth > Decimal("0")

    def test_span_of_control_analysis(self, analytics: HRAnalytics) -> None:
        """Test span of control analysis."""
        manager_reports = {
            "mgr1": 5,
            "mgr2": 7,
            "mgr3": 4,
        }

        analysis = analytics.calculate_span_of_control_analysis(manager_reports)

        assert analysis["average_span"] == Decimal("5.33")
        assert analysis["min_span"] == 4
        assert analysis["max_span"] == 7

    def test_flight_risk_prediction(self, analytics: HRAnalytics) -> None:
        """Test flight risk prediction."""
        emp = Employee(
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
            hire_date=date(2022, 1, 1),
        )

        risk = analytics.flight_risk_prediction(
            emp,
            Decimal("3.0"),
            Decimal("110000"),
        )

        assert Decimal("0") <= risk <= Decimal("100")

    def test_executive_summary(self, analytics: HRAnalytics) -> None:
        """Test executive summary generation."""
        summary = analytics.generate_executive_summary(
            total_employees=100,
            turnover_rate=Decimal("15.00"),
            engagement_index=Decimal("3.5"),
            cost_per_hire=Decimal("5000"),
        )

        assert summary["total_headcount"] == 100
        assert summary["annualized_turnover_rate"] == Decimal("15.00")
        assert "health_status" in summary

    def test_health_assessment_excellent(self, analytics: HRAnalytics) -> None:
        """Test health assessment excellent."""
        health = analytics._assess_health(Decimal("5.00"), Decimal("4.5"))

        assert health == "Excellent"

    def test_health_assessment_poor(self, analytics: HRAnalytics) -> None:
        """Test health assessment poor."""
        health = analytics._assess_health(Decimal("35.00"), Decimal("2.0"))

        assert health == "Poor"
