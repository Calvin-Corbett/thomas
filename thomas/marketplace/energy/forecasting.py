"""
Energy forecasting models.

Provides load forecasting (similar day + regression), solar irradiance
prediction (persistence + NWP blend), wind speed forecasting (autoregressive),
price forecasting, and ensemble methods.
"""

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ForecastResult:
    """Forecast result with confidence interval."""

    point_forecast: list[float]  # Hourly forecast values
    lower_bound: list[float]  # Lower confidence bound
    upper_bound: list[float]  # Upper confidence bound
    mape: float = 0.0  # Mean absolute percentage error
    rmse: float = 0.0  # Root mean squared error


@dataclass
class LoadForecaster:
    """Electricity load forecasting."""

    def similar_day_method(
        self,
        historical_loads: dict,  # datetime -> MW
        target_date: datetime,
        num_similar_days: int = 7,
    ) -> list[float]:
        """
        Forecast load using similar day method.

        Args:
            historical_loads: Historical hourly loads
            target_date: Date to forecast
            num_similar_days: Number of similar days to average

        Returns:
            Hourly load forecast for target date
        """
        if not historical_loads:
            return [0.0] * 24

        # Build daily profiles keyed by date so each calendar day appears once.
        daily_profiles: dict = {}
        for ts, load in historical_loads.items():
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            day = ts.date()
            if day not in daily_profiles:
                daily_profiles[day] = {}
            daily_profiles[day][ts.hour] = float(load)

        # Global hourly fallback profile.
        hourly_totals = [0.0] * 24
        hourly_counts = [0] * 24
        for profile in daily_profiles.values():
            for hour, load in profile.items():
                if 0 <= hour < 24:
                    hourly_totals[hour] += load
                    hourly_counts[hour] += 1
        global_hourly = [(hourly_totals[h] / hourly_counts[h]) if hourly_counts[h] else 0.0 for h in range(24)]

        # Select closest similar days by weekday.
        target_dow = target_date.weekday()
        target_day = target_date.date()
        similar_days = []
        for day in daily_profiles:
            if day.weekday() == target_dow and day != target_day:
                day_diff = abs((day - target_day).days)
                similar_days.append((day_diff, day))

        similar_days.sort(key=lambda x: x[0])
        selected_days = [day for _, day in similar_days[:num_similar_days]]

        if not selected_days:
            return global_hourly

        # Average hour-by-hour across selected days.
        forecast = [0.0] * 24
        counts = [0] * 24
        for day in selected_days:
            profile = daily_profiles.get(day, {})
            for hour in range(24):
                if hour in profile:
                    forecast[hour] += profile[hour]
                    counts[hour] += 1

        for hour in range(24):
            if counts[hour]:
                forecast[hour] /= counts[hour]
            else:
                forecast[hour] = global_hourly[hour]

        # Clamp to conservative load-factor bounds to avoid extreme spikes.
        daily_mean = sum(forecast) / 24.0 if forecast else 0.0
        if daily_mean > 0.0:
            lower = 0.4 * daily_mean
            upper = 1.1 * daily_mean
            forecast = [min(max(load, lower), upper) for load in forecast]

        return forecast

    def regression_method(
        self,
        historical_loads: list[float],
        temperature_forecast: list[float],
        holiday_indicators: list[bool],
    ) -> list[float]:
        """
        Forecast load using regression model (temperature sensitive).

        Args:
            historical_loads: Recent historical hourly loads (MW)
            temperature_forecast: Hourly temperature forecast (Celsius)
            holiday_indicators: Whether each hour is a holiday

        Returns:
            Hourly load forecast
        """
        if not historical_loads or len(historical_loads) < 24:
            return [sum(historical_loads) / len(historical_loads)] * 24

        # Simple regression: Load = base + temp_coefficient * (temp - 20) + holiday_adjustment
        n_hours = min(24, len(historical_loads))

        # Estimate base load (normalized to 20C)
        base_load = (
            sum(historical_loads[-24:]) / 24
            if len(historical_loads) >= 24
            else sum(historical_loads) / len(historical_loads)
        )

        # Temperature sensitivity (estimated)
        temp_coefficient = 0.5  # MW per Celsius

        # Generate forecast
        forecast = []

        for hour in range(n_hours):
            temp = temperature_forecast[hour] if hour < len(temperature_forecast) else 20.0
            is_holiday = holiday_indicators[hour] if hour < len(holiday_indicators) else False

            # Regression equation
            load = base_load + temp_coefficient * (temp - 20.0)

            # Holiday adjustment (reduce by 10%)
            if is_holiday:
                load *= 0.9

            forecast.append(max(0.0, load))

        # Pad to 24 hours if needed
        if len(forecast) < 24:
            forecast.extend([forecast[-1]] * (24 - len(forecast)))

        return forecast

    def ensemble_forecast(
        self,
        forecasts: list[list[float]],
        weights: list[float] | None = None,
    ) -> list[float]:
        """
        Combine multiple forecasts using weighted ensemble.

        Args:
            forecasts: List of forecast arrays
            weights: Weight for each forecast (default: equal weights)

        Returns:
            Ensemble forecast
        """
        if not forecasts:
            return []

        if weights is None:
            weights = [1.0 / len(forecasts)] * len(forecasts)

        # Normalize weights
        weight_sum = sum(weights)
        if weight_sum == 0:
            weights = [1.0 / len(weights)] * len(weights)
        else:
            weights = [w / weight_sum for w in weights]

        # Combine forecasts
        n_hours = len(forecasts[0])
        ensemble = [0.0] * n_hours

        for forecast, weight in zip(forecasts, weights):
            for hour in range(min(n_hours, len(forecast))):
                ensemble[hour] += forecast[hour] * weight

        return ensemble


@dataclass
class SolarForecaster:
    """Solar irradiance and generation forecasting."""

    def persistence_method(
        self,
        recent_irradiance: list[float],
        forecast_hours: int = 24,
    ) -> list[float]:
        """
        Persistence forecast (assume current conditions continue).

        Args:
            recent_irradiance: Recent hourly irradiance (W/m^2)
            forecast_hours: Hours to forecast

        Returns:
            Irradiance forecast
        """
        if not recent_irradiance:
            return [0.0] * forecast_hours

        # Average recent irradiance
        avg_irradiance = sum(recent_irradiance[-6:]) / min(6, len(recent_irradiance))

        # Decay forecast over time (assumes cloudy conditions improve)
        forecast = []
        for hour in range(forecast_hours):
            # Decay factor (returns to 50% of current within 24 hours)
            decay = math.exp(-hour / 24.0)
            forecast.append(avg_irradiance * decay)

        return forecast

    def nwp_blend_method(
        self,
        persistence_forecast: list[float],
        nwp_forecast: list[float],
        nwp_weight: float = 0.3,
    ) -> list[float]:
        """
        Blend persistence and NWP (numerical weather prediction) forecasts.

        Args:
            persistence_forecast: Persistence model output
            nwp_forecast: NWP model output
            nwp_weight: Weight for NWP (0-1)

        Returns:
            Blended forecast
        """
        if len(persistence_forecast) != len(nwp_forecast):
            return persistence_forecast

        forecast = []

        for persist, nwp in zip(persistence_forecast, nwp_forecast):
            blended = (1.0 - nwp_weight) * persist + nwp_weight * nwp
            forecast.append(max(0.0, blended))

        return forecast

    def cloud_cover_adjustment(
        self,
        clear_sky_irradiance: list[float],
        cloud_cover_forecast: list[float],
    ) -> list[float]:
        """
        Adjust clear-sky irradiance for cloud cover forecast.

        Args:
            clear_sky_irradiance: Clear-sky irradiance values
            cloud_cover_forecast: Cloud cover (0.0-1.0)

        Returns:
            Adjusted irradiance forecast
        """
        forecast = []

        for cs_irr, cloud in zip(clear_sky_irradiance, cloud_cover_forecast):
            # Cloud attenuation (empirical relationship)
            # 100% cloud cover reduces irradiance to ~10% of clear-sky
            transmission = 1.0 - cloud * 0.9
            irradiance = cs_irr * transmission

            forecast.append(max(0.0, irradiance))

        return forecast


@dataclass
class WindForecaster:
    """Wind speed and power forecasting."""

    def autoregressive_forecast(
        self,
        historical_wind_speeds: list[float],
        lag_hours: int = 6,
        forecast_hours: int = 24,
    ) -> list[float]:
        """
        Forecast wind speed using autoregressive model.

        Args:
            historical_wind_speeds: Recent hourly wind speeds (m/s)
            lag_hours: Number of past hours to use
            forecast_hours: Hours to forecast

        Returns:
            Wind speed forecast
        """
        if not historical_wind_speeds or len(historical_wind_speeds) < lag_hours:
            # Fallback to average
            avg_wind = sum(historical_wind_speeds) / len(historical_wind_speeds)
            return [avg_wind] * forecast_hours

        # Simple AR(1) model: w_t = mean + phi * (w_{t-1} - mean) + noise
        recent_speeds = historical_wind_speeds[-lag_hours:]
        mean_speed = sum(recent_speeds) / len(recent_speeds)

        # Estimate AR coefficient
        ar_coeff = 0.8  # Typical persistence

        # Forecast
        forecast = []
        current = mean_speed

        for hour in range(forecast_hours):
            # Decay deviation from mean
            forecast_value = mean_speed + ar_coeff ** (hour + 1) * (recent_speeds[-1] - mean_speed)

            # Add seasonal component (wind stronger in afternoon)
            hour_of_day = hour % 24
            seasonal = 1.0 + 0.2 * math.sin(2 * math.pi * hour_of_day / 24)

            forecast.append(max(0.0, forecast_value * seasonal))

        return forecast

    def power_curve_forecast(
        self,
        wind_speed_forecast: list[float],
        power_curve: list[tuple[float, float]],  # (wind_speed, power_mw)
    ) -> list[float]:
        """
        Convert wind speed forecast to power forecast using power curve.

        Args:
            wind_speed_forecast: Wind speed forecast (m/s)
            power_curve: Turbine power curve

        Returns:
            Power forecast (MW)
        """
        if not wind_speed_forecast or not power_curve:
            return []

        # Sort power curve
        sorted_curve = sorted(power_curve, key=lambda x: x[0])

        forecast = []

        for wind_speed in wind_speed_forecast:
            # Interpolate on power curve
            power = 0.0

            for i in range(len(sorted_curve) - 1):
                ws1, p1 = sorted_curve[i]
                ws2, p2 = sorted_curve[i + 1]

                if ws1 <= wind_speed <= ws2:
                    # Linear interpolation
                    fraction = (wind_speed - ws1) / (ws2 - ws1)
                    power = p1 + fraction * (p2 - p1)
                    break

            if wind_speed > sorted_curve[-1][0]:
                power = sorted_curve[-1][1]

            forecast.append(max(0.0, power))

        return forecast


@dataclass
class PriceForecaster:
    """Electricity price forecasting."""

    def demand_supply_based(
        self,
        demand_forecast: list[float],
        renewable_availability: list[float],
        base_price: float = 40.0,
    ) -> list[float]:
        """
        Forecast price based on demand and supply dynamics.

        Args:
            demand_forecast: Hourly demand forecast (MW)
            renewable_availability: Renewable generation available (MW)
            base_price: Base energy price ($/MWh)

        Returns:
            Price forecast
        """
        forecast = []

        for demand, renewable in zip(demand_forecast, renewable_availability):
            # Available margin
            total_capacity = 1000.0  # Assumed system size

            if renewable >= demand:
                # Excess renewable -> low price
                price = base_price * 0.3
            else:
                # Conventional needed -> supply-demand balance
                conventional_needed = demand - renewable
                margin = total_capacity - demand
                conventional_ratio = conventional_needed / demand if demand > 0 else 1.0

                if margin < 100:
                    # Tight market -> high price
                    price = base_price * 1.5
                elif margin < 200:
                    # Normal -> base price
                    price = base_price
                else:
                    # Loose market -> low price
                    price = base_price * 0.8

                # Lower renewable share raises marginal system cost.
                price *= 1.0 + 0.3 * conventional_ratio

            forecast.append(max(10.0, price))

        return forecast

    def seasonality_adjustment(
        self,
        base_forecast: list[float],
        hour_of_year: list[int],
    ) -> list[float]:
        """
        Adjust price forecast for seasonal patterns.

        Args:
            base_forecast: Base price forecast
            hour_of_year: Hour index in year

        Returns:
            Seasonally adjusted forecast
        """
        forecast = []

        for base_price, hour in zip(base_forecast, hour_of_year):
            # Summer (hour 2000-5000) higher prices, winter lower
            day_of_year = hour // 24
            seasonal_factor = 1.0 + 0.3 * math.sin(2 * math.pi * day_of_year / 365.0)

            adjusted_price = base_price * seasonal_factor
            forecast.append(adjusted_price)

        return forecast


def calculate_forecast_error(
    actual: list[float],
    forecast: list[float],
) -> tuple[float, float, float]:
    """
    Calculate forecast accuracy metrics.

    Args:
        actual: Actual values
        forecast: Forecasted values

    Returns:
        Tuple of (MAE, RMSE, MAPE)
    """
    if len(actual) != len(forecast):
        return 0.0, 0.0, 0.0

    mae = sum(abs(a - f) for a, f in zip(actual, forecast)) / len(actual)

    mse = sum((a - f) ** 2 for a, f in zip(actual, forecast)) / len(actual)
    rmse = math.sqrt(mse)

    # MAPE (avoid division by zero)
    mape_values = []
    for a, f in zip(actual, forecast):
        if a > 0:
            mape_values.append(abs(a - f) / a)

    mape = sum(mape_values) / len(mape_values) if mape_values else 0.0

    return mae, rmse, mape


def adaptive_forecast_weights(
    recent_errors: list[float],
    decay_factor: float = 0.9,
) -> list[float]:
    """
    Calculate adaptive weights for ensemble based on recent errors.

    Args:
        recent_errors: List of recent forecast errors
        decay_factor: Exponential decay for recent emphasis

    Returns:
        Normalized weights
    """
    if not recent_errors:
        return []

    # Lower error -> higher weight
    max_error = max(recent_errors)
    if max_error == 0:
        weights = [1.0] * len(recent_errors)
    else:
        weights = [max_error - e for e in recent_errors]

    # Apply exponential decay (recent more important)
    n = len(weights)
    decay_weights = [decay_factor ** (n - i - 1) for i in range(n)]

    # Combine
    combined = [w1 * w2 for w1, w2 in zip(weights, decay_weights)]

    # Normalize
    total = sum(combined)
    if total > 0:
        combined = [w / total for w in combined]
    else:
        combined = [1.0 / len(combined)] * len(combined)

    return combined
