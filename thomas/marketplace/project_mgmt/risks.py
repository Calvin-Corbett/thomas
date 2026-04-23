"""Risk management with probability-impact analysis and Monte Carlo simulation.

Implements risk register management, risk scoring, Monte Carlo simulation
for schedule uncertainty, and risk response planning.
"""

import random
import uuid

from thomas.marketplace.project_mgmt._exceptions import RiskNotFoundError
from thomas.marketplace.project_mgmt._types import (
    RiskCategory,
    RiskItem,
    RiskStatus,
    Task,
)


class RiskManager:
    """Manages project risks and uncertainty analysis.

    Handles risk identification, assessment, response planning,
    Monte Carlo simulation, and risk monitoring.
    """

    def __init__(self) -> None:
        """Initialize risk manager."""
        self.risks: dict[str, RiskItem] = {}
        self.risk_responses: dict[str, dict[str, str]] = {}  # risk_id -> response data

    def create_risk(
        self,
        project_id: str,
        description: str,
        category: RiskCategory = RiskCategory.TECHNICAL,
        probability: float = 0.5,
        impact: float = 0.5,
        owner_id: str | None = None,
    ) -> RiskItem:
        """Create risk register entry.

        Args:
            project_id: Project identifier.
            description: Risk description.
            category: Risk category.
            probability: Probability 0-1.
            impact: Impact 0-1.
            owner_id: Risk owner identifier.

        Returns:
            Created RiskItem instance.
        """
        risk_id = str(uuid.uuid4())
        risk = RiskItem(
            id=risk_id,
            project_id=project_id,
            description=description,
            category=category,
            probability=min(1.0, max(0.0, probability)),
            impact=min(1.0, max(0.0, impact)),
            owner_id=owner_id,
        )
        self.risks[risk_id] = risk
        return risk

    def get_risk(self, risk_id: str) -> RiskItem:
        """Retrieve risk by ID.

        Args:
            risk_id: Risk identifier.

        Returns:
            RiskItem instance.

        Raises:
            RiskNotFoundError: If risk doesn't exist.
        """
        if risk_id not in self.risks:
            raise RiskNotFoundError(f"Risk {risk_id} not found")
        return self.risks[risk_id]

    def update_risk(
        self,
        risk_id: str,
        probability: float | None = None,
        impact: float | None = None,
        status: RiskStatus | None = None,
        mitigation_strategy: str | None = None,
    ) -> RiskItem:
        """Update risk details.

        Args:
            risk_id: Risk identifier.
            probability: New probability value.
            impact: New impact value.
            status: New risk status.
            mitigation_strategy: Mitigation plan.

        Returns:
            Updated RiskItem instance.

        Raises:
            RiskNotFoundError: If risk doesn't exist.
        """
        risk = self.get_risk(risk_id)
        if probability is not None:
            risk.probability = min(1.0, max(0.0, probability))
        if impact is not None:
            risk.impact = min(1.0, max(0.0, impact))
        if status is not None:
            risk.status = status
        if mitigation_strategy is not None:
            risk.mitigation_strategy = mitigation_strategy
        return risk

    def set_risk_response(
        self,
        risk_id: str,
        strategy: str,
        owner_id: str | None = None,
        contingency_plan: str = "",
        trigger: str = "",
    ) -> RiskItem:
        """Set risk response strategy.

        Strategies: avoid, mitigate, transfer, accept

        Args:
            risk_id: Risk identifier.
            strategy: Response strategy.
            owner_id: Response owner.
            contingency_plan: Fallback plan.
            trigger: Risk trigger condition.

        Returns:
            Updated RiskItem instance.

        Raises:
            RiskNotFoundError: If risk doesn't exist.
        """
        risk = self.get_risk(risk_id)
        risk.mitigation_strategy = strategy
        risk.contingency_plan = contingency_plan
        risk.trigger = trigger
        if owner_id:
            risk.owner_id = owner_id

        self.risk_responses[risk_id] = {
            "strategy": strategy,
            "contingency": contingency_plan,
            "trigger": trigger,
        }
        return risk

    def score_risk(self, risk_id: str) -> float:
        """Calculate risk score (probability × impact).

        Args:
            risk_id: Risk identifier.

        Returns:
            Risk score 0-1.

        Raises:
            RiskNotFoundError: If risk doesn't exist.
        """
        risk = self.get_risk(risk_id)
        return risk.risk_score()

    def categorize_risks(
        self,
        project_id: str,
    ) -> dict[str, list[RiskItem]]:
        """Categorize project risks by category.

        Args:
            project_id: Project identifier.

        Returns:
            Dictionary mapping category name to risk items.
        """
        project_risks = [r for r in self.risks.values() if r.project_id == project_id]

        categorized: dict[str, list[RiskItem]] = {cat.value: [] for cat in RiskCategory}

        for risk in project_risks:
            categorized[risk.category.value].append(risk)

        return categorized

    def get_risk_matrix(
        self,
        project_id: str,
    ) -> dict[str, list[RiskItem]]:
        """Get probability-impact matrix for project risks.

        Matrix quadrants: Low-Low, Low-High, High-Low, High-High

        Args:
            project_id: Project identifier.

        Returns:
            Dictionary mapping quadrant name to risks.
        """
        project_risks = [r for r in self.risks.values() if r.project_id == project_id]

        matrix: dict[str, list[RiskItem]] = {
            "low_low": [],
            "low_high": [],
            "high_low": [],
            "high_high": [],
        }

        threshold_prob = 0.5
        threshold_impact = 0.5

        for risk in project_risks:
            prob_high = risk.probability >= threshold_prob
            impact_high = risk.impact >= threshold_impact

            if prob_high and impact_high:
                matrix["high_high"].append(risk)
            elif prob_high:
                matrix["high_low"].append(risk)
            elif impact_high:
                matrix["low_high"].append(risk)
            else:
                matrix["low_low"].append(risk)

        return matrix

    def monte_carlo_simulation(
        self,
        tasks: dict[str, Task],
        iterations: int = 1000,
    ) -> tuple[float, float, float]:
        """Simulate project duration with task duration uncertainty.

        Uses three-point estimates to generate distribution.
        Returns P10, P50 (median), P90 confidence intervals.

        Args:
            tasks: Dictionary of all tasks.
            iterations: Number of simulation iterations.

        Returns:
            Tuple of (P10, P50, P90) durations in days.
        """
        if not tasks:
            return (0.0, 0.0, 0.0)

        simulated_durations: list[float] = []

        for _ in range(iterations):
            total_duration = 0.0

            for task in tasks.values():
                o, m, p = task.estimated_hours
                # Generate random duration from triangular distribution
                if o <= m <= p:
                    # Triangular distribution
                    u = random.random()
                    mode_prob = (m - o) / (p - o)
                    if u <= mode_prob:
                        duration = o + (u * (p - o) * (m - o)) ** 0.5
                    else:
                        duration = p - ((1 - u) * (p - o) * (p - m)) ** 0.5
                else:
                    duration = m

                total_duration += duration

            # Convert hours to days
            simulated_durations.append(total_duration / 24.0)

        # Sort for percentile calculation
        simulated_durations.sort()

        p10_index = max(0, int(iterations * 0.1))
        p50_index = max(0, int(iterations * 0.5))
        p90_index = max(0, int(iterations * 0.9))

        p10 = simulated_durations[p10_index]
        p50 = simulated_durations[p50_index]
        p90 = simulated_durations[p90_index]

        return (p10, p50, p90)

    def get_risk_register(
        self,
        project_id: str,
    ) -> list[dict[str, any]]:
        """Get complete risk register for project.

        Args:
            project_id: Project identifier.

        Returns:
            List of risk register entries with all metrics.
        """
        project_risks = [r for r in self.risks.values() if r.project_id == project_id]

        register: list[dict[str, any]] = []
        for risk in project_risks:
            register.append(
                {
                    "id": risk.id,
                    "description": risk.description,
                    "category": risk.category.value,
                    "probability": risk.probability,
                    "impact": risk.impact,
                    "risk_score": risk.risk_score(),
                    "status": risk.status.value,
                    "owner": risk.owner_id,
                    "mitigation": risk.mitigation_strategy,
                    "contingency": risk.contingency_plan,
                    "trigger": risk.trigger,
                    "identified_date": risk.identified_date,
                }
            )

        # Sort by risk score descending
        register.sort(key=lambda x: x["risk_score"], reverse=True)
        return register

    def get_risk_summary(
        self,
        project_id: str,
    ) -> dict[str, any]:
        """Get risk summary statistics for project.

        Args:
            project_id: Project identifier.

        Returns:
            Dictionary with risk metrics.
        """
        project_risks = [r for r in self.risks.values() if r.project_id == project_id]

        if not project_risks:
            return {
                "total_risks": 0,
                "average_risk_score": 0.0,
                "high_risks": 0,
                "medium_risks": 0,
                "low_risks": 0,
            }

        scores = [r.risk_score() for r in project_risks]
        high_count = sum(1 for s in scores if s > 0.5)
        medium_count = sum(1 for s in scores if 0.25 < s <= 0.5)
        low_count = sum(1 for s in scores if s <= 0.25)

        return {
            "total_risks": len(project_risks),
            "average_risk_score": sum(scores) / len(scores),
            "high_risks": high_count,
            "medium_risks": medium_count,
            "low_risks": low_count,
        }

    def list_risks(
        self,
        project_id: str | None = None,
        status: RiskStatus | None = None,
        category: RiskCategory | None = None,
    ) -> list[RiskItem]:
        """List risks with optional filtering.

        Args:
            project_id: Filter by project.
            status: Filter by status.
            category: Filter by category.

        Returns:
            List of matching RiskItem instances.
        """
        risks = list(self.risks.values())
        if project_id:
            risks = [r for r in risks if r.project_id == project_id]
        if status:
            risks = [r for r in risks if r.status == status]
        if category:
            risks = [r for r in risks if r.category == category]
        return risks

    def trigger_risk(self, risk_id: str) -> RiskItem:
        """Mark risk as triggered.

        Args:
            risk_id: Risk identifier.

        Returns:
            Updated RiskItem instance.

        Raises:
            RiskNotFoundError: If risk doesn't exist.
        """
        risk = self.get_risk(risk_id)
        risk.status = RiskStatus.TRIGGERED
        return risk

    def close_risk(self, risk_id: str) -> RiskItem:
        """Close resolved risk.

        Args:
            risk_id: Risk identifier.

        Returns:
            Updated RiskItem instance.

        Raises:
            RiskNotFoundError: If risk doesn't exist.
        """
        risk = self.get_risk(risk_id)
        risk.status = RiskStatus.CLOSED
        return risk

    def delete_risk(self, risk_id: str) -> None:
        """Delete risk.

        Args:
            risk_id: Risk identifier.

        Raises:
            RiskNotFoundError: If risk doesn't exist.
        """
        risk = self.get_risk(risk_id)
        del self.risks[risk_id]
        if risk_id in self.risk_responses:
            del self.risk_responses[risk_id]
