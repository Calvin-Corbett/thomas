"""
Demand forecasting module for supply chain management.

Provides forecasting methods including exponential smoothing variants,
moving averages, Croston's method for intermittent demand, forecast
accuracy metrics, demand decomposition, and Bass diffusion model.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from thomas.supply_chain._exceptions import (
    DemandForecastException,
    InsufficientHistoricalDataException,
    InvalidForecastMethodException,
)
from thomas.supply_chain._types import SKU, DemandForecast, DemandPattern


@dataclass
class ForecastAccuracy:
    """Forecast accuracy metrics."""

    method: str
    mae: Decimal  # Mean Absolute Error
    mape: Decimal  # Mean Absolute Percentage Error
    rmse: Decimal  # Root Mean Squared Error
    tracking_signal: Decimal  # Bias indicator
    theil_u: Decimal  # Theil's U statistic


@dataclass
class DemandDecomposition:
    """Decomposed demand components."""

    sku: SKU
    trend: list[Decimal]
    seasonal: list[Decimal]
    cyclical: list[Decimal]
    irregular: list[Decimal]
    deseasonalized_demand: list[Decimal]


@dataclass
class BassModel:
    """Bass diffusion model parameters and forecasts."""

    market_potential: Decimal
    coefficient_innovation: Decimal  # p
    coefficient_imitation: Decimal  # q
    time_period: int
    forecast: list[Decimal]


class DemandForecaster:
    """
    Comprehensive demand forecasting system.

    Supports multiple forecasting methods including exponential smoothing,
    moving averages, intermittent demand forecasting, and new product
    forecasting with Bass diffusion model.
    """

    MIN_HISTORICAL_PERIODS = 4
    MIN_SEASONAL_PERIODS = 24

    def __init__(self) -> None:
        """Initialize demand forecaster."""
        pass

    def simple_exponential_smoothing(
        self, sku: SKU, historical_demand: list[Decimal], alpha: Decimal = Decimal("0.3"), forecast_periods: int = 12
    ) -> DemandForecast:
        """
        Simple exponential smoothing forecast (SES).

        Args:
            sku: Stock keeping unit
            historical_demand: Historical demand values
            alpha: Smoothing constant (0-1, higher = more reactive)
            forecast_periods: Number of periods to forecast

        Returns:
            DemandForecast with forecasted demand

        Raises:
            InsufficientHistoricalDataException: If insufficient historical data
        """
        if len(historical_demand) < self.MIN_HISTORICAL_PERIODS:
            raise InsufficientHistoricalDataException(sku.code, self.MIN_HISTORICAL_PERIODS, len(historical_demand))

        # Initialize level as first observation
        level = historical_demand[0]
        forecasts = []

        # Fit model to historical data
        for demand in historical_demand[1:]:
            level = alpha * demand + (Decimal("1") - alpha) * level

        # Generate forecasts
        for _ in range(forecast_periods):
            forecasts.append(level)

        return DemandForecast(
            id=UUID(int=0),
            sku=sku,
            forecast_date=datetime.utcnow(),
            forecast_periods=forecast_periods,
            forecasted_demand=forecasts,
            forecast_method="simple_exponential_smoothing",
        )

    def double_exponential_smoothing(
        self,
        sku: SKU,
        historical_demand: list[Decimal],
        alpha: Decimal = Decimal("0.3"),
        beta: Decimal = Decimal("0.1"),
        forecast_periods: int = 12,
    ) -> DemandForecast:
        """
        Double exponential smoothing (Holt's method) for trended data.

        Args:
            sku: Stock keeping unit
            historical_demand: Historical demand values
            alpha: Level smoothing constant
            beta: Trend smoothing constant
            forecast_periods: Number of periods to forecast

        Returns:
            DemandForecast with trend-adjusted forecasts
        """
        if len(historical_demand) < self.MIN_HISTORICAL_PERIODS:
            raise InsufficientHistoricalDataException(sku.code, self.MIN_HISTORICAL_PERIODS, len(historical_demand))

        # Initialize level and trend
        level = historical_demand[0]
        trend = historical_demand[1] - historical_demand[0]

        # Fit model
        for i in range(1, len(historical_demand)):
            prev_level = level
            level = alpha * historical_demand[i] + (Decimal("1") - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (Decimal("1") - beta) * trend

        # Generate forecasts
        forecasts = [level + (Decimal(h) * trend) for h in range(1, forecast_periods + 1)]

        return DemandForecast(
            id=UUID(int=0),
            sku=sku,
            forecast_date=datetime.utcnow(),
            forecast_periods=forecast_periods,
            forecasted_demand=forecasts,
            forecast_method="double_exponential_smoothing",
            trend_factor=trend,
        )

    def triple_exponential_smoothing(
        self,
        sku: SKU,
        historical_demand: list[Decimal],
        alpha: Decimal = Decimal("0.3"),
        beta: Decimal = Decimal("0.1"),
        gamma: Decimal = Decimal("0.1"),
        seasonal_period: int = 12,
        forecast_periods: int = 12,
    ) -> DemandForecast:
        """
        Triple exponential smoothing (Holt-Winters method) for seasonal data.

        Args:
            sku: Stock keeping unit
            historical_demand: Historical demand values
            alpha: Level smoothing constant
            beta: Trend smoothing constant
            gamma: Seasonal smoothing constant
            seasonal_period: Length of seasonal cycle
            forecast_periods: Number of periods to forecast

        Returns:
            DemandForecast with seasonal adjustments
        """
        if len(historical_demand) < max(self.MIN_SEASONAL_PERIODS, seasonal_period * 2):
            raise InsufficientHistoricalDataException(
                sku.code, max(self.MIN_SEASONAL_PERIODS, seasonal_period * 2), len(historical_demand)
            )

        # Initialize level (average of first season)
        level = Decimal(sum(historical_demand[:seasonal_period])) / Decimal(seasonal_period)

        # Initialize trend
        trend = (
            Decimal(sum(historical_demand[seasonal_period : 2 * seasonal_period])) / Decimal(seasonal_period)
            - Decimal(sum(historical_demand[:seasonal_period])) / Decimal(seasonal_period)
        ) / Decimal(seasonal_period)

        # Initialize seasonal factors
        seasonal = []
        for i in range(seasonal_period):
            avg = Decimal(sum(historical_demand[i::seasonal_period])) / Decimal(
                len([d for j, d in enumerate(historical_demand) if j % seasonal_period == i])
            )
            seasonal.append(avg / level if level > 0 else Decimal("1"))

        # Fit model
        for i, demand in enumerate(historical_demand):
            prev_level = level
            season_idx = i % seasonal_period

            level = alpha * (demand / seasonal[season_idx]) + (Decimal("1") - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (Decimal("1") - beta) * trend
            seasonal[season_idx] = gamma * (demand / level) + (Decimal("1") - gamma) * seasonal[season_idx]

        # Generate forecasts
        forecasts = []
        for h in range(1, forecast_periods + 1):
            season_idx = (len(historical_demand) + h - 1) % seasonal_period
            forecast = (level + Decimal(h) * trend) * seasonal[season_idx]
            forecasts.append(max(Decimal("0"), forecast))

        return DemandForecast(
            id=UUID(int=0),
            sku=sku,
            forecast_date=datetime.utcnow(),
            forecast_periods=forecast_periods,
            forecasted_demand=forecasts,
            forecast_method="triple_exponential_smoothing",
            seasonal_factors=seasonal,
        )

    def moving_average(
        self,
        sku: SKU,
        historical_demand: list[Decimal],
        period: int = 4,
        forecast_periods: int = 12,
        method: str = "simple",
    ) -> DemandForecast:
        """
        Moving average forecast (simple or weighted).

        Args:
            sku: Stock keeping unit
            historical_demand: Historical demand values
            period: Moving average window
            forecast_periods: Number of periods to forecast
            method: "simple" or "weighted"

        Returns:
            DemandForecast with moving average forecasts
        """
        if len(historical_demand) < period:
            raise InsufficientHistoricalDataException(sku.code, period, len(historical_demand))

        if method == "simple":
            # Use last moving average value as forecast
            last_average = Decimal(sum(historical_demand[-period:])) / Decimal(period)
        elif method == "weighted":
            # Weight recent observations more heavily
            weights = [Decimal(i + 1) for i in range(period)]
            total_weight = sum(weights)
            last_average = Decimal(sum(d * w for d, w in zip(historical_demand[-period:], weights))) / total_weight
        else:
            raise InvalidForecastMethodException(method)

        forecasts = [last_average] * forecast_periods

        return DemandForecast(
            id=UUID(int=0),
            sku=sku,
            forecast_date=datetime.utcnow(),
            forecast_periods=forecast_periods,
            forecasted_demand=forecasts,
            forecast_method=f"{method}_moving_average",
        )

    def croston_method(
        self, sku: SKU, historical_demand: list[Decimal], alpha: Decimal = Decimal("0.1"), forecast_periods: int = 12
    ) -> DemandForecast:
        """
        Croston's method for intermittent demand forecasting.

        Args:
            sku: Stock keeping unit
            historical_demand: Historical demand values (may contain zeros)
            alpha: Smoothing constant
            forecast_periods: Number of periods to forecast

        Returns:
            DemandForecast optimized for intermittent demand
        """
        if len(historical_demand) < self.MIN_HISTORICAL_PERIODS:
            raise InsufficientHistoricalDataException(sku.code, self.MIN_HISTORICAL_PERIODS, len(historical_demand))

        # Initialize parameters
        non_zero_demands = [d for d in historical_demand if d > 0]
        avg_demand = (
            Decimal(sum(non_zero_demands)) / Decimal(len(non_zero_demands)) if non_zero_demands else Decimal("0")
        )

        # Count periods between non-zero demands
        periods_between = []
        last_nonzero_idx = -1
        for i, demand in enumerate(historical_demand):
            if demand > 0:
                if last_nonzero_idx >= 0:
                    periods_between.append(i - last_nonzero_idx)
                last_nonzero_idx = i

        avg_interval = (
            Decimal(sum(periods_between)) / Decimal(len(periods_between)) if periods_between else Decimal("1")
        )

        # Forecast as average demand / average interval
        forecast_value = avg_demand / avg_interval if avg_interval > 0 else avg_demand

        forecasts = [forecast_value] * forecast_periods

        return DemandForecast(
            id=UUID(int=0),
            sku=sku,
            forecast_date=datetime.utcnow(),
            forecast_periods=forecast_periods,
            forecasted_demand=forecasts,
            forecast_method="croston",
            demand_pattern=DemandPattern.INTERMITTENT,
        )

    def calculate_accuracy_metrics(self, actual: list[Decimal], forecast: list[Decimal]) -> ForecastAccuracy:
        """
        Calculate forecast accuracy metrics.

        Args:
            actual: Actual demand values
            forecast: Forecasted values

        Returns:
            ForecastAccuracy with MAE, MAPE, RMSE, and tracking signal
        """
        if len(actual) != len(forecast):
            raise DemandForecastException("Actual and forecast lengths must match")

        errors = [a - f for a, f in zip(actual, forecast)]
        abs_errors = [abs(e) for e in errors]

        # Mean Absolute Error
        mae = Decimal(sum(abs_errors)) / Decimal(len(abs_errors))

        # Mean Absolute Percentage Error
        mape_values = []
        for a, e in zip(actual, abs_errors):
            if a != 0:
                mape_values.append(e / a)
        mape = (Decimal(sum(mape_values)) / Decimal(len(mape_values)) * Decimal("100")) if mape_values else Decimal("0")

        # Root Mean Squared Error
        squared_errors = [e * e for e in errors]
        rmse = Decimal(str(math.sqrt(float(Decimal(sum(squared_errors)) / Decimal(len(squared_errors))))))

        # Tracking Signal
        sum_errors = Decimal(sum(errors))
        tracking_signal = sum_errors / mae if mae > 0 else Decimal("0")

        # Theil's U
        numerator = Decimal(sum(e * e for e in errors))
        denominator = Decimal(sum(a * a for a in actual)) + Decimal(sum(f * f for f in forecast))
        theil_u = Decimal(str(math.sqrt(float(numerator / denominator)))) if denominator > 0 else Decimal("0")

        return ForecastAccuracy(
            method="combined", mae=mae, mape=mape, rmse=rmse, tracking_signal=tracking_signal, theil_u=theil_u
        )

    def decompose_demand(
        self, sku: SKU, historical_demand: list[Decimal], seasonal_period: int = 12
    ) -> DemandDecomposition:
        """
        Decompose demand into trend, seasonal, cyclical, and irregular components.

        Args:
            sku: Stock keeping unit
            historical_demand: Historical demand values
            seasonal_period: Length of seasonal cycle

        Returns:
            DemandDecomposition with separated components
        """
        if len(historical_demand) < seasonal_period * 2:
            raise InsufficientHistoricalDataException(sku.code, seasonal_period * 2, len(historical_demand))

        n = len(historical_demand)
        trend = [Decimal("0")] * n
        seasonal = [Decimal("1")] * seasonal_period

        # Calculate trend using moving average
        window = seasonal_period
        for i in range(n):
            start = max(0, i - window // 2)
            end = min(n, i + window // 2 + 1)
            trend[i] = Decimal(sum(historical_demand[start:end])) / Decimal(end - start)

        # Calculate seasonal factors
        detrended = [(historical_demand[i] / trend[i] if trend[i] > 0 else Decimal("1")) for i in range(n)]

        for month in range(seasonal_period):
            month_values = [detrended[i] for i in range(month, n, seasonal_period)]
            if month_values:
                seasonal[month] = Decimal(sum(month_values)) / Decimal(len(month_values))

        # Normalize seasonal factors
        avg_seasonal = Decimal(sum(seasonal)) / Decimal(len(seasonal))
        seasonal = [s / avg_seasonal if avg_seasonal > 0 else s for s in seasonal]

        # Calculate seasonally adjusted demand
        deseasonalized = [
            (
                historical_demand[i] / seasonal[i % seasonal_period]
                if seasonal[i % seasonal_period] > 0
                else historical_demand[i]
            )
            for i in range(n)
        ]

        # Irregular component (residuals)
        cyclical = [Decimal("1")] * n
        irregular = [
            (
                historical_demand[i] / (trend[i] * seasonal[i % seasonal_period] * cyclical[i])
                if (trend[i] > 0 and seasonal[i % seasonal_period] > 0 and cyclical[i] > 0)
                else Decimal("1")
            )
            for i in range(n)
        ]

        return DemandDecomposition(
            sku=sku,
            trend=trend,
            seasonal=seasonal * ((n // seasonal_period) + 1),
            cyclical=cyclical,
            irregular=irregular,
            deseasonalized_demand=deseasonalized,
        )

    def bass_diffusion_model(
        self,
        market_potential: Decimal,
        p: Decimal,  # Coefficient of innovation
        q: Decimal,  # Coefficient of imitation
        time_period: int = 24,
    ) -> BassModel:
        """
        Bass diffusion model for new product forecasting.

        Args:
            market_potential: Total addressable market size
            p: Innovation coefficient (0-1)
            q: Imitation coefficient (0-1)
            time_period: Number of periods to forecast

        Returns:
            BassModel with forecasted adoption curve
        """
        forecasts = []
        cumulative_adoptions = Decimal("0")

        for t in range(1, time_period + 1):
            Decimal(t)
            Decimal(t - 1)

            # Sales at time t = [p + q * (F(t-1) / m)] * (m - F(t-1))
            # where F(t) is cumulative adoptions
            adoption_rate = p + q * (cumulative_adoptions / market_potential if market_potential > 0 else Decimal("0"))
            sales = adoption_rate * (market_potential - cumulative_adoptions)
            forecasts.append(max(Decimal("0"), sales))

            cumulative_adoptions += sales

        return BassModel(
            market_potential=market_potential,
            coefficient_innovation=p,
            coefficient_imitation=q,
            time_period=time_period,
            forecast=forecasts,
        )

    def identify_demand_pattern(self, historical_demand: list[Decimal], seasonal_period: int = 12) -> DemandPattern:
        """
        Identify demand pattern (smooth, trend, seasonal, etc.).

        Args:
            historical_demand: Historical demand values
            seasonal_period: Length of seasonal cycle

        Returns:
            DemandPattern classification
        """
        if len(historical_demand) < 4:
            return DemandPattern.SMOOTH

        # Check for non-zero periods (intermittent)
        non_zero_count = sum(1 for d in historical_demand if d > 0)
        if non_zero_count < len(historical_demand) * Decimal("0.5"):
            return DemandPattern.INTERMITTENT

        # Check coefficient of variation
        floats = [float(d) for d in historical_demand]
        mean = statistics.mean(floats)
        std_dev = statistics.stdev(floats) if len(floats) > 1 else 0
        cv = std_dev / mean if mean > 0 else 0

        if cv > 1.5:
            return DemandPattern.ERRATIC
        if cv > 1.0:
            return DemandPattern.INTERMITTENT

        # Check for trend
        if len(historical_demand) >= 3:
            first_half_avg = float(
                Decimal(sum(historical_demand[: len(historical_demand) // 2])) / Decimal(len(historical_demand) // 2)
            )
            second_half_avg = float(
                Decimal(sum(historical_demand[len(historical_demand) // 2 :]))
                / Decimal(len(historical_demand) - len(historical_demand) // 2)
            )

            trend_strength = abs(second_half_avg - first_half_avg) / first_half_avg if first_half_avg > 0 else 0
            if trend_strength > 0.2:
                return DemandPattern.TREND

        # Check for seasonality
        if len(historical_demand) >= seasonal_period * 2:
            season_vars = []
            for i in range(seasonal_period):
                season_vals = [float(historical_demand[j]) for j in range(i, len(historical_demand), seasonal_period)]
                if len(season_vals) > 1:
                    season_vars.append(statistics.variance(season_vals))

            avg_variance = statistics.mean(season_vars) if season_vars else 0
            overall_variance = statistics.variance(floats) if len(floats) > 1 else 0

            if overall_variance > 0 and avg_variance / overall_variance > 0.3:
                return DemandPattern.SEASONAL

        return DemandPattern.SMOOTH
