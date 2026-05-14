"""Correlation analysis methods."""

import math

from . import descriptive as desc
from . import distributions as dist
from ._exceptions import InsufficientDataError
from ._types import CorrelationResult


def pearson_correlation(x: list[float], y: list[float]) -> CorrelationResult:
    """
    Calculate Pearson correlation coefficient with p-value.

    Args:
        x: First variable.
        y: Second variable (must have same length as x).

    Returns:
        CorrelationResult with coefficient, p-value, and sample size.

    Raises:
        ValueError: If x and y have different lengths.
        InsufficientDataError: If data is too small.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")

    if len(x) < 3:
        raise InsufficientDataError("Need at least 3 pairs for correlation")

    n = len(x)
    mean_x = desc.mean(x)
    mean_y = desc.mean(y)

    cov_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (n - 1)
    std_x = desc.std(x, sample=True)
    std_y = desc.std(y, sample=True)

    if std_x == 0 or std_y == 0:
        r = 0
    else:
        r = cov_xy / (std_x * std_y)

    if r >= 1:
        r = 0.99999
    elif r <= -1:
        r = -0.99999

    df = n - 2
    if df > 0 and abs(r) < 1:
        t_stat = r * math.sqrt(df) / math.sqrt(1 - r**2)
        p_value = 2 * (1 - dist.t_cdf(abs(t_stat), df))
    else:
        p_value = 0 if r != 0 else 1

    return CorrelationResult(coefficient=r, p_value=p_value, n=n, method="pearson")


def spearman_correlation(x: list[float], y: list[float]) -> CorrelationResult:
    """
    Calculate Spearman rank correlation coefficient with p-value.

    Args:
        x: First variable.
        y: Second variable (must have same length as x).

    Returns:
        CorrelationResult with coefficient, p-value, and sample size.

    Raises:
        ValueError: If x and y have different lengths.
        InsufficientDataError: If data is too small.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")

    if len(x) < 3:
        raise InsufficientDataError("Need at least 3 pairs for correlation")

    def rank_data(data: list[float]) -> list[float]:
        """Assign ranks to data, handling ties."""
        indexed = [(val, idx) for idx, val in enumerate(data)]
        indexed.sort()

        ranks = [0] * len(data)
        i = 0
        while i < len(indexed):
            j = i
            while j < len(indexed) and indexed[j][0] == indexed[i][0]:
                j += 1
            avg_rank = (i + j + 1) / 2
            for k in range(i, j):
                ranks[indexed[k][1]] = avg_rank
            i = j

        return ranks

    rank_x = rank_data(x)
    rank_y = rank_data(y)

    return pearson_correlation(rank_x, rank_y)


def kendall_tau(x: list[float], y: list[float]) -> CorrelationResult:
    """
    Calculate Kendall's tau correlation coefficient with p-value.

    Args:
        x: First variable.
        y: Second variable (must have same length as x).

    Returns:
        CorrelationResult with coefficient, p-value, and sample size.

    Raises:
        ValueError: If x and y have different lengths.
        InsufficientDataError: If data is too small.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")

    if len(x) < 3:
        raise InsufficientDataError("Need at least 3 pairs for correlation")

    n = len(x)
    pairs = list(zip(x, y))

    concordant = 0
    discordant = 0

    for i in range(n):
        for j in range(i + 1, n):
            x_diff = pairs[i][0] - pairs[j][0]
            y_diff = pairs[i][1] - pairs[j][1]

            if x_diff != 0 and y_diff != 0:
                if (x_diff > 0 and y_diff > 0) or (x_diff < 0 and y_diff < 0):
                    concordant += 1
                else:
                    discordant += 1

    if concordant + discordant == 0:
        tau = 0
    else:
        tau = (concordant - discordant) / (concordant + discordant)

    n * (n - 1) / 2
    var_tau = 2 * (2 * n + 5) / (9 * n * (n - 1))

    if var_tau > 0:
        z_stat = tau / math.sqrt(var_tau)
        p_value = 2 * (1 - dist._normal_cdf(abs(z_stat)))
    else:
        p_value = 0 if tau != 0 else 1

    return CorrelationResult(coefficient=tau, p_value=p_value, n=n, method="kendall")


def point_biserial_correlation(x: list[float], y: list[int]) -> CorrelationResult:
    """
    Calculate point-biserial correlation (continuous vs binary).

    Args:
        x: Continuous variable.
        y: Binary variable (0 or 1).

    Returns:
        CorrelationResult with coefficient, p-value, and sample size.

    Raises:
        ValueError: If x and y have different lengths.
        InsufficientDataError: If data is too small.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")

    if len(x) < 3:
        raise InsufficientDataError("Need at least 3 pairs for correlation")

    if not all(yi in (0, 1) for yi in y):
        raise ValueError("y must contain only 0 and 1 values")

    x0 = [xi for xi, yi in zip(x, y) if yi == 0]
    x1 = [xi for xi, yi in zip(x, y) if yi == 1]

    if not x0 or not x1:
        return CorrelationResult(coefficient=0, p_value=1, n=len(x), method="point_biserial")

    mean_x0 = desc.mean(x0)
    mean_x1 = desc.mean(x1)
    std_x = desc.std(x, sample=True)

    n = len(x)
    n0 = len(x0)
    n1 = len(x1)

    if std_x == 0:
        r = 0
    else:
        r = (mean_x1 - mean_x0) * math.sqrt(n0 * n1) / (std_x * n)

    df = n - 2
    if df > 0 and abs(r) < 1:
        t_stat = r * math.sqrt(df) / math.sqrt(1 - r**2)
        p_value = 2 * (1 - dist.t_cdf(abs(t_stat), df))
    else:
        p_value = 0 if r != 0 else 1

    return CorrelationResult(coefficient=r, p_value=p_value, n=n, method="point_biserial")


def partial_correlation(x: list[float], y: list[float], z: list[float]) -> CorrelationResult:
    """
    Calculate partial correlation between x and y, controlling for z.

    Args:
        x: First variable.
        y: Second variable.
        z: Control variable.

    Returns:
        CorrelationResult with partial correlation coefficient and p-value.

    Raises:
        ValueError: If variables have different lengths.
        InsufficientDataError: If data is too small.
    """
    if not (len(x) == len(y) == len(z)):
        raise ValueError("All variables must have the same length")

    if len(x) < 4:
        raise InsufficientDataError("Need at least 4 observations for partial correlation")

    rxy = pearson_correlation(x, y).coefficient
    rxz = pearson_correlation(x, z).coefficient
    ryz = pearson_correlation(y, z).coefficient

    numerator = rxy - rxz * ryz
    denominator = math.sqrt((1 - rxz**2) * (1 - ryz**2))

    if denominator == 0:
        r_partial = 0
    else:
        r_partial = numerator / denominator

    n = len(x)
    df = n - 3
    if df > 0 and abs(r_partial) < 1:
        t_stat = r_partial * math.sqrt(df) / math.sqrt(1 - r_partial**2)
        p_value = 2 * (1 - dist.t_cdf(abs(t_stat), df))
    else:
        p_value = 0 if r_partial != 0 else 1

    return CorrelationResult(coefficient=r_partial, p_value=p_value, n=n, method="partial")


def correlation_matrix(data: list[list[float]]) -> tuple[list[list[float]], list[str]]:
    """
    Compute correlation matrix for multiple variables.

    Args:
        data: List of variables (each variable is a list of values).

    Returns:
        Tuple of (correlation matrix, variable names).

    Raises:
        ValueError: If variables have different lengths.
        InsufficientDataError: If data is too small.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    if not all(data):
        raise InsufficientDataError("No variable can be empty")

    n_vars = len(data)
    lengths = [len(var) for var in data]

    if not all(l == lengths[0] for l in lengths):
        raise ValueError("All variables must have the same length")

    if lengths[0] < 3:
        raise InsufficientDataError("Need at least 3 observations")

    corr_matrix = [[0.0] * n_vars for _ in range(n_vars)]

    for i in range(n_vars):
        for j in range(n_vars):
            if i == j:
                corr_matrix[i][j] = 1.0
            elif i > j:
                corr_matrix[i][j] = corr_matrix[j][i]
            else:
                result = pearson_correlation(data[i], data[j])
                corr_matrix[i][j] = result.coefficient

    var_names = [f"var_{i}" for i in range(n_vars)]

    return corr_matrix, var_names


def autocorrelation(data: list[float], lag: int = 1) -> float:
    """
    Calculate autocorrelation at a given lag.

    Args:
        data: Time series data.
        lag: Lag to compute autocorrelation at.

    Returns:
        Autocorrelation coefficient.

    Raises:
        InsufficientDataError: If data is too small.
        ValueError: If lag is invalid.
    """
    if len(data) < lag + 2:
        raise InsufficientDataError("Data too small for requested lag")

    if lag < 0:
        raise ValueError("Lag must be non-negative")

    m = desc.mean(data)
    c0 = sum((x - m) ** 2 for x in data) / len(data)

    if c0 == 0:
        return 0

    c_lag = sum((data[i] - m) * (data[i + lag] - m) for i in range(len(data) - lag)) / len(data)

    return c_lag / c0


def acf(data: list[float], max_lag: int = 10) -> list[float]:
    """
    Calculate autocorrelation function for multiple lags.

    Args:
        data: Time series data.
        max_lag: Maximum lag to compute (default 10).

    Returns:
        List of autocorrelations from lag 0 to max_lag.

    Raises:
        InsufficientDataError: If data is too small.
    """
    if len(data) < 2:
        raise InsufficientDataError("Data too small for ACF")

    if max_lag >= len(data):
        max_lag = len(data) - 1

    return [autocorrelation(data, lag) for lag in range(max_lag + 1)]


def cross_correlation(x: list[float], y: list[float], max_lag: int = 10) -> list[float]:
    """
    Calculate cross-correlation between two time series.

    Args:
        x: First time series.
        y: Second time series (must have same length as x).
        max_lag: Maximum lag to compute (default 10).

    Returns:
        List of cross-correlations from lag -max_lag to max_lag.

    Raises:
        ValueError: If x and y have different lengths.
        InsufficientDataError: If data is too small.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")

    if len(x) < 2:
        raise InsufficientDataError("Data too small for cross-correlation")

    mean_x = desc.mean(x)
    mean_y = desc.mean(y)
    std_x = desc.std(x, sample=True)
    std_y = desc.std(y, sample=True)

    if std_x == 0 or std_y == 0:
        return [0] * (2 * max_lag + 1)

    ccf = []

    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            cc = sum((x[i] - mean_x) * (y[i + lag] - mean_y) for i in range(len(x) - lag)) / (
                (len(x) - lag) * std_x * std_y
            )
        else:
            cc = sum((x[i - lag] - mean_x) * (y[i] - mean_y) for i in range(len(y) + lag)) / (
                (len(y) + lag) * std_x * std_y
            )

        ccf.append(cc)

    return ccf
