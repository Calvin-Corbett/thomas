"""Sampling methods and sample size calculations."""

import math
import random

from . import distributions as dist
from ._exceptions import InsufficientDataError


def simple_random_sample(data: list, sample_size: int) -> list:
    """
    Draw simple random sample without replacement.

    Args:
        data: Population to sample from.
        sample_size: Size of sample to draw.

    Returns:
        Random sample.

    Raises:
        ValueError: If sample_size is invalid.
    """
    if sample_size < 0 or sample_size > len(data):
        raise ValueError("sample_size must be between 0 and population size")

    return random.sample(data, sample_size)


def stratified_sample(data: list, strata: list[int], sample_size: int, proportional: bool = True) -> list:
    """
    Draw stratified random sample.

    Args:
        data: Population to sample from.
        strata: Stratum assignment for each element in data.
        sample_size: Total sample size.
        proportional: If True, allocate sample proportionally to strata sizes.

    Returns:
        Stratified sample.

    Raises:
        ValueError: If parameters are invalid.
    """
    if len(data) != len(strata):
        raise ValueError("data and strata must have same length")

    if sample_size < 0 or sample_size > len(data):
        raise ValueError("sample_size must be between 0 and population size")

    unique_strata = sorted(set(strata))
    strata_dict: dict[int, list] = {s: [] for s in unique_strata}
    strata_indices: dict[int, list[int]] = {s: [] for s in unique_strata}

    for i, (item, stratum) in enumerate(zip(data, strata)):
        strata_dict[stratum].append(item)
        strata_indices[stratum].append(i)

    sample = []

    if proportional:
        for s in unique_strata:
            stratum_size = len(strata_dict[s])
            stratum_sample_size = int((stratum_size / len(data)) * sample_size)
            stratum_sample_size = max(0, min(stratum_sample_size, stratum_size))

            sample.extend(random.sample(strata_dict[s], stratum_sample_size))
    else:
        for s in unique_strata:
            stratum_size = len(strata_dict[s])
            stratum_sample_size = max(0, min(sample_size // len(unique_strata), stratum_size))
            sample.extend(random.sample(strata_dict[s], stratum_sample_size))

    return sample[:sample_size]


def systematic_sample(data: list, sample_size: int, start: int = 0) -> list:
    """
    Draw systematic sample (every kth element).

    Args:
        data: Population to sample from.
        sample_size: Size of sample to draw.
        start: Starting index (default 0).

    Returns:
        Systematic sample.

    Raises:
        ValueError: If parameters are invalid.
    """
    if sample_size < 1 or sample_size > len(data):
        raise ValueError("sample_size must be between 1 and population size")

    k = len(data) // sample_size
    if k < 1:
        k = 1

    sample = []
    idx = start % len(data)

    for _ in range(sample_size):
        if idx < len(data):
            sample.append(data[idx])
        idx = (idx + k) % len(data)

    return sample[:sample_size]


def reservoir_sample(data: list, sample_size: int) -> list:
    """
    Draw random sample using Vitter's reservoir sampling algorithm.
    Works with streaming data without knowing population size in advance.

    Args:
        data: Population to sample from (or stream).
        sample_size: Size of sample to draw.

    Returns:
        Random sample.

    Raises:
        ValueError: If sample_size is invalid.
    """
    if sample_size < 1:
        raise ValueError("sample_size must be at least 1")

    reservoir = []

    for i, item in enumerate(data):
        if i < sample_size:
            reservoir.append(item)
        else:
            j = random.randint(0, i)
            if j < sample_size:
                reservoir[j] = item

    return reservoir


def bootstrap_sample(data: list, sample_size: int = None) -> list:
    """
    Draw bootstrap sample (with replacement).

    Args:
        data: Population to sample from.
        sample_size: Size of sample (default: same as data).

    Returns:
        Bootstrap sample.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    if sample_size is None:
        sample_size = len(data)

    return [random.choice(data) for _ in range(sample_size)]


def jackknife_sample(data: list) -> list[list]:
    """
    Generate jackknife samples (leave-one-out).

    Args:
        data: Population.

    Returns:
        List of jackknife samples (each with n-1 elements).

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    samples = []

    for i in range(len(data)):
        sample = data[:i] + data[i + 1 :]
        samples.append(sample)

    return samples


def sample_size_mean(std: float, margin_error: float, confidence_level: float = 0.95) -> int:
    """
    Calculate sample size needed for estimating a mean.

    Args:
        std: Population standard deviation estimate.
        margin_error: Desired margin of error.
        confidence_level: Confidence level (default 0.95).

    Returns:
        Required sample size.

    Raises:
        ValueError: If parameters are invalid.
    """
    if std <= 0 or margin_error <= 0:
        raise ValueError("std and margin_error must be positive")

    if not (0 < confidence_level < 1):
        raise ValueError("confidence_level must be in (0, 1)")

    alpha = 1 - confidence_level
    z_crit = abs(dist.normal_icdf(alpha / 2))

    n = (z_crit * std / margin_error) ** 2

    return math.ceil(n)


def sample_size_proportion(p: float, margin_error: float, confidence_level: float = 0.95) -> int:
    """
    Calculate sample size needed for estimating a proportion.

    Args:
        p: Estimated proportion (0-1). Use 0.5 if unknown.
        margin_error: Desired margin of error.
        confidence_level: Confidence level (default 0.95).

    Returns:
        Required sample size.

    Raises:
        ValueError: If parameters are invalid.
    """
    if not (0 <= p <= 1) or margin_error <= 0:
        raise ValueError("p must be in [0, 1] and margin_error must be positive")

    if not (0 < confidence_level < 1):
        raise ValueError("confidence_level must be in (0, 1)")

    alpha = 1 - confidence_level
    z_crit = abs(dist.normal_icdf(alpha / 2))

    n = (z_crit**2 * p * (1 - p)) / (margin_error**2)

    return math.ceil(n)


def power_analysis(effect_size: float, alpha: float = 0.05, power: float = 0.80, test_type: str = "two-sided") -> int:
    """
    Calculate sample size for desired statistical power (two-sample t-test).

    Args:
        effect_size: Cohen's d (0.2=small, 0.5=medium, 0.8=large).
        alpha: Significance level (default 0.05).
        power: Desired power (default 0.80).
        test_type: "two-sided", "greater", or "less".

    Returns:
        Required sample size per group.

    Raises:
        ValueError: If parameters are invalid.
    """
    if effect_size <= 0 or not (0 < alpha < 1) or not (0 < power < 1):
        raise ValueError("Parameters must be in valid ranges")

    z_alpha = abs(dist.normal_icdf(alpha / (2 if test_type == "two-sided" else 1)))
    z_beta = abs(dist.normal_icdf(power))

    n = 2 * ((z_alpha + z_beta) / effect_size) ** 2

    return math.ceil(n)


def finite_population_correction(sample_size: int, population_size: int) -> float:
    """
    Calculate finite population correction factor.

    Args:
        sample_size: Size of sample.
        population_size: Size of population.

    Returns:
        Correction factor (multiply standard error by this).

    Raises:
        ValueError: If parameters are invalid.
    """
    if sample_size < 1 or population_size < 1:
        raise ValueError("Sizes must be positive")

    if sample_size > population_size:
        raise ValueError("Sample size cannot exceed population size")

    return math.sqrt((population_size - sample_size) / (population_size - 1))
