"""
Spectrum management module.

Handles frequency allocation, interference calculation, spectrum efficiency,
dynamic spectrum access, cognitive radio, and spectrum auctions.
"""

import math
from dataclasses import dataclass, field
from enum import Enum

from thomas.telecom._types import Frequency


class SpectrumBand(Enum):
    """Licensed spectrum bands."""

    BAND_800 = (800, 900)  # 2G
    BAND_900 = (890, 960)  # 2G
    BAND_1800 = (1800, 1900)  # 2G/3G
    BAND_2100 = (2100, 2200)  # 3G
    BAND_2600 = (2600, 2690)  # 4G/5G
    BAND_3500 = (3400, 3600)  # 5G
    BAND_26 = (24000, 29000)  # 5G mmWave
    BAND_28 = (27000, 28350)  # 5G mmWave
    BAND_39 = (1880, 1920)  # 5G


@dataclass
class SpectrumAllocation:
    """Spectrum allocation to operator."""

    operator_id: str
    band: SpectrumBand
    start_mhz: float
    end_mhz: float
    technology: str  # GSM, UMTS, LTE, NR
    license_expiry: str


@dataclass
class SpectrumManager:
    """Manage spectrum allocation and efficiency."""

    allocations: dict[str, SpectrumAllocation] = field(default_factory=dict)
    allocated_frequencies: set[float] = field(default_factory=set)
    efficiency_metrics: dict[str, float] = field(default_factory=dict)

    def allocate_spectrum(
        self,
        operator_id: str,
        band: SpectrumBand,
        start_mhz: float,
        end_mhz: float,
        technology: str,
    ) -> bool:
        """
        Allocate spectrum to operator.

        Args:
            operator_id: Operator ID
            band: Spectrum band
            start_mhz: Start frequency
            end_mhz: End frequency
            technology: Technology type

        Returns:
            True if successful
        """
        for freq in range(int(start_mhz), int(end_mhz)):
            if freq in self.allocated_frequencies:
                return False
            self.allocated_frequencies.add(freq)

        allocation = SpectrumAllocation(
            operator_id=operator_id,
            band=band,
            start_mhz=start_mhz,
            end_mhz=end_mhz,
            technology=technology,
            license_expiry="2029-12-31",
        )

        allocation_key = f"{operator_id}_{band.name}"
        self.allocations[allocation_key] = allocation
        return True

    def get_available_spectrum(self) -> list[tuple[float, float]]:
        """
        Get available spectrum ranges.

        Returns:
            List of available frequency ranges
        """
        all_frequencies = set()
        for band in SpectrumBand:
            for freq in range(band.value[0], band.value[1]):
                all_frequencies.add(freq)

        available = []
        current_range_start = None

        for freq in sorted(all_frequencies):
            if freq not in self.allocated_frequencies:
                if current_range_start is None:
                    current_range_start = freq
            else:
                if current_range_start is not None:
                    available.append((float(current_range_start), float(freq)))
                    current_range_start = None

        if current_range_start is not None:
            available.append((float(current_range_start), float(max(all_frequencies))))

        return available

    def calculate_spectrum_efficiency_bps_hz(self, data_rate_bps: float, bandwidth_hz: float) -> float:
        """
        Calculate spectrum efficiency.

        Args:
            data_rate_bps: Data rate in bits per second
            bandwidth_hz: Bandwidth in Hz

        Returns:
            Efficiency in bits/second/Hz
        """
        return data_rate_bps / bandwidth_hz if bandwidth_hz > 0 else 0.0


@dataclass
class InterferenceCalculator:
    """Calculate interference between channels."""

    reference_distance_m: float = 1.0

    def calculate_ci_ratio(
        self,
        carrier_power_dbm: float,
        interference_power_dbm: float,
    ) -> float:
        """
        Calculate Carrier-to-Interference ratio.

        Args:
            carrier_power_dbm: Carrier power in dBm
            interference_power_dbm: Interference power in dBm

        Returns:
            C/I ratio in dB
        """
        carrier_linear = 10 ** (carrier_power_dbm / 10)
        interference_linear = 10 ** (interference_power_dbm / 10)
        ci_ratio = 10 * math.log10(carrier_linear / interference_linear)
        return ci_ratio

    def calculate_sinr(
        self,
        carrier_power_dbm: float,
        noise_power_dbm: float,
        interference_power_dbm: float,
    ) -> float:
        """
        Calculate Signal-to-Interference-and-Noise Ratio.

        Args:
            carrier_power_dbm: Carrier power in dBm
            noise_power_dbm: Noise power in dBm
            interference_power_dbm: Interference power in dBm

        Returns:
            SINR in dB
        """
        carrier_linear = 10 ** (carrier_power_dbm / 10)
        noise_linear = 10 ** (noise_power_dbm / 10)
        interference_linear = 10 ** (interference_power_dbm / 10)
        sinr = carrier_linear / (noise_linear + interference_linear)
        return 10 * math.log10(sinr)

    def estimate_interference_distance(
        self,
        tx_power_dbm: float,
        interference_threshold_dbm: float,
        frequency_mhz: float,
    ) -> float:
        """
        Estimate distance at which interference exceeds threshold.

        Args:
            tx_power_dbm: Transmit power in dBm
            interference_threshold_dbm: Threshold in dBm
            frequency_mhz: Frequency in MHz

        Returns:
            Distance in meters
        """
        path_loss = tx_power_dbm - interference_threshold_dbm
        frequency_hz = frequency_mhz * 1e6
        wavelength = 3e8 / frequency_hz

        distance = (wavelength / (4 * math.pi)) * 10 ** (path_loss / 20)
        return distance


@dataclass
class CognitiveRadio:
    """Cognitive radio for dynamic spectrum access."""

    sensed_frequencies: dict[float, float] = field(default_factory=dict)
    detection_threshold_dbm: float = -95.0
    sensing_duration_ms: int = 10
    energy_samples: int = 1000

    def perform_energy_detection(self, frequency_mhz: float, signal_power_dbm: float) -> bool:
        """
        Perform energy detection on frequency.

        Args:
            frequency_mhz: Frequency to sense
            signal_power_dbm: Sensed signal power

        Returns:
            True if spectrum occupied
        """
        self.sensed_frequencies[frequency_mhz] = signal_power_dbm
        return signal_power_dbm > self.detection_threshold_dbm

    def identify_spectrum_holes(self, frequency_range_mhz: tuple[float, float]) -> list[tuple[float, float]]:
        """
        Identify available spectrum holes.

        Args:
            frequency_range_mhz: Frequency range to scan

        Returns:
            List of available frequency ranges
        """
        holes = []
        start_freq, end_freq = frequency_range_mhz
        current_start = None

        for freq in sorted(self.sensed_frequencies.keys()):
            if start_freq <= freq <= end_freq:
                is_occupied = self.sensed_frequencies[freq] > self.detection_threshold_dbm

                if not is_occupied:
                    if current_start is None:
                        current_start = freq
                else:
                    if current_start is not None:
                        holes.append((current_start, freq))
                        current_start = None

        if current_start is not None:
            holes.append((current_start, end_freq))

        return holes

    def calculate_spectrum_sensing_time(self, pfa: float = 0.1, pd: float = 0.9, snr_db: float = 5.0) -> float:
        """
        Calculate required sensing time for reliability.

        Uses Neyman-Pearson detector analysis.

        Args:
            pfa: Probability of false alarm
            pd: Probability of detection
            snr_db: Signal-to-noise ratio

        Returns:
            Required sensing time in seconds
        """
        snr_linear = 10 ** (snr_db / 10)
        required_samples = (2 / (snr_linear**2)) * math.log(pfa / (1 - pd))
        return max(1, required_samples / (self.energy_samples / self.sensing_duration_ms * 1000))


@dataclass
class SpectrumAuction:
    """Spectrum auction simulation (Vickrey auction)."""

    frequencies: list[Frequency] = field(default_factory=list)
    bids: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    winners: dict[str, list[Frequency]] = field(default_factory=dict)
    payments: dict[str, float] = field(default_factory=dict)

    def add_frequency(self, frequency: Frequency) -> None:
        """
        Add frequency for auction.

        Args:
            frequency: Frequency to auction
        """
        self.frequencies.append(frequency)

    def submit_bid(self, operator_id: str, frequency_mhz: float, bid_amount: float) -> None:
        """
        Submit bid for frequency.

        Args:
            operator_id: Operator ID
            frequency_mhz: Frequency bid on
            bid_amount: Bid amount
        """
        if operator_id not in self.bids:
            self.bids[operator_id] = []

        self.bids[operator_id].append((frequency_mhz, bid_amount))

    def run_vickrey_auction(self) -> dict[str, dict]:
        """
        Run Vickrey (second-price sealed bid) auction.

        Returns:
            Dict with auction results
        """
        results = {}

        for frequency in self.frequencies:
            freq_bids = []

            for operator_id, bid_list in self.bids.items():
                for bid_freq, bid_amount in bid_list:
                    if abs(bid_freq - frequency.mhz) < 1.0:
                        freq_bids.append((operator_id, bid_amount))

            if freq_bids:
                freq_bids.sort(key=lambda x: x[1], reverse=True)

                winner = freq_bids[0][0]
                payment = freq_bids[1][1] if len(freq_bids) > 1 else freq_bids[0][1] * 0.9

                if winner not in self.winners:
                    self.winners[winner] = []
                self.winners[winner].append(frequency)
                self.payments[winner] = self.payments.get(winner, 0.0) + payment

                results[frequency.id] = {
                    "winner": winner,
                    "payment": payment,
                    "bids": len(freq_bids),
                }

        return results


@dataclass
class GuardBandCalculator:
    """Calculate guard bands between channels."""

    default_guard_band_percent: float = 5.0

    def calculate_guard_band_mhz(self, channel_bandwidth_mhz: float) -> float:
        """
        Calculate guard band width.

        Args:
            channel_bandwidth_mhz: Channel bandwidth in MHz

        Returns:
            Guard band width in MHz
        """
        return channel_bandwidth_mhz * (self.default_guard_band_percent / 100.0)

    def check_coexistence(
        self,
        freq1_mhz: float,
        bandwidth1_mhz: float,
        freq2_mhz: float,
        bandwidth2_mhz: float,
    ) -> bool:
        """
        Check if two channels can coexist without guard band violation.

        Args:
            freq1_mhz: Center frequency 1 in MHz
            bandwidth1_mhz: Bandwidth 1 in MHz
            freq2_mhz: Center frequency 2 in MHz
            bandwidth2_mhz: Bandwidth 2 in MHz

        Returns:
            True if channels can coexist
        """
        guard_band1 = self.calculate_guard_band_mhz(bandwidth1_mhz)
        guard_band2 = self.calculate_guard_band_mhz(bandwidth2_mhz)

        edge1_upper = freq1_mhz + (bandwidth1_mhz / 2) + guard_band1
        edge2_lower = freq2_mhz - (bandwidth2_mhz / 2) - guard_band2

        return (
            edge1_upper <= edge2_lower
            or freq2_mhz + (bandwidth2_mhz / 2) + guard_band2 <= freq1_mhz - (bandwidth1_mhz / 2) - guard_band1
        )


__all__ = [
    "SpectrumManager",
    "InterferenceCalculator",
    "CognitiveRadio",
    "SpectrumAuction",
    "GuardBandCalculator",
    "SpectrumBand",
    "SpectrumAllocation",
]
