"""Descriptive statistics calculations."""

from ._exceptions import InsufficientDataError
from ._types import DescriptiveStats


def mean(data: list[float]) -> float:
    """
    Calculate the arithmetic mean.

    Args:
        data: List of numeric values.

    Returns:
        The arithmetic mean.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate mean of empty dataset")
    return sum(data) / len(data)


def weighted_mean(data: list[float], weights: list[float]) -> float:
    """
    Calculate the weighted mean.

    Args:
        data: List of numeric values.
        weights: List of weights (must have same length as data).

    Returns:
        The weighted mean.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If weights don't match data length.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate weighted mean of empty dataset")
    if len(data) != len(weights):
        raise ValueError("Data and weights must have same length")

    weight_sum = sum(weights)
    if weight_sum == 0:
        raise ValueError("Sum of weights cannot be zero")

    return sum(d * w for d, w in zip(data, weights)) / weight_sum


def geometric_mean(data: list[float]) -> float:
    """
    Calculate the geometric mean.

    Args:
        data: List of positive numeric values.

    Returns:
        The geometric mean.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If any value is non-positive.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate geometric mean of empty dataset")
    if any(x <= 0 for x in data):
        raise ValueError("All values must be positive for geometric mean")

    n = len(data)
    product = 1.0
    for x in data:
        product *= x

    return product ** (1.0 / n)


def harmonic_mean(data: list[float]) -> float:
    """
    Calculate the harmonic mean.

    Args:
        data: List of positive numeric values.

    Returns:
        The harmonic mean.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If any value is non-positive.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate harmonic mean of empty dataset")
    if any(x <= 0 for x in data):
        raise ValueError("All values must be positive for harmonic mean")

    n = len(data)
    reciprocal_sum = sum(1.0 / x for x in data)
    return n / reciprocal_sum


def median(data: list[float]) -> float:
    """
    Calculate the median using linear interpolation for even-sized datasets.

    Args:
        data: List of numeric values.

    Returns:
        The median.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate median of empty dataset")

    sorted_data = sorted(data)
    n = len(sorted_data)

    if n % 2 == 1:
        return sorted_data[n // 2]
    else:
        mid = n // 2
        return (sorted_data[mid - 1] + sorted_data[mid]) / 2.0


def mode(data: list[float]) -> float | None:
    """
    Calculate the mode (most frequent value).

    Args:
        data: List of numeric values.

    Returns:
        The mode, or None if all values occur with equal frequency.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate mode of empty dataset")

    freq = {}
    for val in data:
        freq[val] = freq.get(val, 0) + 1

    max_freq = max(freq.values())
    modes = [k for k, v in freq.items() if v == max_freq]

    if len(modes) == len(freq):
        return None

    return min(modes)


def variance(data: list[float], sample: bool = False) -> float:
    """
    Calculate the variance.

    Args:
        data: List of numeric values.
        sample: If True, calculate sample variance (divide by n-1).
                If False, calculate population variance (divide by n).

    Returns:
        The variance.

    Raises:
        InsufficientDataError: If data is empty or too small for sample variance.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate variance of empty dataset")

    if sample and len(data) < 2:
        raise InsufficientDataError("Need at least 2 values for sample variance")

    m = mean(data)
    n = len(data)
    denom = n - 1 if sample else n

    ss = sum((x - m) ** 2 for x in data)
    return ss / denom


def std(data: list[float], sample: bool = False) -> float:
    """
    Calculate the standard deviation.

    Args:
        data: List of numeric values.
        sample: If True, calculate sample std (divide by n-1).
                If False, calculate population std (divide by n).

    Returns:
        The standard deviation.

    Raises:
        InsufficientDataError: If data is empty or too small for sample std.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate std of empty dataset")

    return variance(data, sample=sample) ** 0.5


def z_score(x: float, data: list[float], sample: bool = True) -> float:
    """
    Calculate the z-score for a value.

    Args:
        x: The value to standardize.
        data: List of numeric values for reference distribution.
        sample: If True, use sample std. If False, use population std.

    Returns:
        The z-score.

    Raises:
        InsufficientDataError: If data is empty or too small.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate z-score of empty dataset")

    m = mean(data)
    s = std(data, sample=sample)

    if s == 0:
        raise ValueError("Standard deviation is zero; cannot calculate z-score")

    return (x - m) / s


def coefficient_of_variation(data: list[float]) -> float:
    """
    Calculate the coefficient of variation (CV = std / mean).

    Args:
        data: List of numeric values.

    Returns:
        The coefficient of variation.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If mean is zero.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate CV of empty dataset")

    m = mean(data)
    if m == 0:
        raise ValueError("Mean is zero; cannot calculate coefficient of variation")

    s = std(data, sample=True)
    return s / abs(m)


def trimmed_mean(data: list[float], trim: float = 0.1) -> float:
    """
    Calculate the trimmed mean (mean after removing top and bottom trim fraction).

    Args:
        data: List of numeric values.
        trim: Fraction to trim from each end (default 0.1 = 10%).

    Returns:
        The trimmed mean.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If trim is not in [0, 0.5].
    """
    if not data:
        raise InsufficientDataError("Cannot calculate trimmed mean of empty dataset")

    if not (0 <= trim <= 0.5):
        raise ValueError("trim must be between 0 and 0.5")

    sorted_data = sorted(data)
    n = len(sorted_data)
    trim_count = int(n * trim)

    return mean(sorted_data[trim_count : n - trim_count])


def winsorized_mean(data: list[float], limits: float = 0.1) -> float:
    """
    Calculate the winsorized mean (mean after replacing extremes with limits).

    Args:
        data: List of numeric values.
        limits: Fraction to winsorize on each end (default 0.1 = 10%).

    Returns:
        The winsorized mean.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If limits is not in [0, 0.5].
    """
    if not data:
        raise InsufficientDataError("Cannot calculate winsorized mean of empty dataset")

    if not (0 <= limits <= 0.5):
        raise ValueError("limits must be between 0 and 0.5")

    sorted_data = sorted(data)
    n = len(sorted_data)
    limit_count = int(n * limits)

    lower_val = sorted_data[limit_count] if limit_count < n else sorted_data[0]
    upper_val = sorted_data[n - limit_count - 1] if limit_count < n else sorted_data[-1]

    winsorized = [min(max(x, lower_val), upper_val) for x in data]

    return mean(winsorized)


def percentile(data: list[float], p: float) -> float:
    """
    Calculate the percentile using linear interpolation.

    Args:
        data: List of numeric values.
        p: Percentile level (0-100).

    Returns:
        The percentile value.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If p is not in [0, 100].
    """
    if not data:
        raise InsufficientDataError("Cannot calculate percentile of empty dataset")

    if not (0 <= p <= 100):
        raise ValueError("Percentile must be between 0 and 100")

    sorted_data = sorted(data)
    n = len(sorted_data)

    index = (p / 100.0) * (n - 1)
    lower_idx = int(index)
    upper_idx = lower_idx + 1

    if upper_idx >= n:
        return sorted_data[-1]

    fraction = index - lower_idx
    return sorted_data[lower_idx] * (1 - fraction) + sorted_data[upper_idx] * fraction


def quantile(data: list[float], q: float) -> float:
    """
    Calculate the quantile (q in [0, 1]).

    Args:
        data: List of numeric values.
        q: Quantile level (0-1).

    Returns:
        The quantile value.

    Raises:
        InsufficientDataError: If data is empty.
        ValueError: If q is not in [0, 1].
    """
    if not (0 <= q <= 1):
        raise ValueError("Quantile must be between 0 and 1")

    return percentile(data, q * 100)


def range_val(data: list[float]) -> float:
    """
    Calculate the range (max - min).

    Args:
        data: List of numeric values.

    Returns:
        The range.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate range of empty dataset")

    return max(data) - min(data)


def iqr(data: list[float]) -> float:
    """
    Calculate the interquartile range (Q3 - Q1).

    Args:
        data: List of numeric values.

    Returns:
        The IQR.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate IQR of empty dataset")

    q1 = quantile(data, 0.25)
    q3 = quantile(data, 0.75)
    return q3 - q1


def skewness(data: list[float]) -> float | None:
    """
    Calculate the skewness using Fisher's moment coefficient.

    Args:
        data: List of numeric values.

    Returns:
        The skewness, or None if std is zero.

    Raises:
        InsufficientDataError: If data has fewer than 3 values.
    """
    if len(data) < 3:
        raise InsufficientDataError("Need at least 3 values for skewness")

    m = mean(data)
    s = std(data, sample=True)

    if s == 0:
        return None

    n = len(data)
    third_moment = sum((x - m) ** 3 for x in data) / n

    return third_moment / (s**3)


def kurtosis(data: list[float]) -> float | None:
    """
    Calculate the excess kurtosis (Fisher's definition, so normal = 0).

    Args:
        data: List of numeric values.

    Returns:
        The excess kurtosis, or None if std is zero.

    Raises:
        InsufficientDataError: If data has fewer than 4 values.
    """
    if len(data) < 4:
        raise InsufficientDataError("Need at least 4 values for kurtosis")

    m = mean(data)
    s = std(data, sample=True)

    if s == 0:
        return None

    n = len(data)
    fourth_moment = sum((x - m) ** 4 for x in data) / n

    return (fourth_moment / (s**4)) - 3.0


def five_number_summary(data: list[float]) -> tuple[float, float, float, float, float]:
    """
    Calculate the five-number summary: (min, Q1, median, Q3, max).

    Args:
        data: List of numeric values.

    Returns:
        Tuple of (min, Q1, median, Q3, max).

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot calculate summary of empty dataset")

    min_val = min(data)
    q1_val = quantile(data, 0.25)
    med_val = median(data)
    q3_val = quantile(data, 0.75)
    max_val = max(data)

    return (min_val, q1_val, med_val, q3_val, max_val)


def describe(data: list[float]) -> DescriptiveStats:
    """
    Generate a comprehensive summary of descriptive statistics.

    Args:
        data: List of numeric values.

    Returns:
        DescriptiveStats object with all key statistics.

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Cannot describe empty dataset")

    m = mean(data)
    med = median(data)
    mod = mode(data)
    v = variance(data, sample=True)
    s = std(data, sample=True)
    min_val = min(data)
    max_val = max(data)
    r = range_val(data)
    q1_val = quantile(data, 0.25)
    q3_val = quantile(data, 0.75)
    iqr_val = iqr(data)
    skew = skewness(data) if len(data) >= 3 else None
    kurt = kurtosis(data) if len(data) >= 4 else None

    return DescriptiveStats(
        mean=m,
        median=med,
        mode=mod,
        std=s,
        variance=v,
        min=min_val,
        max=max_val,
        range=r,
        q1=q1_val,
        q3=q3_val,
        iqr=iqr_val,
        skewness=skew,
        kurtosis=kurt,
        count=len(data),
    )
