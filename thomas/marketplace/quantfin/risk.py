"""Risk management and measurement algorithms."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from thomas.marketplace.quantfin._exceptions import RiskError


@dataclass
class VaRResults:
    """Value at Risk calculation results.

    Attributes:
        var_value: VaR at specified confidence level
        cvar_value: Conditional VaR (Expected Shortfall)
        method: Calculation method used
        confidence_level: Confidence level (%)
        holding_period: Holding period in days
    """

    var_value: float
    cvar_value: float
    method: str
    confidence_level: float
    holding_period: int = 1


@dataclass
class RiskDecomposition:
    """Risk decomposition results.

    Attributes:
        marginal_var: Marginal VaR contributions
        component_var: Component VaR contributions
        percent_contribution: Percentage contribution to portfolio VaR
    """

    marginal_var: np.ndarray
    component_var: np.ndarray
    percent_contribution: np.ndarray


def historical_var(
    returns: np.ndarray,
    confidence_level: float = 0.95,
) -> float:
    """Calculate Value at Risk using historical method.

    Args:
        returns: Historical return series
        confidence_level: Confidence level (default: 0.95 = 95%)

    Returns:
        VaR (as positive loss value)

    Raises:
        RiskError: If inputs are invalid
    """
    if len(returns) < 10:
        raise RiskError("Need at least 10 return observations")

    if not (0 < confidence_level < 1):
        raise RiskError("Confidence level must be between 0 and 1")

    percentile = (1 - confidence_level) * 100
    var = np.percentile(returns, percentile)

    return float(-var)  # Return as positive loss


def parametric_var(
    mean_return: float,
    volatility: float,
    confidence_level: float = 0.95,
    holding_period: int = 1,
) -> float:
    """Calculate VaR using parametric (normal distribution) method.

    Assumes returns are normally distributed.

    Args:
        mean_return: Mean return
        volatility: Return volatility (standard deviation)
        confidence_level: Confidence level (default: 0.95)
        holding_period: Holding period in days (default: 1)

    Returns:
        VaR as positive loss value
    """
    if volatility <= 0:
        raise RiskError("Volatility must be positive")

    z_score = norm.ppf(1 - confidence_level)
    holding_period_vol = volatility * np.sqrt(holding_period)

    var = mean_return * holding_period + z_score * holding_period_vol

    return float(-var)


def monte_carlo_var(
    mean_return: float,
    volatility: float,
    confidence_level: float = 0.95,
    simulations: int = 10000,
    holding_period: int = 1,
) -> float:
    """Calculate VaR using Monte Carlo simulation.

    Args:
        mean_return: Mean return
        volatility: Volatility
        confidence_level: Confidence level
        simulations: Number of simulations
        holding_period: Holding period in days

    Returns:
        VaR as positive loss value
    """
    if volatility <= 0:
        raise RiskError("Volatility must be positive")

    # Generate random returns
    Z = np.random.standard_normal(simulations)
    future_returns = mean_return * holding_period + volatility * np.sqrt(holding_period) * Z

    percentile = (1 - confidence_level) * 100
    var = np.percentile(future_returns, percentile)

    return float(-var)


def conditional_var(
    returns: np.ndarray,
    confidence_level: float = 0.95,
) -> float:
    """Calculate Conditional VaR (Expected Shortfall).

    CVaR = expected loss given that loss exceeds VaR.

    Args:
        returns: Return series
        confidence_level: Confidence level

    Returns:
        CVaR (as positive loss value)
    """
    if len(returns) < 10:
        raise RiskError("Need at least 10 return observations")

    var = historical_var(returns, confidence_level)
    # Tail beyond VaR
    tail_returns = returns[returns <= -var]

    if len(tail_returns) == 0:
        return float(var)

    cvar = float(np.mean(tail_returns) * -1)
    return cvar


def calculate_drawdown(prices: np.ndarray) -> tuple[np.ndarray, float]:
    """Calculate running drawdown from price series.

    Args:
        prices: Price time series

    Returns:
        Tuple of (drawdown array, maximum drawdown)
    """
    cumulative_max = np.maximum.accumulate(prices)
    drawdown = (prices - cumulative_max) / cumulative_max

    max_drawdown = float(np.min(drawdown))

    return drawdown, max_drawdown


def sortino_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.02,
    target_return: float | None = None,
) -> float:
    """Calculate Sortino ratio (downside risk adjusted return).

    Args:
        returns: Return series
        risk_free_rate: Risk-free rate (default: 0.02)
        target_return: Target return (default: risk-free rate)

    Returns:
        Sortino ratio
    """
    if target_return is None:
        target_return = risk_free_rate

    excess_returns = returns - target_return
    downside_returns = excess_returns[excess_returns < 0]

    if len(downside_returns) == 0:
        return float("inf")

    downside_deviation = np.sqrt(np.mean(downside_returns**2))

    if downside_deviation == 0:
        return 0.0

    mean_return = np.mean(returns)
    sortino = (mean_return - risk_free_rate) / downside_deviation

    return float(sortino)


def calmar_ratio(
    returns: np.ndarray,
    prices: np.ndarray | None = None,
) -> float:
    """Calculate Calmar ratio (return over max drawdown).

    Args:
        returns: Return series
        prices: Price series (if None, calculated from returns)

    Returns:
        Calmar ratio
    """
    if prices is None:
        prices = np.cumprod(1 + returns)

    annual_return = np.mean(returns) * 252

    _, max_dd = calculate_drawdown(prices)

    if max_dd == 0:
        return 0.0

    calmar = annual_return / abs(max_dd)
    return float(calmar)


def information_ratio(
    returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """Calculate information ratio (active return/tracking error).

    Args:
        returns: Portfolio return series
        benchmark_returns: Benchmark return series

    Returns:
        Information ratio
    """
    if len(returns) != len(benchmark_returns):
        raise RiskError("Return series must be same length")

    active_returns = returns - benchmark_returns
    mean_active = np.mean(active_returns)
    tracking_error = np.std(active_returns)

    if tracking_error == 0:
        return 0.0

    ir = mean_active / tracking_error
    return float(ir)


def tracking_error(
    returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """Calculate tracking error (std dev of active returns).

    Args:
        returns: Portfolio returns
        benchmark_returns: Benchmark returns

    Returns:
        Tracking error
    """
    if len(returns) != len(benchmark_returns):
        raise RiskError("Return series must be same length")

    active_returns = returns - benchmark_returns
    return float(np.std(active_returns))


def stress_test(
    returns: np.ndarray,
    historical_scenarios: np.ndarray,
    portfolio_values: np.ndarray,
) -> np.ndarray:
    """Apply historical stress scenarios to portfolio.

    Args:
        returns: Historical market returns
        historical_scenarios: Return scenarios to apply
        portfolio_values: Current portfolio values

    Returns:
        Portfolio values under each scenario
    """
    scenario_results = []

    for scenario_return in historical_scenarios:
        # Apply scenario returns to positions
        stressed_pnl = portfolio_values * scenario_return
        scenario_results.append(np.sum(stressed_pnl))

    return np.array(scenario_results)


def exponential_weighted_cov(
    returns: np.ndarray,
    lambda_param: float = 0.94,
) -> np.ndarray:
    """Calculate exponential weighted covariance matrix.

    Gives more weight to recent observations.

    Args:
        returns: Return matrix (observations x assets)
        lambda_param: Decay factor (default: 0.94)

    Returns:
        Exponential weighted covariance matrix
    """
    if returns.ndim == 1:
        returns = returns.reshape(-1, 1)

    n_obs, n_assets = returns.shape
    mean_return = np.mean(returns, axis=0)
    centered = returns - mean_return

    weights = np.array([(1 - lambda_param) * lambda_param**i for i in range(n_obs)])
    weights = weights / np.sum(weights)

    cov = np.zeros((n_assets, n_assets))
    for i in range(n_obs):
        cov += weights[i] * np.outer(centered[i], centered[i])

    return cov


def correlation_matrix(returns: np.ndarray) -> np.ndarray:
    """Calculate correlation matrix from returns.

    Args:
        returns: Return matrix

    Returns:
        Correlation matrix
    """
    return np.corrcoef(returns.T)


def portfolio_var_decomposition(
    returns: np.ndarray,
    weights: np.ndarray,
    confidence_level: float = 0.95,
) -> RiskDecomposition:
    """Decompose portfolio VaR into marginal and component contributions.

    Args:
        returns: Return matrix (observations x assets)
        weights: Portfolio weights
        confidence_level: Confidence level

    Returns:
        RiskDecomposition with marginal and component VaR
    """
    if returns.ndim == 1:
        returns = returns.reshape(-1, 1)

    portfolio_return = np.dot(returns, weights)
    portfolio_var = historical_var(portfolio_return, confidence_level)

    cov_matrix = np.cov(returns.T)
    std_devs = np.std(returns, axis=0)

    # Marginal VaR approximation
    marginal_var = np.zeros(len(weights))
    for i in range(len(weights)):
        # Approximate marginal by removing asset and recalculating
        weights_copy = weights.copy()
        weights_copy[i] = 0
        if np.sum(weights_copy) > 0:
            weights_copy /= np.sum(weights_copy)
            modified_return = np.dot(returns, weights_copy)
            modified_var = historical_var(modified_return, confidence_level)
            marginal_var[i] = (portfolio_var - modified_var) / weights[i] if weights[i] > 0 else 0

    # Component VaR = marginal VaR * weight
    component_var = marginal_var * weights
    total_var = np.sum(component_var)

    percent_contrib = component_var / total_var if total_var > 0 else np.zeros_like(component_var)

    return RiskDecomposition(
        marginal_var=marginal_var,
        component_var=component_var,
        percent_contribution=percent_contrib,
    )
