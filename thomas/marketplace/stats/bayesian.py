"""Bayesian statistics methods."""

import math
import random

from . import descriptive as desc
from . import distributions as dist
from ._exceptions import ConvergenceError, InsufficientDataError
from ._types import ConfidenceInterval


def bayes_theorem(p_a: float, p_b_given_a: float, p_b_given_not_a: float) -> float:
    """
    Calculate posterior probability using Bayes' theorem.

    P(A|B) = P(B|A) * P(A) / P(B)

    Args:
        p_a: Prior probability P(A).
        p_b_given_a: Likelihood P(B|A).
        p_b_given_not_a: Likelihood P(B|not A).

    Returns:
        Posterior probability P(A|B).

    Raises:
        ValueError: If probabilities are invalid.
    """
    if not (0 <= p_a <= 1 and 0 <= p_b_given_a <= 1 and 0 <= p_b_given_not_a <= 1):
        raise ValueError("All probabilities must be in [0, 1]")

    p_b = p_b_given_a * p_a + p_b_given_not_a * (1 - p_a)

    if p_b == 0:
        return 0

    return (p_b_given_a * p_a) / p_b


def beta_binomial_posterior(
    successes: int, trials: int, alpha_prior: float = 1, beta_prior: float = 1
) -> tuple[float, float]:
    """
    Update Beta distribution parameters using Binomial likelihood (conjugate prior).

    Args:
        successes: Number of observed successes.
        trials: Number of trials.
        alpha_prior: Prior alpha parameter (default 1, uniform).
        beta_prior: Prior beta parameter (default 1, uniform).

    Returns:
        Tuple of (alpha_posterior, beta_posterior).

    Raises:
        ValueError: If parameters are invalid.
    """
    if not (0 <= successes <= trials):
        raise ValueError("Invalid success/trial count")

    if alpha_prior <= 0 or beta_prior <= 0:
        raise ValueError("Prior parameters must be positive")

    alpha_post = alpha_prior + successes
    beta_post = beta_prior + (trials - successes)

    return alpha_post, beta_post


def beta_binomial_credible_interval(alpha: float, beta: float, credible_level: float = 0.95) -> ConfidenceInterval:
    """
    Compute credible interval for Beta distribution.

    Args:
        alpha: Beta distribution alpha parameter.
        beta: Beta distribution beta parameter.
        credible_level: Credible level (default 0.95).

    Returns:
        ConfidenceInterval with bounds.

    Raises:
        ValueError: If parameters are invalid.
    """
    if alpha <= 0 or beta <= 0:
        raise ValueError("Parameters must be positive")

    if not (0 < credible_level < 1):
        raise ValueError("Credible level must be in (0, 1)")

    mean_val = alpha / (alpha + beta)

    lower_q = (1 - credible_level) / 2
    upper_q = 1 - lower_q

    lower = _beta_quantile(lower_q, alpha, beta)
    upper = _beta_quantile(upper_q, alpha, beta)

    return ConfidenceInterval(lower=lower, upper=upper, center=mean_val, level=credible_level)


def _beta_quantile(p: float, alpha: float, beta: float) -> float:
    """Approximate quantile of Beta distribution."""
    if p <= 0:
        return 0
    if p >= 1:
        return 1

    mean_val = alpha / (alpha + beta)
    variance = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))

    if variance == 0:
        return mean_val

    std = math.sqrt(variance)

    z = dist.normal_icdf(p)
    quantile = mean_val + z * std

    return max(0, min(1, quantile))


def normal_normal_posterior(
    data: list[float], prior_mean: float = 0, prior_var: float = 1, likelihood_var: float = 1
) -> tuple[float, float]:
    """
    Update Normal distribution parameters with Normal likelihood (conjugate prior).

    Args:
        data: Observed data.
        prior_mean: Prior mean (default 0).
        prior_var: Prior variance (default 1).
        likelihood_var: Likelihood variance (assumed known, default 1).

    Returns:
        Tuple of (posterior_mean, posterior_variance).

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If variances are invalid.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    if prior_var <= 0 or likelihood_var <= 0:
        raise ValueError("Variances must be positive")

    n = len(data)
    sample_mean = desc.mean(data)

    prior_precision = 1 / prior_var
    likelihood_precision = n / likelihood_var

    posterior_precision = prior_precision + likelihood_precision
    posterior_var = 1 / posterior_precision

    posterior_mean = posterior_var * (prior_precision * prior_mean + likelihood_precision * sample_mean)

    return posterior_mean, posterior_var


def bayesian_ab_test(
    control_successes: int, control_trials: int, treatment_successes: int, treatment_trials: int, samples: int = 10000
) -> tuple[float, float]:
    """
    Perform Bayesian A/B test using Beta-Binomial model with MCMC sampling.

    Args:
        control_successes: Successes in control group.
        control_trials: Total trials in control group.
        treatment_successes: Successes in treatment group.
        treatment_trials: Total trials in treatment group.
        samples: Number of MCMC samples (default 10000).

    Returns:
        Tuple of (control_effect, treatment_effect) where each is the
        posterior probability of the parameter.

    Raises:
        ValueError: If parameters are invalid.
    """
    if not (0 <= control_successes <= control_trials):
        raise ValueError("Invalid control parameters")

    if not (0 <= treatment_successes <= treatment_trials):
        raise ValueError("Invalid treatment parameters")

    alpha_c_post, beta_c_post = beta_binomial_posterior(control_successes, control_trials, alpha_prior=1, beta_prior=1)
    alpha_t_post, beta_t_post = beta_binomial_posterior(
        treatment_successes, treatment_trials, alpha_prior=1, beta_prior=1
    )

    control_samples = [random.betavariate(alpha_c_post, beta_c_post) for _ in range(samples)]
    treatment_samples = [random.betavariate(alpha_t_post, beta_t_post) for _ in range(samples)]

    control_mean = desc.mean(control_samples)
    treatment_mean = desc.mean(treatment_samples)

    return control_mean, treatment_mean


def _mcmc_metropolis_hastings(
    log_likelihood, log_prior, proposal_sd: float = 0.1, samples: int = 1000, burnin: int = 100
) -> list[float]:
    """
    Metropolis-Hastings MCMC sampling.

    Args:
        log_likelihood: Function that takes parameter and returns log likelihood.
        log_prior: Function that takes parameter and returns log prior.
        proposal_sd: Standard deviation for random walk proposal.
        samples: Number of samples to generate.
        burnin: Number of burn-in iterations.

    Returns:
        List of samples from posterior.

    Raises:
        ConvergenceError: If acceptance rate is too low.
    """
    current = 0
    accepted = 0

    samples_list = []

    for iteration in range(samples + burnin):
        proposal = current + random.gauss(0, proposal_sd)

        log_alpha = log_likelihood(proposal) + log_prior(proposal) - log_likelihood(current) - log_prior(current)

        if math.log(random.random()) < log_alpha:
            current = proposal
            accepted += 1

        if iteration >= burnin:
            samples_list.append(current)

    acceptance_rate = accepted / (samples + burnin)
    if acceptance_rate < 0.01:
        raise ConvergenceError(f"Low acceptance rate: {acceptance_rate:.2%}")

    return samples_list


def posterior_predictive(posterior_samples: list[float], n_pred: int = 100) -> list[float]:
    """
    Generate posterior predictive samples.

    Args:
        posterior_samples: Samples from posterior distribution.
        n_pred: Number of predictions per posterior sample (default 100).

    Returns:
        List of posterior predictive samples.

    Raises:
        InsufficientDataError: If posterior_samples is empty.
    """
    if not posterior_samples:
        raise InsufficientDataError("Posterior samples cannot be empty")

    predictions = []

    for param in posterior_samples:
        for _ in range(n_pred):
            prediction = random.gauss(param, 1)
            predictions.append(prediction)

    return predictions


def highest_posterior_density(samples: list[float], level: float = 0.95) -> ConfidenceInterval:
    """
    Compute highest posterior density (credible) interval.

    Args:
        samples: Posterior samples.
        level: Credible level (default 0.95).

    Returns:
        ConfidenceInterval representing HPD.

    Raises:
        InsufficientDataError: If samples are too small.
        ValueError: If level is invalid.
    """
    if len(samples) < 10:
        raise InsufficientDataError("Need at least 10 samples for HPD")

    if not (0 < level < 1):
        raise ValueError("Level must be in (0, 1)")

    sorted_samples = sorted(samples)
    n = len(sorted_samples)

    window_size = int(level * n)

    best_interval = (float("inf"), float("-inf"))
    best_width = float("inf")

    for i in range(n - window_size + 1):
        lower = sorted_samples[i]
        upper = sorted_samples[i + window_size - 1]
        width = upper - lower

        if width < best_width:
            best_width = width
            best_interval = (lower, upper)

    center = desc.mean(samples)

    return ConfidenceInterval(lower=best_interval[0], upper=best_interval[1], center=center, level=level)


def dirichlet_multinomial(counts: list[int], alpha_prior: list[float]) -> list[float]:
    """
    Update Dirichlet distribution with multinomial counts (conjugate prior).

    Args:
        counts: Observed counts for each category.
        alpha_prior: Prior alpha parameters for each category.

    Returns:
        Posterior alpha parameters.

    Raises:
        ValueError: If parameters are invalid.
    """
    if len(counts) != len(alpha_prior):
        raise ValueError("counts and alpha_prior must have same length")

    if any(c < 0 for c in counts):
        raise ValueError("Counts must be non-negative")

    if any(a <= 0 for a in alpha_prior):
        raise ValueError("Prior parameters must be positive")

    return [alpha_prior[i] + counts[i] for i in range(len(counts))]


def credible_interval_proportion(successes: int, trials: int, level: float = 0.95) -> ConfidenceInterval:
    """
    Credible interval for proportion using Beta-Binomial model.

    Args:
        successes: Number of successes observed.
        trials: Total number of trials.
        level: Credible level (default 0.95).

    Returns:
        ConfidenceInterval for the proportion.

    Raises:
        ValueError: If parameters are invalid.
    """
    if not (0 <= successes <= trials):
        raise ValueError("Invalid success/trial count")

    alpha_post, beta_post = beta_binomial_posterior(successes, trials)

    return beta_binomial_credible_interval(alpha_post, beta_post, level)
