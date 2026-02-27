"""
Tests for energy forecasting models.
"""

import math
from datetime import datetime, timedelta

from thomas.energy.forecasting import (
    LoadForecaster,
    PriceForecaster,
    SolarForecaster,
    WindForecaster,
    adaptive_forecast_weights,
    calculate_forecast_error,
)


class TestLoadForecasting:
    """Test load forecasting."""

    def test_similar_day_method(self):
        """Test similar day forecasting method."""
        forecaster = LoadForecaster()

        # Create historical data
        historical = {}
        base_date = datetime(2023, 1, 1)

        # Add 30 days of data
        for day in range(30):
            date = base_date + timedelta(days=day)
            for hour in range(24):
                timestamp = date.replace(hour=hour)
                # Simple pattern: higher during day, lower at night
                load = 50 + 40 * (1 + math.sin(2 * math.pi * (hour - 6) / 24))
                historical[timestamp] = load

        # Forecast for a Monday
        target_date = datetime(2023, 2, 13)  # A Monday

        forecast = forecaster.similar_day_method(historical, target_date)

        assert len(forecast) == 24
        assert all(30 < l < 100 for l in forecast)

    def test_regression_method(self):
        """Test regression forecasting."""
        forecaster = LoadForecaster()

        # Historical loads
        historical = [50, 52, 48, 45, 60, 70, 80, 85, 80, 70, 60, 55] * 2  # 24 hours

        # Temperature forecast
        temperature = [15, 14, 13, 12, 15, 20, 25, 28, 27, 22, 18, 16] * 2

        # Holiday indicators
        holidays = [False] * 24

        forecast = forecaster.regression_method(historical, temperature, holidays)

        assert len(forecast) == 24
        assert all(l >= 0 for l in forecast)

    def test_ensemble_forecast(self):
        """Test ensemble forecasting."""
        forecaster = LoadForecaster()

        forecast1 = [50, 55, 60, 65, 70, 75, 80, 75, 70, 60, 50, 45]
        forecast2 = [48, 52, 58, 62, 68, 72, 78, 73, 68, 58, 52, 48]
        forecast3 = [52, 56, 61, 66, 72, 76, 82, 77, 72, 62, 52, 47]

        ensemble = forecaster.ensemble_forecast([forecast1, forecast2, forecast3])

        assert len(ensemble) == 12

        # Should be between individual forecasts
        for i in range(12):
            assert min(forecast1[i], forecast2[i], forecast3[i]) <= ensemble[i]
            assert ensemble[i] <= max(forecast1[i], forecast2[i], forecast3[i])

    def test_ensemble_weighted(self):
        """Test weighted ensemble."""
        forecaster = LoadForecaster()

        forecast1 = [50, 50, 50]
        forecast2 = [100, 100, 100]

        # Equal weights
        equal = forecaster.ensemble_forecast([forecast1, forecast2], [0.5, 0.5])

        # Forecast1 dominant
        f1_dominant = forecaster.ensemble_forecast([forecast1, forecast2], [0.8, 0.2])

        # Equal should be at 75
        assert abs(equal[0] - 75) < 1

        # F1 dominant should be closer to 50
        assert f1_dominant[0] < equal[0]


class TestSolarForecasting:
    """Test solar irradiance forecasting."""

    def test_persistence_method(self):
        """Test persistence forecasting."""
        forecaster = SolarForecaster()

        recent_irr = [100, 200, 300, 400, 500]
        forecast = forecaster.persistence_method(recent_irr, forecast_hours=12)

        assert len(forecast) == 12
        assert forecast[0] > forecast[-1]  # Should decay
        assert all(i >= 0 for i in forecast)

    def test_nwp_blend(self):
        """Test NWP blending."""
        forecaster = SolarForecaster()

        persist = [200, 200, 200, 200]
        nwp = [300, 300, 300, 300]

        blended = forecaster.nwp_blend_method(persist, nwp, nwp_weight=0.3)

        assert len(blended) == 4

        # Should be weighted average
        for b, p, n in zip(blended, persist, nwp):
            expected = 0.7 * p + 0.3 * n
            assert abs(b - expected) < 1

    def test_cloud_cover_adjustment(self):
        """Test cloud cover adjustment."""
        forecaster = SolarForecaster()

        clear_sky = [800, 800, 800, 800]
        cloud_cover = [0.0, 0.5, 1.0, 0.2]

        adjusted = forecaster.cloud_cover_adjustment(clear_sky, cloud_cover)

        assert adjusted[0] > adjusted[2]  # Clear day > cloudy day
        assert adjusted[2] < 100  # Heavy clouds reduce significantly


class TestWindForecasting:
    """Test wind forecasting."""

    def test_autoregressive_forecast(self):
        """Test AR wind forecasting."""
        forecaster = WindForecaster()

        historical = [5, 5.2, 5.1, 5.3, 5.2, 5.4] * 4  # 24 hourly values

        forecast = forecaster.autoregressive_forecast(
            historical,
            lag_hours=6,
            forecast_hours=12,
        )

        assert len(forecast) == 12
        assert all(w >= 0 for w in forecast)

    def test_power_curve_forecast(self):
        """Test power curve conversion."""
        forecaster = WindForecaster()

        wind_speeds = [3, 5, 10, 12, 15, 20, 25]
        power_curve = [
            (0, 0),
            (3, 0),
            (5, 0.1),
            (10, 1.0),
            (12, 2.0),
            (15, 3.0),
            (25, 3.0),
        ]

        power = forecaster.power_curve_forecast(wind_speeds, power_curve)

        assert len(power) == 7
        assert power[0] == 0.0  # Below cut-in
        assert power[-1] == 3.0  # At rated


class TestPriceForecasting:
    """Test price forecasting."""

    def test_demand_supply_based(self):
        """Test supply-demand based pricing."""
        forecaster = PriceForecaster()

        demand = [300, 350, 400, 350]
        renewable = [100, 150, 50, 100]

        prices = forecaster.demand_supply_based(demand, renewable, base_price=40.0)

        assert len(prices) == 4
        assert all(p > 0 for p in prices)

        # Low renewable should have higher price
        assert prices[2] > prices[1]

    def test_seasonality_adjustment(self):
        """Test seasonality adjustment."""
        forecaster = PriceForecaster()

        base = [40, 40, 40, 40]
        hours = [0, 365 * 24 // 4, 365 * 24 // 2, 3 * 365 * 24 // 4]

        adjusted = forecaster.seasonality_adjustment(base, hours)

        assert len(adjusted) == 4
        assert all(p > 0 for p in adjusted)


class TestForecastErrorMetrics:
    """Test forecast error calculation."""

    def test_perfect_forecast(self):
        """Test error metrics for perfect forecast."""
        actual = [100, 110, 120, 130, 140]
        forecast = [100, 110, 120, 130, 140]

        mae, rmse, mape = calculate_forecast_error(actual, forecast)

        assert mae == 0.0
        assert rmse == 0.0
        assert mape == 0.0

    def test_biased_forecast(self):
        """Test error metrics for biased forecast."""
        actual = [100, 100, 100, 100]
        forecast = [110, 110, 110, 110]  # 10% high

        mae, rmse, mape = calculate_forecast_error(actual, forecast)

        assert mae == 10.0
        assert rmse == 10.0
        assert abs(mape - 0.1) < 0.01  # ~10%

    def test_variable_forecast_error(self):
        """Test error metrics for variable errors."""
        actual = [100, 100, 100, 100]
        forecast = [90, 100, 110, 100]

        mae, rmse, mape = calculate_forecast_error(actual, forecast)

        assert mae > 0
        assert rmse > mae  # RMSE penalizes outliers


class TestAdaptiveWeighting:
    """Test adaptive forecast weights."""

    def test_recent_errors_emphasis(self):
        """Test that recent errors get higher weight."""
        errors = [10, 15, 20, 8, 5]  # Recent errors are lower

        weights = adaptive_forecast_weights(errors, decay_factor=0.9)

        assert len(weights) == 5
        # Recent lower errors should have higher weight
        assert weights[-1] > weights[0]

    def test_uniform_errors(self):
        """Test with uniform errors."""
        errors = [10, 10, 10, 10, 10]

        weights = adaptive_forecast_weights(errors, decay_factor=0.9)

        assert len(weights) == 5
        # Recent should still have slightly higher weight due to decay
        assert weights[-1] >= weights[0]

    def test_weight_normalization(self):
        """Test that weights sum to 1."""
        errors = [5, 10, 15, 20]

        weights = adaptive_forecast_weights(errors)

        assert abs(sum(weights) - 1.0) < 1e-6


class TestForecastingIntegration:
    """Integration tests for forecasting."""

    def test_combined_solar_forecast(self):
        """Test combined solar forecasting pipeline."""
        solar_fcst = SolarForecaster()

        # Step 1: Persistence
        recent = [200, 250, 300, 350, 400, 450, 500]
        persist = solar_fcst.persistence_method(recent, 12)

        # Step 2: NWP forecast (simulated)
        nwp = [250, 280, 310, 340, 370, 380, 370, 350, 320, 280, 240, 200]

        # Step 3: Blend
        blended = solar_fcst.nwp_blend_method(persist, nwp, 0.4)

        # Step 4: Cloud cover adjustment
        cloud = [0.1, 0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0, 0.0]
        final = solar_fcst.cloud_cover_adjustment(blended, cloud)

        assert len(final) == 12
        assert all(f >= 0 for f in final)

    def test_combined_load_wind_forecast(self):
        """Test combined load and wind forecasting."""
        load_fcst = LoadForecaster()
        wind_fcst = WindForecaster()

        # Load forecast
        historical = [50, 55, 60, 65, 70] * 5
        temp = [15, 18, 20, 18, 15] * 5
        load_forecast = load_fcst.regression_method(historical, temp, [False] * 25)

        # Wind forecast
        wind_hist = [5, 5.5, 6, 5.8, 6.2] * 5
        wind_forecast = wind_fcst.autoregressive_forecast(wind_hist, 5, 12)

        # Power curve for wind
        power_curve = [(0, 0), (3, 0), (5, 0.5), (10, 2.0), (15, 2.5)]
        wind_power = wind_fcst.power_curve_forecast(wind_forecast, power_curve)

        assert len(load_forecast) > 0
        assert len(wind_power) == 12
