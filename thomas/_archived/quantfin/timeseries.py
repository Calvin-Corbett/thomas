"""Financial time series analysis and modeling."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from thomas.quantfin._exceptions import TimeSeriesError


@dataclass
class AugmentedDickeyFullerResult:
    """Augmented Dickey-Fuller test result.

    Attributes:
        test_statistic: ADF test statistic
        p_value: P-value for test
        n_lags: Number of lags used
        critical_values: Critical values at 1%, 5%, 10%
        is_stationary: True if series appears stationary at 5% level
    """

    test_statistic: float
    p_value: float
    n_lags: int
    critical_values: dict
    is_stationary: bool


@dataclass
class GARCHResult:
    """GARCH(1,1) volatility estimation result.

    Attributes:
        volatility: Conditional volatility series
        omega: Constant term
        alpha: GARCH parameter (recent shocks)
        beta: GARCH parameter (recent variance)
    """

    volatility: np.ndarray
    omega: float
    alpha: float
    beta: float


def simple_returns(prices: np.ndarray) -> np.ndarray:
    """Calculate simple returns from price series.

    Returns = (P_t - P_{t-1}) / P_{t-1}

    Args:
        prices: Price array

    Returns:
        Simple returns array
    """
    if len(prices) < 2:
        raise TimeSeriesError("Need at least 2 prices")

    return np.diff(prices) / prices[:-1]


def log_returns(prices: np.ndarray) -> np.ndarray:
    """Calculate log returns from price series.

    Returns = ln(P_t / P_{t-1})

    Args:
        prices: Price array

    Returns:
        Log returns array
    """
    if len(prices) < 2:
        raise TimeSeriesError("Need at least 2 prices")

    return np.diff(np.log(prices))


def historical_volatility(
    returns: np.ndarray,
    periods: int = 252,
) -> float:
    """Calculate historical volatility (annualized).

    Args:
        returns: Return series
        periods: Periods per year (default: 252 for daily)

    Returns:
        Annualized volatility
    """
    if len(returns) < 2:
        raise TimeSeriesError("Need at least 2 returns")

    return float(np.std(returns) * np.sqrt(periods))


def ewma_volatility(
    returns: np.ndarray,
    lambda_param: float = 0.94,
    periods: int = 252,
) -> tuple[float, np.ndarray]:
    """Calculate exponential weighted moving average volatility.

    Args:
        returns: Return series
        lambda_param: Decay factor (default: 0.94)
        periods: Periods per year

    Returns:
        Tuple of (current volatility, volatility series)
    """
    if len(returns) < 1:
        raise TimeSeriesError("Need at least 1 return")

    variance = returns[0] ** 2
    variances = [variance]

    for ret in returns[1:]:
        variance = lambda_param * variance + (1 - lambda_param) * ret**2
        variances.append(variance)

    volatility_series = np.sqrt(np.array(variances)) * np.sqrt(periods)
    current_vol = float(volatility_series[-1])

    return current_vol, volatility_series


def garch_11(
    returns: np.ndarray,
    max_iterations: int = 1000,
    tolerance: float = 1e-6,
) -> GARCHResult:
    """Estimate GARCH(1,1) model for volatility.

    GARCH(1,1): σ_t^2 = ω + α*ε_{t-1}^2 + β*σ_{t-1}^2

    Args:
        returns: Return series
        max_iterations: Maximum iterations for optimization
        tolerance: Convergence tolerance

    Returns:
        GARCHResult with estimated parameters and volatility series
    """
    if len(returns) < 10:
        raise TimeSeriesError("Need at least 10 returns for GARCH estimation")

    # Initialize parameters
    mean_return = np.mean(returns)
    centered = returns - mean_return
    variance = np.var(centered)

    omega = 0.001 * variance
    alpha = 0.1
    beta = 0.8

    # EM-like iteration
    for iteration in range(max_iterations):
        # Forward pass: calculate conditional variance
        sigma2 = np.zeros(len(returns))
        sigma2[0] = variance

        for t in range(1, len(returns)):
            sigma2[t] = omega + alpha * centered[t - 1] ** 2 + beta * sigma2[t - 1]

        # Gradient step (simplified)
        gradient_omega = np.sum(1.0 / sigma2 - centered**2 / sigma2**2)
        gradient_alpha = np.sum(centered**2 / sigma2**2 - centered[:-1] ** 2 / sigma2[1:] ** 2)
        gradient_beta = np.sum(sigma2[:-1] / sigma2[1:] ** 2 - 1.0 / sigma2[1:])

        # Update with small step size
        step_size = 0.001
        omega_new = max(omega + step_size * gradient_omega, 1e-6)
        alpha_new = max(min(alpha + step_size * gradient_alpha, 0.99), 0.01)
        beta_new = max(min(beta + step_size * gradient_beta, 0.99), 0.0)

        # Check convergence
        if (
            abs(omega_new - omega) < tolerance
            and abs(alpha_new - alpha) < tolerance
            and abs(beta_new - beta) < tolerance
        ):
            break

        omega, alpha, beta = omega_new, alpha_new, beta_new

    # Final variance calculation
    sigma2 = np.zeros(len(returns))
    sigma2[0] = variance

    for t in range(1, len(returns)):
        sigma2[t] = omega + alpha * centered[t - 1] ** 2 + beta * sigma2[t - 1]

    return GARCHResult(
        volatility=np.sqrt(sigma2) * np.sqrt(252),
        omega=omega,
        alpha=alpha,
        beta=beta,
    )


def autocorrelation(
    returns: np.ndarray,
    max_lags: int = 20,
) -> np.ndarray:
    """Calculate autocorrelation function.

    Args:
        returns: Return series
        max_lags: Maximum lags to calculate (default: 20)

    Returns:
        Autocorrelation array
    """
    if len(returns) < max_lags:
        raise TimeSeriesError("Series too short for autocorrelation calculation")

    mean = np.mean(returns)
    c0 = np.sum((returns - mean) ** 2) / len(returns)

    acf = np.ones(max_lags + 1)
    for k in range(1, max_lags + 1):
        c_k = np.sum((returns[:-k] - mean) * (returns[k:] - mean)) / len(returns)
        acf[k] = c_k / c0

    return acf


def augmented_dickey_fuller(
    series: np.ndarray,
    max_lags: int | None = None,
) -> AugmentedDickeyFullerResult:
    """Augmented Dickey-Fuller stationarity test.

    Tests null hypothesis: series has unit root (non-stationary).

    Args:
        series: Time series data
        max_lags: Maximum lags to use (default: auto)

    Returns:
        AugmentedDickeyFullerResult with test statistic and p-value
    """
    if len(series) < 10:
        raise TimeSeriesError("Series too short for ADF test")

    if max_lags is None:
        max_lags = int(np.ceil(np.sqrt(len(series))))

    # Difference series
    y = np.diff(series)
    n = len(y)

    # Build regression: Δy_t = α + γ*y_{t-1} + Σ β_k*Δy_{t-k} + ε_t
    X = np.column_stack([np.ones(n - max_lags)])

    # Add lagged level
    X = np.column_stack([X, series[max_lags - 1 : -1]])

    # Add lagged differences
    for k in range(1, max_lags + 1):
        if n - k > max_lags:
            X = np.column_stack([X, y[max_lags - k : -k]])

    y_reg = y[max_lags:]

    # OLS regression
    try:
        coeffs = np.linalg.lstsq(X, y_reg, rcond=None)[0]
        residuals = y_reg - X @ coeffs

        # Test statistic for lagged level coefficient (index 1)
        mse = np.sum(residuals**2) / (len(y_reg) - X.shape[1])
        var_coeff = mse * np.linalg.inv(X.T @ X)[1, 1]
        test_stat = coeffs[1] / np.sqrt(var_coeff)

        # Critical values (MacKinnon)
        critical_1pct = -3.43
        critical_5pct = -2.86
        critical_10pct = -2.57

        # Simple p-value approximation
        if test_stat < critical_1pct:
            p_value = 0.01
        elif test_stat < critical_5pct:
            p_value = 0.05
        elif test_stat < critical_10pct:
            p_value = 0.10
        else:
            p_value = 0.90

        is_stationary = p_value < 0.05

        return AugmentedDickeyFullerResult(
            test_statistic=test_stat,
            p_value=p_value,
            n_lags=max_lags,
            critical_values={
                "1%": critical_1pct,
                "5%": critical_5pct,
                "10%": critical_10pct,
            },
            is_stationary=is_stationary,
        )
    except np.linalg.LinAlgError:
        raise TimeSeriesError("ADF test regression failed")


def cointegration_test(
    series1: np.ndarray,
    series2: np.ndarray,
) -> tuple[float, float]:
    """Engle-Granger cointegration test.

    Tests if two non-stationary series are cointegrated.

    Args:
        series1: First series
        series2: Second series

    Returns:
        Tuple of (test_statistic, p_value)
    """
    if len(series1) != len(series2):
        raise TimeSeriesError("Series must be same length")

    if len(series1) < 10:
        raise TimeSeriesError("Series too short for cointegration test")

    # Estimate cointegrating relationship: y1 = a + b*y2 + e
    X = np.column_stack([np.ones(len(series2)), series2])
    coeffs = np.linalg.lstsq(X, series1, rcond=None)[0]

    # Residuals (stationary if cointegrated)
    residuals = series1 - X @ coeffs

    # ADF test on residuals
    adf_result = augmented_dickey_fuller(residuals)

    return adf_result.test_statistic, adf_result.p_value


def rolling_volatility(
    returns: np.ndarray,
    window: int = 20,
    periods: int = 252,
) -> np.ndarray:
    """Calculate rolling volatility.

    Args:
        returns: Return series
        window: Rolling window size (default: 20)
        periods: Periods per year

    Returns:
        Rolling volatility series
    """
    if len(returns) < window:
        raise TimeSeriesError("Series shorter than window")

    vol = np.zeros(len(returns) - window + 1)
    for i in range(len(vol)):
        vol[i] = np.std(returns[i : i + window]) * np.sqrt(periods)

    return vol


def rolling_correlation(
    returns1: np.ndarray,
    returns2: np.ndarray,
    window: int = 20,
) -> np.ndarray:
    """Calculate rolling correlation.

    Args:
        returns1: First return series
        returns2: Second return series
        window: Rolling window size

    Returns:
        Rolling correlation series
    """
    if len(returns1) != len(returns2):
        raise TimeSeriesError("Series must be same length")

    if len(returns1) < window:
        raise TimeSeriesError("Series shorter than window")

    corr = np.zeros(len(returns1) - window + 1)
    for i in range(len(corr)):
        corr[i] = np.corrcoef(returns1[i : i + window], returns2[i : i + window])[0, 1]

    return corr


def hidden_markov_regime(
    returns: np.ndarray,
    n_regimes: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Detect market regimes using Hidden Markov Model.

    Simple 2-regime model: bull (high mean, low vol) and bear (low mean, high vol).

    Args:
        returns: Return series
        n_regimes: Number of regimes (default: 2)

    Returns:
        Tuple of (regime_sequence, probabilities)
    """
    if len(returns) < 20:
        raise TimeSeriesError("Series too short for regime detection")

    if n_regimes != 2:
        raise TimeSeriesError("Only 2-regime model implemented")

    # Initialize parameters
    mean_bull = np.percentile(returns, 75)
    mean_bear = np.percentile(returns, 25)
    vol_bull = np.std(returns[returns > mean_bull])
    vol_bear = np.std(returns[returns < mean_bear])

    # Transition matrix (sticky regimes)
    p_bb = 0.95  # probability bull -> bull
    p_hh = 0.95  # probability bear -> bear

    # Viterbi algorithm
    states = np.zeros(len(returns), dtype=int)
    prob_bull = np.zeros(len(returns))
    prob_bear = np.zeros(len(returns))

    # Forward pass
    for t in range(len(returns)):
        likelihood_bull = norm.pdf(returns[t], mean_bull, vol_bull)
        likelihood_bear = norm.pdf(returns[t], mean_bear, vol_bear)

        if t == 0:
            prob_bull[t] = 0.5 * likelihood_bull
            prob_bear[t] = 0.5 * likelihood_bear
        else:
            prob_bull[t] = likelihood_bull * (p_bb * prob_bull[t - 1] + (1 - p_hh) * prob_bear[t - 1])
            prob_bear[t] = likelihood_bear * ((1 - p_bb) * prob_bull[t - 1] + p_hh * prob_bear[t - 1])

    # Backward pass to get states
    for t in range(len(returns) - 1, -1, -1):
        if prob_bull[t] > prob_bear[t]:
            states[t] = 0  # Bull regime
        else:
            states[t] = 1  # Bear regime

    # Normalize probabilities
    total = prob_bull + prob_bear
    prob_bull = prob_bull / (total + 1e-8)
    prob_bear = prob_bear / (total + 1e-8)

    probabilities = np.column_stack([prob_bull, prob_bear])

    return states, probabilities


def seasonal_decompose(
    series: np.ndarray,
    period: int = 252,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simple seasonal decomposition of time series.

    Returns trend, seasonal, and residual components.

    Args:
        series: Time series
        period: Seasonal period (default: 252 for daily data = 1 year)

    Returns:
        Tuple of (trend, seasonal, residual)
    """
    if len(series) < 2 * period:
        raise TimeSeriesError("Series too short for decomposition")

    # Trend: centered moving average
    trend = np.zeros(len(series))
    for i in range(period // 2, len(series) - period // 2):
        trend[i] = np.mean(series[i - period // 2 : i + period // 2])

    # Pad trend
    trend[: period // 2] = trend[period // 2]
    trend[-period // 2 :] = trend[-period // 2 - 1]

    # Detrended series
    detrended = series - trend

    # Seasonal: average by season
    seasonal = np.zeros(len(series))
    for i in range(period):
        indices = np.arange(i, len(series), period)
        if len(indices) > 0:
            seasonal_value = np.mean(detrended[indices])
            seasonal[indices] = seasonal_value

    # Residual
    residual = series - trend - seasonal

    return trend, seasonal, residual
