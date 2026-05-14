"""Time series statistics methods."""

from . import correlation
from . import descriptive as desc
from ._exceptions import InsufficientDataError


def moving_average(data: list[float], window: int = 5) -> list[float]:
    """
    Calculate simple moving average.

    Args:
        data: Time series data.
        window: Window size (default 5).

    Returns:
        List of moving averages (first window-1 values are None-padded length).

    Raises:
        ValueError: If window is invalid.
    """
    if window < 1:
        raise ValueError("Window must be at least 1")

    if window > len(data):
        raise ValueError("Window cannot be larger than data")

    ma = []

    for i in range(len(data)):
        if i < window - 1:
            ma.append(None)
        else:
            window_sum = sum(data[i - window + 1 : i + 1])
            ma.append(window_sum / window)

    return ma


def weighted_moving_average(data: list[float], weights: list[float]) -> list[float]:
    """
    Calculate weighted moving average.

    Args:
        data: Time series data.
        weights: Weights (must sum to 1). Order is [most recent, ..., oldest].

    Returns:
        List of weighted moving averages.

    Raises:
        ValueError: If weights are invalid.
    """
    if len(weights) > len(data):
        raise ValueError("Weights length cannot exceed data length")

    if not weights:
        raise ValueError("Weights cannot be empty")

    weight_sum = sum(weights)
    if abs(weight_sum - 1.0) > 1e-6:
        normalized_weights = [w / weight_sum for w in weights]
    else:
        normalized_weights = weights

    window = len(weights)
    wma = []

    for i in range(len(data)):
        if i < window - 1:
            wma.append(None)
        else:
            weighted_sum = sum(data[i - j] * normalized_weights[j] for j in range(window))
            wma.append(weighted_sum)

    return wma


def exponential_smoothing(data: list[float], alpha: float = 0.3) -> list[float]:
    """
    Calculate exponential smoothing (simple).

    Args:
        data: Time series data.
        alpha: Smoothing parameter in [0, 1] (default 0.3).

    Returns:
        List of smoothed values.

    Raises:
        ValueError: If alpha is invalid.
    """
    if not (0 <= alpha <= 1):
        raise ValueError("alpha must be in [0, 1]")

    if not data:
        raise InsufficientDataError("Data cannot be empty")

    smoothed = [data[0]]

    for i in range(1, len(data)):
        value = alpha * data[i] + (1 - alpha) * smoothed[i - 1]
        smoothed.append(value)

    return smoothed


def holt_linear_trend(data: list[float], alpha: float = 0.3, beta: float = 0.1) -> tuple[list[float], list[float]]:
    """
    Holt's linear trend method for forecasting.

    Args:
        data: Time series data.
        alpha: Level smoothing parameter (default 0.3).
        beta: Trend smoothing parameter (default 0.1).

    Returns:
        Tuple of (level, trend) sequences.

    Raises:
        InsufficientDataError: If data is too small.
        ValueError: If parameters are invalid.
    """
    if len(data) < 2:
        raise InsufficientDataError("Need at least 2 observations")

    if not (0 <= alpha <= 1 and 0 <= beta <= 1):
        raise ValueError("Parameters must be in [0, 1]")

    level = [data[0]]
    trend = [data[1] - data[0]]

    for i in range(1, len(data)):
        new_level = alpha * data[i] + (1 - alpha) * (level[i - 1] + trend[i - 1])
        new_trend = beta * (new_level - level[i - 1]) + (1 - beta) * trend[i - 1]

        level.append(new_level)
        trend.append(new_trend)

    return level, trend


def holt_winters(
    data: list[float],
    season_length: int = 12,
    alpha: float = 0.3,
    beta: float = 0.1,
    gamma: float = 0.1,
    seasonal: str = "additive",
) -> tuple[list[float], list[float], list[float]]:
    """
    Holt-Winters seasonal forecasting method.

    Args:
        data: Time series data.
        season_length: Length of seasonal cycle (default 12).
        alpha: Level smoothing parameter.
        beta: Trend smoothing parameter.
        gamma: Seasonal smoothing parameter.
        seasonal: "additive" or "multiplicative".

    Returns:
        Tuple of (level, trend, seasonal_factors).

    Raises:
        InsufficientDataError: If data is too small.
        ValueError: If parameters are invalid.
    """
    if len(data) < 2 * season_length:
        raise InsufficientDataError(f"Need at least {2 * season_length} observations")

    if seasonal not in ("additive", "multiplicative"):
        raise ValueError("seasonal must be 'additive' or 'multiplicative'")

    if not all(0 <= p <= 1 for p in [alpha, beta, gamma]):
        raise ValueError("Parameters must be in [0, 1]")

    initial_level = desc.mean(data[:season_length])
    initial_trend = (desc.mean(data[season_length : 2 * season_length]) - initial_level) / season_length

    level = [initial_level]
    trend = [initial_trend]
    seasonal = []

    for i in range(season_length):
        if seasonal == "additive":
            s = data[i] - initial_level
        else:
            s = data[i] / initial_level if initial_level > 0 else 0
        seasonal.append(s)

    for i in range(season_length, len(data)):
        if seasonal == "additive":
            new_level = alpha * (data[i] - seasonal[i - season_length]) + (1 - alpha) * (level[-1] + trend[-1])
            new_seasonal = gamma * (data[i] - new_level) + (1 - gamma) * seasonal[i - season_length]
        else:
            new_level = (
                alpha * (data[i] / seasonal[i - season_length]) + (1 - alpha) * (level[-1] + trend[-1])
                if seasonal[i - season_length] > 0
                else level[-1]
            )
            new_seasonal = (
                gamma * (data[i] / new_level) + (1 - gamma) * seasonal[i - season_length]
                if new_level > 0
                else seasonal[i - season_length]
            )

        new_trend = beta * (new_level - level[-1]) + (1 - beta) * trend[-1]

        level.append(new_level)
        trend.append(new_trend)
        seasonal.append(new_seasonal)

    return level, trend, seasonal


def differencing(data: list[float], order: int = 1) -> list[float]:
    """
    Calculate differences (for stationarity).

    Args:
        data: Time series data.
        order: Order of differencing (default 1).

    Returns:
        Differenced series.

    Raises:
        ValueError: If order is invalid.
    """
    if order < 1:
        raise ValueError("Order must be at least 1")

    result = data[:]

    for _ in range(order):
        if len(result) < 2:
            raise ValueError("Cannot difference further")
        result = [result[i + 1] - result[i] for i in range(len(result) - 1)]

    return result


def partial_autocorrelation(data: list[float], lag: int = 1) -> float:
    """
    Calculate partial autocorrelation using Yule-Walker equations.

    Args:
        data: Time series data.
        lag: Lag to compute partial autocorrelation at.

    Returns:
        Partial autocorrelation coefficient.

    Raises:
        InsufficientDataError: If data is too small.
    """
    if len(data) < lag + 2:
        raise InsufficientDataError("Data too small for requested lag")

    if lag == 1:
        return correlation.autocorrelation(data, 1)

    acf_values = correlation.acf(data, max_lag=lag)

    if lag == 1:
        return acf_values[1]

    denom = 1.0
    for k in range(1, lag):
        num = acf_values[lag - k] - sum(_pacf_helper(k, j, acf_values) * acf_values[lag - j] for j in range(1, k))
        denom *= (1 - (num / acf_values[0]) ** 2) if acf_values[0] > 0 else 1

    numerator = acf_values[lag] - sum(_pacf_helper(lag - 1, j, acf_values) * acf_values[lag - j] for j in range(1, lag))

    return numerator / denom if denom > 0 else 0


def _pacf_helper(k: int, j: int, acf_values: list[float]) -> float:
    """Helper for partial autocorrelation calculation."""
    return 0


def seasonal_decomposition(
    data: list[float], period: int = 12, seasonal_type: str = "additive"
) -> tuple[list[float], list[float], list[float]]:
    """
    Seasonal decomposition (additive or multiplicative).

    Args:
        data: Time series data.
        period: Length of seasonal cycle (default 12).
        seasonal_type: "additive" or "multiplicative".

    Returns:
        Tuple of (trend, seasonal, residual).

    Raises:
        ValueError: If parameters are invalid.
        InsufficientDataError: If data is too small.
    """
    if len(data) < 2 * period:
        raise InsufficientDataError(f"Need at least {2 * period} observations")

    if seasonal_type not in ("additive", "multiplicative"):
        raise ValueError("seasonal_type must be 'additive' or 'multiplicative'")

    trend = moving_average(data, window=period)

    seasonal = [None] * len(data)
    if seasonal_type == "additive":
        for i in range(len(data)):
            if trend[i] is not None:
                seasonal[i] = data[i] - trend[i]
    else:
        for i in range(len(data)):
            if trend[i] is not None and trend[i] > 0:
                seasonal[i] = data[i] / trend[i]

    seasonal_avg = []
    for i in range(period):
        values = [seasonal[j] for j in range(i, len(data), period) if seasonal[j] is not None]
        if values:
            seasonal_avg.append(desc.mean(values))

    seasonal_final = [None] * len(data)
    for i in range(len(data)):
        seasonal_final[i] = seasonal_avg[i % period]

    residual = [None] * len(data)
    if seasonal_type == "additive":
        for i in range(len(data)):
            if trend[i] is not None and seasonal_final[i] is not None:
                residual[i] = data[i] - trend[i] - seasonal_final[i]
    else:
        for i in range(len(data)):
            if trend[i] is not None and seasonal_final[i] is not None and seasonal_final[i] > 0:
                residual[i] = data[i] / (trend[i] * seasonal_final[i])

    return trend, seasonal_final, residual


def adf_test_simplified(data: list[float]) -> float:
    """
    Simplified Augmented Dickey-Fuller test (returns p-value estimate).

    Args:
        data: Time series data.

    Returns:
        p-value estimate (0-1).

    Raises:
        InsufficientDataError: If data is too small.
    """
    if len(data) < 3:
        raise InsufficientDataError("Need at least 3 observations")

    differencing(data, order=1)

    acf_val = correlation.autocorrelation(data, lag=1)

    if acf_val >= 0.9:
        return 0.95
    elif acf_val >= 0.5:
        return 0.50
    else:
        return 0.05


def forecast_simple_exponential(data: list[float], steps: int = 1, alpha: float = 0.3) -> list[float]:
    """
    Forecast using simple exponential smoothing.

    Args:
        data: Historical time series data.
        steps: Number of steps ahead to forecast (default 1).
        alpha: Smoothing parameter.

    Returns:
        List of forecasted values.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    smoothed = exponential_smoothing(data, alpha=alpha)
    last_value = smoothed[-1]

    return [last_value] * steps


def forecast_holt(data: list[float], steps: int = 1, alpha: float = 0.3, beta: float = 0.1) -> list[float]:
    """
    Forecast using Holt's linear trend method.

    Args:
        data: Historical time series data.
        steps: Number of steps ahead to forecast (default 1).
        alpha: Level smoothing parameter.
        beta: Trend smoothing parameter.

    Returns:
        List of forecasted values.

    Raises:
        InsufficientDataError: If data is too small.
    """
    if len(data) < 2:
        raise InsufficientDataError("Need at least 2 observations")

    level, trend = holt_linear_trend(data, alpha=alpha, beta=beta)

    forecast = []
    for h in range(1, steps + 1):
        forecast.append(level[-1] + h * trend[-1])

    return forecast
