"""Tests for time series module."""

import pytest

from thomas.marketplace.stats import timeseries as ts
from thomas.marketplace.stats._exceptions import InsufficientDataError


class TestMovingAverage:
    def test_moving_average_simple(self):
        data = [1, 2, 3, 4, 5]
        result = ts.moving_average(data, window=2)
        assert result[0] is None
        assert abs(result[1] - 1.5) < 1e-10
        assert abs(result[2] - 2.5) < 1e-10

    def test_moving_average_invalid_window(self):
        with pytest.raises(ValueError):
            ts.moving_average([1, 2, 3], window=0)

    def test_moving_average_window_too_large(self):
        with pytest.raises(ValueError):
            ts.moving_average([1, 2, 3], window=10)


class TestWeightedMovingAverage:
    def test_weighted_moving_average(self):
        data = [1, 2, 3, 4, 5]
        weights = [0.5, 0.5]
        result = ts.weighted_moving_average(data, weights)
        assert result[0] is None
        assert abs(result[1] - 1.5) < 1e-10

    def test_weighted_moving_average_empty_weights(self):
        with pytest.raises(ValueError):
            ts.weighted_moving_average([1, 2, 3], [])


class TestExponentialSmoothing:
    def test_exponential_smoothing(self):
        data = [1, 2, 3, 4, 5]
        result = ts.exponential_smoothing(data, alpha=0.3)
        assert len(result) == 5
        assert result[0] == 1

    def test_exponential_smoothing_invalid_alpha(self):
        with pytest.raises(ValueError):
            ts.exponential_smoothing([1, 2, 3], alpha=1.5)

    def test_exponential_smoothing_empty(self):
        with pytest.raises(InsufficientDataError):
            ts.exponential_smoothing([])


class TestHoltLinearTrend:
    def test_holt_linear_trend(self):
        data = [1, 2, 3, 4, 5]
        level, trend = ts.holt_linear_trend(data)
        assert len(level) == 5
        assert len(trend) == 5

    def test_holt_linear_trend_insufficient(self):
        with pytest.raises(InsufficientDataError):
            ts.holt_linear_trend([1])

    def test_holt_linear_trend_invalid_params(self):
        with pytest.raises(ValueError):
            ts.holt_linear_trend([1, 2, 3], alpha=1.5)


class TestHoltWinters:
    def test_holt_winters(self):
        data = list(range(1, 25))
        level, trend, seasonal = ts.holt_winters(data, season_length=12)
        assert len(level) > 0
        assert len(trend) > 0
        assert len(seasonal) > 0

    def test_holt_winters_insufficient(self):
        with pytest.raises(InsufficientDataError):
            ts.holt_winters([1, 2, 3], season_length=12)

    def test_holt_winters_invalid_seasonal(self):
        data = list(range(1, 25))
        with pytest.raises(ValueError):
            ts.holt_winters(data, season_length=12, seasonal="invalid")


class TestDifferencing:
    def test_differencing_first_order(self):
        data = [1, 3, 6, 10, 15]
        result = ts.differencing(data, order=1)
        assert result == [2, 3, 4, 5]

    def test_differencing_second_order(self):
        data = [1, 3, 6, 10, 15]
        result = ts.differencing(data, order=2)
        assert result == [1, 1, 1]

    def test_differencing_invalid_order(self):
        with pytest.raises(ValueError):
            ts.differencing([1, 2, 3], order=0)


class TestPartialAutocorrelation:
    def test_partial_autocorrelation(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8]
        result = ts.partial_autocorrelation(data, lag=1)
        assert -1 <= result <= 1


class TestSeasonalDecomposition:
    def test_seasonal_decomposition(self):
        data = list(range(1, 25))
        trend, seasonal, residual = ts.seasonal_decomposition(data, period=12)
        assert len(trend) == 24
        assert len(seasonal) == 24
        assert len(residual) == 24

    def test_seasonal_decomposition_insufficient(self):
        with pytest.raises(InsufficientDataError):
            ts.seasonal_decomposition([1, 2, 3], period=12)

    def test_seasonal_decomposition_invalid_type(self):
        data = list(range(1, 25))
        with pytest.raises(ValueError):
            ts.seasonal_decomposition(data, period=12, seasonal_type="invalid")


class TestADFTest:
    def test_adf_test_stationary(self):
        data = [1, 2, 3, 4, 5]
        result = ts.adf_test_simplified(data)
        assert 0 <= result <= 1

    def test_adf_test_insufficient(self):
        with pytest.raises(InsufficientDataError):
            ts.adf_test_simplified([1, 2])


class TestForecastSimpleExponential:
    def test_forecast_simple_exponential(self):
        data = [1, 2, 3, 4, 5]
        result = ts.forecast_simple_exponential(data, steps=3)
        assert len(result) == 3

    def test_forecast_simple_exponential_empty(self):
        with pytest.raises(InsufficientDataError):
            ts.forecast_simple_exponential([], steps=1)


class TestForecastHolt:
    def test_forecast_holt(self):
        data = [1, 2, 3, 4, 5]
        result = ts.forecast_holt(data, steps=3)
        assert len(result) == 3

    def test_forecast_holt_insufficient(self):
        with pytest.raises(InsufficientDataError):
            ts.forecast_holt([1], steps=1)
