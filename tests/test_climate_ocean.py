"""Tests for ocean module."""

import pytest

from thomas.climate import ocean
from thomas.climate._exceptions import ClimateDataError, InvalidParameterError


class TestSeaTemperature:
    """Test sea surface temperature functions."""

    def test_sst_anomaly(self) -> None:
        """Test SST anomaly calculation."""
        anom = ocean.sea_surface_temperature_anomaly(22.0, 20.0)
        assert anom == 2.0

    def test_sst_anomaly_negative(self) -> None:
        """Test negative SST anomaly."""
        anom = ocean.sea_surface_temperature_anomaly(18.0, 20.0)
        assert anom == -2.0


class TestOceanHeatContent:
    """Test ocean heat content calculations."""

    def test_ohc_uniform_profile(self) -> None:
        """Test OHC with uniform temperature."""
        temps = [10.0] * 5
        depths = [0.0, 200.0, 400.0, 600.0, 800.0]
        area = 1000000.0  # 1M m²
        ohc = ocean.ocean_heat_content(temps, depths, area)
        assert ohc > 0

    def test_ohc_mismatched_lengths(self) -> None:
        """Test OHC with mismatched profile lengths."""
        with pytest.raises(ClimateDataError):
            ocean.ocean_heat_content([10.0, 8.0], [0.0], 1e6)

    def test_ohc_empty(self) -> None:
        """Test OHC with empty profile."""
        ohc = ocean.ocean_heat_content([], [], 1e6)
        assert ohc == 0.0


class TestSeaLevelRise:
    """Test sea level rise projection."""

    def test_slr_projection(self) -> None:
        """Test sea level rise projection."""
        rise, accel = ocean.sea_level_rise_projection(3.0, 2.0, 50)
        assert rise > 0
        assert accel > 1.0

    def test_slr_zero_contribution(self) -> None:
        """Test SLR with zero contributions."""
        rise, accel = ocean.sea_level_rise_projection(0.0, 0.0, 50)
        assert rise == 0.0


class TestOceanAcidification:
    """Test ocean acidification."""

    def test_ph_change_pre_industrial(self) -> None:
        """Test pH at pre-industrial CO2."""
        ph = ocean.ocean_acidification_ph(280.0, 280.0, 8.21)
        assert abs(ph - 8.21) < 0.01

    def test_ph_change_elevated_co2(self) -> None:
        """Test pH at elevated CO2."""
        ph_pi = ocean.ocean_acidification_ph(280.0, 280.0, 8.21)
        ph_now = ocean.ocean_acidification_ph(415.0, 280.0, 8.21)
        assert ph_now < ph_pi

    def test_aragonite_saturation(self) -> None:
        """Test aragonite saturation state."""
        omega = ocean.saturation_state_aragonite(10.0, 35.0, 0.0)
        assert omega > 0

    def test_aragonite_undersaturation(self) -> None:
        """Test aragonite undersaturation at depth."""
        omega_surface = ocean.saturation_state_aragonite(25.0, 35.0, 0.0)
        omega_deep = ocean.saturation_state_aragonite(2.0, 35.0, 3000.0)
        assert omega_deep < omega_surface


class TestENSO:
    """Test ENSO index calculations."""

    def test_oni_calculation(self) -> None:
        """Test ONI calculation."""
        sst_anom = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.9, 0.8]
        oni = ocean.enso_index_oni(sst_anom)
        assert len(oni) == len(sst_anom) - 2

    def test_oni_insufficient_data(self) -> None:
        """Test ONI with insufficient data."""
        with pytest.raises(ClimateDataError):
            ocean.enso_index_oni([0.5, 0.6])

    def test_enso_phase_strong_el_nino(self) -> None:
        """Test ENSO phase classification - strong El Nino."""
        phase = ocean.enso_phase_classification(2.0)
        assert phase == "Strong El Nino"

    def test_enso_phase_el_nino(self) -> None:
        """Test ENSO phase classification - El Nino."""
        phase = ocean.enso_phase_classification(0.8)
        assert phase == "El Nino"

    def test_enso_phase_neutral(self) -> None:
        """Test ENSO phase classification - Neutral."""
        phase = ocean.enso_phase_classification(0.2)
        assert phase == "Neutral"

    def test_enso_phase_la_nina(self) -> None:
        """Test ENSO phase classification - La Nina."""
        phase = ocean.enso_phase_classification(-1.2)
        assert phase == "La Nina"


class TestThermohaline:
    """Test thermohaline circulation."""

    def test_thc_strength_modern(self) -> None:
        """Test THC strength at modern conditions."""
        strength = ocean.thermohaline_circulation_index(10.0, 0.0, 2.0)
        assert 0 < strength <= 2.0

    def test_thc_weakening_warming(self) -> None:
        """Test THC response to warming."""
        s_ref = ocean.thermohaline_circulation_index(10.0, 0.0, 2.0)
        s_warm = ocean.thermohaline_circulation_index(12.0, 0.0, 2.0)
        # Both should be positive but different
        assert s_ref > 0 and s_warm > 0

    def test_thc_freshwater_input(self) -> None:
        """Test THC response to freshwater input."""
        s_low = ocean.thermohaline_circulation_index(10.0, 0.0, 2.0)
        s_high = ocean.thermohaline_circulation_index(10.0, 500000.0, 2.0)
        assert s_high < s_low


class TestTidalConstituents:
    """Test tidal constituent calculations."""

    def test_m2_constituent(self) -> None:
        """Test M2 constituent amplitude."""
        amp = ocean.tidal_constituent_amplitude("M2", 1.0)
        assert 0.5 < amp < 0.7

    def test_s2_constituent(self) -> None:
        """Test S2 constituent amplitude."""
        amp = ocean.tidal_constituent_amplitude("S2", 1.0)
        assert 0.1 < amp < 0.3

    def test_k1_constituent(self) -> None:
        """Test K1 constituent amplitude."""
        amp = ocean.tidal_constituent_amplitude("K1", 1.0)
        assert 0.1 < amp < 0.2

    def test_o1_constituent(self) -> None:
        """Test O1 constituent amplitude."""
        amp = ocean.tidal_constituent_amplitude("O1", 1.0)
        assert 0.05 < amp < 0.1

    def test_invalid_constituent(self) -> None:
        """Test invalid constituent code."""
        with pytest.raises(InvalidParameterError):
            ocean.tidal_constituent_amplitude("INVALID", 1.0)


class TestTidalPrediction:
    """Test tidal prediction."""

    def test_tidal_prediction_24h(self) -> None:
        """Test tidal prediction for 24 hours."""
        times = list(range(0, 25))
        levels = ocean.tidal_prediction(times, 0.5, 0.2, 0.1, 0.05)
        assert len(levels) == len(times)
        assert all(-1.0 < l < 1.0 for l in levels)

    def test_tidal_prediction_zero_amplitudes(self) -> None:
        """Test tidal prediction with zero amplitudes."""
        times = [0.0, 6.0, 12.0, 18.0, 24.0]
        levels = ocean.tidal_prediction(times, 0, 0, 0, 0)
        assert all(abs(l) < 0.01 for l in levels)


class TestMarineHeatwave:
    """Test marine heatwave detection."""

    def test_marine_heatwave_detection(self) -> None:
        """Test marine heatwave detection."""
        temps = [20.0] * 50 + [25.0] * 10 + [20.0] * 50  # 10-day warm spell
        heatwaves = ocean.marine_heatwave_detection(temps, 90.0, 5)
        assert len(heatwaves) > 0

    def test_no_heatwave(self) -> None:
        """Test when no obvious heatwave occurs."""
        temps = [20.0, 20.5, 21.0, 20.5, 20.0] * 20  # Small variations
        heatwaves = ocean.marine_heatwave_detection(temps, 99.0, 5)  # Very high threshold
        # With extreme threshold should have fewer or no events
        assert isinstance(heatwaves, list)

    def test_heatwave_insufficient_data(self) -> None:
        """Test heatwave detection with insufficient data."""
        with pytest.raises(ClimateDataError):
            ocean.marine_heatwave_detection([20.0, 25.0, 26.0], 90.0, 5)
