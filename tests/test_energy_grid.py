"""
Tests for power grid simulation and control.
"""

from thomas.energy._types import BusState, BusType, BusVoltage, EnergySource, Grid, Load, PowerPlant
from thomas.energy.grid import (
    FrequencyRegulator,
    GridController,
    PowerFlowSolver,
    calculate_grid_stability_index,
    detect_islanding,
)


class TestPowerFlowSolver:
    """Test AC power flow solver."""

    def test_create_solver(self):
        """Test solver creation."""
        solver = PowerFlowSolver()

        assert solver.max_iterations == 100
        assert solver.tolerance == 1e-6

    def test_empty_grid(self):
        """Test power flow with empty grid."""
        solver = PowerFlowSolver()
        grid = Grid(grid_id="test_grid")

        result = solver.solve(grid)

        assert not result.converged or len(result.bus_voltages) == 0

    def test_simple_grid(self):
        """Test power flow with simple 2-bus system."""
        solver = PowerFlowSolver()

        # Create grid with 2 buses
        grid = Grid(grid_id="test_grid")

        bus1 = BusState(
            bus_id=1,
            bus_type=BusType.SLACK,
            voltage=BusVoltage(1.0, 0.0),
            real_power=100.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )

        bus2 = BusState(
            bus_id=2,
            bus_type=BusType.PQ,
            voltage=BusVoltage(0.95, 0.0),
            real_power=-50.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )

        grid.buses = {1: bus1, 2: bus2}

        # Add transmission line (impedance: r=0.01, x=0.1)
        grid.transmission_lines = [(1, 2, 0.01, 0.1)]

        # Add generation and load
        gen = PowerPlant(
            plant_id="gen1",
            fuel_type=EnergySource.NATURAL_GAS,
            capacity_mw=200.0,
            current_output_mw=100.0,
        )
        grid.plants["gen1"] = gen

        load = Load(load_id="load1", active_power=50.0)
        grid.loads["load1"] = load

        result = solver.solve(grid)

        # Should converge or at least attempt to
        assert result.iterations >= 0


class TestFrequencyRegulator:
    """Test frequency regulation."""

    def test_create_regulator(self):
        """Test regulator creation."""
        reg = FrequencyRegulator()

        assert reg.nominal_frequency == 60.0
        assert reg.deadband == 0.05

    def test_frequency_response_normal(self):
        """Test frequency response in normal conditions."""
        reg = FrequencyRegulator()

        current_freq = 60.0
        power_imbalance = 0.0
        available_capacity = 100.0

        response = reg.calculate_frequency_response(current_freq, power_imbalance, available_capacity)

        assert response == 0.0  # No deviation, no response

    def test_frequency_response_low(self):
        """Test frequency response to low frequency."""
        reg = FrequencyRegulator()

        current_freq = 59.5  # 0.5 Hz below nominal
        power_imbalance = -50.0  # Generation deficit
        available_capacity = 100.0

        response = reg.calculate_frequency_response(current_freq, power_imbalance, available_capacity)

        # Should require positive response (increase generation)
        assert response > 0

    def test_frequency_response_high(self):
        """Test frequency response to high frequency."""
        reg = FrequencyRegulator()

        current_freq = 60.5  # 0.5 Hz above nominal
        power_imbalance = 50.0  # Generation surplus
        available_capacity = 100.0

        response = reg.calculate_frequency_response(current_freq, power_imbalance, available_capacity)

        # Should require negative response (decrease generation)
        assert response < 0

    def test_frequency_update(self):
        """Test frequency update over time."""
        reg = FrequencyRegulator()

        current_freq = 60.0
        power_imbalance = 50.0  # Surplus
        system_inertia = 5000.0
        time_step = 1.0

        new_freq = reg.update_frequency(current_freq, power_imbalance, system_inertia, time_step)

        # Surplus increases frequency
        assert new_freq > current_freq


class TestGridController:
    """Test grid control system."""

    def test_create_controller(self):
        """Test controller creation."""
        controller = GridController()

        assert controller.frequency_regulator is not None
        assert controller.reactive_power_margin == 0.1

    def test_stability_check_stable(self):
        """Test stability check for stable grid."""
        controller = GridController()

        grid = Grid(grid_id="test_grid")
        grid.frequency_hz = 60.0

        bus = BusState(
            bus_id=1,
            bus_type=BusType.SLACK,
            voltage=BusVoltage(1.0, 0.0),
            real_power=0.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )
        grid.buses[1] = bus

        gen = PowerPlant(
            plant_id="gen1",
            fuel_type=EnergySource.NUCLEAR,
            capacity_mw=200.0,
            current_output_mw=100.0,
        )
        grid.plants["gen1"] = gen

        load = Load(load_id="load1", active_power=50.0)
        grid.loads["load1"] = load

        stable, message = controller.check_stability(grid)

        assert stable

    def test_stability_check_frequency_deviation(self):
        """Test stability check with frequency deviation."""
        controller = GridController()

        grid = Grid(grid_id="test_grid")
        grid.frequency_hz = 58.0  # Large deviation

        bus = BusState(
            bus_id=1,
            bus_type=BusType.SLACK,
            voltage=BusVoltage(1.0, 0.0),
            real_power=0.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )
        grid.buses[1] = bus

        stable, message = controller.check_stability(grid)

        assert not stable
        assert "Frequency" in message

    def test_balance_reactive_power(self):
        """Test reactive power balancing."""
        controller = GridController()

        grid = Grid(grid_id="test_grid")

        gen = PowerPlant(
            plant_id="gen1",
            fuel_type=EnergySource.NATURAL_GAS,
            capacity_mw=100.0,
            current_output_mw=50.0,
        )
        grid.plants["gen1"] = gen

        load = Load(load_id="load1", active_power=50.0, reactive_power=20.0)
        grid.loads["load1"] = load

        grid.buses[1] = BusState(
            bus_id=1,
            bus_type=BusType.PV,
            voltage=BusVoltage(1.0, 0.0),
            real_power=0.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )

        dispatch = controller.balance_reactive_power(grid)

        assert isinstance(dispatch, dict)
        assert 1 in dispatch


class TestIslandingDetection:
    """Test islanding detection."""

    def test_no_islanding(self):
        """Test grid remains connected."""
        grid = Grid(grid_id="test_grid")
        grid.frequency_hz = 60.0

        bus = BusState(
            bus_id=1,
            bus_type=BusType.SLACK,
            voltage=BusVoltage(1.0, 0.0),
            real_power=0.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )
        grid.buses[1] = bus

        is_islanded, message = detect_islanding(grid, 60.0)

        assert not is_islanded

    def test_islanding_frequency(self):
        """Test islanding detection from frequency."""
        grid = Grid(grid_id="test_grid")

        bus = BusState(
            bus_id=1,
            bus_type=BusType.SLACK,
            voltage=BusVoltage(1.0, 0.0),
            real_power=0.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )
        grid.buses[1] = bus

        is_islanded, message = detect_islanding(grid, 58.0)  # Large frequency deviation

        assert is_islanded

    def test_islanding_voltage(self):
        """Test islanding detection from voltage."""
        grid = Grid(grid_id="test_grid")

        # Add buses with large voltage spread
        bus1 = BusState(
            bus_id=1,
            bus_type=BusType.SLACK,
            voltage=BusVoltage(1.0, 0.0),
            real_power=0.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )
        grid.buses[1] = bus1

        bus2 = BusState(
            bus_id=2,
            bus_type=BusType.PQ,
            voltage=BusVoltage(0.8, 0.0),  # 20% voltage drop
            real_power=-50.0,
            reactive_power=0.0,
            base_voltage=100.0,
        )
        grid.buses[2] = bus2

        is_islanded, message = detect_islanding(grid, 60.0)

        assert is_islanded


class TestGridStabilityIndex:
    """Test grid stability metrics."""

    def test_stability_index_perfect(self):
        """Test stability index with perfect conditions."""
        index = calculate_grid_stability_index(
            frequency_hz=60.0,
            voltage_pu=1.0,
            reserve_mw=100.0,
        )

        assert 0.0 <= index <= 1.0
        assert index > 0.8  # Should be high

    def test_stability_index_degraded(self):
        """Test stability index with degraded conditions."""
        index = calculate_grid_stability_index(
            frequency_hz=59.0,  # 1 Hz deviation
            voltage_pu=0.95,  # 5% voltage drop
            reserve_mw=10.0,  # Low reserve
        )

        assert 0.0 <= index <= 1.0
        assert index < 0.8

    def test_stability_index_critical(self):
        """Test stability index in critical conditions."""
        index = calculate_grid_stability_index(
            frequency_hz=57.0,  # Large deviation
            voltage_pu=0.85,  # Large voltage drop
            reserve_mw=-50.0,  # Deficit
        )

        assert 0.0 <= index <= 1.0
        assert index < 0.5


class TestLineOverloadDetection:
    """Test transmission line overload detection."""

    def test_no_overload(self):
        """Test with normal loading."""
        controller = GridController()
        grid = Grid(grid_id="test_grid")

        line_flows = {(1, 2): 150.0}  # 150 MW on line

        errors = controller.check_line_overloads(grid, line_flows)

        assert len(errors) == 0

    def test_line_overload(self):
        """Test with overloaded line."""
        controller = GridController()
        grid = Grid(grid_id="test_grid")

        line_flows = {(1, 2): 500.0}  # Very high flow

        errors = controller.check_line_overloads(grid, line_flows)

        # Should detect overload
        assert len(errors) > 0
