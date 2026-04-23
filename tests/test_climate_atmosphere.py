"""Tests for atmosphere module."""

import pytest

from thomas.marketplace.climate import atmosphere
from thomas.marketplace.climate._exceptions import InvalidParameterError


class TestIdealGasLaw:
    """Test ideal gas law calculations."""

    def test_ideal_gas_law_standard_conditions(self) -> None:
        """Test ideal gas law at standard conditions."""
        pressure = 101325.0  # Pa
        density = 1.225  # kg/m³
        temperature = 288.15  # K

        r = atmosphere.ideal_gas_law(pressure, density, temperature)
        assert abs(r - 287.0) < 1.0  # Should be close to dry air constant

    def test_ideal_gas_law_invalid_temperature(self) -> None:
        """Test ideal gas law with invalid temperature."""
        with pytest.raises(InvalidParameterError):
            atmosphere.ideal_gas_law(101325.0, 1.225, -100.0)

    def test_ideal_gas_law_invalid_density(self) -> None:
        """Test ideal gas law with invalid density."""
        with pytest.raises(InvalidParameterError):
            atmosphere.ideal_gas_law(101325.0, -1.0, 288.15)


class TestAirDensity:
    """Test air density calculations."""

    def test_air_density_standard_conditions(self) -> None:
        """Test air density at standard conditions."""
        density = atmosphere.air_density(101325.0, 15.0, 0.0)
        assert 1.0 < density < 1.3  # Should be ~1.225 kg/m³

    def test_air_density_with_humidity(self) -> None:
        """Test air density with humidity correction."""
        density_dry = atmosphere.air_density(101325.0, 15.0, 0.0)
        density_humid = atmosphere.air_density(101325.0, 15.0, 80.0)
        assert density_humid < density_dry  # Humidity reduces density

    def test_air_density_invalid_pressure(self) -> None:
        """Test air density with invalid pressure."""
        with pytest.raises(InvalidParameterError):
            atmosphere.air_density(-101325.0, 15.0, 50.0)

    def test_air_density_invalid_humidity(self) -> None:
        """Test air density with invalid humidity."""
        with pytest.raises(InvalidParameterError):
            atmosphere.air_density(101325.0, 15.0, 150.0)


class TestAltitudePressureConversion:
    """Test altitude and pressure conversions."""

    def test_pressure_from_altitude_sea_level(self) -> None:
        """Test pressure at sea level."""
        p = atmosphere.pressure_from_altitude(0.0, 101325.0, 15.0)
        assert abs(p - 101325.0) < 100

    def test_pressure_from_altitude_1000m(self) -> None:
        """Test pressure at 1000 m altitude."""
        p = atmosphere.pressure_from_altitude(1000.0, 101325.0, 15.0)
        assert p < 101325.0

    def test_altitude_from_pressure_roundtrip(self) -> None:
        """Test altitude pressure conversion roundtrip."""
        alt = 2000.0
        p = atmosphere.pressure_from_altitude(alt, 101325.0, 15.0)
        alt_back = atmosphere.altitude_from_pressure(p, 101325.0, 15.0)
        assert abs(alt - alt_back) < 50

    def test_pressure_from_altitude_invalid(self) -> None:
        """Test altitude pressure with invalid values."""
        with pytest.raises(InvalidParameterError):
            atmosphere.pressure_from_altitude(-100.0)


class TestDewPoint:
    """Test dew point calculations."""

    def test_dew_point_magnus_saturation(self) -> None:
        """Test dew point at saturation."""
        dp = atmosphere.dew_point_magnus(20.0, 100.0)
        assert abs(dp - 20.0) < 0.5

    def test_dew_point_magnus_partial(self) -> None:
        """Test dew point at partial saturation."""
        dp = atmosphere.dew_point_magnus(20.0, 50.0)
        assert dp < 20.0

    def test_dew_point_magnus_invalid_humidity(self) -> None:
        """Test dew point with invalid humidity."""
        with pytest.raises(InvalidParameterError):
            atmosphere.dew_point_magnus(20.0, 150.0)


class TestHeatIndex:
    """Test heat index calculations."""

    def test_heat_index_low_humidity(self) -> None:
        """Test heat index with low humidity."""
        hi = atmosphere.heat_index_rothfusz(30.0, 30.0)
        assert hi < 35.0  # Should be lower than temperature

    def test_heat_index_high_humidity(self) -> None:
        """Test heat index with high humidity."""
        hi_low = atmosphere.heat_index_rothfusz(30.0, 30.0)
        hi_high = atmosphere.heat_index_rothfusz(30.0, 80.0)
        assert hi_high > hi_low

    def test_heat_index_invalid_humidity(self) -> None:
        """Test heat index with invalid humidity."""
        with pytest.raises(InvalidParameterError):
            atmosphere.heat_index_rothfusz(30.0, 150.0)


class TestWindChill:
    """Test wind chill calculations."""

    def test_wind_chill_no_wind(self) -> None:
        """Test wind chill with no wind."""
        wc = atmosphere.wind_chill_nws(0.0, 2.0)
        assert wc == 0.0

    def test_wind_chill_with_wind(self) -> None:
        """Test wind chill with strong wind."""
        wc = atmosphere.wind_chill_nws(-10.0, 10.0)
        assert wc < -10.0

    def test_wind_chill_invalid_speed(self) -> None:
        """Test wind chill with invalid speed."""
        with pytest.raises(InvalidParameterError):
            atmosphere.wind_chill_nws(0.0, -5.0)


class TestLapseRate:
    """Test lapse rate calculations."""

    def test_lapse_rate_dry(self) -> None:
        """Test dry adiabatic lapse rate."""
        temp_1000m = atmosphere.atmospheric_lapse_rate(1000.0, 15.0, False)
        assert temp_1000m < 15.0

    def test_lapse_rate_moist(self) -> None:
        """Test moist adiabatic lapse rate."""
        temp_dry = atmosphere.atmospheric_lapse_rate(1000.0, 15.0, False)
        temp_moist = atmosphere.atmospheric_lapse_rate(1000.0, 15.0, True)
        assert abs(temp_moist - temp_dry) < 1.0

    def test_lapse_rate_invalid_altitude(self) -> None:
        """Test lapse rate with invalid altitude."""
        with pytest.raises(InvalidParameterError):
            atmosphere.atmospheric_lapse_rate(-100.0, 15.0)


class TestStability:
    """Test atmospheric stability classification."""

    def test_stability_daytime_strong_radiation(self) -> None:
        """Test daytime stability with strong radiation."""
        stability = atmosphere.pasquill_gifford_stability(15.0, 1.0, 500.0, 12)
        assert stability in ("A", "B", "C")

    def test_stability_nighttime_clear(self) -> None:
        """Test nighttime stability, clear sky."""
        stability = atmosphere.pasquill_gifford_stability(10.0, 2.0, None, 2)
        assert stability in ("E", "F")

    def test_stability_wind_effect(self) -> None:
        """Test stability with increasing wind."""
        s1 = atmosphere.pasquill_gifford_stability(15.0, 1.0, 300.0, 12)
        s5 = atmosphere.pasquill_gifford_stability(15.0, 5.0, 300.0, 12)
        # Higher wind should shift toward neutral/stable
        assert s5 >= s1 or s5 == s1


class TestRelativeHumidity:
    """Test relative humidity calculations."""

    def test_rh_from_dew_point_saturation(self) -> None:
        """Test RH when temperature equals dew point."""
        rh = atmosphere.relative_humidity_from_dewpoint(20.0, 20.0)
        assert abs(rh - 100.0) < 1.0

    def test_rh_from_dew_point_partial(self) -> None:
        """Test RH with dew point depression."""
        rh = atmosphere.relative_humidity_from_dewpoint(20.0, 10.0)
        assert 50 < rh < 100


class TestMixingRatio:
    """Test mixing ratio calculations."""

    def test_mixing_ratio_valid(self) -> None:
        """Test mixing ratio calculation."""
        mr = atmosphere.mixing_ratio(12.0, 1000.0)
        assert mr > 0

    def test_mixing_ratio_invalid_pressure(self) -> None:
        """Test mixing ratio with invalid pressure."""
        with pytest.raises(InvalidParameterError):
            atmosphere.mixing_ratio(10.0, -100.0)


class TestThetaE:
    """Test equivalent potential temperature."""

    def test_theta_e_calculation(self) -> None:
        """Test theta-e calculation."""
        theta_e = atmosphere.equivalent_potential_temperature(20.0, 12.0, 1000.0)
        assert theta_e > 293.0  # Should be > 20°C in K
