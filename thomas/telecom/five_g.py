"""
5G specific features and optimizations.

Implements network slicing, massive MIMO, mmWave propagation, beam management,
edge computing/MEC placement, and ultra-reliable low-latency calculations.
"""

import math
from dataclasses import dataclass, field
from enum import Enum

from thomas.telecom._types import NetworkSlice


class SliceType(Enum):
    """5G network slice types."""

    EMBB = "eMBB"  # Enhanced Mobile Broadband
    URLLC = "URLLC"  # Ultra-Reliable Low-Latency
    MMTC = "mMTC"  # Massive Machine Type Communications


@dataclass
class NetworkSlicingManager:
    """Manage 5G network slices."""

    slices: dict[str, NetworkSlice] = field(default_factory=dict)
    total_spectrum_mhz: float = 2000.0
    total_compute_percent: float = 100.0
    subscriber_slice_mapping: dict[str, str] = field(default_factory=dict)

    def create_slice(
        self,
        name: str,
        slice_type: str,
        latency_sla_ms: float,
        throughput_sla_gbps: float,
        reliability_sla_percent: float,
    ) -> NetworkSlice:
        """
        Create network slice.

        Args:
            name: Slice name
            slice_type: eMBB, URLLC, or mMTC
            latency_sla_ms: Latency SLA in ms
            throughput_sla_gbps: Throughput SLA in Gbps
            reliability_sla_percent: Reliability SLA percentage

        Returns:
            Created NetworkSlice
        """
        slice_obj = NetworkSlice(
            name=name,
            slice_type=slice_type,
            latency_sla_ms=latency_sla_ms,
            throughput_sla_gbps=throughput_sla_gbps,
            reliability_sla_percent=reliability_sla_percent,
        )
        self.slices[slice_obj.id] = slice_obj
        return slice_obj

    def allocate_resources_to_slice(
        self,
        slice_id: str,
        spectrum_mhz: float,
        compute_percent: float,
    ) -> bool:
        """
        Allocate resources to slice.

        Args:
            slice_id: Slice ID
            spectrum_mhz: Spectrum in MHz
            compute_percent: Compute percentage

        Returns:
            True if successful
        """
        if slice_id not in self.slices:
            return False

        available_spectrum = self.total_spectrum_mhz - sum(s.allocated_spectrum_mhz for s in self.slices.values())
        available_compute = self.total_compute_percent - sum(s.allocated_compute_percent for s in self.slices.values())

        if spectrum_mhz > available_spectrum or compute_percent > available_compute:
            return False

        slice_obj = self.slices[slice_id]
        slice_obj.allocated_spectrum_mhz = spectrum_mhz
        slice_obj.allocated_compute_percent = compute_percent
        return True

    def assign_subscriber_to_slice(self, msisdn: str, slice_id: str) -> bool:
        """
        Assign subscriber to slice.

        Args:
            msisdn: Phone number
            slice_id: Slice ID

        Returns:
            True if successful
        """
        if slice_id not in self.slices:
            return False

        self.subscriber_slice_mapping[msisdn] = slice_id
        self.slices[slice_id].subscribers.add(msisdn)
        return True

    def get_slice_utilization(self, slice_id: str) -> float:
        """
        Get slice resource utilization.

        Args:
            slice_id: Slice ID

        Returns:
            Utilization percentage
        """
        if slice_id not in self.slices:
            return 0.0

        slice_obj = self.slices[slice_id]
        return slice_obj.resource_utilization()


@dataclass
class MassiveMIMO:
    """Massive MIMO implementation for 5G."""

    num_antennas: int = 64  # Base station antenna array size
    frequency_mhz: float = 3500.0
    subcarrier_spacing_khz: float = 15.0

    def estimate_channel_capacity(
        self,
        snr_db: float,
        num_users: int = 1,
        bandwidth_mhz: float = 100.0,
    ) -> float:
        """
        Estimate capacity with massive MIMO precoding.

        Args:
            snr_db: SNR in dB per antenna element
            num_users: Number of users
            bandwidth_mhz: Bandwidth in MHz

        Returns:
            Capacity in Gbps
        """
        bandwidth_hz = bandwidth_mhz * 1e6
        num_users = max(1, int(num_users))

        array_gain = 10 * math.log10(self.num_antennas)
        effective_snr_db = snr_db + array_gain
        effective_snr_linear = 10 ** (effective_snr_db / 10)

        spatial_streams = max(1, min(self.num_antennas, num_users))
        capacity_hz = bandwidth_hz * spatial_streams * math.log2(1 + effective_snr_linear / num_users)

        return capacity_hz / 1e9

    def calculate_channel_estimation_overhead(self, pilot_sequence_length: int = 128) -> float:
        """
        Calculate overhead for channel estimation.

        Args:
            pilot_sequence_length: Pilot sequence length

        Returns:
            Overhead percentage
        """
        subcarriers_per_frame = 14  # OFDM symbols per slot
        total_subcarriers = 3300  # 100 MHz bandwidth
        overhead = (pilot_sequence_length * self.num_antennas) / (total_subcarriers * subcarriers_per_frame)
        return min(overhead * 100, 50.0)

    def calculate_precoding_gain(
        self,
        num_users: int,
        user_snr_db: float,
    ) -> float:
        """
        Calculate precoding gain (Zero-forcing, MRC, ZFBF).

        Args:
            num_users: Number of users
            user_snr_db: User SNR in dB

        Returns:
            Precoding gain in dB
        """
        if num_users > self.num_antennas:
            return 0.0

        independence_gain = 10 * math.log10(self.num_antennas - num_users + 1)
        multiplexing_gain = 10 * math.log10(num_users)
        total_gain = independence_gain + multiplexing_gain / 2

        return total_gain


@dataclass
class BeamManager:
    """Beam management for mmWave communications."""

    num_beams: int = 64
    beam_width_degrees: float = 5.6
    current_beam_index: int = 0
    beam_training_overhead_percent: float = 5.0

    def calculate_beam_gain(self, angle_from_boresight: float) -> float:
        """
        Calculate beam gain at angle.

        Args:
            angle_from_boresight: Angle in degrees

        Returns:
            Gain in dB relative to boresight
        """
        normalized_angle = abs(angle_from_boresight) / (self.beam_width_degrees / 2)
        boresight_gain = 10 * math.log10(self.num_beams)

        if normalized_angle <= 1.0:
            gain = boresight_gain - 3.0 * (normalized_angle**2)
        else:
            edge_gain = boresight_gain - 3.0
            gain = edge_gain - 12 * (normalized_angle - 1) ** 2

        return gain

    def perform_beam_sweeping(
        self,
        signal_strengths: dict[int, float],
    ) -> int:
        """
        Perform beam sweeping to find best beam.

        Args:
            signal_strengths: Signal strength per beam index

        Returns:
            Best beam index
        """
        if not signal_strengths:
            return self.current_beam_index

        best_beam = max(signal_strengths, key=signal_strengths.get)
        self.current_beam_index = best_beam
        return best_beam

    def estimate_beam_tracking_overhead(self, velocity_kmh: float) -> float:
        """
        Estimate beam tracking overhead for moving user.

        Args:
            velocity_kmh: Velocity in km/h

        Returns:
            Overhead percentage
        """
        beam_tracking_interval_ms = 10
        frequency_ghz = self.num_beams  # Approximation

        beam_change_rate = (velocity_kmh / 3.6) * frequency_ghz / (3e8)
        required_updates = beam_change_rate * beam_tracking_interval_ms / 1000

        overhead = (required_updates / 100) * 100
        return min(overhead, 20.0)

    def narrow_beam_search(
        self,
        signal_strengths: dict[int, float],
        num_best_beams: int = 4,
    ) -> list[int]:
        """
        Narrow beam search for better beams.

        Args:
            signal_strengths: Signal strength per beam
            num_best_beams: Number of best beams to consider

        Returns:
            List of candidate beam indices
        """
        sorted_beams = sorted(signal_strengths.items(), key=lambda x: x[1], reverse=True)

        candidates = []
        for beam_idx, strength in sorted_beams[:num_best_beams]:
            candidates.append(beam_idx)

            for neighboring_beam in [beam_idx - 1, beam_idx + 1]:
                if 0 <= neighboring_beam < self.num_beams and neighboring_beam not in candidates:
                    candidates.append(neighboring_beam)

        return candidates


@dataclass
class MMWavePropagation:
    """mmWave path loss and propagation models."""

    frequency_ghz: float = 28.0
    frequency_dependent_loss: float = 0.0

    def __post_init__(self) -> None:
        self.frequency_dependent_loss = 20 * math.log10(self.frequency_ghz * 1000)

    def calculate_path_loss_los(self, distance_m: float) -> float:
        """
        Line-of-sight mmWave path loss.

        Args:
            distance_m: Distance in meters

        Returns:
            Path loss in dB
        """
        wavelength = 3e8 / (self.frequency_ghz * 1e9)
        path_loss = 20 * math.log10(4 * math.pi * distance_m / wavelength) + self.frequency_dependent_loss
        return path_loss

    def calculate_path_loss_nlos(self, distance_m: float, num_obstacles: int = 1) -> float:
        """
        Non-line-of-sight mmWave path loss (with obstruction).

        Args:
            distance_m: Distance in meters
            num_obstacles: Number of obstructions

        Returns:
            Path loss in dB
        """
        los_loss = self.calculate_path_loss_los(distance_m)
        obstruction_loss = num_obstacles * 25.0
        return los_loss + obstruction_loss

    def estimate_coverage_range(
        self,
        tx_power_dbm: float,
        sensitivity_dbm: float,
        antenna_gain_dbi: float = 0.0,
    ) -> float:
        """
        Estimate coverage range.

        Args:
            tx_power_dbm: Transmit power in dBm
            sensitivity_dbm: Receiver sensitivity in dBm
            antenna_gain_dbi: Antenna gain in dBi

        Returns:
            Coverage range in meters
        """
        eirp = tx_power_dbm + antenna_gain_dbi
        path_loss_budget = eirp - sensitivity_dbm

        wavelength = 3e8 / (self.frequency_ghz * 1e9)
        distance = (wavelength / (4 * math.pi)) * 10 ** (path_loss_budget / 20)

        return distance


@dataclass
class EdgeComputeOptimizer:
    """Optimize Multi-access Edge Computing (MEC) placement."""

    mec_locations: dict[str, dict] = field(default_factory=dict)
    subscriber_latency_targets: dict[str, float] = field(default_factory=dict)

    def add_mec_location(
        self,
        location_id: str,
        lat: float,
        lon: float,
        compute_capacity_percent: float,
    ) -> None:
        """
        Add MEC location.

        Args:
            location_id: Location ID
            lat: Latitude
            lon: Longitude
            compute_capacity_percent: Available compute capacity
        """
        self.mec_locations[location_id] = {
            "lat": lat,
            "lon": lon,
            "compute_capacity": compute_capacity_percent,
            "current_load_percent": 0.0,
        }

    def calculate_edge_latency(
        self,
        distance_km: float,
        processing_time_ms: float = 10.0,
    ) -> float:
        """
        Calculate latency to MEC server.

        Args:
            distance_km: Distance to MEC in km
            processing_time_ms: Processing time in ms

        Returns:
            Total latency in ms
        """
        network_speed_km_per_ms = 3e5 / 1000 / 1000
        propagation_latency = distance_km / network_speed_km_per_ms
        return propagation_latency + processing_time_ms

    def select_optimal_mec(
        self,
        subscriber_lat: float,
        subscriber_lon: float,
        latency_requirement_ms: float,
    ) -> str | None:
        """
        Select optimal MEC location for subscriber.

        Args:
            subscriber_lat: Subscriber latitude
            subscriber_lon: Subscriber longitude
            latency_requirement_ms: Maximum acceptable latency

        Returns:
            MEC location ID or None
        """
        candidates = []

        for loc_id, loc_data in self.mec_locations.items():
            distance_km = (
                math.sqrt((subscriber_lat - loc_data["lat"]) ** 2 + (subscriber_lon - loc_data["lon"]) ** 2) * 111
            )  # approx km per degree

            latency = self.calculate_edge_latency(distance_km)

            if latency <= latency_requirement_ms:
                candidates.append((loc_id, loc_data["current_load_percent"], latency))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[1], x[2]))
        return candidates[0][0]

    def estimate_urllc_latency_budget(self) -> dict[str, float]:
        """
        Estimate URLLC latency budget breakdown.

        Returns:
            Dict with latency components in ms
        """
        return {
            "scheduling": 0.5,  # Scheduling delay
            "transmission": 0.125,  # 1 slot = 0.5ms
            "retransmission": 0.5,  # HARQ round
            "processing": 1.0,  # Edge computing
            "propagation": 1.0,  # Network propagation
            "total": 3.125,  # Total available
        }


__all__ = [
    "NetworkSlicingManager",
    "MassiveMIMO",
    "BeamManager",
    "MMWavePropagation",
    "EdgeComputeOptimizer",
    "SliceType",
]
