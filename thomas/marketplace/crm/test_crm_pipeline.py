"""
Tests for the sales pipeline management system.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from thomas.marketplace.crm._exceptions import (
    InvalidStageError,
    PipelineNotFoundError,
)
from thomas.marketplace.crm._types import Deal, Pipeline
from thomas.marketplace.crm.pipeline import PipelineManager


@pytest.fixture
def pipeline_manager() -> PipelineManager:
    """Create a pipeline manager instance."""
    return PipelineManager()


@pytest.fixture
def sample_pipeline(pipeline_manager: PipelineManager) -> Pipeline:
    """Create a sample pipeline."""
    return pipeline_manager.create_pipeline(
        name="Sales Pipeline",
        stages=[
            ("Lead", 1, False, False),
            ("Qualified", 2, False, False),
            ("Proposal", 3, False, False),
            ("Won", 4, True, False),
            ("Lost", 5, False, True),
        ],
    )


class TestPipelineCreation:
    """Test pipeline creation and management."""

    def test_create_pipeline(self, pipeline_manager: PipelineManager) -> None:
        """Test creating a pipeline."""
        pipeline = pipeline_manager.create_pipeline(
            name="Sales Pipeline",
            stages=[
                ("Lead", 1, False, False),
                ("Won", 2, True, False),
            ],
        )

        assert pipeline.name == "Sales Pipeline"
        assert len(pipeline.stages) == 2
        assert pipeline.stages[0].name == "Lead"

    def test_get_pipeline(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test getting a pipeline."""
        retrieved = pipeline_manager.get_pipeline(sample_pipeline.id)

        assert retrieved.id == sample_pipeline.id
        assert retrieved.name == "Sales Pipeline"

    def test_get_nonexistent_pipeline(self, pipeline_manager: PipelineManager) -> None:
        """Test getting a non-existent pipeline raises error."""
        with pytest.raises(PipelineNotFoundError):
            pipeline_manager.get_pipeline("nonexistent-id")

    def test_list_pipelines(self, pipeline_manager: PipelineManager) -> None:
        """Test listing pipelines."""
        pipeline_manager.create_pipeline(
            name="Pipeline 1",
            stages=[("Lead", 1, False, False)],
        )
        pipeline_manager.create_pipeline(
            name="Pipeline 2",
            stages=[("Lead", 1, False, False)],
        )

        pipelines = pipeline_manager.list_pipelines()

        assert len(pipelines) == 2


class TestDealMovement:
    """Test moving deals between stages."""

    def test_add_deal(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test adding a deal to the pipeline."""
        deal = Deal(
            id="deal-1",
            name="Big Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id=sample_pipeline.stages[0].id,
            value=Decimal("10000"),
            probability=30,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        pipeline_manager.add_deal(deal)

        deals = pipeline_manager.get_pipeline_deals(sample_pipeline.id)
        assert len(deals) == 1

    def test_move_deal(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test moving a deal to a different stage."""
        deal = Deal(
            id="deal-1",
            name="Big Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id=sample_pipeline.stages[0].id,
            value=Decimal("10000"),
            probability=30,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        pipeline_manager.add_deal(deal)

        moved = pipeline_manager.move_deal(
            deal.id,
            sample_pipeline.stages[1].id,
            sample_pipeline.id,
        )

        assert moved.stage_id == sample_pipeline.stages[1].id

    def test_move_deal_to_invalid_stage(
        self,
        sample_pipeline: Pipeline,
        pipeline_manager: PipelineManager,
    ) -> None:
        """Test moving a deal to an invalid stage raises error."""
        deal = Deal(
            id="deal-1",
            name="Big Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id=sample_pipeline.stages[0].id,
            value=Decimal("10000"),
            probability=30,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        pipeline_manager.add_deal(deal)

        with pytest.raises(InvalidStageError):
            pipeline_manager.move_deal(
                deal.id,
                "invalid-stage",
                sample_pipeline.id,
            )


class TestPipelineAnalytics:
    """Test pipeline analytics."""

    def test_conversion_rates(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test calculating conversion rates."""
        # Add deals at different stages
        deal1 = Deal(
            id="deal-1",
            name="Deal 1",
            company_id="company-1",
            contact_id="contact-1",
            stage_id=sample_pipeline.stages[0].id,
            value=Decimal("10000"),
            probability=30,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        deal2 = Deal(
            id="deal-2",
            name="Deal 2",
            company_id="company-2",
            contact_id="contact-2",
            stage_id=sample_pipeline.stages[0].id,
            value=Decimal("15000"),
            probability=40,
            expected_close=datetime.utcnow() + timedelta(days=45),
            owner="Jane",
        )

        pipeline_manager.add_deal(deal1)
        pipeline_manager.add_deal(deal2)

        # Move one to next stage
        pipeline_manager.move_deal(
            deal1.id,
            sample_pipeline.stages[1].id,
            sample_pipeline.id,
        )

        rates = pipeline_manager.calculate_conversion_rates(sample_pipeline.id)

        assert len(rates) > 0

    def test_average_deal_size(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test calculating average deal size."""
        pipeline_manager.add_deal(
            Deal(
                id="deal-1",
                name="Deal 1",
                company_id="company-1",
                contact_id="contact-1",
                stage_id=sample_pipeline.stages[0].id,
                value=Decimal("10000"),
                probability=30,
                expected_close=datetime.utcnow() + timedelta(days=30),
                owner="John",
            )
        )

        pipeline_manager.add_deal(
            Deal(
                id="deal-2",
                name="Deal 2",
                company_id="company-2",
                contact_id="contact-2",
                stage_id=sample_pipeline.stages[0].id,
                value=Decimal("20000"),
                probability=40,
                expected_close=datetime.utcnow() + timedelta(days=45),
                owner="Jane",
            )
        )

        avg = pipeline_manager.calculate_average_deal_size(sample_pipeline.id)

        assert avg == Decimal("15000")

    def test_weighted_forecast(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test calculating weighted forecast."""
        pipeline_manager.add_deal(
            Deal(
                id="deal-1",
                name="Deal 1",
                company_id="company-1",
                contact_id="contact-1",
                stage_id=sample_pipeline.stages[0].id,
                value=Decimal("10000"),
                probability=50,
                expected_close=datetime.utcnow() + timedelta(days=30),
                owner="John",
            )
        )

        forecast = pipeline_manager.calculate_weighted_forecast(sample_pipeline.id)

        # 10000 * 50% = 5000
        assert forecast == Decimal("5000")

    def test_forecast_by_owner(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test getting forecast by owner."""
        pipeline_manager.add_deal(
            Deal(
                id="deal-1",
                name="Deal 1",
                company_id="company-1",
                contact_id="contact-1",
                stage_id=sample_pipeline.stages[0].id,
                value=Decimal("10000"),
                probability=50,
                expected_close=datetime.utcnow() + timedelta(days=30),
                owner="John",
            )
        )

        pipeline_manager.add_deal(
            Deal(
                id="deal-2",
                name="Deal 2",
                company_id="company-2",
                contact_id="contact-2",
                stage_id=sample_pipeline.stages[0].id,
                value=Decimal("20000"),
                probability=50,
                expected_close=datetime.utcnow() + timedelta(days=30),
                owner="Jane",
            )
        )

        forecast = pipeline_manager.get_forecast_by_owner(sample_pipeline.id)

        assert "John" in forecast
        assert "Jane" in forecast
        assert forecast["John"] == Decimal("5000")
        assert forecast["Jane"] == Decimal("10000")


class TestBottleneckDetection:
    """Test bottleneck detection."""

    def test_detect_bottleneck(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test detecting deals stuck in a stage."""
        # Create a deal with old stage entry time
        deal = Deal(
            id="deal-1",
            name="Deal 1",
            company_id="company-1",
            contact_id="contact-1",
            stage_id=sample_pipeline.stages[0].id,
            value=Decimal("10000"),
            probability=30,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        # Set stage entered time to 40 days ago
        deal.stage_entered_at = datetime.utcnow() - timedelta(days=40)

        pipeline_manager.add_deal(deal)

        bottlenecks = pipeline_manager.detect_bottlenecks(
            sample_pipeline.id,
            threshold_days=30,
        )

        assert len(bottlenecks) == 1
        assert bottlenecks[0]["deal_id"] == "deal-1"
        assert bottlenecks[0]["days_in_stage"] > 30


class TestStageDistribution:
    """Test stage distribution reporting."""

    def test_stage_distribution(self, sample_pipeline: Pipeline, pipeline_manager: PipelineManager) -> None:
        """Test getting deal distribution across stages."""
        stage1_id = sample_pipeline.stages[0].id
        stage2_id = sample_pipeline.stages[1].id

        pipeline_manager.add_deal(
            Deal(
                id="deal-1",
                name="Deal 1",
                company_id="company-1",
                contact_id="contact-1",
                stage_id=stage1_id,
                value=Decimal("10000"),
                probability=30,
                expected_close=datetime.utcnow() + timedelta(days=30),
                owner="John",
            )
        )

        pipeline_manager.add_deal(
            Deal(
                id="deal-2",
                name="Deal 2",
                company_id="company-2",
                contact_id="contact-2",
                stage_id=stage1_id,
                value=Decimal("20000"),
                probability=40,
                expected_close=datetime.utcnow() + timedelta(days=45),
                owner="Jane",
            )
        )

        pipeline_manager.add_deal(
            Deal(
                id="deal-3",
                name="Deal 3",
                company_id="company-3",
                contact_id="contact-3",
                stage_id=stage2_id,
                value=Decimal("15000"),
                probability=50,
                expected_close=datetime.utcnow() + timedelta(days=60),
                owner="John",
            )
        )

        distribution = pipeline_manager.get_stage_distribution(sample_pipeline.id)

        assert distribution[stage1_id] == 2
        assert distribution[stage2_id] == 1
