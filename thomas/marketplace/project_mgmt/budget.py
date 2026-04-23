"""Budget and earned value management with financial tracking.

Implements budget planning, earned value management (EVM),
budget tracking, cost variance analysis, and financial forecasting.
"""

import uuid
from datetime import datetime, timedelta

from thomas.marketplace.project_mgmt._exceptions import (
    ProjectNotFoundError,
)
from thomas.marketplace.project_mgmt._types import (
    Budget,
    Task,
)


class BudgetManager:
    """Manages project budgets and earned value management.

    Handles budget planning, cost tracking, EVM metrics,
    variance analysis, and financial forecasting.
    """

    def __init__(self) -> None:
        """Initialize budget manager."""
        self.budgets: dict[str, Budget] = {}
        self.cost_rates: dict[str, float] = {}  # resource_id -> hourly_rate

    def create_budget(
        self,
        project_id: str,
        work_package_id: str,
        planned_value: float,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> Budget:
        """Create project/work package budget.

        Args:
            project_id: Project identifier.
            work_package_id: Work package identifier.
            planned_value: Planned cost (PV).
            period_start: Budget period start.
            period_end: Budget period end.

        Returns:
            Created Budget instance.
        """
        if period_start is None:
            period_start = datetime.now()
        if period_end is None:
            period_end = period_start + timedelta(days=30)

        budget_id = str(uuid.uuid4())
        budget = Budget(
            id=budget_id,
            project_id=project_id,
            work_package_id=work_package_id,
            planned_value=planned_value,
            period_start=period_start,
            period_end=period_end,
        )
        self.budgets[budget_id] = budget
        return budget

    def get_budget(self, budget_id: str) -> Budget:
        """Retrieve budget by ID.

        Args:
            budget_id: Budget identifier.

        Returns:
            Budget instance.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        if budget_id not in self.budgets:
            raise ProjectNotFoundError(f"Budget {budget_id} not found")
        return self.budgets[budget_id]

    def record_cost(
        self,
        budget_id: str,
        actual_cost: float,
        description: str = "",
    ) -> Budget:
        """Record actual cost incurred.

        Args:
            budget_id: Budget identifier.
            actual_cost: Cost amount.
            description: Cost description.

        Returns:
            Updated Budget instance.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        budget.actual_cost += actual_cost
        return budget

    def record_earned_value(
        self,
        budget_id: str,
        earned_value: float,
    ) -> Budget:
        """Record earned value (value of completed work).

        Args:
            budget_id: Budget identifier.
            earned_value: EV amount.

        Returns:
            Updated Budget instance.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        budget.earned_value = min(budget.planned_value, budget.earned_value + earned_value)
        return budget

    def set_cost_rate(self, resource_id: str, hourly_rate: float) -> None:
        """Set hourly cost rate for resource.

        Args:
            resource_id: Resource identifier.
            hourly_rate: Hourly cost in currency units.
        """
        self.cost_rates[resource_id] = hourly_rate

    def calculate_earned_value_from_tasks(
        self,
        budget_id: str,
        tasks: list[Task],
    ) -> tuple[float, float]:
        """Calculate earned value from task completion percentage.

        EV = PV * percent_complete / 100

        Args:
            budget_id: Budget identifier.
            tasks: List of associated tasks.

        Returns:
            Tuple of (earned_value, total_value).
        """
        budget = self.get_budget(budget_id)

        if not tasks:
            return (0.0, budget.planned_value)

        avg_completion = sum(t.percent_complete for t in tasks) / len(tasks)
        earned_value = budget.planned_value * (avg_completion / 100.0)

        return (earned_value, budget.planned_value)

    def calculate_cost_variance(self, budget_id: str) -> float:
        """Calculate cost variance.

        CV = EV - AC (positive = under budget)

        Args:
            budget_id: Budget identifier.

        Returns:
            Cost variance.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        return budget.cost_variance()

    def calculate_schedule_variance(self, budget_id: str) -> float:
        """Calculate schedule variance.

        SV = EV - PV (positive = ahead of schedule)

        Args:
            budget_id: Budget identifier.

        Returns:
            Schedule variance.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        return budget.schedule_variance(budget.planned_value)

    def calculate_cost_performance_index(self, budget_id: str) -> float:
        """Calculate cost performance index.

        CPI = EV / AC (>1 = under budget, <1 = over budget)

        Args:
            budget_id: Budget identifier.

        Returns:
            Cost performance index.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        return budget.cost_performance_index()

    def calculate_schedule_performance_index(
        self,
        budget_id: str,
    ) -> float:
        """Calculate schedule performance index.

        SPI = EV / PV (>1 = ahead of schedule, <1 = behind)

        Args:
            budget_id: Budget identifier.

        Returns:
            Schedule performance index.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        return budget.schedule_performance_index()

    def forecast_estimate_at_completion(
        self,
        budget_id: str,
    ) -> float:
        """Forecast final cost estimate (EAC).

        EAC = BAC / CPI (assumes current performance continues)

        Args:
            budget_id: Budget identifier.

        Returns:
            Estimate at completion.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        cpi = budget.cost_performance_index()
        if cpi == 0:
            return budget.planned_value

        eac = budget.planned_value / cpi
        return eac

    def forecast_estimate_to_complete(
        self,
        budget_id: str,
    ) -> float:
        """Forecast remaining work cost (ETC).

        ETC = EAC - AC

        Args:
            budget_id: Budget identifier.

        Returns:
            Estimate to complete.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        eac = self.forecast_estimate_at_completion(budget_id)
        return eac - budget.actual_cost

    def forecast_variance_at_completion(
        self,
        budget_id: str,
    ) -> float:
        """Forecast final cost variance (VAC).

        VAC = BAC - EAC

        Args:
            budget_id: Budget identifier.

        Returns:
            Variance at completion.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        eac = self.forecast_estimate_at_completion(budget_id)
        vac = budget.planned_value - eac
        return vac

    def calculate_burn_rate(
        self,
        budget_id: str,
        days: int = 7,
    ) -> float:
        """Calculate average daily cost burn rate.

        Args:
            budget_id: Budget identifier.
            days: Number of days to calculate average over.

        Returns:
            Daily burn rate (cost per day).

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        if days <= 0:
            return 0.0

        elapsed_days = (datetime.now() - budget.period_start).days
        if elapsed_days == 0:
            return 0.0

        period_days = min(days, elapsed_days)
        if period_days == 0:
            return 0.0

        return budget.actual_cost / period_days

    def get_budget_status(self, budget_id: str) -> dict[str, any]:
        """Get comprehensive budget status.

        Args:
            budget_id: Budget identifier.

        Returns:
            Dictionary with budget metrics.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)

        cv = self.calculate_cost_variance(budget_id)
        sv = self.calculate_schedule_variance(budget_id)
        cpi = self.calculate_cost_performance_index(budget_id)
        spi = self.calculate_schedule_performance_index(budget_id)
        eac = self.forecast_estimate_at_completion(budget_id)
        etc = self.forecast_estimate_to_complete(budget_id)
        vac = self.forecast_variance_at_completion(budget_id)
        burn_rate = self.calculate_burn_rate(budget_id)

        # Determine status
        if cv < 0:
            cost_status = "RED"
        elif cv > budget.planned_value * 0.1:
            cost_status = "GREEN"
        else:
            cost_status = "AMBER"

        if spi < 0.9:
            schedule_status = "RED"
        elif spi > 1.1:
            schedule_status = "GREEN"
        else:
            schedule_status = "AMBER"

        return {
            "budget_id": budget_id,
            "planned_value": budget.planned_value,
            "earned_value": budget.earned_value,
            "actual_cost": budget.actual_cost,
            "cost_variance": cv,
            "schedule_variance": sv,
            "cost_performance_index": cpi,
            "schedule_performance_index": spi,
            "estimate_at_completion": eac,
            "estimate_to_complete": etc,
            "variance_at_completion": vac,
            "burn_rate": burn_rate,
            "cost_status": cost_status,
            "schedule_status": schedule_status,
            "percent_complete": (
                (budget.earned_value / budget.planned_value * 100.0) if budget.planned_value > 0 else 0.0
            ),
        }

    def list_budgets(
        self,
        project_id: str | None = None,
        work_package_id: str | None = None,
    ) -> list[Budget]:
        """List budgets with optional filtering.

        Args:
            project_id: Filter by project.
            work_package_id: Filter by work package.

        Returns:
            List of matching Budget instances.
        """
        budgets = list(self.budgets.values())
        if project_id:
            budgets = [b for b in budgets if b.project_id == project_id]
        if work_package_id:
            budgets = [b for b in budgets if b.work_package_id == work_package_id]
        return budgets

    def get_project_budget_summary(
        self,
        project_id: str,
    ) -> dict[str, float]:
        """Get project-level budget summary.

        Args:
            project_id: Project identifier.

        Returns:
            Dictionary with aggregate budget metrics.
        """
        project_budgets = self.list_budgets(project_id=project_id)

        total_pv = sum(b.planned_value for b in project_budgets)
        total_ac = sum(b.actual_cost for b in project_budgets)
        total_ev = sum(b.earned_value for b in project_budgets)

        return {
            "total_planned_value": total_pv,
            "total_actual_cost": total_ac,
            "total_earned_value": total_ev,
            "total_cost_variance": total_ev - total_ac,
            "total_cost_performance_index": ((total_ev / total_ac) if total_ac > 0 else 0.0),
            "total_schedule_variance": total_ev - total_pv,
            "total_schedule_performance_index": ((total_ev / total_pv) if total_pv > 0 else 0.0),
        }

    def delete_budget(self, budget_id: str) -> None:
        """Delete budget.

        Args:
            budget_id: Budget identifier.

        Raises:
            ProjectNotFoundError: If budget doesn't exist.
        """
        budget = self.get_budget(budget_id)
        del self.budgets[budget_id]
