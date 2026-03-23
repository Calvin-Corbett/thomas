"""
Network architecture and optimization module.

Provides cell tower placement optimization, frequency reuse planning, handover
management, load balancing, and network topology management.
"""

import math
from dataclasses import dataclass, field
from enum import Enum

from thomas.marketplace.telecom._exceptions import HandoverFailedError
from thomas.marketplace.telecom._types import (
    BaseStation,
    Cell,
    Frequency,
    Handover,
    Protocol,
    Subscriber,
)


class NetworkTopology(Enum):
    """Network topology types."""

    STAR = "star"
    RING = "ring"
    MESH = "mesh"


@dataclass
class NetworkArchitecture:
    """Network architecture definition."""

    base_stations: dict[str, BaseStation] = field(default_factory=dict)
    topology: NetworkTopology = NetworkTopology.STAR
    core_ip_address: str = "10.0.0.1"
    region_name: str = "default"

    def add_base_station(self, bs: BaseStation) -> None:
        """
        Add a base station to the network.

        Args:
            bs: BaseStation to add
        """
        self.base_stations[bs.id] = bs

    def get_coverage_percentage(self) -> float:
        """
        Calculate total coverage percentage.

        Returns:
            Coverage as percentage of total area
        """
        if not self.base_stations:
            return 0.0
        total_coverage = sum(bs.total_coverage_km2() for bs in self.base_stations.values())
        return min(100.0, total_coverage / 2500.0 * 100)

    def find_nearest_basestation(self, lat: float, lon: float) -> BaseStation | None:
        """
        Find nearest base station to location.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            Nearest BaseStation or None
        """
        if not self.base_stations:
            return None

        min_distance = float("inf")
        nearest = None

        for bs in self.base_stations.values():
            distance = math.sqrt((bs.lat - lat) ** 2 + (bs.lon - lon) ** 2)
            if distance < min_distance:
                min_distance = distance
                nearest = bs

        return nearest

    def get_network_load(self) -> float:
        """
        Calculate network average load.

        Returns:
            Average load percentage
        """
        if not self.base_stations:
            return 0.0

        total_subscribers = sum(bs.total_active_subscribers() for bs in self.base_stations.values())
        total_capacity = sum(
            bs.cells[cell_id].max_subscribers for bs in self.base_stations.values() for cell_id in bs.cells
        )

        return (total_subscribers / total_capacity * 100) if total_capacity > 0 else 0.0


@dataclass
class CellTowerOptimizer:
    """Optimize cell tower placement for coverage and capacity."""

    min_distance_between_towers_km: float = 0.5
    target_coverage_percent: float = 95.0
    coverage_radius_km: float = 2.0

    def calculate_optimal_spacing(self, frequency_mhz: float, area_km2: float) -> float:
        """
        Calculate optimal tower spacing for coverage.

        Args:
            frequency_mhz: Operating frequency in MHz
            area_km2: Area to cover in km²

        Returns:
            Optimal spacing in km
        """
        wavelength_m = 3e8 / (frequency_mhz * 1e6)
        wavelength_km = wavelength_m / 1000

        spacing_km = 2.0 * wavelength_km * self.coverage_radius_km
        return max(spacing_km, self.min_distance_between_towers_km)

    def estimate_towers_needed(self, area_km2: float, spacing_km: float) -> int:
        """
        Estimate number of towers needed.

        Args:
            area_km2: Area in km²
            spacing_km: Tower spacing in km

        Returns:
            Estimated number of towers
        """
        towers_per_km2 = 1.0 / (spacing_km**2)
        return max(1, int(math.ceil(area_km2 * towers_per_km2)))

    def generate_grid_locations(
        self, center_lat: float, center_lon: float, num_towers: int, spacing_km: float
    ) -> list[tuple[float, float]]:
        """
        Generate grid of tower locations around center.

        Args:
            center_lat: Center latitude
            center_lon: Center longitude
            num_towers: Number of towers to place
            spacing_km: Spacing between towers in km

        Returns:
            List of (latitude, longitude) tuples
        """
        locations = []
        km_to_degrees = 1.0 / 111.0

        grid_size = int(math.ceil(math.sqrt(num_towers)))

        for i in range(grid_size):
            for j in range(grid_size):
                if len(locations) >= num_towers:
                    break

                offset_x = (i - grid_size / 2) * spacing_km * km_to_degrees
                offset_y = (j - grid_size / 2) * spacing_km * km_to_degrees

                lat = center_lat + offset_x
                lon = center_lon + offset_y

                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    locations.append((lat, lon))

        return locations[:num_towers]


@dataclass
class FrequencyPlanner:
    """Frequency allocation and reuse planning."""

    available_frequencies: list[Frequency] = field(default_factory=list)
    reuse_factor: int = 3  # 1/3 frequency reuse
    guard_band_mhz: float = 5.0

    def add_frequency(self, frequency: Frequency) -> None:
        """
        Add available frequency.

        Args:
            frequency: Frequency to add
        """
        self.available_frequencies.append(frequency)

    def allocate_frequencies(self, num_cells: int) -> dict[int, list[Frequency]]:
        """
        Allocate frequencies using reuse pattern.

        Args:
            num_cells: Number of cells

        Returns:
            Mapping of cell index to allocated frequencies
        """
        allocation = {}
        freq_index = 0

        for cell_idx in range(num_cells):
            cell_frequencies = []
            reuse_index = cell_idx % self.reuse_factor

            for i, freq in enumerate(self.available_frequencies):
                if i % self.reuse_factor == reuse_index:
                    cell_frequencies.append(freq)

            allocation[cell_idx] = cell_frequencies

        return allocation

    def calculate_interference(self, frequency_mhz: float, distance_m: float) -> float:
        """
        Estimate interference at distance (log-distance model).

        Args:
            frequency_mhz: Frequency in MHz
            distance_m: Distance in meters

        Returns:
            Interference level in dBm
        """
        path_loss = 20 * math.log10(4 * math.pi * distance_m / (3e8 / (frequency_mhz * 1e6)))
        interference = 46.0 - path_loss
        return interference


@dataclass
class HandoverManager:
    """Manage handover operations between cells."""

    handover_hysteresis_db: float = 2.0
    handover_margin_db: float = 3.0
    handover_timeout_ms: int = 200
    handover_success_rate: float = 0.98

    def should_handover(
        self,
        current_signal_dbm: float,
        target_signal_dbm: float,
    ) -> bool:
        """
        Determine if handover should occur using hysteresis.

        Args:
            current_signal_dbm: Signal from current cell in dBm
            target_signal_dbm: Signal from target cell in dBm

        Returns:
            True if handover should occur
        """
        threshold = target_signal_dbm + self.handover_hysteresis_db
        return current_signal_dbm < threshold

    def execute_handover(
        self,
        subscriber: Subscriber,
        source_cell: Cell,
        target_cell: Cell,
    ) -> Handover:
        """
        Execute handover operation.

        Args:
            subscriber: Subscriber performing handover
            source_cell: Source cell
            target_cell: Target cell

        Returns:
            Handover record

        Raises:
            HandoverFailedError: If handover fails
        """
        import random

        if random.random() > self.handover_success_rate:
            raise HandoverFailedError(
                subscriber.msisdn,
                source_cell.id,
                target_cell.id,
                "Random failure simulation",
            )

        if source_cell.active_subscribers > 0:
            source_cell.active_subscribers -= 1
        if target_cell.active_subscribers < target_cell.max_subscribers:
            target_cell.active_subscribers += 1

        subscriber.current_cell = target_cell

        handover = Handover(
            msisdn=subscriber.msisdn,
            source_cell=source_cell.id,
            target_cell=target_cell.id,
            handover_type="hard",
            success=True,
            duration_ms=100.0,
        )

        return handover

    def find_best_target_cell(
        self,
        current_cell: Cell,
        nearby_cells: list[Cell],
        signal_strengths: dict[str, float],
    ) -> Cell | None:
        """
        Find best target cell for handover.

        Args:
            current_cell: Current cell
            nearby_cells: List of nearby cells
            signal_strengths: Dict mapping cell ID to signal strength

        Returns:
            Best target cell or None
        """
        candidates = [
            cell
            for cell in nearby_cells
            if signal_strengths.get(cell.id, -150) > -140 and cell.active_subscribers < cell.max_subscribers
        ]

        if not candidates:
            return None

        return max(candidates, key=lambda c: signal_strengths.get(c.id, -150))


@dataclass
class LoadBalancer:
    """Load balancing across cells."""

    max_cell_load_percent: float = 85.0
    rebalance_threshold_percent: float = 10.0

    def get_cell_load(self, cell: Cell) -> float:
        """
        Get cell load percentage.

        Args:
            cell: Cell to check

        Returns:
            Load percentage
        """
        return cell.load_percentage()

    def is_overloaded(self, cell: Cell) -> bool:
        """
        Check if cell is overloaded.

        Args:
            cell: Cell to check

        Returns:
            True if overloaded
        """
        return self.get_cell_load(cell) > self.max_cell_load_percent

    def find_lightly_loaded_cells(self, cells: list[Cell], threshold_percent: float = 50.0) -> list[Cell]:
        """
        Find lightly loaded cells.

        Args:
            cells: List of cells to check
            threshold_percent: Load threshold

        Returns:
            List of cells below threshold
        """
        return [c for c in cells if self.get_cell_load(c) < threshold_percent]

    def calculate_load_variance(self, cells: list[Cell]) -> float:
        """
        Calculate variance in cell loads.

        Args:
            cells: List of cells

        Returns:
            Load variance
        """
        if not cells:
            return 0.0

        loads = [self.get_cell_load(c) for c in cells]
        mean_load = sum(loads) / len(loads)
        variance = sum((l - mean_load) ** 2 for l in loads) / len(loads)
        return math.sqrt(variance)

    def suggest_rebalancing(self, cells: list[Cell]) -> dict[str, str]:
        """
        Suggest load rebalancing operations.

        Args:
            cells: List of cells

        Returns:
            Dict with rebalancing suggestions
        """
        overloaded = [c for c in cells if self.is_overloaded(c)]
        underloaded = self.find_lightly_loaded_cells(cells)

        suggestions = {
            "overloaded_cells": len(overloaded),
            "underloaded_cells": len(underloaded),
            "action": "rebalance" if overloaded and underloaded else "none",
        }

        return suggestions


@dataclass
class BackhaulPlanner:
    """Plan and optimize backhaul capacity."""

    average_user_throughput_mbps: float = 5.0
    peak_hour_traffic_multiplier: float = 2.5

    def estimate_backhaul_capacity(self, num_subscribers: int, protocol: Protocol = Protocol.LTE) -> float:
        """
        Estimate required backhaul capacity.

        Args:
            num_subscribers: Number of subscribers
            protocol: Protocol type

        Returns:
            Required capacity in Mbps
        """
        if protocol == Protocol.NR:
            throughput = self.average_user_throughput_mbps * 3
        elif protocol == Protocol.LTE:
            throughput = self.average_user_throughput_mbps * 1.5
        else:
            throughput = self.average_user_throughput_mbps

        total_capacity = num_subscribers * throughput * self.peak_hour_traffic_multiplier
        return total_capacity

    def calculate_utilization(self, current_traffic_mbps: float, capacity_mbps: float) -> float:
        """
        Calculate backhaul utilization.

        Args:
            current_traffic_mbps: Current traffic in Mbps
            capacity_mbps: Total capacity in Mbps

        Returns:
            Utilization percentage
        """
        return (current_traffic_mbps / capacity_mbps * 100) if capacity_mbps > 0 else 0.0


__all__ = [
    "NetworkArchitecture",
    "NetworkTopology",
    "CellTowerOptimizer",
    "FrequencyPlanner",
    "HandoverManager",
    "LoadBalancer",
    "BackhaulPlanner",
]
