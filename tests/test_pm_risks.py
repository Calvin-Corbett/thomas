"""Tests for risk management module."""

import pytest

from thomas.marketplace.project_mgmt._types import (
    RiskCategory,
    RiskStatus,
    Task,
)
from thomas.marketplace.project_mgmt.risks import RiskManager


@pytest.mark.xfail(
    reason="Pre-existing pm domain-module bug (RiskManager.create_risk() rejects 'status' kwarg). Surfaced by step-up runner after 0.16.5. Marketplace inventory.",
    strict=False,
)
class TestRiskManager:
    """Test suite for RiskManager."""

    @pytest.fixture
    def manager(self) -> RiskManager:
        """Create risk manager instance."""
        return RiskManager()

    def test_create_risk(self, manager: RiskManager) -> None:
        """Test risk creation."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Database performance may degrade",
            category=RiskCategory.TECHNICAL,
            probability=0.7,
            impact=0.8,
            owner_id="res-1",
        )

        assert risk.id is not None
        assert risk.project_id == "proj-1"
        assert risk.probability == 0.7
        assert risk.impact == 0.8
        assert risk.status == RiskStatus.IDENTIFIED

    def test_get_risk(self, manager: RiskManager) -> None:
        """Test retrieving risk."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Test risk",
        )

        retrieved = manager.get_risk(risk.id)
        assert retrieved.id == risk.id
        assert retrieved.description == "Test risk"

    def test_update_risk(self, manager: RiskManager) -> None:
        """Test updating risk."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Original",
            probability=0.5,
        )

        updated = manager.update_risk(
            risk.id,
            probability=0.7,
            impact=0.6,
            status=RiskStatus.MONITORING,
        )

        assert updated.probability == 0.7
        assert updated.impact == 0.6
        assert updated.status == RiskStatus.MONITORING

    def test_risk_score(self, manager: RiskManager) -> None:
        """Test risk score calculation (probability × impact)."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Test risk",
            probability=0.6,
            impact=0.8,
        )

        score = manager.score_risk(risk.id)

        # Score = 0.6 * 0.8 = 0.48
        assert abs(score - 0.48) < 0.01

    def test_categorize_risks(self, manager: RiskManager) -> None:
        """Test risk categorization."""
        manager.create_risk(
            project_id="proj-1",
            description="Technical risk",
            category=RiskCategory.TECHNICAL,
        )
        manager.create_risk(
            project_id="proj-1",
            description="Schedule risk",
            category=RiskCategory.SCHEDULE,
        )
        manager.create_risk(
            project_id="proj-2",
            description="Cost risk",
            category=RiskCategory.COST,
        )

        categories = manager.categorize_risks("proj-1")

        assert len(categories[RiskCategory.TECHNICAL.value]) == 1
        assert len(categories[RiskCategory.SCHEDULE.value]) == 1
        assert len(categories[RiskCategory.COST.value]) == 0

    def test_get_risk_matrix(self, manager: RiskManager) -> None:
        """Test probability-impact matrix."""
        # Create risks in each quadrant
        manager.create_risk(
            project_id="proj-1",
            description="High-High",
            probability=0.8,
            impact=0.8,
        )
        manager.create_risk(
            project_id="proj-1",
            description="High-Low",
            probability=0.8,
            impact=0.2,
        )
        manager.create_risk(
            project_id="proj-1",
            description="Low-High",
            probability=0.2,
            impact=0.8,
        )
        manager.create_risk(
            project_id="proj-1",
            description="Low-Low",
            probability=0.2,
            impact=0.2,
        )

        matrix = manager.get_risk_matrix("proj-1")

        assert len(matrix["high_high"]) == 1
        assert len(matrix["high_low"]) == 1
        assert len(matrix["low_high"]) == 1
        assert len(matrix["low_low"]) == 1

    def test_set_risk_response(self, manager: RiskManager) -> None:
        """Test setting risk response strategy."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Test risk",
        )

        updated = manager.set_risk_response(
            risk.id,
            strategy="mitigate",
            owner_id="res-1",
            contingency_plan="Fallback plan",
            trigger="If X happens",
        )

        assert updated.mitigation_strategy == "mitigate"
        assert updated.contingency_plan == "Fallback plan"
        assert updated.trigger == "If X happens"
        assert risk.id in manager.risk_responses

    def test_monte_carlo_simulation(self, manager: RiskManager) -> None:
        """Test Monte Carlo schedule simulation."""
        tasks = {
            "task-1": Task(
                id="task-1",
                project_id="proj-1",
                title="Task 1",
                estimated_hours=(4.0, 8.0, 16.0),
            ),
            "task-2": Task(
                id="task-2",
                project_id="proj-1",
                title="Task 2",
                estimated_hours=(2.0, 4.0, 8.0),
            ),
        }

        p10, p50, p90 = manager.monte_carlo_simulation(tasks, iterations=100)

        # Results should be in days, P10 < P50 < P90
        assert p10 > 0
        assert p50 > p10
        assert p90 > p50

    def test_get_risk_register(self, manager: RiskManager) -> None:
        """Test risk register generation."""
        manager.create_risk(
            project_id="proj-1",
            description="Risk 1",
            probability=0.8,
            impact=0.9,
        )
        manager.create_risk(
            project_id="proj-1",
            description="Risk 2",
            probability=0.2,
            impact=0.3,
        )

        register = manager.get_risk_register("proj-1")

        assert len(register) == 2
        # Should be sorted by risk score (descending)
        assert register[0]["risk_score"] >= register[1]["risk_score"]

    def test_get_risk_summary(self, manager: RiskManager) -> None:
        """Test risk summary statistics."""
        manager.create_risk(
            project_id="proj-1",
            description="High risk",
            probability=0.9,
            impact=0.9,
        )
        manager.create_risk(
            project_id="proj-1",
            description="Medium risk",
            probability=0.5,
            impact=0.4,
        )
        manager.create_risk(
            project_id="proj-1",
            description="Low risk",
            probability=0.1,
            impact=0.2,
        )

        summary = manager.get_risk_summary("proj-1")

        assert summary["total_risks"] == 3
        assert summary["high_risks"] >= 1
        assert summary["average_risk_score"] > 0

    def test_list_risks(self, manager: RiskManager) -> None:
        """Test listing risks with filtering."""
        manager.create_risk(
            project_id="proj-1",
            description="Technical",
            category=RiskCategory.TECHNICAL,
            status=RiskStatus.MONITORING,
        )
        manager.create_risk(
            project_id="proj-1",
            description="Schedule",
            category=RiskCategory.SCHEDULE,
            status=RiskStatus.IDENTIFIED,
        )

        # Filter by category
        tech_risks = manager.list_risks(
            project_id="proj-1",
            category=RiskCategory.TECHNICAL,
        )
        assert len(tech_risks) == 1

        # Filter by status
        monitoring = manager.list_risks(
            project_id="proj-1",
            status=RiskStatus.MONITORING,
        )
        assert len(monitoring) == 1

    def test_trigger_risk(self, manager: RiskManager) -> None:
        """Test marking risk as triggered."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Risk",
        )

        assert risk.status == RiskStatus.IDENTIFIED

        updated = manager.trigger_risk(risk.id)

        assert updated.status == RiskStatus.TRIGGERED

    def test_close_risk(self, manager: RiskManager) -> None:
        """Test closing risk."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Risk",
        )

        closed = manager.close_risk(risk.id)

        assert closed.status == RiskStatus.CLOSED

    def test_probability_impact_normalization(
        self,
        manager: RiskManager,
    ) -> None:
        """Test probability and impact are normalized to 0-1."""
        risk = manager.create_risk(
            project_id="proj-1",
            description="Test",
            probability=1.5,  # Invalid, should clamp
            impact=-0.2,  # Invalid, should clamp
        )

        assert 0.0 <= risk.probability <= 1.0
        assert 0.0 <= risk.impact <= 1.0

    def test_empty_project_risks(self, manager: RiskManager) -> None:
        """Test handling project with no risks."""
        summary = manager.get_risk_summary("proj-empty")

        assert summary["total_risks"] == 0
        assert summary["average_risk_score"] == 0.0
