"""
Monte Carlo simulation methods.

Implements random sampling, integration, pi estimation,
risk simulation, and variance reduction techniques.
"""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from ._exceptions import DistributionError


@dataclass
class MonteCarloResult:
    """Result of Monte Carlo simulation."""

    estimate: float
    std_error: float
    confidence_interval: tuple[float, float]
    samples: list[float] = field(default_factory=list)
    num_samples: int = 0


class RandomVariableGenerator:
    """Generate random samples from standard distributions."""

    def __init__(self, seed: int | None = None) -> None:
        """
        Initialize RNG.

        Args:
            seed: Random seed for reproducibility
        """
        if seed is not None:
            random.seed(seed)

    def uniform(self, min_val: float, max_val: float) -> float:
        """
        Generate uniform random variable.

        Args:
            min_val: Lower bound
            max_val: Upper bound

        Returns:
            Uniform random in [min_val, max_val]
        """
        return random.uniform(min_val, max_val)

    def normal(self, mean: float = 0.0, std: float = 1.0) -> float:
        """
        Generate normal random variable via Box-Muller transform.

        Args:
            mean: Mean
            std: Standard deviation

        Returns:
            Normal random variable
        """
        u1 = random.random()
        u2 = random.random()

        # Box-Muller transform
        z0 = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)

        return mean + std * z0

    def exponential(self, rate: float) -> float:
        """
        Generate exponential random variable via inverse CDF.

        Args:
            rate: Rate parameter lambda (must be > 0)

        Returns:
            Exponential random variable

        Raises:
            DistributionError: If rate <= 0
        """
        if rate <= 0:
            raise DistributionError(f"Exponential rate must be positive, got {rate}")

        u = random.random()
        return -math.log(u) / rate

    def poisson(self, lambda_val: float) -> int:
        """
        Generate Poisson random variable via Knuth algorithm.

        Args:
            lambda_val: Rate parameter (must be > 0)

        Returns:
            Poisson random integer

        Raises:
            DistributionError: If lambda_val <= 0
        """
        if lambda_val <= 0:
            raise DistributionError(f"Poisson lambda must be positive, got {lambda_val}")

        L = math.exp(-lambda_val)
        k = 0
        p = 1.0

        while p > L:
            k += 1
            u = random.random()
            p *= u

        return k - 1

    def triangular(self, min_val: float, mode: float, max_val: float) -> float:
        """
        Generate triangular random variable.

        Args:
            min_val: Minimum value
            mode: Mode (peak)
            max_val: Maximum value

        Returns:
            Triangular random variable

        Raises:
            DistributionError: If parameters invalid
        """
        if not (min_val <= mode <= max_val):
            raise DistributionError(f"Triangular: min {min_val} <= mode {mode} <= max {max_val} required")

        u = random.random()
        c = (mode - min_val) / (max_val - min_val)

        if u <= c:
            return min_val + math.sqrt(u * c) * (max_val - min_val)
        else:
            return max_val - math.sqrt((1 - u) * (1 - c)) * (max_val - min_val)

    def lognormal(self, mean: float, std: float) -> float:
        """
        Generate log-normal random variable.

        Args:
            mean: Mean of underlying normal
            std: Std dev of underlying normal

        Returns:
            Log-normal random variable
        """
        z = self.normal(mean, std)
        return math.exp(z)

    def weibull(self, shape: float, scale: float) -> float:
        """
        Generate Weibull random variable.

        Args:
            shape: Shape parameter k (must be > 0)
            scale: Scale parameter lambda (must be > 0)

        Returns:
            Weibull random variable

        Raises:
            DistributionError: If parameters invalid
        """
        if shape <= 0 or scale <= 0:
            raise DistributionError(f"Weibull: shape {shape} and scale {scale} must be positive")

        u = random.random()
        return scale * ((-math.log(u)) ** (1 / shape))

    def beta(self, alpha: float, beta: float) -> float:
        """
        Generate beta random variable.

        Args:
            alpha: Alpha parameter (must be > 0)
            beta: Beta parameter (must be > 0)

        Returns:
            Beta random variable in [0, 1]

        Raises:
            DistributionError: If parameters invalid
        """
        if alpha <= 0 or beta <= 0:
            raise DistributionError(f"Beta: alpha {alpha} and beta {beta} must be positive")

        # Use Gamma variates method
        x = self._gamma(alpha, 1.0)
        y = self._gamma(beta, 1.0)
        return x / (x + y)

    def gamma(self, shape: float, scale: float) -> float:
        """
        Generate gamma random variable.

        Args:
            shape: Shape parameter alpha (must be > 0)
            scale: Scale parameter beta (must be > 0)

        Returns:
            Gamma random variable

        Raises:
            DistributionError: If parameters invalid
        """
        if shape <= 0 or scale <= 0:
            raise DistributionError(f"Gamma: shape {shape} and scale {scale} must be positive")

        return self._gamma(shape, scale)

    def _gamma(self, shape: float, scale: float) -> float:
        """Internal gamma generation using shape-scale parameterization."""
        if shape < 1:
            u = random.random()
            return self._gamma(shape + 1, scale) * (u ** (1 / shape))

        d = shape - 1 / 3
        c = 1 / math.sqrt(9 * d)

        while True:
            z = self.normal(0, 1)
            v = (1 + c * z) ** 3

            if v > 0:
                u = random.random()
                if u < 1 - 0.0331 * (z**4):
                    return scale * d * v
                if math.log(u) < 0.5 * z * z + d * (1 - v + math.log(v)):
                    return scale * d * v


class MonteCarloIntegration:
    """Monte Carlo integration methods."""

    def __init__(self, seed: int | None = None) -> None:
        """Initialize integrator."""
        self.rng = RandomVariableGenerator(seed)

    def estimate_area_under_curve(
        self,
        func: Callable[[float], float],
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        num_samples: int = 10000,
        confidence_level: float = 0.95,
    ) -> MonteCarloResult:
        """
        Estimate area under curve via rejection sampling.

        Args:
            func: Function to integrate
            x_min: Minimum x
            x_max: Maximum x
            y_min: Minimum y
            y_max: Maximum y
            num_samples: Number of points to sample
            confidence_level: Confidence level for CI

        Returns:
            MonteCarloResult with estimate and confidence interval
        """
        area_box = (x_max - x_min) * (y_max - y_min)
        count_under = 0

        for _ in range(num_samples):
            x = self.rng.uniform(x_min, x_max)
            y = self.rng.uniform(y_min, y_max)

            if y <= func(x):
                count_under += 1

        estimate = area_box * (count_under / num_samples)

        # Confidence interval via normal approximation
        p = count_under / num_samples
        se = area_box * math.sqrt(p * (1 - p) / num_samples)
        z = 1.96 if confidence_level == 0.95 else 2.576  # 95% or 99%
        ci = (estimate - z * se, estimate + z * se)

        return MonteCarloResult(
            estimate=estimate,
            std_error=se,
            confidence_interval=ci,
            num_samples=num_samples,
        )

    def estimate_pi(
        self,
        num_samples: int = 100000,
        confidence_level: float = 0.95,
    ) -> MonteCarloResult:
        """
        Estimate pi via circular sampling.

        Sample points in [0,1] x [0,1] and count those in unit circle.
        Ratio * 4 ≈ π

        Args:
            num_samples: Number of points to sample
            confidence_level: Confidence level for CI

        Returns:
            MonteCarloResult with pi estimate
        """
        count_in_circle = 0

        for _ in range(num_samples):
            x = random.random()
            y = random.random()

            if (x**2 + y**2) <= 1:
                count_in_circle += 1

        estimate = 4 * count_in_circle / num_samples

        # Confidence interval
        p = count_in_circle / num_samples
        se = 4 * math.sqrt(p * (1 - p) / num_samples)
        z = 1.96 if confidence_level == 0.95 else 2.576
        ci = (estimate - z * se, estimate + z * se)

        return MonteCarloResult(
            estimate=estimate,
            std_error=se,
            confidence_interval=ci,
            num_samples=num_samples,
        )


class RiskSimulation:
    """Risk and scenario simulation via Monte Carlo."""

    def __init__(self, seed: int | None = None) -> None:
        """Initialize risk simulator."""
        self.rng = RandomVariableGenerator(seed)

    def aggregate_risk(
        self,
        distributions: list[tuple[str, Callable[[], float]]],
        num_simulations: int = 10000,
        confidence_level: float = 0.95,
    ) -> MonteCarloResult:
        """
        Aggregate risks by sampling from multiple distributions.

        Args:
            distributions: List of (name, sampling_function) pairs
            num_simulations: Number of Monte Carlo iterations
            confidence_level: For confidence interval

        Returns:
            MonteCarloResult with aggregate distribution
        """
        aggregates = []

        for _ in range(num_simulations):
            total = sum(sample_func() for _, sample_func in distributions)
            aggregates.append(total)

        mean = sum(aggregates) / len(aggregates)
        variance = sum((x - mean) ** 2 for x in aggregates) / len(aggregates)
        std_dev = math.sqrt(variance)
        std_error = std_dev / math.sqrt(num_simulations)

        # Percentiles for confidence interval
        aggregates.sort()
        alpha = 1 - confidence_level
        lower_idx = int(num_simulations * (alpha / 2))
        upper_idx = int(num_simulations * (1 - alpha / 2))

        ci = (aggregates[lower_idx], aggregates[upper_idx])

        return MonteCarloResult(
            estimate=mean,
            std_error=std_error,
            confidence_interval=ci,
            samples=aggregates,
            num_samples=num_simulations,
        )

    def var_at_risk(
        self,
        distributions: list[tuple[str, Callable[[], float]]],
        confidence_level: float = 0.95,
        num_simulations: int = 10000,
    ) -> float:
        """
        Compute Value at Risk (VaR) at given confidence level.

        Args:
            distributions: Risk distributions
            confidence_level: Confidence level (e.g., 0.95 for 95% VaR)
            num_simulations: Number of scenarios

        Returns:
            VaR value (loss threshold)
        """
        aggregates = []

        for _ in range(num_simulations):
            total = sum(sample_func() for _, sample_func in distributions)
            aggregates.append(total)

        aggregates.sort()
        idx = int(num_simulations * (1 - confidence_level))
        return aggregates[idx]


class VarianceReduction:
    """Variance reduction techniques for Monte Carlo."""

    def __init__(self, seed: int | None = None) -> None:
        """Initialize variance reduction."""
        self.rng = RandomVariableGenerator(seed)

    def antithetic_variates(
        self,
        func: Callable[[float], float],
        num_pairs: int = 1000,
    ) -> tuple[float, float]:
        """
        Reduce variance using antithetic variates.

        For each U in [0,1], use both U and (1-U) to estimate integral.

        Args:
            func: Function to estimate expectation of
            num_pairs: Number of antithetic pairs

        Returns:
            (estimate, variance) tuple
        """
        estimates = []

        for _ in range(num_pairs):
            u = random.random()

            # Use U and 1-U
            val1 = func(u)
            val2 = func(1 - u)

            estimate = (val1 + val2) / 2
            estimates.append(estimate)

        mean = sum(estimates) / len(estimates)
        variance = sum((x - mean) ** 2 for x in estimates) / len(estimates)

        return mean, variance

    def control_variates(
        self,
        func: Callable[[float], float],
        control_func: Callable[[float], float],
        control_expectation: float,
        num_samples: int = 1000,
    ) -> tuple[float, float]:
        """
        Reduce variance using control variate.

        Assume control_func has known expectation and is correlated with func.

        Args:
            func: Function to estimate
            control_func: Control function (correlated with func)
            control_expectation: Known E[control_func]
            num_samples: Number of samples

        Returns:
            (estimate, variance) tuple
        """
        samples_f = []
        samples_c = []

        for _ in range(num_samples):
            u = random.random()
            samples_f.append(func(u))
            samples_c.append(control_func(u))

        mean_f = sum(samples_f) / num_samples
        mean_c = sum(samples_c) / num_samples

        # Compute optimal coefficient
        numerator = sum((samples_f[i] - mean_f) * (samples_c[i] - mean_c) for i in range(num_samples))
        denominator = sum((samples_c[i] - mean_c) ** 2 for i in range(num_samples))

        if denominator == 0:
            return mean_f, 0.0

        beta = numerator / denominator

        # Adjusted estimate
        estimate = mean_f - beta * (mean_c - control_expectation)

        # Variance reduction
        variance_f = sum((x - mean_f) ** 2 for x in samples_f) / num_samples
        correlation = numerator / (
            math.sqrt(sum((samples_f[i] - mean_f) ** 2 for i in range(num_samples))) * math.sqrt(denominator)
        )

        reduced_variance = variance_f * (1 - correlation**2)

        return estimate, reduced_variance


class ConvergenceMonitoring:
    """Monitor and analyze Monte Carlo convergence."""

    @staticmethod
    def running_mean(samples: list[float]) -> list[float]:
        """Compute running mean of samples."""
        means = []
        cumsum = 0.0

        for i, x in enumerate(samples, 1):
            cumsum += x
            means.append(cumsum / i)

        return means

    @staticmethod
    def running_std_error(samples: list[float]) -> list[float]:
        """Compute running standard error of estimates."""
        errors = []
        means = ConvergenceMonitoring.running_mean(samples)

        for i, mean_i in enumerate(means, 1):
            if i == 1:
                errors.append(0.0)
            else:
                variance = sum((samples[j] - mean_i) ** 2 for j in range(i)) / i
                std_dev = math.sqrt(variance)
                se = std_dev / math.sqrt(i)
                errors.append(se)

        return errors

    @staticmethod
    def required_samples(
        target_std_error: float,
        sample_variance: float,
        confidence_level: float = 0.95,
    ) -> int:
        """
        Calculate samples needed to achieve target precision.

        Args:
            target_std_error: Target standard error
            sample_variance: Variance estimate from pilot run
            confidence_level: Confidence level

        Returns:
            Minimum number of samples needed
        """
        z = 1.96 if confidence_level == 0.95 else 2.576
        return int(math.ceil((z * math.sqrt(sample_variance) / target_std_error) ** 2))

    @staticmethod
    def has_converged(
        samples: list[float],
        relative_tolerance: float = 0.01,
        min_samples: int = 100,
    ) -> bool:
        """
        Check if estimate has converged.

        Args:
            samples: Sample values collected so far
            relative_tolerance: Convergence threshold (as fraction of mean)
            min_samples: Minimum samples before checking

        Returns:
            True if converged
        """
        if len(samples) < min_samples:
            return False

        mean = sum(samples) / len(samples)
        variance = sum((x - mean) ** 2 for x in samples) / len(samples)
        std_dev = math.sqrt(variance)
        std_error = std_dev / math.sqrt(len(samples))

        relative_error = std_error / abs(mean) if mean != 0 else std_error

        return relative_error < relative_tolerance
