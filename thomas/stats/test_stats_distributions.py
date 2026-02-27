"""Tests for distributions module."""

import math

import pytest

from thomas.stats import distributions as dist


class TestNormalDistribution:
    def test_normal_pdf_mean(self):
        result = dist.normal_pdf(0, mu=0, sigma=1)
        expected = 1.0 / math.sqrt(2 * math.pi)
        assert abs(result - expected) < 1e-10

    def test_normal_pdf_shifted(self):
        result1 = dist.normal_pdf(0, mu=0, sigma=1)
        result2 = dist.normal_pdf(1, mu=1, sigma=1)
        assert abs(result1 - result2) < 1e-10

    def test_normal_cdf_zero(self):
        result = dist.normal_cdf(0, mu=0, sigma=1)
        assert abs(result - 0.5) < 0.01

    def test_normal_cdf_bounds(self):
        assert 0 < dist.normal_cdf(-4) < 0.01
        assert 0.99 < dist.normal_cdf(4) < 1

    def test_normal_icdf_inverse(self):
        result = dist.normal_cdf(dist.normal_icdf(0.95))
        assert abs(result - 0.95) < 0.01

    def test_normal_icdf_invalid(self):
        with pytest.raises(ValueError):
            dist.normal_icdf(1.5)

    def test_normal_sample_mean(self):
        samples = dist.normal_sample(mu=100, sigma=15, size=1000)
        assert len(samples) == 1000
        sample_mean = sum(samples) / len(samples)
        assert 95 < sample_mean < 105


class TestTDistribution:
    def test_t_pdf_standard(self):
        result = dist.t_pdf(0, df=1)
        assert result > 0

    def test_t_cdf_bounds(self):
        assert 0 < dist.t_cdf(0, df=10) < 1

    def test_t_cdf_special_df1(self):
        result = dist.t_cdf(0, df=1)
        assert abs(result - 0.5) < 0.01


class TestChi2Distribution:
    def test_chi2_pdf_positive(self):
        result = dist.chi2_pdf(1, df=2)
        assert result > 0

    def test_chi2_pdf_negative_x(self):
        result = dist.chi2_pdf(-1, df=2)
        assert result == 0

    def test_chi2_cdf_bounds(self):
        assert 0 < dist.chi2_cdf(1, df=2) < 1


class TestFDistribution:
    def test_f_pdf_positive(self):
        result = dist.f_pdf(1, df1=2, df2=2)
        assert result > 0

    def test_f_pdf_negative(self):
        result = dist.f_pdf(-1, df1=2, df2=2)
        assert result == 0

    def test_f_cdf_bounds(self):
        assert 0 < dist.f_cdf(1, df1=2, df2=2) < 1


class TestBinomialDistribution:
    def test_binomial_pmf_zero(self):
        result = dist.binomial_pmf(0, n=5, p=0.5)
        assert abs(result - 0.03125) < 1e-10

    def test_binomial_pmf_certain(self):
        result = dist.binomial_pmf(5, n=5, p=1.0)
        assert abs(result - 1.0) < 1e-10

    def test_binomial_pmf_impossible(self):
        result = dist.binomial_pmf(5, n=5, p=0)
        assert result == 0

    def test_binomial_cdf_cumulative(self):
        result1 = dist.binomial_pmf(0, n=3, p=0.5) + dist.binomial_pmf(1, n=3, p=0.5)
        result2 = dist.binomial_cdf(1, n=3, p=0.5)
        assert abs(result1 - result2) < 1e-10


class TestPoissonDistribution:
    def test_poisson_pmf_simple(self):
        result = dist.poisson_pmf(0, lambda_param=1.0)
        expected = math.exp(-1.0)
        assert abs(result - expected) < 1e-10

    def test_poisson_cdf_bounds(self):
        result = dist.poisson_cdf(10, lambda_param=1.0)
        assert 0 <= result <= 1


class TestExponentialDistribution:
    def test_exponential_pdf_simple(self):
        result = dist.exponential_pdf(0, rate=1)
        assert abs(result - 1.0) < 1e-10

    def test_exponential_cdf_zero(self):
        result = dist.exponential_cdf(0, rate=1)
        assert abs(result - 0.0) < 1e-10

    def test_exponential_cdf_large(self):
        result = dist.exponential_cdf(100, rate=1)
        assert result > 0.99


class TestUniformDistribution:
    def test_uniform_pdf_inside(self):
        result = dist.uniform_pdf(0.5, a=0, b=1)
        assert abs(result - 1.0) < 1e-10

    def test_uniform_pdf_outside(self):
        result = dist.uniform_pdf(2, a=0, b=1)
        assert result == 0

    def test_uniform_cdf_bounds(self):
        assert dist.uniform_cdf(0.5, a=0, b=1) == 0.5


class TestBetaDistribution:
    def test_beta_pdf_uniform(self):
        result1 = dist.beta_pdf(0.3, alpha=1, beta=1)
        result2 = dist.beta_pdf(0.7, alpha=1, beta=1)
        assert abs(result1 - result2) < 1e-10

    def test_beta_pdf_bounds(self):
        result = dist.beta_pdf(-0.5, alpha=2, beta=2)
        assert result == 0

        result = dist.beta_pdf(1.5, alpha=2, beta=2)
        assert result == 0


class TestGammaDistribution:
    def test_gamma_pdf_positive(self):
        result = dist.gamma_pdf(1, shape=2, rate=2)
        assert result > 0

    def test_gamma_pdf_negative_x(self):
        result = dist.gamma_pdf(-1, shape=2, rate=2)
        assert result == 0


class TestEstimateNormalParams:
    def test_estimate_normal(self):
        data = [98, 99, 100, 101, 102]
        mu, sigma = dist.estimate_normal_params(data)
        assert abs(mu - 100) < 1e-10
        assert sigma > 0

    def test_estimate_normal_empty(self):
        from thomas.stats._exceptions import InsufficientDataError

        with pytest.raises(InsufficientDataError):
            dist.estimate_normal_params([])


class TestEstimateExponentialParams:
    def test_estimate_exponential(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        rate = dist.estimate_exponential_params(data)
        assert rate > 0

    def test_estimate_exponential_negative(self):
        with pytest.raises(ValueError):
            dist.estimate_exponential_params([1, -2, 3])


class TestEstimatePoissonParams:
    def test_estimate_poisson(self):
        data = [1, 2, 3, 2, 1, 0, 2]
        lambda_param = dist.estimate_poisson_params(data)
        assert abs(lambda_param - 1.57) < 0.1


class TestEstimateBinomialParams:
    def test_estimate_binomial(self):
        p = dist.estimate_binomial_params(successes=5, trials=10)
        assert abs(p - 0.5) < 1e-10

    def test_estimate_binomial_invalid(self):
        with pytest.raises(ValueError):
            dist.estimate_binomial_params(successes=15, trials=10)
