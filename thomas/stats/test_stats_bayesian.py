"""Tests for Bayesian statistics module."""

import pytest

from thomas.stats import bayesian as bayes


class TestBayesTheorem:
    def test_bayes_theorem_simple(self):
        result = bayes.bayes_theorem(p_a=0.01, p_b_given_a=0.99, p_b_given_not_a=0.05)
        assert 0 < result < 1

    def test_bayes_theorem_zero_prior(self):
        result = bayes.bayes_theorem(p_a=0, p_b_given_a=0.99, p_b_given_not_a=0.05)
        assert result == 0

    def test_bayes_theorem_invalid_prob(self):
        with pytest.raises(ValueError):
            bayes.bayes_theorem(p_a=1.5, p_b_given_a=0.99, p_b_given_not_a=0.05)


class TestBetaBinomialPosterior:
    def test_beta_binomial_posterior(self):
        alpha_post, beta_post = bayes.beta_binomial_posterior(successes=5, trials=10)
        assert alpha_post == 6
        assert beta_post == 6

    def test_beta_binomial_posterior_no_data(self):
        alpha_post, beta_post = bayes.beta_binomial_posterior(successes=0, trials=0)
        assert alpha_post == 1
        assert beta_post == 1

    def test_beta_binomial_posterior_invalid(self):
        with pytest.raises(ValueError):
            bayes.beta_binomial_posterior(successes=15, trials=10)


class TestBetaBinomialCredibleInterval:
    def test_credible_interval(self):
        interval = bayes.beta_binomial_credible_interval(alpha=10, beta=10)
        assert 0 <= interval.lower <= interval.center <= interval.upper <= 1

    def test_credible_interval_invalid_level(self):
        with pytest.raises(ValueError):
            bayes.beta_binomial_credible_interval(alpha=10, beta=10, credible_level=1.5)


class TestNormalNormalPosterior:
    def test_normal_normal_posterior(self):
        data = [98, 99, 100, 101, 102]
        post_mean, post_var = bayes.normal_normal_posterior(data)
        assert post_mean is not None
        assert post_var > 0

    def test_normal_normal_posterior_empty(self):
        from thomas.stats._exceptions import InsufficientDataError

        with pytest.raises(InsufficientDataError):
            bayes.normal_normal_posterior([])


class TestBayesianABTest:
    def test_bayesian_ab_test(self):
        control, treatment = bayes.bayesian_ab_test(
            control_successes=50, control_trials=100, treatment_successes=60, treatment_trials=100, samples=1000
        )
        assert 0 < control < 1
        assert 0 < treatment < 1

    def test_bayesian_ab_test_invalid(self):
        with pytest.raises(ValueError):
            bayes.bayesian_ab_test(
                control_successes=150, control_trials=100, treatment_successes=50, treatment_trials=100
            )


class TestPosteriorPredictive:
    def test_posterior_predictive(self):
        posterior_samples = [0.5, 0.6, 0.55]
        predictions = bayes.posterior_predictive(posterior_samples, n_pred=10)
        assert len(predictions) == 30

    def test_posterior_predictive_empty(self):
        from thomas.stats._exceptions import InsufficientDataError

        with pytest.raises(InsufficientDataError):
            bayes.posterior_predictive([], n_pred=10)


class TestHighestPosteriorDensity:
    def test_hpd_interval(self):
        samples = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        interval = bayes.highest_posterior_density(samples, level=0.95)
        assert interval.lower <= interval.center <= interval.upper

    def test_hpd_insufficient(self):
        from thomas.stats._exceptions import InsufficientDataError

        with pytest.raises(InsufficientDataError):
            bayes.highest_posterior_density([1, 2, 3], level=0.95)

    def test_hpd_invalid_level(self):
        samples = list(range(100))
        with pytest.raises(ValueError):
            bayes.highest_posterior_density(samples, level=1.5)


class TestDirichletMultinomial:
    def test_dirichlet_multinomial(self):
        counts = [10, 20, 30]
        alpha_prior = [1, 1, 1]
        result = bayes.dirichlet_multinomial(counts, alpha_prior)
        assert len(result) == 3
        assert result == [11, 21, 31]

    def test_dirichlet_multinomial_mismatch(self):
        with pytest.raises(ValueError):
            bayes.dirichlet_multinomial([10, 20], [1, 1, 1])


class TestCredibleIntervalProportion:
    def test_credible_interval_proportion(self):
        interval = bayes.credible_interval_proportion(successes=50, trials=100)
        assert 0 <= interval.lower <= interval.center <= interval.upper <= 1

    def test_credible_interval_proportion_invalid(self):
        with pytest.raises(ValueError):
            bayes.credible_interval_proportion(successes=150, trials=100)
