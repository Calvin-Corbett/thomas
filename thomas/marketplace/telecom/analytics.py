"""
Network analytics module.

Implements KPI computation, coverage map generation, traffic heat maps,
capacity forecasting, anomaly detection, and RAN optimization recommendations.
"""

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from thomas.marketplace.telecom._types import BaseStation, Handover


class KPIType(Enum):
    """Key Performance Indicators."""

    DROP_CALL_RATE = "drop_call_rate"
    HANDOVER_SUCCESS_RATE = "handover_success_rate"
    AVERAGE_THROUGHPUT = "avg_throughput"
    AVERAGE_LATENCY = "avg_latency"
    COVERAGE_AREA_PERCENT = "coverage_percent"
    CELL_LOAD = "cell_load"
    VOICE_QUALITY_MOS = "mos"


@dataclass
class KPIMonitor:
    """Monitor and compute network KPIs."""

    kpi_history: dict[str, list[tuple[datetime, float]]] = field(default_factory=dict)
    cell_metrics: dict[str, dict] = field(default_factory=dict)
    call_records: list[dict] = field(default_factory=list)
    handover_records: list[Handover] = field(default_factory=list)

    def record_call_drop(self, cell_id: str, duration_seconds: float) -> None:
        """
        Record a dropped call.

        Args:
            cell_id: Cell ID
            duration_seconds: Call duration before drop
        """
        self.call_records.append(
            {
                "cell_id": cell_id,
                "dropped": True,
                "duration": duration_seconds,
                "timestamp": datetime.now(),
            }
        )

    def record_successful_call(self, cell_id: str, duration_seconds: float) -> None:
        """
        Record a successful call.

        Args:
            cell_id: Cell ID
            duration_seconds: Call duration
        """
        self.call_records.append(
            {
                "cell_id": cell_id,
                "dropped": False,
                "duration": duration_seconds,
                "timestamp": datetime.now(),
            }
        )

    def calculate_drop_call_rate(self, cell_id: str | None = None, time_window_hours: int = 1) -> float:
        """
        Calculate drop call rate.

        Args:
            cell_id: Specific cell or None for network
            time_window_hours: Time window in hours

        Returns:
            Drop call rate as percentage
        """
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        relevant_calls = [
            cr
            for cr in self.call_records
            if cr["timestamp"] > cutoff_time and (cell_id is None or cr["cell_id"] == cell_id)
        ]

        if not relevant_calls:
            return 0.0

        dropped = sum(1 for cr in relevant_calls if cr["dropped"])
        return (dropped / len(relevant_calls)) * 100

    def record_handover(self, handover: Handover) -> None:
        """
        Record handover event.

        Args:
            handover: Handover event
        """
        self.handover_records.append(handover)

    def calculate_handover_success_rate(self, source_cell: str | None = None, time_window_hours: int = 1) -> float:
        """
        Calculate handover success rate.

        Args:
            source_cell: Specific source cell or None
            time_window_hours: Time window in hours

        Returns:
            Success rate as percentage
        """
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        relevant_ho = [
            ho
            for ho in self.handover_records
            if ho.timestamp > cutoff_time and (source_cell is None or ho.source_cell == source_cell)
        ]

        if not relevant_ho:
            return 100.0

        successful = sum(1 for ho in relevant_ho if ho.success)
        return (successful / len(relevant_ho)) * 100

    def record_throughput(self, cell_id: str, throughput_mbps: float) -> None:
        """
        Record throughput measurement.

        Args:
            cell_id: Cell ID
            throughput_mbps: Throughput in Mbps
        """
        if cell_id not in self.cell_metrics:
            self.cell_metrics[cell_id] = {"throughput": []}

        self.cell_metrics[cell_id]["throughput"].append(
            {
                "timestamp": datetime.now(),
                "value": throughput_mbps,
            }
        )

    def calculate_average_throughput(self, cell_id: str | None = None, time_window_hours: int = 1) -> float:
        """
        Calculate average throughput.

        Args:
            cell_id: Specific cell or None for network
            time_window_hours: Time window in hours

        Returns:
            Average throughput in Mbps
        """
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        throughputs = []

        if cell_id:
            cells_to_check = [cell_id]
        else:
            cells_to_check = list(self.cell_metrics.keys())

        for cid in cells_to_check:
            if cid in self.cell_metrics:
                measurements = [
                    m["value"] for m in self.cell_metrics[cid].get("throughput", []) if m["timestamp"] > cutoff_time
                ]
                throughputs.extend(measurements)

        return statistics.mean(throughputs) if throughputs else 0.0

    def calculate_percentile_latency(self, percentile: float = 95.0, cell_id: str | None = None) -> float:
        """
        Calculate latency at percentile.

        Args:
            percentile: Percentile (0-100)
            cell_id: Specific cell or None

        Returns:
            Latency in milliseconds
        """
        latencies = []

        if cell_id:
            cells = [cell_id]
        else:
            cells = list(self.cell_metrics.keys())

        for cid in cells:
            if cid in self.cell_metrics:
                latencies.extend([m["value"] for m in self.cell_metrics[cid].get("latency", [])])

        if not latencies:
            return 0.0

        sorted_latencies = sorted(latencies)
        index = int((percentile / 100) * len(sorted_latencies))
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]


@dataclass
class NetworkAnalytics:
    """Network analytics and optimization."""

    base_stations: dict[str, BaseStation] = field(default_factory=dict)
    kpi_monitor: KPIMonitor = field(default_factory=KPIMonitor)
    coverage_map: dict[tuple[int, int], float] = field(default_factory=dict)

    def add_base_station(self, bs: BaseStation) -> None:
        """
        Add base station for analytics.

        Args:
            bs: BaseStation
        """
        self.base_stations[bs.id] = bs

    def generate_coverage_map(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        grid_size_km: float = 1.0,
    ) -> dict[tuple[int, int], float]:
        """
        Generate coverage map for region.

        Args:
            lat_min: Min latitude
            lat_max: Max latitude
            lon_min: Min longitude
            lon_max: Max longitude
            grid_size_km: Grid cell size in km

        Returns:
            Dict mapping grid coords to signal strength
        """
        km_per_degree = 111.0
        grid_size_degrees = grid_size_km / km_per_degree

        lat = lat_min
        coverage_map = {}
        grid_y = 0

        while lat < lat_max:
            lon = lon_min
            grid_x = 0

            while lon < lon_max:
                max_signal = -150.0

                for bs in self.base_stations.values():
                    distance_m = math.sqrt((bs.lat - lat) ** 2 + (bs.lon - lon) ** 2) * km_per_degree * 1000

                    if distance_m < 50000:
                        path_loss = 20 * math.log10(4 * math.pi * distance_m / 300e6 * 2.1e9)
                        signal = 46.0 - path_loss
                        max_signal = max(max_signal, signal)

                coverage_map[(grid_x, grid_y)] = max_signal
                lon += grid_size_degrees
                grid_x += 1

            lat += grid_size_degrees
            grid_y += 1

        self.coverage_map = coverage_map
        return coverage_map

    def get_coverage_percentage(self, threshold_dbm: float = -95.0) -> float:
        """
        Calculate coverage percentage.

        Args:
            threshold_dbm: Signal strength threshold

        Returns:
            Coverage percentage
        """
        if not self.coverage_map:
            return 0.0

        covered = sum(1 for signal in self.coverage_map.values() if signal >= threshold_dbm)
        return (covered / len(self.coverage_map)) * 100

    def generate_traffic_heatmap(self, cell_load_data: dict[str, float]) -> dict[tuple[float, float], float]:
        """
        Generate traffic heat map.

        Args:
            cell_load_data: Cell load percentage per cell ID

        Returns:
            Dict mapping location to traffic intensity
        """
        heatmap = {}

        for cell_id, load_percent in cell_load_data.items():
            for bs in self.base_stations.values():
                if cell_id in bs.cells:
                    cell = bs.cells[cell_id]
                    location = (cell.lat, cell.lon)
                    heatmap[location] = load_percent

        return heatmap

    def detect_anomalies(
        self,
        kpi_name: str,
        threshold_std_dev: float = 2.0,
    ) -> list[tuple[datetime, float]]:
        """
        Detect KPI anomalies using Z-score.

        Args:
            kpi_name: KPI name
            threshold_std_dev: Number of standard deviations

        Returns:
            List of (timestamp, value) anomalies
        """
        if kpi_name not in self.kpi_monitor.kpi_history:
            return []

        values = [v for _, v in self.kpi_monitor.kpi_history[kpi_name]]
        if len(values) < 2:
            return []

        mean_val = statistics.mean(values)
        std_dev = statistics.stdev(values)

        anomalies = []
        for timestamp, value in self.kpi_monitor.kpi_history[kpi_name]:
            z_score = abs((value - mean_val) / std_dev) if std_dev > 0 else 0
            if z_score > threshold_std_dev:
                anomalies.append((timestamp, value))

        return anomalies

    def forecast_capacity(self, cell_id: str, forecast_days: int = 7) -> list[tuple[datetime, float]]:
        """
        Forecast cell capacity demand.

        Args:
            cell_id: Cell ID
            forecast_days: Days to forecast

        Returns:
            List of (date, predicted_load) tuples
        """
        historical_loads = []
        if cell_id in self.kpi_monitor.cell_metrics:
            historical_loads = [m["value"] for m in self.kpi_monitor.cell_metrics[cell_id].get("load", [])]

        if not historical_loads:
            return []

        trend = (historical_loads[-1] - historical_loads[0]) / len(historical_loads)
        forecast = []

        current_date = datetime.now()
        current_value = historical_loads[-1]

        for day in range(1, forecast_days + 1):
            current_value = min(100.0, current_value + trend)
            forecast_date = current_date + timedelta(days=day)
            forecast.append((forecast_date, current_value))

        return forecast

    def recommend_optimizations(self, cell_id: str | None = None) -> list[str]:
        """
        Recommend RAN optimization actions.

        Args:
            cell_id: Specific cell or None for network

        Returns:
            List of recommendations
        """
        recommendations = []

        dcr = self.kpi_monitor.calculate_drop_call_rate(cell_id)
        if dcr > 2.0:
            recommendations.append("High drop call rate detected. Review backhaul capacity.")

        hsr = self.kpi_monitor.calculate_handover_success_rate(cell_id)
        if hsr < 95.0:
            recommendations.append("Low handover success rate. Optimize handover hysteresis.")

        avg_throughput = self.kpi_monitor.calculate_average_throughput(cell_id)
        if avg_throughput < 5.0:
            recommendations.append("Low average throughput. Consider spectrum refarming.")

        coverage = self.get_coverage_percentage()
        if coverage < 85.0:
            recommendations.append("Coverage gaps detected. Plan new sites.")

        return recommendations if recommendations else ["Network operating normally."]


__all__ = [
    "NetworkAnalytics",
    "KPIMonitor",
    "KPIType",
]
