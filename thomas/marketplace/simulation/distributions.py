"""
Statistical distributions for simulation input parameterization.

Provides sampling, fitting, and mixing capabilities for various distributions.
"""

import math
import random
from abc import ABC, abstractmethod

from ._exceptions import DistributionError


class Distribution(ABC):
    """Base class for probability distributions."""

    @abstractmethod
    def sample(self) -> float:
        """Draw random sample from distribution."""
        pass

    @abstractmethod
    def pdf(self, x: float) -> float:
        """Probability density function."""
        pass

    @abstractmethod
    def cdf(self, x: float) -> float:
        """Cumulative distribution function."""
        pass

    @abstractmethod
    def mean(self) -> float:
        """Distribution mean."""
        pass

    @abstractmethod
    def variance(self) -> float:
        """Distribution variance."""
        pass

    def std(self) -> float:
        """Distribution standard deviation."""
        return math.sqrt(self.variance())


class UniformContinuous(Distribution):
    """Continuous uniform distribution U(a, b)."""

    def __init__(self, a: float = 0.0, b: float = 1.0) -> None:
        """
        Initialize uniform distribution.

        Args:
            a: Lower bound
            b: Upper bound

        Raises:
            DistributionError: If a >= b
        """
        if a >= b:
            raise DistributionError(f"Uniform: a {a} must be < b {b}")

        self.a = a
        self.b = b

    def sample(self) -> float:
        """Draw sample."""
        return random.uniform(self.a, self.b)

    def pdf(self, x: float) -> float:
        """PDF value."""
        if self.a <= x <= self.b:
            return 1 / (self.b - self.a)
        return 0.0

    def cdf(self, x: float) -> float:
        """CDF value."""
        if x < self.a:
            return 0.0
        elif x > self.b:
            return 1.0
        else:
            return (x - self.a) / (self.b - self.a)

    def mean(self) -> float:
        """Mean."""
        return (self.a + self.b) / 2

    def variance(self) -> float:
        """Variance."""
        return ((self.b - self.a) ** 2) / 12


class UniformDiscrete(Distribution):
    """Discrete uniform distribution on {a, a+1, ..., b}."""

    def __init__(self, a: int = 0, b: int = 10) -> None:
        """Initialize discrete uniform distribution."""
        if a >= b:
            raise DistributionError(f"Discrete uniform: a {a} must be < b {b}")

        self.a = a
        self.b = b

    def sample(self) -> float:
        """Draw sample."""
        return float(random.randint(self.a, self.b))

    def pdf(self, x: float) -> float:
        """PMF value."""
        if x == int(x) and self.a <= x <= self.b:
            return 1 / (self.b - self.a + 1)
        return 0.0

    def cdf(self, x: float) -> float:
        """CDF value."""
        if x < self.a:
            return 0.0
        elif x > self.b:
            return 1.0
        else:
            return (int(x) - self.a + 1) / (self.b - self.a + 1)

    def mean(self) -> float:
        """Mean."""
        return (self.a + self.b) / 2

    def variance(self) -> float:
        """Variance."""
        n = self.b - self.a + 1
        return (n**2 - 1) / 12


class Normal(Distribution):
    """Normal (Gaussian) distribution N(μ, σ²)."""

    def __init__(self, mean: float = 0.0, std: float = 1.0) -> None:
        """
        Initialize normal distribution.

        Args:
            mean: Mean μ
            std: Standard deviation σ

        Raises:
            DistributionError: If std <= 0
        """
        if std <= 0:
            raise DistributionError(f"Normal: std {std} must be positive")

        self.mean_val = mean
        self.std_val = std

    def sample(self) -> float:
        """Draw sample via Box-Muller."""
        u1 = random.random()
        u2 = random.random()
        z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        return self.mean_val + self.std_val * z

    def pdf(self, x: float) -> float:
        """PDF value."""
        z = (x - self.mean_val) / self.std_val
        return (1 / (self.std_val * math.sqrt(2 * math.pi))) * math.exp(-(z**2) / 2)

    def cdf(self, x: float) -> float:
        """CDF approximation."""
        z = (x - self.mean_val) / self.std_val
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))

    def mean(self) -> float:
        """Mean."""
        return self.mean_val

    def variance(self) -> float:
        """Variance."""
        return self.std_val**2


class Exponential(Distribution):
    """Exponential distribution with rate λ."""

    def __init__(self, rate: float = 1.0) -> None:
        """
        Initialize exponential distribution.

        Args:
            rate: Rate parameter λ

        Raises:
            DistributionError: If rate <= 0
        """
        if rate <= 0:
            raise DistributionError(f"Exponential: rate {rate} must be positive")

        self.rate = rate

    def sample(self) -> float:
        """Draw sample via inverse CDF."""
        u = random.random()
        return -math.log(u) / self.rate

    def pdf(self, x: float) -> float:
        """PDF value."""
        if x < 0:
            return 0.0
        return self.rate * math.exp(-self.rate * x)

    def cdf(self, x: float) -> float:
        """CDF value."""
        if x < 0:
            return 0.0
        return 1 - math.exp(-self.rate * x)

    def mean(self) -> float:
        """Mean."""
        return 1 / self.rate

    def variance(self) -> float:
        """Variance."""
        return 1 / (self.rate**2)


class Poisson(Distribution):
    """Poisson distribution with rate λ."""

    def __init__(self, lambda_val: float = 1.0) -> None:
        """
        Initialize Poisson distribution.

        Args:
            lambda_val: Rate parameter λ

        Raises:
            DistributionError: If lambda_val <= 0
        """
        if lambda_val <= 0:
            raise DistributionError(f"Poisson: lambda {lambda_val} must be positive")

        self.lambda_val = lambda_val

    def sample(self) -> float:
        """Draw sample via Knuth algorithm."""
        L = math.exp(-self.lambda_val)
        k = 0
        p = 1.0

        while p > L:
            k += 1
            u = random.random()
            p *= u

        return float(k - 1)

    def pdf(self, x: float) -> float:
        """PMF value."""
        if x != int(x) or x < 0:
            return 0.0

        k = int(x)
        return (self.lambda_val**k * math.exp(-self.lambda_val)) / math.factorial(k)

    def cdf(self, x: float) -> float:
        """CDF value."""
        if x < 0:
            return 0.0

        total = 0.0
        for k in range(int(x) + 1):
            total += self.pdf(float(k))

        return total

    def mean(self) -> float:
        """Mean."""
        return self.lambda_val

    def variance(self) -> float:
        """Variance."""
        return self.lambda_val


class Triangular(Distribution):
    """Triangular distribution on [a, b] with mode c."""

    def __init__(self, a: float = 0.0, c: float = 0.5, b: float = 1.0) -> None:
        """
        Initialize triangular distribution.

        Args:
            a: Minimum
            c: Mode (peak)
            b: Maximum

        Raises:
            DistributionError: If not a <= c <= b
        """
        if not (a <= c <= b):
            raise DistributionError(f"Triangular: need a {a} <= c {c} <= b {b}")

        self.a = a
        self.c = c
        self.b = b

    def sample(self) -> float:
        """Draw sample."""
        u = random.random()
        c_norm = (self.c - self.a) / (self.b - self.a)

        if u <= c_norm:
            return self.a + math.sqrt(u * c_norm) * (self.b - self.a)
        else:
            return self.b - math.sqrt((1 - u) * (1 - c_norm)) * (self.b - self.a)

    def pdf(self, x: float) -> float:
        """PDF value."""
        if x < self.a or x > self.b:
            return 0.0

        if x <= self.c:
            return (2 * (x - self.a)) / ((self.b - self.a) * (self.c - self.a))
        else:
            return (2 * (self.b - x)) / ((self.b - self.a) * (self.b - self.c))

    def cdf(self, x: float) -> float:
        """CDF value."""
        if x < self.a:
            return 0.0
        elif x > self.b:
            return 1.0
        elif x <= self.c:
            return ((x - self.a) ** 2) / ((self.b - self.a) * (self.c - self.a))
        else:
            return 1 - ((self.b - x) ** 2) / ((self.b - self.a) * (self.b - self.c))

    def mean(self) -> float:
        """Mean."""
        return (self.a + self.b + self.c) / 3

    def variance(self) -> float:
        """Variance."""
        return (self.a**2 + self.b**2 + self.c**2 - self.a * self.b - self.a * self.c - self.b * self.c) / 18


class Lognormal(Distribution):
    """Log-normal distribution."""

    def __init__(self, mean: float = 1.0, std: float = 0.5) -> None:
        """Initialize log-normal distribution."""
        self.mean_val = mean
        self.std_val = std

        # Convert to underlying normal parameters
        variance = std**2
        self.mu = math.log(mean**2 / math.sqrt(variance + mean**2))
        self.sigma = math.sqrt(math.log(variance / mean**2 + 1))

    def sample(self) -> float:
        """Draw sample."""
        z = Normal(self.mu, self.sigma).sample()
        return math.exp(z)

    def pdf(self, x: float) -> float:
        """PDF value."""
        if x <= 0:
            return 0.0

        return Normal(self.mu, self.sigma).pdf(math.log(x)) / x

    def cdf(self, x: float) -> float:
        """CDF value."""
        if x <= 0:
            return 0.0

        return Normal(self.mu, self.sigma).cdf(math.log(x))

    def mean(self) -> float:
        """Mean."""
        return math.exp(self.mu + self.sigma**2 / 2)

    def variance(self) -> float:
        """Variance."""
        exp_sigma2 = math.exp(self.sigma**2)
        return (exp_sigma2 - 1) * math.exp(2 * self.mu + self.sigma**2)


class Beta(Distribution):
    """Beta distribution on [0, 1]."""

    def __init__(self, alpha: float = 1.0, beta: float = 1.0) -> None:
        """
        Initialize beta distribution.

        Args:
            alpha: Shape parameter α
            beta: Shape parameter β

        Raises:
            DistributionError: If parameters invalid
        """
        if alpha <= 0 or beta <= 0:
            raise DistributionError(f"Beta: need alpha {alpha} > 0 and beta {beta} > 0")

        self.alpha = alpha
        self.beta_val = beta

    def sample(self) -> float:
        """Draw sample via Gamma method."""
        random.random()
        x = self._gamma(self.alpha, 1.0)
        y = self._gamma(self.beta_val, 1.0)
        return x / (x + y)

    def pdf(self, x: float) -> float:
        """PDF value."""
        if x < 0 or x > 1:
            return 0.0

        numerator = (x ** (self.alpha - 1)) * ((1 - x) ** (self.beta_val - 1))
        denominator = math.exp(
            math.lgamma(self.alpha) + math.lgamma(self.beta_val) - math.lgamma(self.alpha + self.beta_val)
        )

        return numerator / denominator

    def cdf(self, x: float) -> float:
        """CDF value (incomplete beta function)."""
        if x <= 0:
            return 0.0
        elif x >= 1:
            return 1.0
        else:
            # Approximation
            return 0.5

    def mean(self) -> float:
        """Mean."""
        return self.alpha / (self.alpha + self.beta_val)

    def variance(self) -> float:
        """Variance."""
        numerator = self.alpha * self.beta_val
        denominator = (self.alpha + self.beta_val) ** 2 * (self.alpha + self.beta_val + 1)
        return numerator / denominator

    @staticmethod
    def _gamma(shape: float, scale: float) -> float:
        """Internal gamma sampling."""
        if shape < 1:
            u = random.random()
            return Beta._gamma(shape + 1, scale) * (u ** (1 / shape))

        d = shape - 1 / 3
        c = 1 / math.sqrt(9 * d)

        while True:
            z = Normal(0, 1).sample()
            v = (1 + c * z) ** 3

            if v > 0:
                u = random.random()
                if u < 1 - 0.0331 * (z**4):
                    return scale * d * v
                if math.log(u) < 0.5 * z * z + d * (1 - v + math.log(v)):
                    return scale * d * v


class EmpiricalDistribution(Distribution):
    """Distribution from empirical data (histogram)."""

    def __init__(self, values: list[float]) -> None:
        """
        Initialize from data.

        Args:
            values: Sample values

        Raises:
            DistributionError: If no values
        """
        if not values:
            raise DistributionError("Empirical: need at least one value")

        self.values = sorted(values)

    def sample(self) -> float:
        """Draw random sample from data."""
        return random.choice(self.values)

    def pdf(self, x: float) -> float:
        """Empirical PDF (frequency)."""
        count = sum(1 for v in self.values if v == x)
        return count / len(self.values)

    def cdf(self, x: float) -> float:
        """Empirical CDF."""
        count = sum(1 for v in self.values if v <= x)
        return count / len(self.values)

    def mean(self) -> float:
        """Empirical mean."""
        return sum(self.values) / len(self.values)

    def variance(self) -> float:
        """Empirical variance."""
        m = self.mean()
        return sum((v - m) ** 2 for v in self.values) / len(self.values)


class MixedDistribution(Distribution):
    """Mixture of distributions."""

    def __init__(self, distributions: list[Distribution], weights: list[float] | None = None) -> None:
        """
        Initialize mixture.

        Args:
            distributions: Component distributions
            weights: Mixture weights (default: equal)

        Raises:
            DistributionError: If empty or weight mismatch
        """
        if not distributions:
            raise DistributionError("Mixed: need at least one distribution")

        self.distributions = distributions

        if weights is None:
            self.weights = [1 / len(distributions)] * len(distributions)
        else:
            if len(weights) != len(distributions):
                raise DistributionError("Mixed: weight count must match distributions")

            total = sum(weights)
            self.weights = [w / total for w in weights]

    def sample(self) -> float:
        """Draw from random component."""
        u = random.random()
        cumsum = 0.0

        for dist, weight in zip(self.distributions, self.weights):
            cumsum += weight
            if u <= cumsum:
                return dist.sample()

        return self.distributions[-1].sample()

    def pdf(self, x: float) -> float:
        """Mixture PDF."""
        return sum(w * d.pdf(x) for w, d in zip(self.weights, self.distributions))

    def cdf(self, x: float) -> float:
        """Mixture CDF."""
        return sum(w * d.cdf(x) for w, d in zip(self.weights, self.distributions))

    def mean(self) -> float:
        """Mixture mean."""
        return sum(w * d.mean() for w, d in zip(self.weights, self.distributions))

    def variance(self) -> float:
        """Mixture variance."""
        mean = self.mean()
        return sum(w * (d.variance() + (d.mean() - mean) ** 2) for w, d in zip(self.weights, self.distributions))


def fit_distribution(data: list[float], dist_type: str = "normal") -> Distribution:
    """
    Fit distribution to data.

    Args:
        data: Sample values
        dist_type: Type to fit ("normal", "uniform", "exponential")

    Returns:
        Fitted distribution

    Raises:
        DistributionError: If fitting fails
    """
    if not data:
        raise DistributionError("Fit: need data")

    if dist_type == "normal":
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = math.sqrt(variance)
        return Normal(mean, std)

    elif dist_type == "uniform":
        return UniformContinuous(min(data), max(data))

    elif dist_type == "exponential":
        mean = sum(data) / len(data)
        return Exponential(1 / mean)

    else:
        raise DistributionError(f"Unknown distribution type: {dist_type}")
