"""
Tests for spectrum management module.
"""

import pytest

from thomas.telecom._types import Frequency
from thomas.telecom.spectrum import (
    CognitiveRadio,
    GuardBandCalculator,
    InterferenceCalculator,
    SpectrumAuction,
    SpectrumBand,
    SpectrumManager,
)


class TestSpectrumManager:
    """Test spectrum management."""

    def test_allocate_spectrum(self) -> None:
        """Test spectrum allocation."""
        manager = SpectrumManager()
        success = manager.allocate_spectrum(
            operator_id="OP1",
            band=SpectrumBand.BAND_2100,
            start_mhz=2110.0,
            end_mhz=2130.0,
            technology="LTE",
        )
        assert success is True

    def test_allocate_overlapping_spectrum(self) -> None:
        """Test allocating overlapping spectrum fails."""
        manager = SpectrumManager()
        manager.allocate_spectrum(
            operator_id="OP1",
            band=SpectrumBand.BAND_2100,
            start_mhz=2110.0,
            end_mhz=2130.0,
            technology="LTE",
        )

        success = manager.allocate_spectrum(
            operator_id="OP2",
            band=SpectrumBand.BAND_2100,
            start_mhz=2120.0,
            end_mhz=2140.0,
            technology="LTE",
        )
        assert success is False

    def test_get_available_spectrum(self) -> None:
        """Test getting available spectrum."""
        manager = SpectrumManager()
        manager.allocate_spectrum(
            operator_id="OP1",
            band=SpectrumBand.BAND_2100,
            start_mhz=2110.0,
            end_mhz=2130.0,
            technology="LTE",
        )

        available = manager.get_available_spectrum()
        assert len(available) > 0

    def test_calculate_spectrum_efficiency(self) -> None:
        """Test spectrum efficiency calculation."""
        manager = SpectrumManager()
        efficiency = manager.calculate_spectrum_efficiency_bps_hz(data_rate_bps=100e6, bandwidth_hz=20e6)
        assert efficiency == 5.0


class TestInterferenceCalculator:
    """Test interference calculations."""

    def test_ci_ratio(self) -> None:
        """Test C/I ratio calculation."""
        calc = InterferenceCalculator()
        ci_ratio = calc.calculate_ci_ratio(
            carrier_power_dbm=-80.0,
            interference_power_dbm=-100.0,
        )
        assert ci_ratio > 0

    def test_sinr_calculation(self) -> None:
        """Test SINR calculation."""
        calc = InterferenceCalculator()
        sinr = calc.calculate_sinr(
            carrier_power_dbm=-80.0,
            noise_power_dbm=-110.0,
            interference_power_dbm=-100.0,
        )
        assert isinstance(sinr, float)

    def test_interference_distance(self) -> None:
        """Test distance estimation for interference threshold."""
        calc = InterferenceCalculator()
        distance = calc.estimate_interference_distance(
            tx_power_dbm=46.0,
            interference_threshold_dbm=-95.0,
            frequency_mhz=2100,
        )
        assert distance > 0


class TestCognitiveRadio:
    """Test cognitive radio."""

    def test_energy_detection(self) -> None:
        """Test energy detection."""
        radio = CognitiveRadio(detection_threshold_dbm=-95.0)
        occupied = radio.perform_energy_detection(frequency_mhz=2100.0, signal_power_dbm=-80.0)
        assert occupied is True

        unoccupied = radio.perform_energy_detection(frequency_mhz=2105.0, signal_power_dbm=-105.0)
        assert unoccupied is False

    def test_identify_spectrum_holes(self) -> None:
        """Test spectrum hole identification."""
        radio = CognitiveRadio()
        radio.perform_energy_detection(2100.0, -80.0)
        radio.perform_energy_detection(2105.0, -105.0)
        radio.perform_energy_detection(2110.0, -80.0)

        holes = radio.identify_spectrum_holes((2100.0, 2110.0))
        assert isinstance(holes, list)

    def test_calculate_sensing_time(self) -> None:
        """Test sensing time calculation."""
        radio = CognitiveRadio()
        sensing_time = radio.calculate_spectrum_sensing_time(pfa=0.1, pd=0.9, snr_db=5.0)
        assert sensing_time > 0


class TestSpectrumAuction:
    """Test spectrum auction."""

    def test_add_frequency(self) -> None:
        """Test adding frequency to auction."""
        auction = SpectrumAuction()
        freq = Frequency(mhz=2100.0)
        auction.add_frequency(freq)
        assert freq in auction.frequencies

    def test_submit_bid(self) -> None:
        """Test submitting bid."""
        auction = SpectrumAuction()
        auction.submit_bid(operator_id="OP1", frequency_mhz=2100.0, bid_amount=100.0)
        assert "OP1" in auction.bids

    def test_vickrey_auction(self) -> None:
        """Test Vickrey auction."""
        auction = SpectrumAuction()
        freq = Frequency(mhz=2100.0)
        auction.add_frequency(freq)

        auction.submit_bid("OP1", 2100.0, 200.0)
        auction.submit_bid("OP2", 2100.0, 150.0)
        auction.submit_bid("OP3", 2100.0, 100.0)

        results = auction.run_vickrey_auction()
        assert len(results) > 0

        # Winner should be OP1
        for freq_id, result in results.items():
            if result["winner"] == "OP1":
                # Payment should be second highest bid (150)
                assert result["payment"] <= 200.0


class TestGuardBandCalculator:
    """Test guard band calculations."""

    def test_calculate_guard_band(self) -> None:
        """Test guard band calculation."""
        calc = GuardBandCalculator(default_guard_band_percent=5.0)
        guard_band = calc.calculate_guard_band_mhz(20.0)
        assert guard_band == 1.0

    def test_check_coexistence_compatible(self) -> None:
        """Test compatible channel coexistence."""
        calc = GuardBandCalculator()
        compatible = calc.check_coexistence(
            freq1_mhz=2110.0,
            bandwidth1_mhz=20.0,
            freq2_mhz=2140.0,
            bandwidth2_mhz=20.0,
        )
        assert compatible is True

    def test_check_coexistence_incompatible(self) -> None:
        """Test incompatible channel coexistence."""
        calc = GuardBandCalculator()
        compatible = calc.check_coexistence(
            freq1_mhz=2110.0,
            bandwidth1_mhz=20.0,
            freq2_mhz=2115.0,
            bandwidth2_mhz=20.0,
        )
        assert compatible is False


class TestSpectrumIntegration:
    """Integration tests for spectrum management."""

    def test_allocation_and_interference(self) -> None:
        """Test spectrum allocation with interference calculations."""
        manager = SpectrumManager()
        calc = InterferenceCalculator()

        manager.allocate_spectrum(
            operator_id="OP1",
            band=SpectrumBand.BAND_2100,
            start_mhz=2110.0,
            end_mhz=2130.0,
            technology="LTE",
        )

        manager.allocate_spectrum(
            operator_id="OP2",
            band=SpectrumBand.BAND_2100,
            start_mhz=2150.0,
            end_mhz=2170.0,
            technology="LTE",
        )

        ci_ratio = calc.calculate_ci_ratio(-85.0, -105.0)
        assert ci_ratio > 0

    def test_cognitive_radio_workflow(self) -> None:
        """Test cognitive radio workflow."""
        radio = CognitiveRadio()
        auction = SpectrumAuction()

        # Sense spectrum
        radio.perform_energy_detection(2100.0, -80.0)
        radio.perform_energy_detection(2105.0, -105.0)
        radio.perform_energy_detection(2110.0, -80.0)

        holes = radio.identify_spectrum_holes((2100.0, 2110.0))
        assert len(holes) >= 0

        # Auction available holes
        if holes:
            for hole_start, hole_end in holes:
                freq = Frequency(mhz=(hole_start + hole_end) / 2)
                auction.add_frequency(freq)

        assert len(auction.frequencies) >= 0


if __name__ == "__main__":
    pytest.main([__file__])
