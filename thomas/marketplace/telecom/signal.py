"""
Signal processing module for telecommunications networks.

Implements path loss models, fading channels, SNR calculation, Shannon capacity,
link budget analysis, antenna patterns, and beamforming algorithms.
"""

import math
from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class PathLossModelType(Enum):
    """Path loss model selection."""

    FREE_SPACE = "free_space"
    OKUMURA_HATA = "okumura_hata"
    COST_231 = "cost_231"


@dataclass
class PathLossModel:
    """Path loss calculation models for radio propagation."""

    model_type: PathLossModelType = PathLossModelType.FREE_SPACE
    reference_distance_m: float = 1.0
    reference_loss_db: float = 0.0

    def free_space_path_loss(self, distance_m: float, frequency_mhz: float) -> float:
        """
        Calculate free-space path loss using Friis equation.

        Args:
            distance_m: Distance in meters
            frequency_mhz: Frequency in MHz

        Returns:
            Path loss in dB
        """
        if distance_m <= 0:
            return 0.0
        frequency_hz = frequency_mhz * 1e6
        wavelength = 3e8 / frequency_hz
        path_loss = 20 * math.log10((4 * math.pi * distance_m) / wavelength)
        return path_loss

    def okumura_hata_path_loss(
        self,
        distance_m: float,
        frequency_mhz: float,
        tx_height_m: float = 50.0,
        rx_height_m: float = 1.5,
        urban: bool = True,
    ) -> float:
        """
        Okumura-Hata path loss model (150-1500 MHz, 1-20 km).

        Args:
            distance_m: Distance in meters
            frequency_mhz: Frequency in MHz
            tx_height_m: Transmitter height in meters
            rx_height_m: Receiver height in meters
            urban: Urban area (True) or suburban (False)

        Returns:
            Path loss in dB
        """
        if distance_m <= 0:
            return 0.0

        distance_km = distance_m / 1000.0
        freq_log = math.log10(frequency_mhz)
        distance_log = math.log10(distance_km)

        base_loss = (
            69.55
            + 26.16 * freq_log
            - 13.82 * math.log10(tx_height_m)
            + (44.9 - 6.55 * math.log10(tx_height_m)) * distance_log
        )

        if urban:
            correction = -13.82 * math.log10(tx_height_m) + 0.14 * (frequency_mhz - 150) / 100
        else:
            correction = -4.78 * (freq_log**2) + 18.33 * freq_log - 40.94

        return base_loss + correction

    def cost_231_path_loss(
        self,
        distance_m: float,
        frequency_mhz: float,
        tx_height_m: float = 50.0,
        rx_height_m: float = 1.5,
        urban: bool = True,
    ) -> float:
        """
        COST-231 Hata path loss model (800-2000 MHz).

        Args:
            distance_m: Distance in meters
            frequency_mhz: Frequency in MHz
            tx_height_m: Transmitter height in meters
            rx_height_m: Receiver height in meters
            urban: Urban area (True) or suburban (False)

        Returns:
            Path loss in dB
        """
        if distance_m <= 0:
            return 0.0

        distance_km = distance_m / 1000.0
        freq_log = math.log10(frequency_mhz)
        distance_log = math.log10(distance_km)

        base_loss = (
            46.3
            + 33.9 * freq_log
            - 13.82 * math.log10(tx_height_m)
            + (44.9 - 6.55 * math.log10(tx_height_m)) * distance_log
        )

        if urban:
            cm = 0.0
        else:
            cm = -6.0

        return base_loss + cm

    def calculate(
        self,
        distance_m: float,
        frequency_mhz: float,
        tx_height_m: float = 50.0,
        rx_height_m: float = 1.5,
    ) -> float:
        """
        Calculate path loss based on selected model.

        Args:
            distance_m: Distance in meters
            frequency_mhz: Frequency in MHz
            tx_height_m: Transmitter height in meters
            rx_height_m: Receiver height in meters

        Returns:
            Path loss in dB
        """
        if self.model_type == PathLossModelType.FREE_SPACE:
            return self.free_space_path_loss(distance_m, frequency_mhz)
        elif self.model_type == PathLossModelType.OKUMURA_HATA:
            return self.okumura_hata_path_loss(distance_m, frequency_mhz, tx_height_m, rx_height_m)
        elif self.model_type == PathLossModelType.COST_231:
            return self.cost_231_path_loss(distance_m, frequency_mhz, tx_height_m, rx_height_m)
        return 0.0


@dataclass
class SignalProcessor:
    """Signal processing and propagation calculations."""

    path_loss_model: PathLossModel = field(default_factory=PathLossModel)
    shadowing_std_db: float = 6.0  # Log-normal shadowing standard deviation
    fading_type: str = "rayleigh"  # rayleigh or rician

    def log_normal_shadowing(self, distance_m: float) -> float:
        """
        Log-normal shadowing (multipath fading variance).

        Args:
            distance_m: Distance in meters

        Returns:
            Shadowing loss in dB
        """
        return float(np.random.normal(0, self.shadowing_std_db))

    def rayleigh_fading(self) -> float:
        """
        Rayleigh fading (non-line-of-sight).

        Returns:
            Fading magnitude in linear scale
        """
        i = np.random.normal(0, 1)
        q = np.random.normal(0, 1)
        magnitude = math.sqrt(i**2 + q**2)
        return 10 * math.log10(magnitude**2)

    def rician_fading(self, k_factor: float = 5.0) -> float:
        """
        Rician fading (line-of-sight with multipath).

        Args:
            k_factor: Rician K-factor (ratio of LoS to multipath power)

        Returns:
            Fading magnitude in dB
        """
        los_power = math.sqrt(2 * k_factor / (k_factor + 1))
        multipath_i = np.random.normal(0, math.sqrt(1 / (k_factor + 1)))
        multipath_q = np.random.normal(0, math.sqrt(1 / (k_factor + 1)))
        magnitude = math.sqrt((los_power + multipath_i) ** 2 + multipath_q**2)
        return 10 * math.log10(magnitude**2)

    def calculate_fading(self, k_factor: float = 0.0) -> float:
        """
        Calculate fading based on configured type.

        Args:
            k_factor: Rician K-factor (only used for Rician fading)

        Returns:
            Fading in dB
        """
        if self.fading_type == "rician":
            return self.rician_fading(k_factor)
        return self.rayleigh_fading()

    def calculate_received_power(
        self,
        tx_power_dbm: float,
        distance_m: float,
        frequency_mhz: float,
        antenna_gain_dbi: float = 0.0,
        include_fading: bool = True,
        include_shadowing: bool = True,
    ) -> float:
        """
        Calculate received power at receiver.

        Args:
            tx_power_dbm: Transmit power in dBm
            distance_m: Distance in meters
            frequency_mhz: Frequency in MHz
            antenna_gain_dbi: Antenna gain in dBi
            include_fading: Include fast fading
            include_shadowing: Include slow fading (shadowing)

        Returns:
            Received power in dBm
        """
        path_loss = self.path_loss_model.calculate(distance_m, frequency_mhz)
        rx_power = tx_power_dbm + antenna_gain_dbi - path_loss

        if include_shadowing:
            rx_power += self.log_normal_shadowing(distance_m)

        if include_fading:
            rx_power += self.calculate_fading()

        return rx_power

    def calculate_snr(
        self,
        rx_power_dbm: float,
        noise_power_dbm: float,
        interference_power_dbm: float = -100.0,
    ) -> float:
        """
        Calculate Signal-to-Noise Ratio.

        Args:
            rx_power_dbm: Received signal power in dBm
            noise_power_dbm: Noise power in dBm
            interference_power_dbm: Interference power in dBm

        Returns:
            SNR in dB
        """
        signal_linear = 10 ** (rx_power_dbm / 10)
        noise_linear = 10 ** (noise_power_dbm / 10)
        interference_linear = 10 ** (interference_power_dbm / 10)
        sinr_linear = signal_linear / (noise_linear + interference_linear)
        return 10 * math.log10(sinr_linear)

    def shannon_capacity(self, bandwidth_hz: float, snr_db: float) -> float:
        """
        Calculate Shannon channel capacity.

        Args:
            bandwidth_hz: Bandwidth in Hz
            snr_db: Signal-to-Noise Ratio in dB

        Returns:
            Capacity in bits per second
        """
        snr_linear = 10 ** (snr_db / 10)
        return bandwidth_hz * math.log2(1 + snr_linear)

    def link_budget_analysis(
        self,
        tx_power_dbm: float,
        distance_m: float,
        frequency_mhz: float,
        tx_antenna_gain_dbi: float = 0.0,
        rx_antenna_gain_dbi: float = 0.0,
        rx_noise_figure_db: float = 5.0,
        required_snr_db: float = 7.0,
    ) -> dict:
        """
        Perform link budget analysis.

        Args:
            tx_power_dbm: Transmit power in dBm
            distance_m: Distance in meters
            frequency_mhz: Frequency in MHz
            tx_antenna_gain_dbi: TX antenna gain in dBi
            rx_antenna_gain_dbi: RX antenna gain in dBi
            rx_noise_figure_db: RX noise figure in dB
            required_snr_db: Required SNR in dB

        Returns:
            Dictionary with link budget analysis
        """
        path_loss = self.path_loss_model.calculate(distance_m, frequency_mhz)
        eirp = tx_power_dbm + tx_antenna_gain_dbi
        rx_power = eirp + rx_antenna_gain_dbi - path_loss
        noise_power_dbm = -174 + 10 * math.log10(1e6) + rx_noise_figure_db
        snr = self.calculate_snr(rx_power, noise_power_dbm)
        margin = snr - required_snr_db

        return {
            "tx_power_dbm": tx_power_dbm,
            "eirp_dbm": eirp,
            "path_loss_db": path_loss,
            "rx_power_dbm": rx_power,
            "noise_power_dbm": noise_power_dbm,
            "snr_db": snr,
            "required_snr_db": required_snr_db,
            "link_margin_db": margin,
            "feasible": margin >= 0,
        }


@dataclass
class AntennaPattern:
    """Antenna radiation patterns and gain calculations."""

    pattern_type: str = "directional"  # isotropic, directional, mimo
    azimuth_degrees: float = 0.0
    elevation_degrees: float = 0.0
    gain_dbi: float = 10.0
    beamwidth_degrees: float = 65.0
    side_lobe_suppression_db: float = 13.0

    def isotropic_gain(self) -> float:
        """
        Isotropic antenna (equal gain in all directions).

        Returns:
            Gain in dBi (reference)
        """
        return 0.0

    def directional_gain(self, target_azimuth: float, target_elevation: float) -> float:
        """
        Calculate directional antenna gain.

        Args:
            target_azimuth: Target azimuth in degrees
            target_elevation: Target elevation in degrees

        Returns:
            Gain in dBi
        """
        azimuth_offset = abs(target_azimuth - self.azimuth_degrees)
        elevation_offset = abs(target_elevation - self.elevation_degrees)

        azimuth_offset = min(azimuth_offset, 360 - azimuth_offset)
        normalized_az = azimuth_offset / (self.beamwidth_degrees / 2)
        normalized_el = elevation_offset / (self.beamwidth_degrees / 2)

        normalized = math.sqrt(normalized_az**2 + normalized_el**2)

        if normalized <= 1.0:
            gain = self.gain_dbi
        else:
            gain = self.gain_dbi - 12 * (normalized - 1) ** 2
            gain = max(gain, self.gain_dbi - self.side_lobe_suppression_db)

        return gain

    def calculate_gain(self, target_azimuth: float = 0.0, target_elevation: float = 0.0) -> float:
        """
        Calculate antenna gain based on pattern type.

        Args:
            target_azimuth: Target azimuth in degrees
            target_elevation: Target elevation in degrees

        Returns:
            Gain in dBi
        """
        if self.pattern_type == "isotropic":
            return self.isotropic_gain()
        elif self.pattern_type == "directional":
            return self.directional_gain(target_azimuth, target_elevation)
        elif self.pattern_type == "mimo":
            return self.gain_dbi + 10 * math.log10(4)  # 4 element MIMO
        return self.gain_dbi


@dataclass
class Beamformer:
    """Beamforming for phased array antennas."""

    num_elements: int = 8
    element_spacing_wavelengths: float = 0.5
    frequency_mhz: float = 2100.0

    def steering_vector(self, angle_degrees: float) -> np.ndarray:
        """
        Calculate phased array steering vector.

        Args:
            angle_degrees: Target angle in degrees from boresight

        Returns:
            Complex steering vector
        """
        angle_rad = math.radians(angle_degrees)
        indices = np.arange(self.num_elements)
        phase_shift = 2 * math.pi * self.element_spacing_wavelengths * np.sin(angle_rad)
        return np.exp(1j * phase_shift * indices)

    def calculate_weights(self, target_angle_degrees: float) -> np.ndarray:
        """
        Calculate beamformer weights for target angle.

        Args:
            target_angle_degrees: Target angle in degrees

        Returns:
            Complex weights for each element
        """
        steering = self.steering_vector(target_angle_degrees)
        weights = steering / np.sqrt(self.num_elements)
        return weights

    def main_lobe_gain(self) -> float:
        """
        Calculate main lobe gain in dBi.

        Returns:
            Gain in dBi
        """
        return 10 * math.log10(self.num_elements)

    def half_power_beamwidth(self) -> float:
        """
        Calculate half-power beamwidth.

        Returns:
            Beamwidth in degrees
        """
        wavelength = 3e8 / (self.frequency_mhz * 1e6)
        d_wavelengths = self.element_spacing_wavelengths
        return math.degrees(0.886 / (self.num_elements * d_wavelengths))

    def array_pattern(self, angle_degrees: float, target_angle_degrees: float = 0.0) -> float:
        """
        Calculate array pattern response.

        Args:
            angle_degrees: Angle to evaluate
            target_angle_degrees: Target steering angle

        Returns:
            Pattern response in dB
        """
        steering = self.steering_vector(target_angle_degrees)
        observation = self.steering_vector(angle_degrees)
        response = np.abs(np.dot(steering.conj(), observation)) ** 2
        response_db = 10 * math.log10(response / self.num_elements)
        return response_db


__all__ = [
    "PathLossModel",
    "PathLossModelType",
    "SignalProcessor",
    "AntennaPattern",
    "Beamformer",
]
