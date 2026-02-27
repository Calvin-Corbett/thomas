"""Tests for temperature module."""

import pytest

from thomas.climate import temperature
from thomas.climate._exceptions import ClimateDataError, InvalidParameterError


class TestAnomalyCalculation:
    """Test temperature anomaly calculations."""

    def test_temperature_anomaly_positive(self) -> None:
        """Test positive temperature anomaly."""
        anom = temperature.temperature_anomaly(15.0, 10.0)
        assert anom == 5.0

    def test_temperature_anomaly_negative(self) -> None:
        """Test negative temperature anomaly."""
        anom = temperature.temperature_anomaly(8.0, 10.0)
        assert anom == -2.0

    def test_global_temperature_anomaly_series(self) -> None:
        """Test global anomaly calculation."""
        temps = [10 + i * 0.05 for i in range(100)]
        anomalies, baseline = temperature.global_temperature_anomaly(temps)
        assert len(anomalies) == len(temps)
        assert baseline > 0


class TestUrbanHeatIsland:
    """Test urban heat island calculations."""

    def test_uhi_estimation_positive(self) -> None:
        """Test positive UHI effect."""
        uhi = temperature.urban_heat_island_estimation(25.0, 20.0, 500.0)
        assert uhi == 5.0

    def test_uhi_estimation_zero(self) -> None:
        """Test zero UHI effect."""
        uhi = temperature.urban_heat_island_estimation(20.0, 20.0, 500.0)
        assert uhi == 0.0


class TestTrendAnalysis:
    """Test temperature trend analysis."""

    def test_linear_trend_increasing(self) -> None:
        """Test increasing temperature trend."""
        temps = [10 + i * 0.1 for i in range(50)]
        slope, intercept, r2 = temperature.linear_temperature_trend(temps)
        assert slope > 0
        assert r2 > 0.9

    def test_linear_trend_decreasing(self) -> None:
        """Test decreasing temperature trend."""
        temps = [20 - i * 0.05 for i in range(50)]
        slope, intercept, r2 = temperature.linear_temperature_trend(temps)
        assert slope < 0

    def test_linear_trend_insufficient_data(self) -> None:
        """Test trend with insufficient data."""
        with pytest.raises(ClimateDataError):
            temperature.linear_temperature_trend([10.0])


class TestSeasonalDecomposition:
    """Test seasonal decomposition."""

    def test_seasonal_decomposition(self) -> None:
        """Test seasonal decomposition."""
        temps = [15, 16, 17, 18, 19, 20, 20, 19, 18, 17, 16, 15] * 3
        months = list(range(1, 13)) * 3
        norms, anoms = temperature.seasonal_decomposition_climatological(temps, months, 3)
        assert len(norms) == len(temps)
        assert len(anoms) == len(temps)

    def test_seasonal_insufficient_data(self) -> None:
        """Test decomposition with insufficient data."""
        with pytest.raises(ClimateDataError):
            temperature.seasonal_decomposition_climatological([10.0], [1])


class TestExtremeEventDetection:
    """Test extreme event detection."""

    def test_return_period_gev(self) -> None:
        """Test GEV return period estimation."""
        extremes = [30 + i * 0.1 for i in range(50)]
        val_100 = temperature.return_period_gev(extremes, 100)
        assert val_100 > extremes[-1]

    def test_return_period_insufficient_data(self) -> None:
        """Test GEV with insufficient data."""
        with pytest.raises(ClimateDataError):
            temperature.return_period_gev([30.0], 100)

    def test_extreme_event_frequency_hot(self) -> None:
        """Test hot extreme event frequency."""
        temps = [15] * 300 + [35] * 50  # 50 hot days in 350
        count, freq = temperature.extreme_event_frequency(temps, 30.0, "hot")
        assert 10 < freq < 20

    def test_extreme_event_frequency_invalid_type(self) -> None:
        """Test extreme event with invalid type."""
        with pytest.raises(InvalidParameterError):
            temperature.extreme_event_frequency([15.0], 20.0, "invalid")


class TestDegreeDay:
    """Test degree day calculations."""

    def test_growing_degree_days(self) -> None:
        """Test GDD calculation."""
        temps = [15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
        gdd = temperature.growing_degree_days(temps, 10.0)
        assert gdd > 0

    def test_heating_degree_days(self) -> None:
        """Test HDD calculation."""
        temps = [0, 2, 4, 6, 8, 10, 8, 6, 4, 2]
        hdd = temperature.heating_degree_days(temps, 18.3)
        assert hdd > 0

    def test_cooling_degree_days(self) -> None:
        """Test CDD calculation."""
        temps = [20, 22, 24, 26, 28, 30, 28, 26, 24, 22]
        cdd = temperature.cooling_degree_days(temps, 18.3)
        assert cdd > 0

    def test_gdd_with_maximum_cap(self) -> None:
        """Test GDD with maximum temperature cap."""
        temps = [10, 20, 30, 40]
        gdd_uncap = temperature.growing_degree_days(temps, 10.0)
        gdd_cap = temperature.growing_degree_days(temps, 10.0, 30.0)
        assert gdd_cap < gdd_uncap


class TestPercentile:
    """Test percentile calculations."""

    def test_temperature_percentile_median(self) -> None:
        """Test 50th percentile."""
        temps = [10, 15, 20, 25, 30]
        p50 = temperature.temperature_percentile(temps, 50.0)
        assert 19 < p50 < 21

    def test_temperature_percentile_empty(self) -> None:
        """Test percentile with empty data."""
        with pytest.raises(ClimateDataError):
            temperature.temperature_percentile([], 50.0)

    def test_temperature_percentile_invalid_percentile(self) -> None:
        """Test percentile with invalid value."""
        with pytest.raises(InvalidParameterError):
            temperature.temperature_percentile([10.0], 150.0)


class TestDiurnalRange:
    """Test diurnal temperature range."""

    def test_diurnal_range_calculation(self) -> None:
        """Test DTR calculation."""
        highs = [25, 26, 27, 28, 29]
        lows = [15, 16, 17, 18, 19]
        dtr = temperature.diurnal_temperature_range(highs, lows)
        assert abs(dtr - 10.0) < 0.1

    def test_diurnal_range_mismatched_lengths(self) -> None:
        """Test DTR with mismatched lengths."""
        with pytest.raises(ClimateDataError):
            temperature.diurnal_temperature_range([25, 26], [15])


class TestMannKendall:
    """Test Mann-Kendall trend test."""

    def test_mann_kendall_increasing_trend(self) -> None:
        """Test Mann-Kendall with increasing trend."""
        data = [10 + i * 0.1 for i in range(30)]
        z, p = temperature.mann_kendall_trend_test(data)
        assert z > 0

    def test_mann_kendall_decreasing_trend(self) -> None:
        """Test Mann-Kendall with decreasing trend."""
        data = [20 - i * 0.05 for i in range(30)]
        z, p = temperature.mann_kendall_trend_test(data)
        assert z < 0

    def test_mann_kendall_insufficient_data(self) -> None:
        """Test Mann-Kendall with insufficient data."""
        with pytest.raises(ClimateDataError):
            temperature.mann_kendall_trend_test([10.0, 11.0])
