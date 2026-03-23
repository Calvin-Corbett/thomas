"""Portfolio theory and optimization algorithms."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from thomas.marketplace.quantfin._exceptions import PortfolioError


@dataclass
class PortfolioMetrics:
    """Portfolio performance metrics.

    Attributes:
        expected_return: Expected portfolio return
        volatility: Portfolio standard deviation
        sharpe_ratio: Sharpe ratio (return/volatility)
        weights: Asset weights
        beta: Portfolio beta vs benchmark
        alpha: Jensen's alpha vs benchmark
    """

    expected_return: float
    volatility: float
    sharpe_ratio: float
    weights: np.ndarray
    beta: float | None = None
    alpha: float | None = None


@dataclass
class EfficientFrontier:
    """Efficient frontier results.

    Attributes:
        returns: Expected returns for frontier portfolios
        volatilities: Volatilities for frontier portfolios
        weights: Weight arrays for frontier portfolios
        sharpe_ratios: Sharpe ratios for frontier portfolios
    """

    returns: np.ndarray
    volatilities: np.ndarray
    weights: np.ndarray
    sharpe_ratios: np.ndarray


def calculate_expected_return(weights: np.ndarray, mean_returns: np.ndarray) -> float:
    """Calculate portfolio expected return.

    Args:
        weights: Asset weights
        mean_returns: Expected returns for each asset

    Returns:
        Portfolio expected return
    """
    return float(np.dot(weights, mean_returns))


def calculate_portfolio_volatility(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
) -> float:
    """Calculate portfolio volatility (standard deviation).

    Args:
        weights: Asset weights
        cov_matrix: Covariance matrix of returns

    Returns:
        Portfolio volatility
    """
    return float(np.sqrt(np.dot(weights, np.dot(cov_matrix, weights))))


def sharpe_ratio(
    weights: np.ndarray,
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_free_rate: float = 0.02,
) -> float:
    """Calculate portfolio Sharpe ratio.

    Args:
        weights: Asset weights
        mean_returns: Expected returns
        cov_matrix: Covariance matrix
        risk_free_rate: Risk-free rate

    Returns:
        Sharpe ratio
    """
    ret = calculate_expected_return(weights, mean_returns)
    vol = calculate_portfolio_volatility(weights, cov_matrix)

    if vol == 0:
        return 0.0

    return (ret - risk_free_rate) / vol


def minimum_variance_portfolio(
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
) -> PortfolioMetrics:
    """Find minimum variance portfolio.

    Solves: minimize w^T * Cov * w subject to sum(w) = 1, w >= 0

    Args:
        mean_returns: Expected returns for each asset
        cov_matrix: Covariance matrix of returns

    Returns:
        PortfolioMetrics with minimum variance weights
    """
    n_assets = len(mean_returns)

    def objective(w: np.ndarray) -> float:
        return calculate_portfolio_volatility(w, cov_matrix)

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
    bounds = tuple((0, 1) for _ in range(n_assets))
    initial_weights = np.array([1.0 / n_assets] * n_assets)

    result = minimize(
        objective,
        initial_weights,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not result.success:
        raise PortfolioError("Minimum variance optimization failed")

    weights = result.x
    expected_return = calculate_expected_return(weights, mean_returns)
    volatility = calculate_portfolio_volatility(weights, cov_matrix)
    sharpe = sharpe_ratio(weights, mean_returns, cov_matrix)

    return PortfolioMetrics(
        expected_return=expected_return,
        volatility=volatility,
        sharpe_ratio=sharpe,
        weights=weights,
    )


def maximum_sharpe_portfolio(
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_free_rate: float = 0.02,
) -> PortfolioMetrics:
    """Find portfolio with maximum Sharpe ratio.

    Solves: maximize (w^T*r - rf) / sqrt(w^T*Cov*w) subject to sum(w) = 1, w >= 0

    Args:
        mean_returns: Expected returns
        cov_matrix: Covariance matrix
        risk_free_rate: Risk-free rate

    Returns:
        PortfolioMetrics with maximum Sharpe weights
    """
    n_assets = len(mean_returns)

    def negative_sharpe(w: np.ndarray) -> float:
        return -sharpe_ratio(w, mean_returns, cov_matrix, risk_free_rate)

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
    bounds = tuple((0, 1) for _ in range(n_assets))
    initial_weights = np.array([1.0 / n_assets] * n_assets)

    result = minimize(
        negative_sharpe,
        initial_weights,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not result.success:
        raise PortfolioError("Maximum Sharpe optimization failed")

    weights = result.x
    expected_return = calculate_expected_return(weights, mean_returns)
    volatility = calculate_portfolio_volatility(weights, cov_matrix)
    sharpe = sharpe_ratio(weights, mean_returns, cov_matrix, risk_free_rate)

    return PortfolioMetrics(
        expected_return=expected_return,
        volatility=volatility,
        sharpe_ratio=sharpe,
        weights=weights,
    )


def efficient_frontier(
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    num_portfolios: int = 100,
    risk_free_rate: float = 0.02,
) -> EfficientFrontier:
    """Generate efficient frontier via random sampling.

    Creates portfolios spanning the risk-return spectrum by sampling
    random weight combinations and keeping the efficient ones.

    Args:
        mean_returns: Expected returns
        cov_matrix: Covariance matrix
        num_portfolios: Number of portfolios to generate
        risk_free_rate: Risk-free rate

    Returns:
        EfficientFrontier with efficient portfolio points
    """
    n_assets = len(mean_returns)
    results_returns = []
    results_vols = []
    results_weights = []
    results_sharpe = []

    # Generate random portfolios
    for _ in range(num_portfolios * 10):  # Generate more to select efficient ones
        weights = np.random.dirichlet(np.ones(n_assets))
        ret = calculate_expected_return(weights, mean_returns)
        vol = calculate_portfolio_volatility(weights, cov_matrix)
        sh = sharpe_ratio(weights, mean_returns, cov_matrix, risk_free_rate)

        results_returns.append(ret)
        results_vols.append(vol)
        results_weights.append(weights)
        results_sharpe.append(sh)

    # Find efficient portfolios (Pareto frontier)
    returns = np.array(results_returns)
    vols = np.array(results_vols)
    sharpes = np.array(results_sharpe)
    weights = np.array(results_weights)

    # Sort by return and filter dominated portfolios
    sorted_idx = np.argsort(returns)
    efficient_idx = [sorted_idx[0]]
    max_sharpe = sharpes[sorted_idx[0]]

    for idx in sorted_idx[1:]:
        if sharpes[idx] >= max_sharpe:
            efficient_idx.append(idx)
            max_sharpe = sharpes[idx]

    efficient_idx = efficient_idx[:num_portfolios]

    return EfficientFrontier(
        returns=returns[efficient_idx],
        volatilities=vols[efficient_idx],
        weights=weights[efficient_idx],
        sharpe_ratios=sharpes[efficient_idx],
    )


def calculate_beta(
    asset_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """Calculate asset beta relative to benchmark.

    Beta = Cov(asset, benchmark) / Var(benchmark)

    Args:
        asset_returns: Asset return series
        benchmark_returns: Benchmark return series

    Returns:
        Beta coefficient
    """
    covariance = np.cov(asset_returns, benchmark_returns)[0, 1]
    benchmark_variance = np.var(benchmark_returns)

    if benchmark_variance == 0:
        return 0.0

    return covariance / benchmark_variance


def calculate_alpha(
    asset_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    risk_free_rate: float = 0.02,
) -> float:
    """Calculate Jensen's alpha.

    Alpha = asset_return - (rf + beta*(benchmark_return - rf))

    Args:
        asset_returns: Asset return series
        benchmark_returns: Benchmark return series
        risk_free_rate: Risk-free rate

    Returns:
        Jensen's alpha
    """
    asset_return = np.mean(asset_returns)
    benchmark_return = np.mean(benchmark_returns)
    beta = calculate_beta(asset_returns, benchmark_returns)

    alpha = asset_return - (risk_free_rate + beta * (benchmark_return - risk_free_rate))
    return alpha


def portfolio_rebalance_threshold(
    current_weights: np.ndarray,
    target_weights: np.ndarray,
    threshold: float = 0.05,
) -> bool:
    """Check if portfolio needs rebalancing based on threshold.

    Args:
        current_weights: Current portfolio weights
        target_weights: Target portfolio weights
        threshold: Rebalancing threshold (default: 5%)

    Returns:
        True if any weight drifted beyond threshold
    """
    weight_drift = np.abs(current_weights - target_weights)
    return np.any(weight_drift > threshold)


def herfindahl_index(weights: np.ndarray) -> float:
    """Calculate Herfindahl-Hirschman Index (HHI).

    HHI = sum(w_i^2). Ranges from 1/n (perfectly diversified) to 1 (concentrated).

    Args:
        weights: Portfolio weights

    Returns:
        HHI value
    """
    return float(np.sum(weights**2))


def effective_number_of_bets(weights: np.ndarray) -> float:
    """Calculate effective number of bets (diversification ratio).

    ENB = 1 / HHI, ranges from 1 (concentrated) to n (perfectly diversified).

    Args:
        weights: Portfolio weights

    Returns:
        Effective number of bets
    """
    hhi = herfindahl_index(weights)
    if hhi == 0:
        return float(len(weights))
    return 1.0 / hhi


def diversification_ratio(
    weights: np.ndarray,
    volatilities: np.ndarray,
    cov_matrix: np.ndarray,
) -> float:
    """Calculate diversification ratio.

    DR = sum(w_i * vol_i) / portfolio_volatility
    Higher values indicate better diversification.

    Args:
        weights: Portfolio weights
        volatilities: Asset volatilities
        cov_matrix: Covariance matrix

    Returns:
        Diversification ratio
    """
    weighted_vol_sum = np.dot(weights, volatilities)
    portfolio_vol = calculate_portfolio_volatility(weights, cov_matrix)

    if portfolio_vol == 0:
        return 0.0

    return weighted_vol_sum / portfolio_vol


def risk_contribution(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
) -> np.ndarray:
    """Calculate risk contribution of each asset.

    Marginal risk contribution * weight = component risk contribution.

    Args:
        weights: Portfolio weights
        cov_matrix: Covariance matrix

    Returns:
        Risk contribution for each asset
    """
    portfolio_vol = calculate_portfolio_volatility(weights, cov_matrix)

    if portfolio_vol == 0:
        return np.zeros_like(weights)

    marginal_contrib = np.dot(cov_matrix, weights) / portfolio_vol
    return weights * marginal_contrib
