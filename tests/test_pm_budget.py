"""Tests for budget and earned value management."""

from datetime import datetime, timedelta

import pytest

from thomas.marketplace.project_mgmt._types import Task
from thomas.marketplace.project_mgmt.budget import BudgetManager


class TestBudgetManager:
    """Test suite for BudgetManager."""

    @pytest.fixture
    def manager(self) -> BudgetManager:
        """Create budget manager instance."""
        return BudgetManager()

    def test_create_budget(self, manager: BudgetManager) -> None:
        """Test budget creation."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        assert budget.id is not None
        assert budget.project_id == "proj-1"
        assert budget.planned_value == 1000.0
        assert budget.actual_cost == 0.0
        assert budget.earned_value == 0.0

    def test_get_budget(self, manager: BudgetManager) -> None:
        """Test retrieving budget."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        retrieved = manager.get_budget(budget.id)
        assert retrieved.id == budget.id
        assert retrieved.planned_value == 1000.0

    def test_record_cost(self, manager: BudgetManager) -> None:
        """Test recording actual costs."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_cost(budget.id, 100.0)
        manager.record_cost(budget.id, 50.0)

        budget = manager.get_budget(budget.id)
        assert budget.actual_cost == 150.0

    def test_record_earned_value(self, manager: BudgetManager) -> None:
        """Test recording earned value."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 500.0)

        budget = manager.get_budget(budget.id)
        assert budget.earned_value == 500.0

    def test_cost_variance(self, manager: BudgetManager) -> None:
        """Test cost variance calculation (EV - AC)."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 800.0)
        manager.record_cost(budget.id, 700.0)

        cv = manager.calculate_cost_variance(budget.id)

        # CV = EV - AC = 800 - 700 = 100 (favorable, under budget)
        assert cv == 100.0

    def test_schedule_variance(self, manager: BudgetManager) -> None:
        """Test schedule variance calculation (EV - PV)."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 800.0)

        sv = manager.calculate_schedule_variance(budget.id)

        # SV = EV - PV = 800 - 1000 = -200 (unfavorable, behind schedule)
        assert sv == -200.0

    def test_cost_performance_index(self, manager: BudgetManager) -> None:
        """Test CPI calculation (EV / AC)."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 1000.0)
        manager.record_cost(budget.id, 800.0)

        cpi = manager.calculate_cost_performance_index(budget.id)

        # CPI = 1000 / 800 = 1.25 (under budget)
        assert abs(cpi - 1.25) < 0.01

    def test_schedule_performance_index(self, manager: BudgetManager) -> None:
        """Test SPI calculation (EV / PV)."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 1200.0)

        spi = manager.calculate_schedule_performance_index(budget.id)

        # SPI = 1200 / 1000 = 1.2 (ahead of schedule)
        assert abs(spi - 1.2) < 0.01

    def test_estimate_at_completion(self, manager: BudgetManager) -> None:
        """Test EAC calculation."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 500.0)
        manager.record_cost(budget.id, 600.0)

        eac = manager.forecast_estimate_at_completion(budget.id)

        # CPI = 500 / 600 = 0.833, EAC = 1000 / 0.833 = 1200
        assert abs(eac - 1200.0) < 50.0

    def test_estimate_to_complete(self, manager: BudgetManager) -> None:
        """Test ETC calculation."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 500.0)
        manager.record_cost(budget.id, 600.0)

        etc = manager.forecast_estimate_to_complete(budget.id)

        # ETC = EAC - AC
        eac = manager.forecast_estimate_at_completion(budget.id)
        assert etc == eac - 600.0

    def test_variance_at_completion(self, manager: BudgetManager) -> None:
        """Test VAC calculation."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 500.0)
        manager.record_cost(budget.id, 600.0)

        vac = manager.forecast_variance_at_completion(budget.id)

        # VAC = BAC - EAC
        eac = manager.forecast_estimate_at_completion(budget.id)
        assert vac == 1000.0 - eac

    def test_burn_rate(self, manager: BudgetManager) -> None:
        """Test burn rate calculation."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
            period_start=datetime.now() - timedelta(days=7),
        )

        manager.record_cost(budget.id, 700.0)

        burn_rate = manager.calculate_burn_rate(budget.id, days=7)

        # ~100 per day
        assert 80.0 < burn_rate < 120.0

    def test_calculate_earned_value_from_tasks(
        self,
        manager: BudgetManager,
    ) -> None:
        """Test EV calculation from task completion."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        tasks = [
            Task(
                id="task-1",
                project_id="proj-1",
                title="Task 1",
                percent_complete=100.0,
            ),
            Task(
                id="task-2",
                project_id="proj-1",
                title="Task 2",
                percent_complete=50.0,
            ),
        ]

        ev, pv = manager.calculate_earned_value_from_tasks(budget.id, tasks)

        # Average completion: (100 + 50) / 2 = 75%
        # EV = 1000 * 0.75 = 750
        assert abs(ev - 750.0) < 10.0

    def test_get_budget_status(self, manager: BudgetManager) -> None:
        """Test comprehensive budget status."""
        budget = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )

        manager.record_earned_value(budget.id, 800.0)
        manager.record_cost(budget.id, 700.0)

        status = manager.get_budget_status(budget.id)

        assert "budget_id" in status
        assert "planned_value" in status
        assert "cost_variance" in status
        assert "cost_performance_index" in status
        assert "cost_status" in status

    def test_list_budgets(self, manager: BudgetManager) -> None:
        """Test listing budgets with filtering."""
        b1 = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )
        manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-2",
            planned_value=2000.0,
        )
        manager.create_budget(
            project_id="proj-2",
            work_package_id="wp-3",
            planned_value=3000.0,
        )

        # Filter by project
        proj1_budgets = manager.list_budgets(project_id="proj-1")
        assert len(proj1_budgets) == 2

        # Filter by work package
        wp1_budgets = manager.list_budgets(work_package_id="wp-1")
        assert len(wp1_budgets) == 1
        assert wp1_budgets[0].id == b1.id

    def test_project_budget_summary(self, manager: BudgetManager) -> None:
        """Test project-level budget summary."""
        b1 = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-1",
            planned_value=1000.0,
        )
        b2 = manager.create_budget(
            project_id="proj-1",
            work_package_id="wp-2",
            planned_value=2000.0,
        )

        manager.record_cost(b1.id, 500.0)
        manager.record_cost(b2.id, 1500.0)
        manager.record_earned_value(b1.id, 800.0)
        manager.record_earned_value(b2.id, 1800.0)

        summary = manager.get_project_budget_summary("proj-1")

        assert summary["total_planned_value"] == 3000.0
        assert summary["total_actual_cost"] == 2000.0
        assert summary["total_earned_value"] == 2600.0

    def test_set_cost_rate(self, manager: BudgetManager) -> None:
        """Test setting resource cost rates."""
        manager.set_cost_rate("res-1", 100.0)
        manager.set_cost_rate("res-2", 150.0)

        assert manager.cost_rates["res-1"] == 100.0
        assert manager.cost_rates["res-2"] == 150.0
