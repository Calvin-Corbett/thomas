"""
Sales pipeline management for the CRM.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from thomas.crm._exceptions import (
    DealNotFoundError,
    InvalidStageError,
    PipelineNotFoundError,
)
from thomas.crm._types import Deal, Pipeline, Stage


class PipelineManager:
    """Manages sales pipelines in the CRM system.

    Handles pipeline creation, stage configuration, deal movement,
    analytics, forecasting, and bottleneck detection.
    """

    def __init__(self) -> None:
        """Initialize the pipeline manager."""
        self._pipelines: dict[str, Pipeline] = {}
        self._deals: dict[str, Deal] = {}
        self._stage_history: dict[str, list[dict[str, Any]]] = {}

    def create_pipeline(
        self,
        name: str,
        stages: list[tuple[str, int, bool, bool]],
    ) -> Pipeline:
        """Create a new pipeline with stages.

        Args:
            name: Pipeline name
            stages: List of tuples (stage_name, order, is_closed_won, is_closed_lost)

        Returns:
            Created Pipeline object
        """
        pipeline_id = str(uuid.uuid4())

        stage_objects = [
            Stage(
                id=str(uuid.uuid4()),
                name=stage_name,
                order=order,
                is_closed_won=closed_won,
                is_closed_lost=closed_lost,
            )
            for stage_name, order, closed_won, closed_lost in stages
        ]

        pipeline = Pipeline(
            id=pipeline_id,
            name=name,
            stages=sorted(stage_objects, key=lambda s: s.order),
        )

        self._pipelines[pipeline_id] = pipeline
        return pipeline

    def get_pipeline(self, pipeline_id: str) -> Pipeline:
        """Get a pipeline by ID.

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            Pipeline object

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        if pipeline_id not in self._pipelines:
            raise PipelineNotFoundError(f"Pipeline {pipeline_id} not found")
        return self._pipelines[pipeline_id]

    def list_pipelines(self) -> list[Pipeline]:
        """Get all pipelines.

        Returns:
            List of Pipeline objects
        """
        return list(self._pipelines.values())

    def add_deal(self, deal: Deal) -> None:
        """Add a deal to the pipeline.

        Args:
            deal: Deal object to add
        """
        self._deals[deal.id] = deal
        self._stage_history[deal.id] = []

        # Log initial stage entry
        self._stage_history[deal.id].append(
            {
                "stage_id": deal.stage_id,
                "entered_at": deal.created_at.isoformat(),
                "exited_at": None,
            }
        )

    def move_deal(
        self,
        deal_id: str,
        new_stage_id: str,
        pipeline_id: str,
    ) -> Deal:
        """Move a deal to a different stage.

        Args:
            deal_id: Deal identifier
            new_stage_id: New stage identifier
            pipeline_id: Pipeline identifier

        Returns:
            Updated Deal object

        Raises:
            DealNotFoundError: If deal not found
            InvalidStageError: If stage is invalid for the pipeline
        """
        if deal_id not in self._deals:
            raise DealNotFoundError(f"Deal {deal_id} not found")

        pipeline = self.get_pipeline(pipeline_id)
        new_stage = pipeline.get_stage_by_id(new_stage_id)

        if not new_stage:
            raise InvalidStageError(f"Stage {new_stage_id} not in pipeline")

        deal = self._deals[deal_id]

        # Close out previous stage entry
        if self._stage_history[deal_id]:
            self._stage_history[deal_id][-1]["exited_at"] = datetime.utcnow().isoformat()

        # Record new stage entry
        self._stage_history[deal_id].append(
            {
                "stage_id": new_stage_id,
                "entered_at": datetime.utcnow().isoformat(),
                "exited_at": None,
            }
        )

        deal.stage_id = new_stage_id
        deal.stage_entered_at = datetime.utcnow()

        return deal

    def get_deals_by_stage(
        self,
        pipeline_id: str,
        stage_id: str,
    ) -> list[Deal]:
        """Get all deals in a specific stage.

        Args:
            pipeline_id: Pipeline identifier
            stage_id: Stage identifier

        Returns:
            List of Deal objects in that stage

        Raises:
            InvalidStageError: If stage is invalid for the pipeline
        """
        pipeline = self.get_pipeline(pipeline_id)

        if not pipeline.get_stage_by_id(stage_id):
            raise InvalidStageError(f"Stage {stage_id} not in pipeline")

        return [deal for deal in self._deals.values() if deal.stage_id == stage_id]

    def get_pipeline_deals(self, pipeline_id: str) -> list[Deal]:
        """Get all deals in a pipeline.

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            List of Deal objects

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        self.get_pipeline(pipeline_id)
        return list(self._deals.values())

    def get_stage_duration(self, deal_id: str) -> timedelta | None:
        """Get the current duration in the current stage.

        Args:
            deal_id: Deal identifier

        Returns:
            Duration as timedelta or None

        Raises:
            DealNotFoundError: If deal not found
        """
        if deal_id not in self._deals:
            raise DealNotFoundError(f"Deal {deal_id} not found")

        deal = self._deals[deal_id]
        return datetime.utcnow() - deal.stage_entered_at

    def calculate_conversion_rates(
        self,
        pipeline_id: str,
    ) -> dict[str, float]:
        """Calculate conversion rates stage-to-stage.

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            Dictionary mapping "stage_from->stage_to" to conversion rate

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        pipeline = self.get_pipeline(pipeline_id)

        conversion_rates = {}

        # Analyze all deals and their stage transitions
        stage_transitions: dict[tuple[str, str], int] = {}
        stage_entries: dict[str, int] = {}

        for deal in self._deals.values():
            history = self._stage_history.get(deal.id, [])

            for i, entry in enumerate(history):
                stage_id = entry["stage_id"]
                stage_entries[stage_id] = stage_entries.get(stage_id, 0) + 1

                # Check if there's a next stage
                if i + 1 < len(history):
                    next_stage_id = history[i + 1]["stage_id"]
                    key = (stage_id, next_stage_id)
                    stage_transitions[key] = stage_transitions.get(key, 0) + 1

        # Calculate rates
        for (from_stage, to_stage), count in stage_transitions.items():
            total_from = stage_entries.get(from_stage, 0)

            if total_from > 0:
                rate = count / total_from
                conversion_rates[f"{from_stage}->{to_stage}"] = rate

        return conversion_rates

    def calculate_average_deal_size(
        self,
        pipeline_id: str,
        stage_id: str | None = None,
    ) -> Decimal:
        """Calculate average deal size.

        Args:
            pipeline_id: Pipeline identifier
            stage_id: Optional stage to filter by

        Returns:
            Average deal value

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        self.get_pipeline(pipeline_id)

        deals = self._deals.values()

        if stage_id:
            deals = [d for d in deals if d.stage_id == stage_id]

        if not deals:
            return Decimal(0)

        total = sum(d.value for d in deals)
        return total / Decimal(len(deals))

    def calculate_average_cycle_time(
        self,
        pipeline_id: str,
    ) -> timedelta | None:
        """Calculate average sales cycle time.

        Based on deals that have been won or lost.

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            Average cycle time or None if no closed deals

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        pipeline = self.get_pipeline(pipeline_id)

        cycle_times = []

        for deal in self._deals.values():
            history = self._stage_history.get(deal.id, [])

            if history:
                first_entry = history[0]
                last_entry = history[-1]

                first_time = datetime.fromisoformat(first_entry["entered_at"])
                last_time = datetime.fromisoformat(last_entry["exited_at"]) if last_entry["exited_at"] else None

                if last_time:
                    cycle_time = last_time - first_time
                    cycle_times.append(cycle_time)

        if not cycle_times:
            return None

        total_seconds = sum(ct.total_seconds() for ct in cycle_times)
        avg_seconds = total_seconds / len(cycle_times)

        return timedelta(seconds=avg_seconds)

    def calculate_weighted_forecast(
        self,
        pipeline_id: str,
    ) -> Decimal:
        """Calculate weighted pipeline forecast.

        Forecast = sum of (deal_value * probability / 100)

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            Weighted forecast value

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        self.get_pipeline(pipeline_id)

        total_weighted = Decimal(0)

        for deal in self._deals.values():
            total_weighted += deal.weighted_value

        return total_weighted

    def get_forecast_by_owner(
        self,
        pipeline_id: str,
    ) -> dict[str, Decimal]:
        """Get weighted forecast broken down by deal owner.

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            Dictionary mapping owner name to forecast value

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        self.get_pipeline(pipeline_id)

        forecast_by_owner: dict[str, Decimal] = {}

        for deal in self._deals.values():
            if deal.owner not in forecast_by_owner:
                forecast_by_owner[deal.owner] = Decimal(0)

            forecast_by_owner[deal.owner] += deal.weighted_value

        return forecast_by_owner

    def get_forecast_by_stage(
        self,
        pipeline_id: str,
    ) -> dict[str, Decimal]:
        """Get weighted forecast broken down by stage.

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            Dictionary mapping stage ID to forecast value

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        self.get_pipeline(pipeline_id)

        forecast_by_stage: dict[str, Decimal] = {}

        for deal in self._deals.values():
            if deal.stage_id not in forecast_by_stage:
                forecast_by_stage[deal.stage_id] = Decimal(0)

            forecast_by_stage[deal.stage_id] += deal.weighted_value

        return forecast_by_stage

    def detect_bottlenecks(
        self,
        pipeline_id: str,
        threshold_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Detect bottlenecks in the pipeline.

        Bottlenecks are deals that have been in a stage longer than the threshold.

        Args:
            pipeline_id: Pipeline identifier
            threshold_days: Days threshold for detecting bottlenecks

        Returns:
            List of bottleneck deals with details

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        pipeline = self.get_pipeline(pipeline_id)

        bottlenecks = []
        threshold_time = datetime.utcnow() - timedelta(days=threshold_days)

        for deal in self._deals.values():
            if deal.stage_entered_at < threshold_time:
                stage = pipeline.get_stage_by_id(deal.stage_id)
                days_in_stage = (datetime.utcnow() - deal.stage_entered_at).days

                bottlenecks.append(
                    {
                        "deal_id": deal.id,
                        "deal_name": deal.name,
                        "stage_id": deal.stage_id,
                        "stage_name": stage.name if stage else None,
                        "days_in_stage": days_in_stage,
                        "owner": deal.owner,
                        "value": deal.value,
                    }
                )

        return sorted(bottlenecks, key=lambda x: x["days_in_stage"], reverse=True)

    def get_stage_distribution(
        self,
        pipeline_id: str,
    ) -> dict[str, int]:
        """Get the distribution of deals across stages.

        Args:
            pipeline_id: Pipeline identifier

        Returns:
            Dictionary mapping stage ID to deal count

        Raises:
            PipelineNotFoundError: If pipeline not found
        """
        self.get_pipeline(pipeline_id)

        distribution: dict[str, int] = {}

        for deal in self._deals.values():
            distribution[deal.stage_id] = distribution.get(deal.stage_id, 0) + 1

        return distribution
