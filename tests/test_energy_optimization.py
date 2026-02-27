"""
Tests for energy system optimization.
"""

import pytest

from thomas.energy._exceptions import NoFeasibleSolutionError
from thomas.energy._types import EnergySource, Load, PowerPlant, StorageUnit
from thomas.energy.optimization import (
    EconomicDispatch,
    LoadShiftingOptimizer,
    MicrogridOptimizer,
    MultiObjectiveOptimizer,
    PeakShavingStrategy,
    UnitCommitment,
)


class TestUnitCommitment:
    """Test unit commitment solver."""

    def test_create_solver(self):
        """Test solver creation."""
        solver = UnitCommitment()

        assert solver is not None

    def test_unit_commitment_simple(self):
        """Test unit commitment with simple case."""
        solver = UnitCommitment()

        plants = [
            PowerPlant(
                plant_id="gen1",
                fuel_type=EnergySource.NATURAL_GAS,
                capacity_mw=100.0,
                min_power_mw=20.0,
                startup_cost_usd=500.0,
                fuel_cost_per_mwh=30.0,
            ),
            PowerPlant(
                plant_id="gen2",
                fuel_type=EnergySource.COAL,
                capacity_mw=200.0,
                min_power_mw=50.0,
                startup_cost_usd=1000.0,
                fuel_cost_per_mwh=25.0,
            ),
        ]

        load_profile = [150.0, 100.0, 80.0, 120.0]  # 4 hours

        solution = solver.solve_relaxation(plants, load_profile)

        assert solution.feasible
        assert len(solution.on_off_schedule["gen1"]) == 4
        assert solution.total_cost >= 0


class TestEconomicDispatch:
    """Test economic dispatch."""

    def test_create_dispatcher(self):
        """Test dispatcher creation."""
        dispatcher = EconomicDispatch()

        assert dispatcher is not None

    def test_economic_dispatch_lambda_iteration(self):
        """Test lambda iteration dispatch."""
        dispatcher = EconomicDispatch()

        plants = [
            PowerPlant(
                plant_id="gen1",
                fuel_type=EnergySource.NATURAL_GAS,
                capacity_mw=100.0,
                min_power_mw=10.0,
                efficiency=0.40,
                fuel_cost_per_mwh=30.0,
                variable_om_per_mwh=5.0,
            ),
            PowerPlant(
                plant_id="gen2",
                fuel_type=EnergySource.COAL,
                capacity_mw=150.0,
                min_power_mw=30.0,
                efficiency=0.35,
                fuel_cost_per_mwh=25.0,
                variable_om_per_mwh=3.0,
            ),
        ]

        demand = 150.0  # MW

        solution = dispatcher.solve_lambda_iteration(plants, demand)

        assert solution.converged
        assert solution.total_generation >= demand * 0.95
        assert all(v >= 0 for v in solution.dispatch.values())

    def test_economic_dispatch_insufficient_capacity(self):
        """Test dispatch with insufficient capacity."""
        dispatcher = EconomicDispatch()

        plants = [
            PowerPlant(
                plant_id="gen1",
                fuel_type=EnergySource.NATURAL_GAS,
                capacity_mw=100.0,
                min_power_mw=20.0,
            ),
        ]

        demand = 200.0  # Exceeds capacity

        with pytest.raises(NoFeasibleSolutionError):
            dispatcher.solve_lambda_iteration(plants, demand)

    def test_economic_dispatch_merit_order(self):
        """Test that cheaper units dispatch first."""
        dispatcher = EconomicDispatch()

        plants = [
            PowerPlant(
                plant_id="expensive",
                fuel_type=EnergySource.NATURAL_GAS,
                capacity_mw=100.0,
                min_power_mw=0.0,
                efficiency=0.40,
                fuel_cost_per_mwh=50.0,  # Expensive
            ),
            PowerPlant(
                plant_id="cheap",
                fuel_type=EnergySource.COAL,
                capacity_mw=100.0,
                min_power_mw=0.0,
                efficiency=0.35,
                fuel_cost_per_mwh=20.0,  # Cheap
            ),
        ]

        demand = 150.0

        solution = dispatcher.solve_lambda_iteration(plants, demand)

        # Cheaper plant should be dispatched more
        assert solution.dispatch.get("cheap", 0) >= solution.dispatch.get("expensive", 0)


class TestMicrogridOptimizer:
    """Test microgrid optimization."""

    def test_create_optimizer(self):
        """Test optimizer creation."""
        optimizer = MicrogridOptimizer()

        assert optimizer is not None

    def test_microgrid_optimization_all_renewable(self):
        """Test optimization with ample renewable."""
        optimizer = MicrogridOptimizer()

        plants = [
            PowerPlant(
                plant_id="gen1",
                fuel_type=EnergySource.NATURAL_GAS,
                capacity_mw=50.0,
                min_power_mw=0.0,
            ),
        ]

        loads = [
            Load(load_id="load1", active_power=30.0),
            Load(load_id="load2", active_power=20.0),
        ]

        storage = [
            StorageUnit(
                storage_id="storage1",
                storage_type="battery",
                capacity_mwh=50.0,
                power_rating_mw=10.0,
            ),
        ]

        renewable_available = {
            "solar": 80.0,
            "wind": 20.0,
        }

        result = optimizer.optimize_microgrid(plants, loads, storage, renewable_available)

        assert result.renewable_penetration > 0.8  # Most from renewable
        assert result.total_cost >= 0

    def test_microgrid_optimization_limited_renewable(self):
        """Test optimization with limited renewable."""
        optimizer = MicrogridOptimizer()

        plants = [
            PowerPlant(
                plant_id="gen1",
                fuel_type=EnergySource.NATURAL_GAS,
                capacity_mw=100.0,
                min_power_mw=10.0,
            ),
        ]

        loads = [
            Load(load_id="load1", active_power=60.0),
        ]

        storage = []

        renewable_available = {
            "solar": 20.0,
        }

        result = optimizer.optimize_microgrid(plants, loads, storage, renewable_available)

        # Most power from conventional
        assert result.renewable_penetration < 0.5


class TestPeakShaving:
    """Test peak shaving."""

    def test_peak_shaving_strategy(self):
        """Test peak shaving with storage."""
        strategy = PeakShavingStrategy()

        load_profile = [50, 60, 80, 100, 120, 90, 70, 50]  # Peak at 120 MW

        storage = StorageUnit(
            storage_id="storage1",
            storage_type="battery",
            capacity_mwh=100.0,
            power_rating_mw=30.0,
            soc=0.8,
        )

        shaved, dispatch = strategy.shave_peak(load_profile, storage, peak_threshold=100.0)

        # Peak should be reduced
        assert max(shaved) <= max(load_profile)
        assert max(shaved) <= 100.0 + 1  # Some tolerance

    def test_peak_shaving_no_peaks(self):
        """Test peak shaving with no peaks."""
        strategy = PeakShavingStrategy()

        load_profile = [30, 35, 40, 35, 30, 25, 20, 25]

        storage = StorageUnit(
            storage_id="storage1",
            storage_type="battery",
            capacity_mwh=50.0,
            power_rating_mw=10.0,
            soc=0.5,
        )

        shaved, dispatch = strategy.shave_peak(load_profile, storage, peak_threshold=50.0)

        # Profile should be unchanged
        assert shaved == load_profile


class TestLoadShifting:
    """Test load shifting optimization."""

    def test_load_shifting(self):
        """Test load shift from high to low price."""
        optimizer = LoadShiftingOptimizer()

        baseline = [50, 60, 80, 100, 90, 70, 50, 40]
        prices = [50, 55, 60, 100, 110, 80, 40, 30]

        shifted = optimizer.optimize_shift(baseline, prices, shiftable_load_fraction=0.2)

        # Should shift load from high-price (hour 3) to low-price (hour 7)
        assert shifted[3] <= baseline[3]  # Less load during peak price
        assert shifted[7] >= baseline[7]  # More load during off-peak


class TestMultiObjectiveOptimization:
    """Test multi-objective optimization."""

    def test_pareto_frontier(self):
        """Test Pareto frontier calculation."""
        optimizer = MultiObjectiveOptimizer()

        solutions = [
            (100, 500),  # Low cost, high emissions
            (120, 400),
            (150, 300),
            (200, 100),  # High cost, low emissions
            (180, 150),
        ]

        frontier = optimizer.pareto_frontier(solutions)

        # Frontier should have solutions with improving tradeoff
        assert len(frontier) > 0
        assert len(frontier) <= len(solutions)

    def test_optimal_weight_cost_preference(self):
        """Test optimization with cost preference."""
        optimizer = MultiObjectiveOptimizer()

        solutions = [
            (100, 500),
            (150, 300),
            (200, 100),
        ]

        # Prefer low cost
        cost_weight = 0.8
        emissions_weight = 0.2

        optimal = optimizer.find_optimal_weight(cost_weight, emissions_weight, solutions)

        # Should prefer low cost solution
        assert optimal[0] <= 150

    def test_optimal_weight_emissions_preference(self):
        """Test optimization with emissions preference."""
        optimizer = MultiObjectiveOptimizer()

        solutions = [
            (100, 500),
            (150, 300),
            (200, 100),
        ]

        # Prefer low emissions
        cost_weight = 0.2
        emissions_weight = 0.8

        optimal = optimizer.find_optimal_weight(cost_weight, emissions_weight, solutions)

        # Should prefer low emissions solution
        assert optimal[1] <= 300


class TestIntegration:
    """Integration tests for optimization."""

    def test_complete_optimization_workflow(self):
        """Test complete optimization workflow."""
        # Create dispatcher and optimizer
        dispatcher = EconomicDispatch()
        microgrid_opt = MicrogridOptimizer()

        # Define systems
        plants = [
            PowerPlant(
                plant_id="gas1",
                fuel_type=EnergySource.NATURAL_GAS,
                capacity_mw=100.0,
                min_power_mw=20.0,
                efficiency=0.40,
                fuel_cost_per_mwh=30.0,
            ),
            PowerPlant(
                plant_id="coal1",
                fuel_type=EnergySource.COAL,
                capacity_mw=150.0,
                min_power_mw=50.0,
                efficiency=0.35,
                fuel_cost_per_mwh=25.0,
            ),
        ]

        loads = [
            Load(load_id="load1", active_power=100.0),
            Load(load_id="load2", active_power=80.0),
        ]

        storage = [
            StorageUnit(
                storage_id="battery1",
                storage_type="battery",
                capacity_mwh=50.0,
                power_rating_mw=20.0,
                soc=0.5,
            ),
        ]

        renewable = {"solar": 40.0, "wind": 30.0}

        # Run dispatcher
        ed_result = dispatcher.solve_lambda_iteration(plants, 180.0)

        # Run microgrid optimizer
        mg_result = microgrid_opt.optimize_microgrid(plants, loads, storage, renewable)

        # Both should produce results
        assert ed_result.converged
        assert mg_result.total_dispatch_mw > 0
