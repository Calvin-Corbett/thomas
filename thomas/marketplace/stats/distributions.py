"""Probability distributions and parameter estimation."""

import math

from ._exceptions import InsufficientDataError


def _erf(x: float) -> float:
    """Approximation of the error function using Abramowitz and Stegun."""
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    sign = 1 if x >= 0 else -1
    x = abs(x)

    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)

    return sign * y


def _normal_cdf(x: float, mu: float = 0, sigma: float = 1) -> float:
    """CDF of normal distribution using error function approximation."""
    return 0.5 * (1 + _erf((x - mu) / (sigma * math.sqrt(2))))


def _normal_pdf(x: float, mu: float = 0, sigma: float = 1) -> float:
    """PDF of normal distribution."""
    if sigma <= 0:
        return 0
    coeff = 1.0 / (sigma * math.sqrt(2 * math.pi))
    exponent = -0.5 * ((x - mu) / sigma) ** 2
    return coeff * math.exp(exponent)


def normal_pdf(x: float, mu: float = 0, sigma: float = 1) -> float:
    """
    PDF of the normal distribution.

    Args:
        x: Value to evaluate PDF at.
        mu: Mean (default 0).
        sigma: Standard deviation (default 1).

    Returns:
        PDF value.
    """
    return _normal_pdf(x, mu, sigma)


def normal_cdf(x: float, mu: float = 0, sigma: float = 1) -> float:
    """
    CDF of the normal distribution.

    Args:
        x: Value to evaluate CDF at.
        mu: Mean (default 0).
        sigma: Standard deviation (default 1).

    Returns:
        CDF value in [0, 1].
    """
    return _normal_cdf(x, mu, sigma)


def normal_icdf(p: float, mu: float = 0, sigma: float = 1) -> float:
    """
    Inverse CDF (quantile) of normal distribution using Newton-Raphson.

    Args:
        p: Probability in (0, 1).
        mu: Mean (default 0).
        sigma: Standard deviation (default 1).

    Returns:
        The quantile.

    Raises:
        ValueError: If p is not in (0, 1).
    """
    if not (0 < p < 1):
        raise ValueError("p must be in (0, 1)")

    if p < 0.5:
        result = -math.sqrt(-2 * math.log(p))
    else:
        result = math.sqrt(-2 * math.log(1 - p))

    for _ in range(10):
        f = _normal_cdf(result) - p
        fp = _normal_pdf(result)
        if fp == 0:
            break
        result -= f / fp

    return mu + sigma * result


def normal_sample(mu: float = 0, sigma: float = 1, size: int = 1) -> list[float]:
    """
    Generate samples from normal distribution using Box-Muller transform.

    Args:
        mu: Mean (default 0).
        sigma: Standard deviation (default 1).
        size: Number of samples.

    Returns:
        List of samples.
    """
    import random

    samples = []
    for _ in range((size + 1) // 2):
        u1 = random.random()
        u2 = random.random()
        if u1 > 0:
            z0 = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
            z1 = math.sqrt(-2 * math.log(u1)) * math.sin(2 * math.pi * u2)
            samples.append(mu + sigma * z0)
            if len(samples) < size:
                samples.append(mu + sigma * z1)

    return samples[:size]


def t_pdf(x: float, df: float) -> float:
    """
    PDF of Student's t-distribution.

    Args:
        x: Value to evaluate PDF at.
        df: Degrees of freedom (must be > 0).

    Returns:
        PDF value.
    """
    if df <= 0:
        return 0

    numerator = math.gamma((df + 1) / 2)
    denominator = math.sqrt(df * math.pi) * math.gamma(df / 2)
    coeff = numerator / denominator

    return coeff * (1 + x**2 / df) ** (-(df + 1) / 2)


def t_cdf(x: float, df: float) -> float:
    """
    CDF of Student's t-distribution (using approximation).

    Args:
        x: Value to evaluate CDF at.
        df: Degrees of freedom (must be > 0).

    Returns:
        CDF value in [0, 1].
    """
    if df <= 0:
        return 0.5

    if df == 1:
        return 0.5 + math.atan(x) / math.pi
    elif df == 2:
        return 0.5 + x / (2 * math.sqrt(2 + x**2))

    if x == 0:
        return 0.5

    if x > 0:
        beta = math.atan(x / math.sqrt(df))
        return 1 - 0.5 * (1 - beta / (0.5 * math.pi))
    else:
        beta = math.atan(x / math.sqrt(df))
        return 0.5 + beta / (math.pi)


def chi2_pdf(x: float, df: float) -> float:
    """
    PDF of chi-squared distribution.

    Args:
        x: Value to evaluate PDF at.
        df: Degrees of freedom (must be > 0).

    Returns:
        PDF value.
    """
    if x < 0 or df <= 0:
        return 0

    coeff = 1.0 / (2 ** (df / 2) * math.gamma(df / 2))
    return coeff * (x ** (df / 2 - 1)) * math.exp(-x / 2)


def chi2_cdf(x: float, df: float) -> float:
    """
    CDF of chi-squared distribution (using approximation).

    Args:
        x: Value to evaluate CDF at.
        df: Degrees of freedom (must be > 0).

    Returns:
        CDF value in [0, 1].
    """
    if x < 0 or df <= 0:
        return 0

    if x == 0:
        return 0

    sum_val = 0.0
    term = math.exp(-x / 2) * (x / 2) ** (df / 2) / math.gamma(df / 2 + 1)

    for k in range(100):
        sum_val += term
        term *= x / (2 * (k + 1 + df / 2))
        if term < 1e-10:
            break

    return sum_val


def f_pdf(x: float, df1: float, df2: float) -> float:
    """
    PDF of F-distribution.

    Args:
        x: Value to evaluate PDF at.
        df1: Numerator degrees of freedom.
        df2: Denominator degrees of freedom.

    Returns:
        PDF value.
    """
    if x < 0 or df1 <= 0 or df2 <= 0:
        return 0

    num = math.gamma((df1 + df2) / 2) * (df1 ** (df1 / 2)) * (df2 ** (df2 / 2))
    denom = math.gamma(df1 / 2) * math.gamma(df2 / 2)
    coeff = num / denom

    return coeff * (x ** (df1 / 2 - 1)) / ((df1 * x + df2) ** ((df1 + df2) / 2))


def f_cdf(x: float, df1: float, df2: float) -> float:
    """
    CDF of F-distribution (using approximation).

    Args:
        x: Value to evaluate CDF at.
        df1: Numerator degrees of freedom.
        df2: Denominator degrees of freedom.

    Returns:
        CDF value in [0, 1].
    """
    if x < 0 or df1 <= 0 or df2 <= 0:
        return 0

    if x == 0:
        return 0

    z = (df1 * x) / (df1 * x + df2)

    sum_val = 0.0
    for k in range(100):
        term = (z ** (df1 / 2 + k)) * ((1 - z) ** (df2 / 2)) / (k + 1)
        sum_val += term
        if abs(term) < 1e-10:
            break

    coeff = math.gamma((df1 + df2) / 2) / (math.gamma(df1 / 2) * math.gamma(df2 / 2))
    return coeff * (df1 / 2) * (df2 / 2) * sum_val


def binomial_pmf(k: int, n: int, p: float) -> float:
    """
    PMF of binomial distribution.

    Args:
        k: Number of successes (0 <= k <= n).
        n: Number of trials (n >= 1).
        p: Probability of success (0 <= p <= 1).

    Returns:
        Probability mass.
    """
    if not (0 <= k <= n) or not (0 <= p <= 1):
        return 0

    if p == 0:
        return 1.0 if k == 0 else 0.0
    if p == 1:
        return 1.0 if k == n else 0.0

    binom_coeff = math.factorial(n) / (math.factorial(k) * math.factorial(n - k))
    return binom_coeff * (p**k) * ((1 - p) ** (n - k))


def binomial_cdf(k: int, n: int, p: float) -> float:
    """
    CDF of binomial distribution.

    Args:
        k: Number of successes.
        n: Number of trials.
        p: Probability of success.

    Returns:
        Cumulative probability.
    """
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0

    return sum(binomial_pmf(i, n, p) for i in range(int(k) + 1))


def poisson_pmf(k: int, lambda_param: float) -> float:
    """
    PMF of Poisson distribution.

    Args:
        k: Number of events (k >= 0).
        lambda_param: Rate parameter (lambda > 0).

    Returns:
        Probability mass.
    """
    if k < 0 or lambda_param <= 0:
        return 0

    return (lambda_param**k) * math.exp(-lambda_param) / math.factorial(k)


def poisson_cdf(k: int, lambda_param: float) -> float:
    """
    CDF of Poisson distribution.

    Args:
        k: Number of events.
        lambda_param: Rate parameter.

    Returns:
        Cumulative probability.
    """
    if k < 0:
        return 0

    return sum(poisson_pmf(i, lambda_param) for i in range(int(k) + 1))


def exponential_pdf(x: float, rate: float) -> float:
    """
    PDF of exponential distribution.

    Args:
        x: Value to evaluate PDF at (x >= 0).
        rate: Rate parameter (rate > 0).

    Returns:
        PDF value.
    """
    if x < 0 or rate <= 0:
        return 0

    return rate * math.exp(-rate * x)


def exponential_cdf(x: float, rate: float) -> float:
    """
    CDF of exponential distribution.

    Args:
        x: Value to evaluate CDF at (x >= 0).
        rate: Rate parameter (rate > 0).

    Returns:
        CDF value in [0, 1].
    """
    if x < 0 or rate <= 0:
        return 0

    return 1 - math.exp(-rate * x)


def uniform_pdf(x: float, a: float = 0, b: float = 1) -> float:
    """
    PDF of continuous uniform distribution.

    Args:
        x: Value to evaluate PDF at.
        a: Lower bound (default 0).
        b: Upper bound (default 1).

    Returns:
        PDF value.
    """
    if a >= b:
        return 0

    if a <= x <= b:
        return 1.0 / (b - a)

    return 0


def uniform_cdf(x: float, a: float = 0, b: float = 1) -> float:
    """
    CDF of continuous uniform distribution.

    Args:
        x: Value to evaluate CDF at.
        a: Lower bound (default 0).
        b: Upper bound (default 1).

    Returns:
        CDF value in [0, 1].
    """
    if a >= b:
        return 0.5

    if x <= a:
        return 0
    elif x >= b:
        return 1
    else:
        return (x - a) / (b - a)


def beta_pdf(x: float, alpha: float, beta: float) -> float:
    """
    PDF of beta distribution.

    Args:
        x: Value in [0, 1].
        alpha: First shape parameter (alpha > 0).
        beta: Second shape parameter (beta > 0).

    Returns:
        PDF value.
    """
    if not (0 <= x <= 1) or alpha <= 0 or beta <= 0:
        return 0

    coeff = math.gamma(alpha + beta) / (math.gamma(alpha) * math.gamma(beta))
    return coeff * (x ** (alpha - 1)) * ((1 - x) ** (beta - 1))


def gamma_pdf(x: float, shape: float, rate: float) -> float:
    """
    PDF of gamma distribution (shape and rate parameterization).

    Args:
        x: Value to evaluate PDF at (x > 0).
        shape: Shape parameter k (shape > 0).
        rate: Rate parameter (rate > 0).

    Returns:
        PDF value.
    """
    if x <= 0 or shape <= 0 or rate <= 0:
        return 0

    coeff = (rate**shape) / math.gamma(shape)
    return coeff * (x ** (shape - 1)) * math.exp(-rate * x)


def estimate_normal_params(data: list[float]) -> tuple[float, float]:
    """
    Estimate normal distribution parameters using MLE.

    Args:
        data: List of numeric values.

    Returns:
        Tuple of (mu, sigma).

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot estimate parameters from empty dataset")

    n = len(data)
    mu = sum(data) / n
    sigma = math.sqrt(sum((x - mu) ** 2 for x in data) / n)

    return mu, sigma


def estimate_exponential_params(data: list[float]) -> float:
    """
    Estimate exponential distribution rate parameter using MLE.

    Args:
        data: List of numeric values (all > 0).

    Returns:
        The rate parameter.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If any value is non-positive.
    """
    if not data:
        raise InsufficientDataError("Cannot estimate parameters from empty dataset")

    if any(x <= 0 for x in data):
        raise ValueError("All values must be positive for exponential distribution")

    return 1.0 / (sum(data) / len(data))


def estimate_poisson_params(data: list[int]) -> float:
    """
    Estimate Poisson distribution rate parameter using MLE.

    Args:
        data: List of non-negative integer values.

    Returns:
        The rate parameter (lambda).

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot estimate parameters from empty dataset")

    return sum(data) / len(data)


def estimate_binomial_params(successes: int, trials: int) -> float:
    """
    Estimate binomial probability parameter using MLE.

    Args:
        successes: Number of successes.
        trials: Number of trials.

    Returns:
        The probability parameter p.

    Raises:
        ValueError: If parameters are invalid.
    """
    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError("Invalid trial or success count")

    return successes / trials
