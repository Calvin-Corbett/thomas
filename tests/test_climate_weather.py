"""Tests for weather module."""

import pytest

from thomas.climate import weather
from thomas.climate._exceptions import ClimateDataError, InvalidParameterError


class TestBeaufortScale:
    """Test Beaufort wind scale."""

    def test_beaufort_calm(self) -> None:
        """Test Beaufort scale for calm."""
        desc = weather.beaufort_wind_scale_description(0)
        assert "Calm" in desc

    def test_beaufort_breeze(self) -> None:
        """Test Beaufort scale for breeze."""
        desc = weather.beaufort_wind_scale_description(5)
        assert "Breeze" in desc

    def test_beaufort_hurricane(self) -> None:
        """Test Beaufort scale for hurricane."""
        desc = weather.beaufort_wind_scale_description(12)
        assert "Hurricane" in desc

    def test_beaufort_invalid(self) -> None:
        """Test invalid Beaufort number."""
        with pytest.raises(InvalidParameterError):
            weather.beaufort_wind_scale_description(15)


class TestPrecipitationType:
    """Test precipitation type determination."""

    def test_rain_warm(self) -> None:
        """Test rain determination."""
        ptype = weather.precipitation_type_determination(15.0, 10.0, 5.0)
        assert ptype == "rain"

    def test_snow_cold(self) -> None:
        """Test snow determination."""
        ptype = weather.precipitation_type_determination(-5.0, -8.0, -3.0)
        assert ptype == "snow"

    def test_freezing_rain(self) -> None:
        """Test freezing rain determination."""
        ptype = weather.precipitation_type_determination(5.0, 2.0, -2.0)
        assert ptype == "freezing_rain"


class TestVisibility:
    """Test visibility estimation."""

    def test_visibility_clear(self) -> None:
        """Test visibility in clear conditions."""
        vis = weather.visibility_estimation(0.0)
        assert vis == float("inf")

    def test_visibility_fog(self) -> None:
        """Test visibility in fog."""
        vis = weather.visibility_estimation(0.5, 10.0)
        assert vis < 100000  # Much reduced from clear sky

    def test_visibility_invalid_lwc(self) -> None:
        """Test visibility with invalid liquid water content."""
        with pytest.raises(InvalidParameterError):
            weather.visibility_estimation(-0.1)


class TestAQI:
    """Test Air Quality Index calculations."""

    def test_aqi_good(self) -> None:
        """Test AQI in good air quality."""
        aqi, category = weather.air_quality_index_from_pollutants(10, 20, 40, 20, 10, 0.5)
        assert aqi < 50
        assert category == "Good"

    def test_aqi_moderate(self) -> None:
        """Test AQI in moderate air quality."""
        aqi, category = weather.air_quality_index_from_pollutants(30, 50, 60, 40, 20, 1.0)
        assert 50 <= aqi <= 100
        assert category == "Moderate"

    def test_aqi_hazardous(self) -> None:
        """Test AQI in hazardous conditions."""
        aqi, category = weather.air_quality_index_from_pollutants(400, 500, 300, 200, 150, 10)
        assert aqi > 300
        assert category == "Hazardous"


class TestUVIndex:
    """Test UV Index calculations."""

    def test_uvi_noon(self) -> None:
        """Test UV index at solar noon."""
        uvi, category = weather.uv_index_calculation(0.0, 300.0, 0.1)
        assert uvi > 8
        assert category in ("High", "Very High", "Extreme")

    def test_uvi_morning(self) -> None:
        """Test UV index in morning."""
        uvi, category = weather.uv_index_calculation(45.0, 300.0, 0.1)
        assert uvi < 12

    def test_uvi_evening(self) -> None:
        """Test UV index in evening."""
        uvi, category = weather.uv_index_calculation(85.0, 300.0, 0.1)
        assert uvi < 2

    def test_uvi_night(self) -> None:
        """Test UV index at night."""
        uvi, category = weather.uv_index_calculation(95.0, 300.0, 0.1)
        assert uvi == 0.0
        assert category == "Night"

    def test_uvi_invalid_zenith_angle(self) -> None:
        """Test UV index with invalid zenith angle."""
        with pytest.raises(InvalidParameterError):
            weather.uv_index_calculation(-10.0, 300.0)


class TestForecastVerification:
    """Test forecast verification metrics."""

    def test_brier_score_perfect(self) -> None:
        """Test Brier Score for perfect forecast."""
        forecasts = [0.0, 1.0, 0.0, 1.0]
        observations = [0, 1, 0, 1]
        bs = weather.forecast_brier_score(forecasts, observations)
        assert bs == 0.0

    def test_brier_score_worst(self) -> None:
        """Test Brier Score for worst forecast."""
        forecasts = [1.0, 0.0, 1.0, 0.0]
        observations = [0, 1, 0, 1]
        bs = weather.forecast_brier_score(forecasts, observations)
        assert bs == 1.0

    def test_brier_score_mismatch(self) -> None:
        """Test Brier Score with mismatched lengths."""
        with pytest.raises(ClimateDataError):
            weather.forecast_brier_score([0.5], [0, 1])

    def test_hit_rate_calculation(self) -> None:
        """Test hit rate calculation."""
        forecasts = [1, 0, 1, 1, 0]
        observations = [1, 0, 1, 0, 0]
        hit_rate, false_alarm = weather.forecast_hit_rate_and_false_alarm_rate(forecasts, observations)
        assert 0 <= hit_rate <= 1
        assert 0 <= false_alarm <= 1

    def test_hit_rate_perfect(self) -> None:
        """Test perfect hit rate."""
        forecasts = [1, 1, 0, 0]
        observations = [1, 1, 0, 0]
        hit_rate, false_alarm = weather.forecast_hit_rate_and_false_alarm_rate(forecasts, observations)
        assert hit_rate == 1.0
        assert false_alarm == 0.0

    def test_hit_rate_mismatch(self) -> None:
        """Test hit rate with mismatched lengths."""
        with pytest.raises(ClimateDataError):
            weather.forecast_hit_rate_and_false_alarm_rate([1, 0], [1])


class TestPressureTendency:
    """Test pressure tendency calculation."""

    def test_pressure_tendency_falling(self) -> None:
        """Test falling pressure tendency."""
        pressures = [1013.25, 1012.50, 1011.75]
        hours = [0, 3, 6]
        tendency = weather.pressure_tendency_forecast(pressures, hours)
        assert tendency < 0

    def test_pressure_tendency_rising(self) -> None:
        """Test rising pressure tendency."""
        pressures = [1010.0, 1011.0, 1012.0]
        hours = [0, 3, 6]
        tendency = weather.pressure_tendency_forecast(pressures, hours)
        assert tendency > 0

    def test_pressure_tendency_insufficient_data(self) -> None:
        """Test pressure tendency with insufficient data."""
        with pytest.raises(ClimateDataError):
            weather.pressure_tendency_forecast([1013.0], [0])


class TestLiftedIndex:
    """Test Lifted Index stability."""

    def test_lifted_index_stability_value(self) -> None:
        """Test lifted index returns valid value."""
        li = weather.lifted_index_stability(10.0, 1000.0, -10.0, 500.0)
        assert isinstance(li, float)

    def test_lifted_index_varies(self) -> None:
        """Test lifted index varies with conditions."""
        li_cold = weather.lifted_index_stability(5.0, 1000.0, -20.0, 500.0)
        li_warm = weather.lifted_index_stability(25.0, 1000.0, -20.0, 500.0)
        # Lifted index should change with temperature
        assert li_warm != li_cold

    def test_lifted_index_high_temp(self) -> None:
        """Test lifted index with high surface temp."""
        li = weather.lifted_index_stability(35.0, 1000.0, -10.0, 500.0)
        assert isinstance(li, float)
