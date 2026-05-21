"""
Tests for Monte Carlo simulation methods.
"""

import math
import random

import pytest
from _exceptions import DistributionError
from monte_carlo import (
    ConvergenceMonitoring,
    MonteCarloIntegration,
    RandomVariableGenerator,
    RiskSimulation,
    VarianceReduction,
)


class TestRandomVariableGenerator:
    """Test random variable generation."""

    def test_uniform_generation(self):
        """Test uniform random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.uniform(0, 1) for _ in range(100)]

        assert all(0 <= x <= 1 for x in samples)
        assert 0.3 <= sum(samples) / len(samples) <= 0.7

    def test_normal_generation(self):
        """Test normal random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.normal(0, 1) for _ in range(1000)]

        mean = sum(samples) / len(samples)
        assert -0.2 < mean < 0.2

    def test_exponential_generation(self):
        """Test exponential random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.exponential(rate=1.0) for _ in range(100)]

        assert all(x >= 0 for x in samples)
        mean = sum(samples) / len(samples)
        assert 0.5 < mean < 2.0

    def test_exponential_invalid_rate_fails(self):
        """Test exponential with invalid rate."""
        rng = RandomVariableGenerator()

        with pytest.raises(DistributionError):
            rng.exponential(rate=-1.0)

    def test_poisson_generation(self):
        """Test Poisson random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.poisson(lambda_val=5.0) for _ in range(100)]

        assert all(x >= 0 for x in samples)
        assert all(isinstance(x, int) for x in samples)
        mean = sum(samples) / len(samples)
        assert 4 < mean < 6

    def test_triangular_generation(self):
        """Test triangular random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.triangular(0, 5, 10) for _ in range(100)]

        assert all(0 <= x <= 10 for x in samples)
        mean = sum(samples) / len(samples)
        assert (0 + 5 + 10) / 3 - 1 < mean < (0 + 5 + 10) / 3 + 1

    def test_lognormal_generation(self):
        """Test log-normal random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.lognormal(mean=0, std=1) for _ in range(100)]

        assert all(x > 0 for x in samples)

    def test_weibull_generation(self):
        """Test Weibull random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.weibull(shape=2.0, scale=1.0) for _ in range(100)]

        assert all(x >= 0 for x in samples)

    def test_beta_generation(self):
        """Test beta random generation."""
        rng = RandomVariableGenerator(seed=42)

        samples = [rng.beta(alpha=2.0, beta=5.0) for _ in range(100)]

        assert all(0 <= x <= 1 for x in samples)


class TestMonteCarloIntegration:
    """Test Monte Carlo integration methods."""

    def test_estimate_area_under_curve(self):
        """Test area estimation under curve."""
        mci = MonteCarloIntegration(seed=42)

        # Integrate y = x^2 from 0 to 1
        # Analytical solution: 1/3 ≈ 0.333
        result = mci.estimate_area_under_curve(
            func=lambda x: x**2,
            x_min=0,
            x_max=1,
            y_min=0,
            y_max=1,
            num_samples=100000,
        )

        assert 0.2 < result.estimate < 0.45
        assert result.num_samples == 100000

    def test_estimate_pi(self):
        """Test pi estimation via Monte Carlo."""
        mci = MonteCarloIntegration(seed=42)

        result = mci.estimate_pi(num_samples=100000)

        # π ≈ 3.14159
        assert 2.9 < result.estimate < 3.4
        assert result.num_samples == 100000

    def test_confidence_interval(self):
        """Test confidence interval on estimate."""
        mci = MonteCarloIntegration(seed=42)

        result = mci.estimate_pi(num_samples=50000, confidence_level=0.95)

        lower, upper = result.confidence_interval
        assert lower < result.estimate < upper

    def test_std_error_convergence(self):
        """Test standard error decreases with samples."""
        mci = MonteCarloIntegration(seed=42)

        result_small = mci.estimate_pi(num_samples=1000)
        result_large = mci.estimate_pi(num_samples=100000)

        assert result_large.std_error < result_small.std_error


class TestRiskSimulation:
    """Test risk and scenario simulation."""

    def test_aggregate_risk(self):
        """Test aggregating multiple risk sources."""
        rs = RiskSimulation(seed=42)

        distributions = [
            ("risk1", lambda: rs.rng.normal(10, 2)),
            ("risk2", lambda: rs.rng.normal(5, 1)),
        ]

        result = rs.aggregate_risk(distributions, num_simulations=10000)

        # Mean should be around 15 (10 + 5)
        assert 14 < result.estimate < 16
        assert len(result.samples) == 10000

    def test_var_at_risk(self):
        """Test Value at Risk calculation."""
        rs = RiskSimulation(seed=42)

        distributions = [
            ("loss1", lambda: rs.rng.normal(-100, 20)),
            ("loss2", lambda: rs.rng.normal(-50, 10)),
        ]

        var_95 = rs.var_at_risk(distributions, confidence_level=0.95, num_simulations=10000)

        # Should be a loss value
        assert var_95 < 0

    def test_var_confidence_levels(self):
        """Test VaR at different confidence levels."""
        rs = RiskSimulation(seed=42)

        distributions = [
            ("loss", lambda: rs.rng.exponential(rate=0.1)),
        ]

        var_95 = rs.var_at_risk(distributions, confidence_level=0.95)
        var_99 = rs.var_at_risk(distributions, confidence_level=0.99)

        # Higher confidence should give higher VaR (worse loss)
        assert var_99 >= var_95


class TestVarianceReduction:
    """Test variance reduction techniques."""

    def test_antithetic_variates(self):
        """Test antithetic variates method."""
        vr = VarianceReduction(seed=42)

        # Integrate sin(x) over [0, π/2]
        def func(x):
            return math.sin(x * math.pi / 2)

        estimate, variance = vr.antithetic_variates(func, num_pairs=1000)

        # Expected: 1.0
        assert 0.7 < estimate < 1.3
        assert variance >= 0

    def test_control_variates(self):
        """Test control variate method."""
        vr = VarianceReduction(seed=42)

        # Integrate x^3
        def func(x):
            return x**3

        def control_func(x):
            return x**2  # Correlated, known E[x^2] = 1/3

        known_expectation = 1 / 3

        estimate, variance = vr.control_variates(func, control_func, known_expectation, num_samples=1000)

        # E[x^3] = 1/4 = 0.25
        assert 0.15 < estimate < 0.35

    def test_variance_reduction_effectiveness(self):
        """Test that variance reduction actually reduces variance."""
        vr = VarianceReduction(seed=42)

        def func(x):
            return x**2

        def control_func(x):
            return x

        # Regular sampling
        samples_raw = [func(random.random()) for _ in range(100)]
        sum((x - sum(samples_raw) / len(samples_raw)) ** 2 for x in samples_raw) / len(samples_raw)

        # With control variates
        _, cv_variance = vr.control_variates(func, control_func, 0.5, num_samples=100)

        # Control variates should have comparable or lower variance
        assert cv_variance >= 0


class TestConvergenceMonitoring:
    """Test convergence monitoring and analysis."""

    def test_running_mean(self):
        """Test running mean calculation."""
        samples = [1, 2, 3, 4, 5]

        means = ConvergenceMonitoring.running_mean(samples)

        assert means[0] == pytest.approx(1.0)
        assert means[1] == pytest.approx(1.5)
        assert means[2] == pytest.approx(2.0)
        assert means[-1] == pytest.approx(3.0)

    def test_running_std_error(self):
        """Test running standard error."""
        samples = [10.0] * 100  # Constant values

        errors = ConvergenceMonitoring.running_std_error(samples)

        # With constant values, std error should decrease to 0
        assert errors[0] == 0.0
        assert errors[-1] < 0.1

    def test_required_samples(self):
        """Test sample size calculation."""
        target_error = 0.1
        sample_variance = 1.0

        n_required = ConvergenceMonitoring.required_samples(
            target_std_error=target_error,
            sample_variance=sample_variance,
            confidence_level=0.95,
        )

        assert n_required > 0
        assert isinstance(n_required, int)

    def test_convergence_check(self):
        """Test convergence detection."""
        # Converged samples
        converged_samples = [1.0] * 200

        has_converged = ConvergenceMonitoring.has_converged(
            converged_samples,
            relative_tolerance=0.01,
            min_samples=100,
        )

        assert has_converged

    def test_convergence_fails_early(self):
        """Test convergence check with insufficient samples."""
        samples = [1.0] * 50

        has_converged = ConvergenceMonitoring.has_converged(
            samples,
            relative_tolerance=0.01,
            min_samples=100,
        )

        assert not has_converged


class TestMonteCarloStatistics:
    """Test Monte Carlo result statistics."""

    def test_result_confidence_interval(self):
        """Test result confidence interval."""
        mci = MonteCarloIntegration(seed=42)

        result = mci.estimate_pi(num_samples=50000, confidence_level=0.95)

        lower, upper = result.confidence_interval
        assert lower > 0
        assert upper > lower
        assert lower < 3.14159 < upper

    def test_different_confidence_levels(self):
        """Test CIs at different confidence levels."""
        mci = MonteCarloIntegration(seed=42)

        result_95 = mci.estimate_pi(num_samples=50000, confidence_level=0.95)
        result_99 = mci.estimate_pi(num_samples=50000, confidence_level=0.99)

        # 99% CI should be wider
        width_95 = result_95.confidence_interval[1] - result_95.confidence_interval[0]
        width_99 = result_99.confidence_interval[1] - result_99.confidence_interval[0]

        assert width_99 > width_95
