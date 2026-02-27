"""
Tests for network architecture and management module.
"""

import pytest

from thomas.telecom._types import (
    BaseStation,
    Cell,
    Frequency,
    Protocol,
    Subscriber,
)
from thomas.telecom.network import (
    BackhaulPlanner,
    CellTowerOptimizer,
    FrequencyPlanner,
    HandoverManager,
    LoadBalancer,
    NetworkArchitecture,
    NetworkTopology,
)


class TestNetworkArchitecture:
    """Test network architecture."""

    def test_create_network(self) -> None:
        """Test network creation."""
        network = NetworkArchitecture(
            topology=NetworkTopology.STAR,
            region_name="Test Region",
        )
        assert network.region_name == "Test Region"
        assert network.topology == NetworkTopology.STAR

    def test_add_base_station(self) -> None:
        """Test adding base station."""
        network = NetworkArchitecture()
        bs = BaseStation(name="BS-1", lat=0.0, lon=0.0)
        network.add_base_station(bs)
        assert bs.id in network.base_stations

    def test_find_nearest_basestation(self) -> None:
        """Test finding nearest base station."""
        network = NetworkArchitecture()
        bs1 = BaseStation(name="BS-1", lat=0.0, lon=0.0)
        bs2 = BaseStation(name="BS-2", lat=1.0, lon=1.0)
        network.add_base_station(bs1)
        network.add_base_station(bs2)

        nearest = network.find_nearest_basestation(lat=0.1, lon=0.1)
        assert nearest is not None
        assert nearest.id == bs1.id

    def test_network_load_calculation(self) -> None:
        """Test network load calculation."""
        network = NetworkArchitecture()
        bs = BaseStation(name="BS-1", lat=0.0, lon=0.0)
        cell = Cell(lat=0.0, lon=0.0, radius_meters=1000)
        cell.active_subscribers = 100
        cell.max_subscribers = 500
        bs.cells[cell.id] = cell
        network.add_base_station(bs)

        load = network.get_network_load()
        assert load > 0
        assert load < 100


class TestCellTowerOptimizer:
    """Test cell tower optimization."""

    def test_optimal_spacing_calculation(self) -> None:
        """Test optimal tower spacing."""
        optimizer = CellTowerOptimizer(coverage_radius_km=2.0)
        spacing = optimizer.calculate_optimal_spacing(frequency_mhz=2100, area_km2=100)
        assert spacing > 0
        assert spacing >= optimizer.min_distance_between_towers_km

    def test_towers_needed_estimation(self) -> None:
        """Test tower count estimation."""
        optimizer = CellTowerOptimizer()
        num_towers = optimizer.estimate_towers_needed(area_km2=100, spacing_km=2.0)
        assert num_towers > 0
        assert num_towers <= 100

    def test_grid_location_generation(self) -> None:
        """Test grid location generation."""
        optimizer = CellTowerOptimizer()
        locations = optimizer.generate_grid_locations(center_lat=0.0, center_lon=0.0, num_towers=9, spacing_km=1.0)
        assert len(locations) == 9
        for lat, lon in locations:
            assert -90 <= lat <= 90
            assert -180 <= lon <= 180


class TestFrequencyPlanner:
    """Test frequency planning."""

    def test_add_frequency(self) -> None:
        """Test adding frequency."""
        planner = FrequencyPlanner()
        freq = Frequency(mhz=2100.0)
        planner.add_frequency(freq)
        assert freq in planner.available_frequencies

    def test_frequency_allocation(self) -> None:
        """Test frequency allocation."""
        planner = FrequencyPlanner(reuse_factor=3)
        freqs = [Frequency(mhz=f) for f in [2100, 2105, 2110]]
        for f in freqs:
            planner.add_frequency(f)

        allocation = planner.allocate_frequencies(num_cells=9)
        assert len(allocation) == 9
        for cell_idx, cell_freqs in allocation.items():
            assert isinstance(cell_freqs, list)

    def test_interference_calculation(self) -> None:
        """Test interference calculation."""
        planner = FrequencyPlanner()
        interference = planner.calculate_interference(frequency_mhz=2100, distance_m=5000)
        assert isinstance(interference, float)


class TestHandoverManager:
    """Test handover management."""

    def test_handover_hysteresis(self) -> None:
        """Test handover hysteresis logic."""
        manager = HandoverManager(handover_hysteresis_db=2.0)
        should_ho = manager.should_handover(current_signal_dbm=-100.0, target_signal_dbm=-95.0)
        assert should_ho is True

    def test_handover_no_trigger(self) -> None:
        """Test when handover should not trigger."""
        manager = HandoverManager(handover_hysteresis_db=2.0)
        should_ho = manager.should_handover(current_signal_dbm=-90.0, target_signal_dbm=-95.0)
        assert should_ho is False

    def test_execute_handover_success(self) -> None:
        """Test successful handover execution."""
        manager = HandoverManager(handover_success_rate=1.0)

        subscriber = Subscriber(
            msisdn="1234567890",
            imsi="310410123456789",
            imei="990000862471854",
            name="Test User",
        )

        source_cell = Cell(lat=0.0, lon=0.0, radius_meters=1000)
        source_cell.active_subscribers = 10
        target_cell = Cell(lat=0.1, lon=0.1, radius_meters=1000)
        target_cell.active_subscribers = 5
        target_cell.max_subscribers = 100

        subscriber.current_cell = source_cell

        handover = manager.execute_handover(subscriber, source_cell, target_cell)

        assert handover.success is True
        assert subscriber.current_cell == target_cell
        assert source_cell.active_subscribers == 9
        assert target_cell.active_subscribers == 6

    def test_find_best_target_cell(self) -> None:
        """Test best target cell selection."""
        manager = HandoverManager()

        cell1 = Cell(lat=0.0, lon=0.0, radius_meters=1000)
        cell2 = Cell(lat=0.1, lon=0.1, radius_meters=1000)
        cell3 = Cell(lat=-0.1, lon=-0.1, radius_meters=1000)

        cell2.max_subscribers = 100
        cell3.max_subscribers = 100

        signal_strengths = {
            cell1.id: -100.0,
            cell2.id: -80.0,
            cell3.id: -120.0,
        }

        best = manager.find_best_target_cell(cell1, [cell2, cell3], signal_strengths)
        assert best is not None
        assert best.id == cell2.id


class TestLoadBalancer:
    """Test load balancing."""

    def test_cell_load_calculation(self) -> None:
        """Test cell load percentage."""
        balancer = LoadBalancer()
        cell = Cell(lat=0.0, lon=0.0, radius_meters=1000)
        cell.active_subscribers = 250
        cell.max_subscribers = 500

        load = balancer.get_cell_load(cell)
        assert load == 50.0

    def test_overload_detection(self) -> None:
        """Test overload detection."""
        balancer = LoadBalancer(max_cell_load_percent=80.0)
        cell = Cell(lat=0.0, lon=0.0, radius_meters=1000)
        cell.active_subscribers = 400
        cell.max_subscribers = 500

        assert balancer.is_overloaded(cell) is False

        cell.active_subscribers = 450
        assert balancer.is_overloaded(cell) is True

    def test_find_lightly_loaded_cells(self) -> None:
        """Test finding lightly loaded cells."""
        balancer = LoadBalancer()
        cells = []
        for i in range(3):
            cell = Cell(lat=float(i), lon=0.0, radius_meters=1000)
            cell.max_subscribers = 100
            cell.active_subscribers = 30 + i * 20
            cells.append(cell)

        lightly_loaded = balancer.find_lightly_loaded_cells(cells, threshold_percent=50.0)
        assert len(lightly_loaded) >= 1

    def test_load_variance_calculation(self) -> None:
        """Test load variance."""
        balancer = LoadBalancer()
        cells = []
        for i in range(3):
            cell = Cell(lat=float(i), lon=0.0, radius_meters=1000)
            cell.max_subscribers = 100
            cell.active_subscribers = 25 * (i + 1)
            cells.append(cell)

        variance = balancer.calculate_load_variance(cells)
        assert variance >= 0

    def test_rebalancing_suggestions(self) -> None:
        """Test rebalancing suggestions."""
        balancer = LoadBalancer(max_cell_load_percent=80.0)
        cells = []
        for i in range(3):
            cell = Cell(lat=float(i), lon=0.0, radius_meters=1000)
            cell.max_subscribers = 100
            cell.active_subscribers = 90 if i == 0 else 20
            cells.append(cell)

        suggestions = balancer.suggest_rebalancing(cells)
        assert "overloaded_cells" in suggestions
        assert "underloaded_cells" in suggestions


class TestBackhaulPlanner:
    """Test backhaul planning."""

    def test_backhaul_capacity_estimation(self) -> None:
        """Test backhaul capacity estimation."""
        planner = BackhaulPlanner()
        capacity = planner.estimate_backhaul_capacity(num_subscribers=100, protocol=Protocol.LTE)
        assert capacity > 0

    def test_backhaul_utilization(self) -> None:
        """Test backhaul utilization calculation."""
        planner = BackhaulPlanner()
        utilization = planner.calculate_utilization(current_traffic_mbps=500, capacity_mbps=1000)
        assert utilization == 50.0


if __name__ == "__main__":
    pytest.main([__file__])
