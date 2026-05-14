"""Nonparametric statistical methods."""

import math
import random
from collections.abc import Callable

from . import descriptive as desc
from ._exceptions import InsufficientDataError
from ._types import ConfidenceInterval


def kernel_density_estimation(
    data: list[float], x: float, bandwidth: float | None = None, kernel: str = "gaussian"
) -> float:
    """
    Kernel density estimation at a point using Gaussian kernel.

    Args:
        data: Sample data.
        x: Point to evaluate density at.
        bandwidth: Bandwidth for kernel (default: Silverman's rule).
        kernel: Type of kernel ("gaussian" or "uniform").

    Returns:
        Estimated density at x.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If kernel type is invalid.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    if kernel not in ("gaussian", "uniform"):
        raise ValueError("kernel must be 'gaussian' or 'uniform'")

    if bandwidth is None:
        bandwidth = silverman_bandwidth(data)

    if bandwidth <= 0:
        raise ValueError("Bandwidth must be positive")

    n = len(data)
    density = 0

    if kernel == "gaussian":
        for xi in data:
            z = (x - xi) / bandwidth
            density += math.exp(-0.5 * z**2)
        density /= n * bandwidth * math.sqrt(2 * math.pi)
    else:
        for xi in data:
            if abs(x - xi) <= bandwidth / 2:
                density += 1
        density /= n * bandwidth

    return density


def silverman_bandwidth(data: list[float]) -> float:
    """
    Calculate bandwidth using Silverman's rule of thumb.

    Args:
        data: Sample data.

    Returns:
        Suggested bandwidth.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    n = len(data)
    std = desc.std(data, sample=True)
    iqr_val = desc.iqr(data)

    if iqr_val > 0:
        sigma = iqr_val / 1.35
    else:
        sigma = std

    return 1.06 * sigma * (n ** (-1 / 5))


def bootstrap_confidence_interval(
    data: list[float], statistic: Callable[[list[float]], float], level: float = 0.95, samples: int = 1000
) -> ConfidenceInterval:
    """
    Calculate confidence interval using percentile bootstrap.

    Args:
        data: Original sample.
        statistic: Function that computes statistic from data.
        level: Confidence level (default 0.95).
        samples: Number of bootstrap samples (default 1000).

    Returns:
        ConfidenceInterval from bootstrap percentiles.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If level is invalid.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    if not (0 < level < 1):
        raise ValueError("Level must be in (0, 1)")

    bootstrap_stats = []

    for _ in range(samples):
        bootstrap_sample = [random.choice(data) for _ in range(len(data))]
        bootstrap_stats.append(statistic(bootstrap_sample))

    sorted_stats = sorted(bootstrap_stats)
    lower_idx = int((1 - level) / 2 * samples)
    upper_idx = int((1 + level) / 2 * samples)

    lower = sorted_stats[max(0, lower_idx)]
    upper = sorted_stats[min(len(sorted_stats) - 1, upper_idx)]

    return ConfidenceInterval(lower=lower, upper=upper, center=statistic(data), level=level)


def bca_confidence_interval(
    data: list[float], statistic: Callable[[list[float]], float], level: float = 0.95, samples: int = 1000
) -> ConfidenceInterval:
    """
    Calculate confidence interval using BCa (bias-corrected, accelerated) bootstrap.

    Args:
        data: Original sample.
        statistic: Function that computes statistic from data.
        level: Confidence level (default 0.95).
        samples: Number of bootstrap samples (default 1000).

    Returns:
        ConfidenceInterval using BCa correction.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If level is invalid.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    if not (0 < level < 1):
        raise ValueError("Level must be in (0, 1)")

    theta_hat = statistic(data)
    bootstrap_stats = []

    for _ in range(samples):
        bootstrap_sample = [random.choice(data) for _ in range(len(data))]
        bootstrap_stats.append(statistic(bootstrap_sample))

    desc.mean(bootstrap_stats)

    z0 = 0
    bootstrap_less = sum(1 for b in bootstrap_stats if b < theta_hat)
    if bootstrap_less > 0 and bootstrap_less < len(bootstrap_stats):
        p_less = bootstrap_less / len(bootstrap_stats)
        from . import distributions as dist

        z0 = dist.normal_icdf(p_less)

    jackknife_stats = []
    for i in range(len(data)):
        jackknife_sample = data[:i] + data[i + 1 :]
        if jackknife_sample:
            jackknife_stats.append(statistic(jackknife_sample))

    jackknife_mean = desc.mean(jackknife_stats) if jackknife_stats else theta_hat
    numerator = sum((jackknife_mean - s) ** 3 for s in jackknife_stats)
    denominator = 6 * (sum((jackknife_mean - s) ** 2 for s in jackknife_stats) ** 1.5)

    acceleration = numerator / denominator if denominator > 0 else 0

    sorted_stats = sorted(bootstrap_stats)

    1 - level
    z_alpha_lower = -1.96
    z_alpha_upper = 1.96

    p_lower = dist._normal_cdf(z0 + (z0 + z_alpha_lower) / (1 - acceleration * (z0 + z_alpha_lower)))
    p_upper = dist._normal_cdf(z0 + (z0 + z_alpha_upper) / (1 - acceleration * (z0 + z_alpha_upper)))

    idx_lower = int(max(0, min(len(sorted_stats) - 1, p_lower * len(sorted_stats))))
    idx_upper = int(max(0, min(len(sorted_stats) - 1, p_upper * len(sorted_stats))))

    lower = sorted_stats[idx_lower]
    upper = sorted_stats[idx_upper]

    return ConfidenceInterval(lower=lower, upper=upper, center=theta_hat, level=level)


def permutation_test(
    data1: list[float],
    data2: list[float],
    statistic: Callable[[list[float], list[float]], float],
    alternative: str = "two-sided",
    samples: int = 1000,
) -> float:
    """
    Permutation test for comparing two samples.

    Args:
        data1: First sample.
        data2: Second sample.
        statistic: Function that computes test statistic from two samples.
        alternative: "two-sided", "greater", or "less".
        samples: Number of permutations (default 1000).

    Returns:
        p-value from permutation test.

    Raises:
        ValueError: If samples are empty or alternative is invalid.
    """
    if not data1 or not data2:
        raise ValueError("Both samples must be non-empty")

    if alternative not in ("two-sided", "greater", "less"):
        raise ValueError("alternative must be 'two-sided', 'greater', or 'less'")

    observed_stat = statistic(data1, data2)
    combined = data1 + data2
    n1 = len(data1)

    count = 0

    for _ in range(samples):
        random.shuffle(combined)
        perm_data1 = combined[:n1]
        perm_data2 = combined[n1:]
        perm_stat = statistic(perm_data1, perm_data2)

        if alternative == "two-sided":
            if abs(perm_stat) >= abs(observed_stat):
                count += 1
        elif alternative == "greater":
            if perm_stat >= observed_stat:
                count += 1
        else:
            if perm_stat <= observed_stat:
                count += 1

    return count / samples


def empirical_cdf(data: list[float]) -> Callable[[float], float]:
    """
    Create empirical CDF function from data.

    Args:
        data: Sample data.

    Returns:
        Function that evaluates empirical CDF at any point.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    sorted_data = sorted(data)
    n = len(sorted_data)

    def ecdf(x: float) -> float:
        """Evaluate empirical CDF at x."""
        count = sum(1 for xi in sorted_data if xi <= x)
        return count / n

    return ecdf


def qq_plot_values(
    data: list[float], theoretical_quantiles: Callable[[float], float]
) -> tuple[list[float], list[float]]:
    """
    Calculate Q-Q plot points for comparison with theoretical distribution.

    Args:
        data: Sample data.
        theoretical_quantiles: Function that returns theoretical quantile at p.

    Returns:
        Tuple of (sample_quantiles, theoretical_quantiles).

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    sorted_data = sorted(data)
    n = len(sorted_data)

    sample_quantiles = sorted_data
    theoretical = []

    for i in range(n):
        p = (i + 1) / (n + 1)
        theoretical.append(theoretical_quantiles(p))

    return sample_quantiles, theoretical


def jackknife_resampling(data: list[float], statistic: Callable[[list[float]], float]) -> tuple[float, float, float]:
    """
    Jackknife resampling for bias and standard error estimation.

    Args:
        data: Sample data.
        statistic: Function that computes statistic from data.

    Returns:
        Tuple of (theta_hat, bias, se) where theta_hat is original estimate,
        bias is estimated bias, and se is standard error.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    theta_hat = statistic(data)
    n = len(data)

    jack_stats = []

    for i in range(n):
        jack_sample = data[:i] + data[i + 1 :]
        jack_stats.append(statistic(jack_sample))

    jack_mean = desc.mean(jack_stats)

    bias = (n - 1) * (jack_mean - theta_hat)

    variance = ((n - 1) / n) * sum((j - jack_mean) ** 2 for j in jack_stats)
    se = math.sqrt(variance) if variance > 0 else 0

    return theta_hat, bias, se
