"""
Tests for the reporting engine.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from thomas.marketplace.crm._types import Activity, ActivityType, Deal
from thomas.marketplace.crm.reporting import ReportingEngine


@pytest.fixture
def reporting_engine() -> ReportingEngine:
    """Create a reporting engine instance."""
    return ReportingEngine()


@pytest.fixture
def sample_deals() -> list:
    """Create sample deals for testing."""
    return [
        Deal(
            id="deal-1",
            name="Deal 1",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("10000"),
            probability=30,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        ),
        Deal(
            id="deal-2",
            name="Deal 2",
            company_id="company-2",
            contact_id="contact-2",
            stage_id="stage-2",
            value=Decimal("25000"),
            probability=60,
            expected_close=datetime.utcnow() + timedelta(days=45),
            owner="Jane",
        ),
        Deal(
            id="deal-3",
            name="Deal 3",
            company_id="company-3",
            contact_id="contact-3",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=80,
            expected_close=datetime.utcnow() + timedelta(days=60),
            owner="John",
        ),
    ]


@pytest.fixture
def pipeline_stages() -> dict:
    """Create sample pipeline stages."""
    return {
        "stage-1": "Lead",
        "stage-2": "Qualified",
        "stage-3": "Proposal",
        "stage-4": "Won",
        "stage-5": "Lost",
    }


class TestPipelineReport:
    """Test pipeline reporting."""

    def test_generate_pipeline_report(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
        pipeline_stages: dict,
    ) -> None:
        """Test generating a pipeline report."""
        report = reporting_engine.generate_pipeline_report(
            sample_deals,
            pipeline_stages,
        )

        assert "total_deals" in report
        assert report["total_deals"] == 3
        assert "total_pipeline_value" in report
        assert report["total_pipeline_value"] == Decimal("85000")

    def test_pipeline_report_by_stage(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
        pipeline_stages: dict,
    ) -> None:
        """Test pipeline report includes stage breakdown."""
        report = reporting_engine.generate_pipeline_report(
            sample_deals,
            pipeline_stages,
        )

        assert "by_stage" in report
        assert "stage-1" in report["by_stage"]
        assert report["by_stage"]["stage-1"]["count"] == 2

    def test_pipeline_report_by_owner(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
        pipeline_stages: dict,
    ) -> None:
        """Test pipeline report includes owner breakdown."""
        report = reporting_engine.generate_pipeline_report(
            sample_deals,
            pipeline_stages,
        )

        assert "by_owner" in report
        assert "John" in report["by_owner"]
        assert report["by_owner"]["John"]["count"] == 2

    def test_weighted_forecast(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
        pipeline_stages: dict,
    ) -> None:
        """Test weighted forecast in pipeline report."""
        report = reporting_engine.generate_pipeline_report(
            sample_deals,
            pipeline_stages,
        )

        # Forecast should be weighted by probability
        # 10000*0.3 + 25000*0.6 + 50000*0.8 = 3000 + 15000 + 40000 = 58000
        assert report["weighted_forecast"] == Decimal("58000")


class TestActivityReport:
    """Test activity reporting."""

    def test_generate_activity_report(self, reporting_engine: ReportingEngine) -> None:
        """Test generating an activity report."""
        activities = [
            Activity(
                id="activity-1",
                type=ActivityType.CALL,
                contact_id="contact-1",
                deal_id="deal-1",
                timestamp=datetime.utcnow(),
                notes="Discussed pricing",
                duration=30,
                user="John",
            ),
            Activity(
                id="activity-2",
                type=ActivityType.EMAIL,
                contact_id="contact-2",
                deal_id="deal-2",
                timestamp=datetime.utcnow() - timedelta(days=1),
                notes="Sent proposal",
                user="Jane",
            ),
        ]

        report = reporting_engine.generate_activity_report(activities)

        assert "total_activities" in report
        assert report["total_activities"] == 2

    def test_activity_report_by_type(self, reporting_engine: ReportingEngine) -> None:
        """Test activity report includes breakdown by type."""
        activities = [
            Activity(
                id="activity-1",
                type=ActivityType.CALL,
                contact_id="contact-1",
                deal_id=None,
                timestamp=datetime.utcnow(),
                notes="Call 1",
            ),
            Activity(
                id="activity-2",
                type=ActivityType.CALL,
                contact_id="contact-2",
                deal_id=None,
                timestamp=datetime.utcnow(),
                notes="Call 2",
            ),
            Activity(
                id="activity-3",
                type=ActivityType.EMAIL,
                contact_id="contact-3",
                deal_id=None,
                timestamp=datetime.utcnow(),
                notes="Email",
            ),
        ]

        report = reporting_engine.generate_activity_report(activities)

        assert report["by_type"]["call"] == 2
        assert report["by_type"]["email"] == 1

    def test_activity_duration_stats(self, reporting_engine: ReportingEngine) -> None:
        """Test activity report includes duration statistics."""
        activities = [
            Activity(
                id="activity-1",
                type=ActivityType.CALL,
                contact_id="contact-1",
                deal_id=None,
                timestamp=datetime.utcnow(),
                notes="Call 1",
                duration=30,
            ),
            Activity(
                id="activity-2",
                type=ActivityType.CALL,
                contact_id="contact-2",
                deal_id=None,
                timestamp=datetime.utcnow(),
                notes="Call 2",
                duration=45,
            ),
        ]

        report = reporting_engine.generate_activity_report(activities)

        assert report["total_duration_minutes"] == 75
        assert report["average_duration_minutes"] == 37.5


class TestWinLossReport:
    """Test win/loss reporting."""

    def test_generate_win_loss_report(
        self,
        reporting_engine: ReportingEngine,
    ) -> None:
        """Test generating a win/loss report."""
        won_deals = [
            Deal(
                id="deal-1",
                name="Won Deal 1",
                company_id="company-1",
                contact_id="contact-1",
                stage_id="stage-won",
                value=Decimal("50000"),
                probability=100,
                expected_close=datetime.utcnow(),
                owner="John",
            ),
        ]

        lost_deals = [
            Deal(
                id="deal-2",
                name="Lost Deal 1",
                company_id="company-2",
                contact_id="contact-2",
                stage_id="stage-lost",
                value=Decimal("25000"),
                probability=0,
                expected_close=datetime.utcnow(),
                owner="Jane",
            ),
        ]

        report = reporting_engine.generate_win_loss_report(won_deals, lost_deals)

        assert report["total_deals"] == 2
        assert report["won_deals"] == 1
        assert report["lost_deals"] == 1
        assert report["win_rate"] == 50.0

    def test_win_loss_avg_size(
        self,
        reporting_engine: ReportingEngine,
    ) -> None:
        """Test win/loss report includes average deal sizes."""
        won_deals = [
            Deal(
                id="deal-1",
                name="Won 1",
                company_id="company-1",
                contact_id="contact-1",
                stage_id="stage-won",
                value=Decimal("50000"),
                probability=100,
                expected_close=datetime.utcnow(),
                owner="John",
            ),
            Deal(
                id="deal-3",
                name="Won 2",
                company_id="company-3",
                contact_id="contact-3",
                stage_id="stage-won",
                value=Decimal("60000"),
                probability=100,
                expected_close=datetime.utcnow(),
                owner="John",
            ),
        ]

        lost_deals = [
            Deal(
                id="deal-2",
                name="Lost 1",
                company_id="company-2",
                contact_id="contact-2",
                stage_id="stage-lost",
                value=Decimal("20000"),
                probability=0,
                expected_close=datetime.utcnow(),
                owner="Jane",
            ),
        ]

        report = reporting_engine.generate_win_loss_report(won_deals, lost_deals)

        assert report["avg_won_size"] == Decimal("55000")
        assert report["avg_lost_size"] == Decimal("20000")


class TestRevenueReport:
    """Test revenue reporting."""

    def test_generate_revenue_report(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test generating a revenue report."""
        report = reporting_engine.generate_revenue_report(sample_deals)

        assert "total_deals" in report
        assert report["total_deals"] == 3
        assert "total_value" in report

    def test_revenue_report_forecast(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test revenue report includes forecast."""
        report = reporting_engine.generate_revenue_report(sample_deals)

        assert "total_forecast" in report


class TestLeaderboard:
    """Test leaderboard generation."""

    def test_generate_leaderboard(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test generating a sales leaderboard."""
        leaderboard = reporting_engine.generate_leaderboard(sample_deals)

        assert len(leaderboard) == 2  # John and Jane
        assert leaderboard[0]["rank"] == 1

    def test_leaderboard_by_value(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test leaderboard sorted by deal value."""
        leaderboard = reporting_engine.generate_leaderboard(
            sample_deals,
            metric="value",
        )

        # John should be first (60k > 25k)
        assert leaderboard[0]["owner"] == "John"


class TestFunnelAnalysis:
    """Test funnel analysis."""

    def test_generate_funnel_report(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test generating a sales funnel report."""
        stages = [
            ("stage-1", "Lead"),
            ("stage-2", "Qualified"),
            ("stage-3", "Proposal"),
            ("stage-4", "Won"),
        ]

        report = reporting_engine.generate_funnel_report(sample_deals, stages)

        assert "funnel" in report
        assert len(report["funnel"]) == 4

    def test_funnel_conversion_rates(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test funnel includes conversion rates."""
        stages = [
            ("stage-1", "Lead"),
            ("stage-2", "Qualified"),
            ("stage-3", "Proposal"),
            ("stage-4", "Won"),
        ]

        report = reporting_engine.generate_funnel_report(sample_deals, stages)

        # All stages should have conversion rates
        for stage in report["funnel"]:
            assert "conversion_rate" in stage


class TestCohortAnalysis:
    """Test cohort analysis."""

    def test_generate_cohort_report(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test generating a cohort analysis report."""
        stages = {
            "stage-1": "Lead",
            "stage-2": "Qualified",
            "stage-3": "Proposal",
        }

        report = reporting_engine.generate_cohort_report(sample_deals, stages)

        assert "cohorts" in report
        assert len(report["cohorts"]) > 0

    def test_cohort_deals_by_stage(
        self,
        reporting_engine: ReportingEngine,
        sample_deals: list,
    ) -> None:
        """Test cohort report includes stage breakdown."""
        stages = {
            "stage-1": "Lead",
            "stage-2": "Qualified",
        }

        report = reporting_engine.generate_cohort_report(sample_deals, stages)

        for cohort in report["cohorts"]:
            assert "by_stage" in cohort
            assert "total_deals" in cohort
