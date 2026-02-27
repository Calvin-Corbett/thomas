"""
Tests for supply chain demand forecasting module.

Tests demand forecasting methods including exponential smoothing variants,
moving averages, Croston's method, forecast accuracy metrics, decomposition,
and Bass diffusion model.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from thomas.supply_chain import (
    SKU,
    DemandForecaster,
    DemandPattern,
    InsufficientHistoricalDataException,
)


class TestSimpleExponentialSmoothing:
    """Test simple exponential smoothing forecasting."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()
        self.sku = SKU(code="FORECAST001", product_id=uuid4())

    def test_ses_basic_forecast(self) -> None:
        """Test basic SES forecast."""
        demand = [Decimal(str(100 + i)) for i in range(12)]

        forecast = self.forecaster.simple_exponential_smoothing(
            sku=self.sku, historical_demand=demand, alpha=Decimal("0.3"), forecast_periods=6
        )

        assert len(forecast.forecasted_demand) == 6
        assert all(d > 0 for d in forecast.forecasted_demand)
        assert forecast.forecast_method == "simple_exponential_smoothing"

    def test_ses_different_alpha(self) -> None:
        """Test SES with different smoothing constants."""
        demand = [Decimal("100")] * 10 + [Decimal("150")] * 2

        forecast_low_alpha = self.forecaster.simple_exponential_smoothing(
            sku=self.sku, historical_demand=demand, alpha=Decimal("0.1"), forecast_periods=1
        )

        forecast_high_alpha = self.forecaster.simple_exponential_smoothing(
            sku=self.sku, historical_demand=demand, alpha=Decimal("0.9"), forecast_periods=1
        )

        # High alpha should react faster to recent changes
        assert forecast_high_alpha.forecasted_demand[0] >= forecast_low_alpha.forecasted_demand[0]

    def test_ses_insufficient_data(self) -> None:
        """Test SES with insufficient historical data."""
        with pytest.raises(InsufficientHistoricalDataException):
            self.forecaster.simple_exponential_smoothing(
                sku=self.sku, historical_demand=[Decimal("100"), Decimal("150")], forecast_periods=1
            )


class TestDoubleExponentialSmoothing:
    """Test double exponential smoothing (Holt's method)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()
        self.sku = SKU(code="FORECAST002", product_id=uuid4())

    def test_des_with_trend(self) -> None:
        """Test DES captures trend."""
        # Create trending demand
        demand = [Decimal(str(100 + i * 5)) for i in range(12)]

        forecast = self.forecaster.double_exponential_smoothing(
            sku=self.sku, historical_demand=demand, alpha=Decimal("0.3"), beta=Decimal("0.1"), forecast_periods=6
        )

        assert len(forecast.forecasted_demand) == 6
        # Forecasts should show upward trend
        assert forecast.forecasted_demand[-1] > forecast.forecasted_demand[0]

    def test_des_captures_slope(self) -> None:
        """Test DES captures trend slope."""
        demand = [Decimal(str(100 + i * 10)) for i in range(12)]

        forecast = self.forecaster.double_exponential_smoothing(
            sku=self.sku, historical_demand=demand, forecast_periods=1
        )

        assert forecast.trend_factor > 0


class TestTripleExponentialSmoothing:
    """Test triple exponential smoothing (Holt-Winters)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()
        self.sku = SKU(code="FORECAST003", product_id=uuid4())

    def test_tes_seasonal_forecast(self) -> None:
        """Test TES captures seasonality."""
        # Create seasonal demand pattern
        base_demand = [Decimal(str(100 + (i % 4) * 25)) for i in range(24)]

        forecast = self.forecaster.triple_exponential_smoothing(
            sku=self.sku, historical_demand=base_demand, seasonal_period=4, forecast_periods=8
        )

        assert len(forecast.forecasted_demand) == 8
        assert len(forecast.seasonal_factors) > 0

    def test_tes_sufficient_data_required(self) -> None:
        """Test TES requires sufficient data."""
        with pytest.raises(InsufficientHistoricalDataException):
            self.forecaster.triple_exponential_smoothing(
                sku=self.sku, historical_demand=[Decimal("100")] * 10, seasonal_period=12
            )


class TestMovingAverage:
    """Test moving average forecasting."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()
        self.sku = SKU(code="FORECAST004", product_id=uuid4())

    def test_simple_moving_average(self) -> None:
        """Test simple moving average."""
        demand = [Decimal(str(100 + i)) for i in range(12)]

        forecast = self.forecaster.moving_average(
            sku=self.sku, historical_demand=demand, period=3, forecast_periods=6, method="simple"
        )

        assert len(forecast.forecasted_demand) == 6
        assert forecast.forecast_method == "simple_moving_average"

    def test_weighted_moving_average(self) -> None:
        """Test weighted moving average."""
        demand = [Decimal("100"), Decimal("150"), Decimal("200")]

        forecast_simple = self.forecaster.moving_average(
            sku=self.sku, historical_demand=demand, period=3, forecast_periods=1, method="simple"
        )

        forecast_weighted = self.forecaster.moving_average(
            sku=self.sku, historical_demand=demand, period=3, forecast_periods=1, method="weighted"
        )

        # Weighted should emphasize recent values more
        assert forecast_weighted.forecasted_demand[0] >= forecast_simple.forecasted_demand[0]

    def test_moving_average_insufficient_period(self) -> None:
        """Test moving average with period larger than data."""
        with pytest.raises(InsufficientHistoricalDataException):
            self.forecaster.moving_average(
                sku=self.sku, historical_demand=[Decimal("100"), Decimal("150")], period=3, forecast_periods=1
            )


class TestCrostonMethod:
    """Test Croston's method for intermittent demand."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()
        self.sku = SKU(code="FORECAST005", product_id=uuid4())

    def test_croston_intermittent_demand(self) -> None:
        """Test Croston method with intermittent demand."""
        # Create intermittent demand pattern
        demand = [
            Decimal("0"),
            Decimal("100"),
            Decimal("0"),
            Decimal("0"),
            Decimal("150"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("120"),
            Decimal("0"),
        ]

        forecast = self.forecaster.croston_method(
            sku=self.sku, historical_demand=demand, alpha=Decimal("0.1"), forecast_periods=6
        )

        assert len(forecast.forecasted_demand) == 6
        assert forecast.demand_pattern == DemandPattern.INTERMITTENT
        assert all(d >= 0 for d in forecast.forecasted_demand)

    def test_croston_constant_demand(self) -> None:
        """Test Croston with constant demand."""
        demand = [Decimal("100")] * 10

        forecast = self.forecaster.croston_method(sku=self.sku, historical_demand=demand, forecast_periods=3)

        # Should stabilize to average
        assert all(f > 0 for f in forecast.forecasted_demand)


class TestForecastAccuracy:
    """Test forecast accuracy metrics."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()

    def test_mae_calculation(self) -> None:
        """Test Mean Absolute Error calculation."""
        actual = [Decimal("100"), Decimal("110"), Decimal("120")]
        forecast = [Decimal("95"), Decimal("105"), Decimal("130")]

        metrics = self.forecaster.calculate_accuracy_metrics(actual, forecast)

        assert metrics.mae > 0
        assert metrics.mae == Decimal("10")  # (5 + 5 + 10) / 3

    def test_mape_calculation(self) -> None:
        """Test Mean Absolute Percentage Error calculation."""
        actual = [Decimal("100"), Decimal("100"), Decimal("100")]
        forecast = [Decimal("90"), Decimal("100"), Decimal("110")]

        metrics = self.forecaster.calculate_accuracy_metrics(actual, forecast)

        assert metrics.mape > 0
        assert metrics.mape < Decimal("100")

    def test_rmse_calculation(self) -> None:
        """Test Root Mean Squared Error calculation."""
        actual = [Decimal("100"), Decimal("110"), Decimal("120")]
        forecast = [Decimal("100"), Decimal("110"), Decimal("120")]

        metrics = self.forecaster.calculate_accuracy_metrics(actual, forecast)

        assert metrics.rmse == Decimal("0")

    def test_tracking_signal(self) -> None:
        """Test tracking signal calculation."""
        actual = [Decimal("100"), Decimal("110"), Decimal("120")]
        forecast = [Decimal("95"), Decimal("105"), Decimal("115")]

        metrics = self.forecaster.calculate_accuracy_metrics(actual, forecast)

        # Positive bias (forecast below actual)
        assert metrics.tracking_signal > 0


class TestDemandDecomposition:
    """Test demand decomposition."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()
        self.sku = SKU(code="FORECAST006", product_id=uuid4())

    def test_decompose_seasonal_demand(self) -> None:
        """Test decomposition of seasonal demand."""
        # Create seasonal pattern
        base = [Decimal(str(100 + (i % 4) * 50)) for i in range(24)]

        decomp = self.forecaster.decompose_demand(sku=self.sku, historical_demand=base, seasonal_period=4)

        assert len(decomp.trend) == len(base)
        assert len(decomp.seasonal) >= 4
        assert len(decomp.irregular) == len(base)
        assert len(decomp.deseasonalized_demand) == len(base)

    def test_decompose_constant_demand(self) -> None:
        """Test decomposition of constant demand."""
        demand = [Decimal("100")] * 12

        decomp = self.forecaster.decompose_demand(sku=self.sku, historical_demand=demand, seasonal_period=4)

        assert all(d > 0 for d in decomp.deseasonalized_demand)


class TestBassDiffusionModel:
    """Test Bass diffusion model for new products."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()

    def test_bass_model_adoption(self) -> None:
        """Test Bass diffusion model adoption curve."""
        forecast = self.forecaster.bass_diffusion_model(
            market_potential=Decimal("1000000"),
            p=Decimal("0.03"),  # Innovation coefficient
            q=Decimal("0.4"),  # Imitation coefficient
            time_period=24,
        )

        assert len(forecast.forecast) == 24
        assert all(f >= 0 for f in forecast.forecast)
        assert forecast.market_potential == Decimal("1000000")

    def test_bass_model_s_curve(self) -> None:
        """Test Bass model produces S-curve pattern."""
        forecast = self.forecaster.bass_diffusion_model(
            market_potential=Decimal("1000000"), p=Decimal("0.03"), q=Decimal("0.4"), time_period=30
        )

        # Should have increasing then decreasing sales (S-curve)
        assert len(forecast.forecast) > 10
        # Peak should be somewhere in the middle
        peak_idx = forecast.forecast.index(max(forecast.forecast))
        assert 5 < peak_idx < len(forecast.forecast) - 5

    def test_bass_different_parameters(self) -> None:
        """Test Bass model with different coefficients."""
        high_innovation = self.forecaster.bass_diffusion_model(
            market_potential=Decimal("1000000"), p=Decimal("0.1"), q=Decimal("0.1"), time_period=24
        )

        low_innovation = self.forecaster.bass_diffusion_model(
            market_potential=Decimal("1000000"), p=Decimal("0.01"), q=Decimal("0.5"), time_period=24
        )

        # Early period adoption should be higher with high innovation
        assert high_innovation.forecast[5] > low_innovation.forecast[5]


class TestDemandPatternIdentification:
    """Test demand pattern identification."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.forecaster = DemandForecaster()

    def test_identify_smooth_demand(self) -> None:
        """Test identification of smooth demand."""
        demand = [Decimal("100")] * 20

        pattern = self.forecaster.identify_demand_pattern(demand)

        assert pattern == DemandPattern.SMOOTH

    def test_identify_trend(self) -> None:
        """Test identification of trend."""
        demand = [Decimal(str(100 + i * 5)) for i in range(20)]

        pattern = self.forecaster.identify_demand_pattern(demand)

        assert pattern in [DemandPattern.TREND, DemandPattern.SMOOTH]

    def test_identify_seasonal(self) -> None:
        """Test identification of seasonality."""
        demand = [Decimal(str(100 + (i % 4) * 30)) for i in range(24)]

        pattern = self.forecaster.identify_demand_pattern(demand, seasonal_period=4)

        assert pattern in [DemandPattern.SEASONAL, DemandPattern.SMOOTH]

    def test_identify_intermittent(self) -> None:
        """Test identification of intermittent demand."""
        demand = [Decimal("0"), Decimal("100"), Decimal("0"), Decimal("0"), Decimal("0")] * 4

        pattern = self.forecaster.identify_demand_pattern(demand)

        assert pattern in [DemandPattern.INTERMITTENT, DemandPattern.ERRATIC]
