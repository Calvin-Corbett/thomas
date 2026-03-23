"""
Tests for signal processing module.
"""

import math

import pytest

from thomas.marketplace.telecom.signal import (
    AntennaPattern,
    Beamformer,
    PathLossModel,
    PathLossModelType,
    SignalProcessor,
)


class TestPathLossModel:
    """Test path loss models."""

    def test_free_space_path_loss(self) -> None:
        """Test free-space path loss calculation."""
        model = PathLossModel(model_type=PathLossModelType.FREE_SPACE)
        loss = model.free_space_path_loss(distance_m=1000, frequency_mhz=2100)
        assert loss > 0
        assert loss < 150

    def test_free_space_path_loss_zero_distance(self) -> None:
        """Test path loss at zero distance."""
        model = PathLossModel()
        loss = model.free_space_path_loss(0, 2100)
        assert loss == 0.0

    def test_okumura_hata_path_loss(self) -> None:
        """Test Okumura-Hata model."""
        model = PathLossModel(model_type=PathLossModelType.OKUMURA_HATA)
        loss = model.okumura_hata_path_loss(distance_m=5000, frequency_mhz=900, tx_height_m=50)
        assert loss > 0
        assert loss < 200

    def test_cost_231_path_loss(self) -> None:
        """Test COST-231 model."""
        model = PathLossModel(model_type=PathLossModelType.COST_231)
        loss = model.cost_231_path_loss(distance_m=2000, frequency_mhz=1800)
        assert loss > 0
        assert loss < 180

    def test_path_loss_frequency_dependency(self) -> None:
        """Test that path loss increases with frequency."""
        model = PathLossModel(model_type=PathLossModelType.FREE_SPACE)
        loss_900 = model.free_space_path_loss(1000, 900)
        loss_2100 = model.free_space_path_loss(1000, 2100)
        assert loss_2100 > loss_900

    def test_path_loss_distance_dependency(self) -> None:
        """Test that path loss increases with distance."""
        model = PathLossModel(model_type=PathLossModelType.FREE_SPACE)
        loss_1km = model.free_space_path_loss(1000, 2100)
        loss_10km = model.free_space_path_loss(10000, 2100)
        assert loss_10km > loss_1km


class TestSignalProcessor:
    """Test signal processing."""

    def test_received_power_calculation(self) -> None:
        """Test received power calculation."""
        processor = SignalProcessor()
        rx_power = processor.calculate_received_power(
            tx_power_dbm=46.0,
            distance_m=1000,
            frequency_mhz=2100,
            include_fading=False,
            include_shadowing=False,
        )
        assert rx_power < 46.0
        assert rx_power > -150.0

    def test_snr_calculation(self) -> None:
        """Test SNR calculation."""
        processor = SignalProcessor()
        snr = processor.calculate_snr(
            rx_power_dbm=-80.0,
            noise_power_dbm=-110.0,
            interference_power_dbm=-100.0,
        )
        assert snr > 0
        assert snr < 100

    def test_shannon_capacity(self) -> None:
        """Test Shannon capacity calculation."""
        processor = SignalProcessor()
        capacity = processor.shannon_capacity(bandwidth_hz=20e6, snr_db=15.0)
        assert capacity > 0
        assert capacity < 1e9  # Less than 1 Gbps for these parameters

    def test_link_budget_analysis(self) -> None:
        """Test link budget analysis."""
        processor = SignalProcessor()
        budget = processor.link_budget_analysis(
            tx_power_dbm=46.0,
            distance_m=2000,
            frequency_mhz=2100,
            tx_antenna_gain_dbi=10.0,
            rx_antenna_gain_dbi=5.0,
            required_snr_db=7.0,
        )
        assert "rx_power_dbm" in budget
        assert "snr_db" in budget
        assert "link_margin_db" in budget
        assert "feasible" in budget

    def test_rayleigh_fading(self) -> None:
        """Test Rayleigh fading generation."""
        processor = SignalProcessor(fading_type="rayleigh")
        fading_values = [processor.rayleigh_fading() for _ in range(100)]
        avg_fading = sum(fading_values) / len(fading_values)
        assert isinstance(avg_fading, float)

    def test_rician_fading(self) -> None:
        """Test Rician fading generation."""
        processor = SignalProcessor(fading_type="rician")
        fading = processor.rician_fading(k_factor=5.0)
        assert isinstance(fading, float)

    def test_log_normal_shadowing(self) -> None:
        """Test log-normal shadowing."""
        processor = SignalProcessor(shadowing_std_db=6.0)
        shadowing = processor.log_normal_shadowing(1000)
        assert isinstance(shadowing, float)


class TestAntennaPattern:
    """Test antenna radiation patterns."""

    def test_isotropic_antenna(self) -> None:
        """Test isotropic antenna (zero gain reference)."""
        antenna = AntennaPattern(pattern_type="isotropic")
        gain = antenna.calculate_gain()
        assert gain == 0.0

    def test_directional_antenna_boresight(self) -> None:
        """Test directional antenna at boresight."""
        antenna = AntennaPattern(
            pattern_type="directional",
            gain_dbi=10.0,
            azimuth_degrees=0.0,
        )
        gain = antenna.directional_gain(target_azimuth=0.0, target_elevation=0.0)
        assert gain == 10.0

    def test_directional_antenna_off_axis(self) -> None:
        """Test directional antenna off-axis."""
        antenna = AntennaPattern(
            pattern_type="directional",
            gain_dbi=10.0,
            beamwidth_degrees=65.0,
        )
        gain_center = antenna.directional_gain(0.0, 0.0)
        gain_edge = antenna.directional_gain(32.5, 0.0)
        assert gain_center > gain_edge

    def test_mimo_antenna(self) -> None:
        """Test MIMO antenna array gain."""
        antenna = AntennaPattern(
            pattern_type="mimo",
            gain_dbi=10.0,
        )
        gain = antenna.calculate_gain()
        assert gain > 10.0

    def test_antenna_gain_calculation(self) -> None:
        """Test antenna gain calculation method dispatch."""
        antenna = AntennaPattern(pattern_type="directional", gain_dbi=5.0)
        gain = antenna.calculate_gain(target_azimuth=0.0, target_elevation=0.0)
        assert isinstance(gain, float)


class TestBeamformer:
    """Test beamforming."""

    def test_steering_vector(self) -> None:
        """Test steering vector calculation."""
        beamformer = Beamformer(num_elements=8)
        steering = beamformer.steering_vector(angle_degrees=0.0)
        assert len(steering) == 8
        assert all(isinstance(s, complex) for s in steering)

    def test_main_lobe_gain(self) -> None:
        """Test main lobe gain."""
        beamformer = Beamformer(num_elements=16)
        gain = beamformer.main_lobe_gain()
        assert gain > 0
        assert abs(gain - 10 * math.log10(16)) < 0.01

    def test_half_power_beamwidth(self) -> None:
        """Test HPBW calculation."""
        beamformer = Beamformer(num_elements=8, element_spacing_wavelengths=0.5)
        hpbw = beamformer.half_power_beamwidth()
        assert hpbw > 0
        assert hpbw < 180

    def test_array_pattern(self) -> None:
        """Test array pattern response."""
        beamformer = Beamformer(num_elements=8)
        response = beamformer.array_pattern(angle_degrees=0.0, target_angle_degrees=0.0)
        assert isinstance(response, float)

    def test_calculate_weights(self) -> None:
        """Test weight calculation."""
        beamformer = Beamformer(num_elements=8)
        weights = beamformer.calculate_weights(target_angle_degrees=30.0)
        assert len(weights) == 8


class TestSignalProcessingIntegration:
    """Integration tests for signal processing."""

    def test_complete_link_budget(self) -> None:
        """Test complete link budget with all components."""
        processor = SignalProcessor()
        budget = processor.link_budget_analysis(
            tx_power_dbm=46.0,
            distance_m=5000,
            frequency_mhz=2100,
            tx_antenna_gain_dbi=15.0,
            rx_antenna_gain_dbi=0.0,
            rx_noise_figure_db=5.0,
            required_snr_db=10.0,
        )
        assert budget["feasible"] in (True, False)
        assert budget["link_margin_db"] > -50

    def test_path_loss_vs_received_power(self) -> None:
        """Test consistency between path loss and received power."""
        model = PathLossModel(model_type=PathLossModelType.FREE_SPACE)
        processor = SignalProcessor(path_loss_model=model)

        tx_power = 46.0
        distance = 1000
        freq = 2100

        path_loss = model.calculate(distance, freq)
        rx_power = processor.calculate_received_power(
            tx_power,
            distance,
            freq,
            include_fading=False,
            include_shadowing=False,
        )

        expected_rx = tx_power - path_loss
        assert abs(rx_power - expected_rx) < 1.0

    def test_antenna_impact_on_received_power(self) -> None:
        """Test antenna gain impact on received power."""
        processor = SignalProcessor()

        rx_no_gain = processor.calculate_received_power(
            46.0, 1000, 2100, antenna_gain_dbi=0.0, include_fading=False, include_shadowing=False
        )

        rx_with_gain = processor.calculate_received_power(
            46.0, 1000, 2100, antenna_gain_dbi=10.0, include_fading=False, include_shadowing=False
        )

        assert rx_with_gain > rx_no_gain
        assert abs((rx_with_gain - rx_no_gain) - 10.0) < 1.0


if __name__ == "__main__":
    pytest.main([__file__])
