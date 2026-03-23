"""Hypothesis testing methods."""

import math

from . import descriptive as desc
from . import distributions as dist
from ._exceptions import InsufficientDataError
from ._types import TestResult


def _t_test_p_value(t_stat: float, df: float, two_tailed: bool = True) -> float:
    """Calculate p-value from t-statistic."""
    cdf_val = dist.t_cdf(abs(t_stat), df)
    p = 1 - cdf_val
    return 2 * p if two_tailed else p


def _chi2_test_p_value(chi2_stat: float, df: float) -> float:
    """Calculate p-value from chi-squared statistic."""
    return 1 - dist.chi2_cdf(chi2_stat, df)


def one_sample_t_test(data: list[float], mu: float = 0, alternative: str = "two-sided") -> TestResult:
    """
    One-sample t-test against a hypothesized mean.

    Args:
        data: List of numeric values.
        mu: Hypothesized mean (default 0).
        alternative: "two-sided", "greater", or "less".

    Returns:
        TestResult with t-statistic, p-value, and degrees of freedom.

    Raises:
        InsufficientDataError: If data has fewer than 2 values.
        ValueError: If alternative is invalid.
    """
    if len(data) < 2:
        raise InsufficientDataError("Need at least 2 values for t-test")

    if alternative not in ("two-sided", "greater", "less"):
        raise ValueError("alternative must be 'two-sided', 'greater', or 'less'")

    n = len(data)
    sample_mean = desc.mean(data)
    sample_std = desc.std(data, sample=True)
    df = n - 1

    if sample_std == 0:
        t_stat = 0 if sample_mean == mu else float("inf")
    else:
        t_stat = (sample_mean - mu) / (sample_std / math.sqrt(n))

    if alternative == "two-sided":
        p_value = _t_test_p_value(t_stat, df, two_tailed=True)
    elif alternative == "greater":
        cdf_val = dist.t_cdf(t_stat, df)
        p_value = 1 - cdf_val
    else:  # less
        p_value = dist.t_cdf(t_stat, df)

    reject_null = p_value < 0.05

    return TestResult(statistic=t_stat, p_value=p_value, df=float(df), reject_null=reject_null)


def two_sample_t_test(
    data1: list[float], data2: list[float], equal_var: bool = False, alternative: str = "two-sided"
) -> TestResult:
    """
    Two-sample t-test (Welch's if equal_var=False).

    Args:
        data1: First sample.
        data2: Second sample.
        equal_var: If True, use standard t-test. If False, use Welch's test.
        alternative: "two-sided", "greater", or "less".

    Returns:
        TestResult with t-statistic, p-value, and degrees of freedom.

    Raises:
        InsufficientDataError: If either sample is too small.
        ValueError: If alternative is invalid.
    """
    if len(data1) < 2 or len(data2) < 2:
        raise InsufficientDataError("Each sample needs at least 2 values")

    if alternative not in ("two-sided", "greater", "less"):
        raise ValueError("alternative must be 'two-sided', 'greater', or 'less'")

    n1 = len(data1)
    n2 = len(data2)
    mean1 = desc.mean(data1)
    mean2 = desc.mean(data2)
    std1 = desc.std(data1, sample=True)
    std2 = desc.std(data2, sample=True)

    if equal_var:
        pooled_var = ((n1 - 1) * std1**2 + (n2 - 1) * std2**2) / (n1 + n2 - 2)
        se = math.sqrt(pooled_var * (1 / n1 + 1 / n2))
        df = n1 + n2 - 2
    else:
        var1 = std1**2
        var2 = std2**2
        se = math.sqrt(var1 / n1 + var2 / n2)

        numerator = (var1 / n1 + var2 / n2) ** 2
        denominator = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        df = numerator / denominator if denominator > 0 else n1 + n2 - 2

    if se == 0:
        t_stat = 0 if mean1 == mean2 else float("inf")
    else:
        t_stat = (mean1 - mean2) / se

    if alternative == "two-sided":
        p_value = _t_test_p_value(t_stat, df, two_tailed=True)
    elif alternative == "greater":
        cdf_val = dist.t_cdf(t_stat, df)
        p_value = 1 - cdf_val
    else:  # less
        p_value = dist.t_cdf(t_stat, df)

    reject_null = p_value < 0.05

    return TestResult(statistic=t_stat, p_value=p_value, df=df, reject_null=reject_null)


def paired_t_test(data1: list[float], data2: list[float]) -> TestResult:
    """
    Paired t-test (one-sample t-test on differences).

    Args:
        data1: First paired sample.
        data2: Second paired sample (must have same length as data1).

    Returns:
        TestResult with t-statistic, p-value, and degrees of freedom.

    Raises:
        InsufficientDataError: If samples are too small.
        ValueError: If samples have different lengths.
    """
    if len(data1) != len(data2):
        raise ValueError("data1 and data2 must have the same length")

    if len(data1) < 2:
        raise InsufficientDataError("Need at least 2 pairs for paired t-test")

    differences = [d1 - d2 for d1, d2 in zip(data1, data2)]
    return one_sample_t_test(differences, mu=0, alternative="two-sided")


def chi2_goodness_of_fit(observed: list[float], expected: list[float]) -> TestResult:
    """
    Chi-squared goodness of fit test.

    Args:
        observed: Observed frequencies.
        expected: Expected frequencies (must have same length as observed).

    Returns:
        TestResult with chi-squared statistic, p-value, and degrees of freedom.

    Raises:
        ValueError: If lengths don't match or expected has values <= 0.
    """
    if len(observed) != len(expected):
        raise ValueError("observed and expected must have same length")

    if any(e <= 0 for e in expected):
        raise ValueError("All expected frequencies must be positive")

    chi2_stat = sum((o - e) ** 2 / e for o, e in zip(observed, expected))
    df = len(observed) - 1

    p_value = _chi2_test_p_value(chi2_stat, df)
    reject_null = p_value < 0.05

    return TestResult(statistic=chi2_stat, p_value=p_value, df=float(df), reject_null=reject_null)


def chi2_contingency(contingency_table: list[list[int]]) -> TestResult:
    """
    Chi-squared test of independence for contingency table.

    Args:
        contingency_table: 2D list of observed frequencies.

    Returns:
        TestResult with chi-squared statistic, p-value, and degrees of freedom.

    Raises:
        ValueError: If table is invalid.
    """
    if not contingency_table or not all(contingency_table):
        raise ValueError("Contingency table cannot be empty")

    rows = len(contingency_table)
    cols = len(contingency_table[0])

    if not all(len(row) == cols for row in contingency_table):
        raise ValueError("All rows must have the same length")

    row_totals = [sum(row) for row in contingency_table]
    col_totals = [sum(contingency_table[i][j] for i in range(rows)) for j in range(cols)]
    grand_total = sum(row_totals)

    if grand_total == 0:
        raise ValueError("Grand total cannot be zero")

    chi2_stat = 0
    for i in range(rows):
        for j in range(cols):
            expected = (row_totals[i] * col_totals[j]) / grand_total
            if expected > 0:
                chi2_stat += (contingency_table[i][j] - expected) ** 2 / expected

    df = (rows - 1) * (cols - 1)
    p_value = _chi2_test_p_value(chi2_stat, df)
    reject_null = p_value < 0.05

    return TestResult(statistic=chi2_stat, p_value=p_value, df=float(df), reject_null=reject_null)


def mann_whitney_u(data1: list[float], data2: list[float]) -> TestResult:
    """
    Mann-Whitney U test (nonparametric alternative to t-test).

    Args:
        data1: First sample.
        data2: Second sample.

    Returns:
        TestResult with U statistic, p-value, and degrees of freedom (None).

    Raises:
        InsufficientDataError: If either sample is empty.
    """
    if not data1 or not data2:
        raise InsufficientDataError("Both samples must be non-empty")

    combined = [(x, 1) for x in data1] + [(x, 2) for x in data2]
    combined.sort()

    n1 = len(data1)
    n2 = len(data2)
    rank_sum1 = sum(i + 1 for i, (_, group) in enumerate(combined) if group == 1)

    u1 = rank_sum1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    u_stat = min(u1, u2)

    mean_u = n1 * n2 / 2
    var_u = n1 * n2 * (n1 + n2 + 1) / 12

    if var_u == 0:
        p_value = 1.0
    else:
        z_stat = (u_stat - mean_u) / math.sqrt(var_u)
        p_value = 2 * (1 - dist._normal_cdf(abs(z_stat)))

    reject_null = p_value < 0.05

    return TestResult(statistic=u_stat, p_value=p_value, df=None, reject_null=reject_null)


def wilcoxon_signed_rank(data1: list[float], data2: list[float]) -> TestResult:
    """
    Wilcoxon signed-rank test (nonparametric paired test).

    Args:
        data1: First paired sample.
        data2: Second paired sample.

    Returns:
        TestResult with W statistic, p-value, and degrees of freedom (None).

    Raises:
        ValueError: If samples have different lengths.
        InsufficientDataError: If samples are too small.
    """
    if len(data1) != len(data2):
        raise ValueError("Samples must have the same length")

    if len(data1) < 2:
        raise InsufficientDataError("Need at least 2 pairs")

    differences = [d1 - d2 for d1, d2 in zip(data1, data2)]
    abs_diff = [abs(d) for d in differences if d != 0]

    if not abs_diff:
        return TestResult(statistic=0, p_value=1.0, df=None, reject_null=False)

    ranked = sorted(enumerate(abs_diff), key=lambda x: x[1])
    rank_dict = {}
    current_rank = 1
    i = 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][1] == ranked[i][1]:
            j += 1
        avg_rank = (current_rank + j) / 2
        for k in range(i, j):
            rank_dict[ranked[k][0]] = avg_rank
        current_rank = j + 1
        i = j

    w_stat = sum(rank_dict[i] for i, d in enumerate(differences) if d > 0)

    n = len(abs_diff)
    mean_w = n * (n + 1) / 4
    var_w = n * (n + 1) * (2 * n + 1) / 24

    if var_w == 0:
        p_value = 1.0
    else:
        z_stat = (w_stat - mean_w) / math.sqrt(var_w)
        p_value = 2 * (1 - dist._normal_cdf(abs(z_stat)))

    reject_null = p_value < 0.05

    return TestResult(statistic=w_stat, p_value=p_value, df=None, reject_null=reject_null)


def f_test_equal_variance(data1: list[float], data2: list[float]) -> TestResult:
    """
    F-test for equality of variances.

    Args:
        data1: First sample.
        data2: Second sample.

    Returns:
        TestResult with F statistic, p-value, and degrees of freedom.

    Raises:
        InsufficientDataError: If either sample is too small.
    """
    if len(data1) < 2 or len(data2) < 2:
        raise InsufficientDataError("Each sample needs at least 2 values")

    var1 = desc.variance(data1, sample=True)
    var2 = desc.variance(data2, sample=True)

    if var1 >= var2:
        f_stat = var1 / var2 if var2 > 0 else float("inf")
        df1 = len(data1) - 1
        df2 = len(data2) - 1
    else:
        f_stat = var2 / var1 if var1 > 0 else float("inf")
        df1 = len(data2) - 1
        df2 = len(data1) - 1

    cdf_val = dist.f_cdf(f_stat, df1, df2)
    p_value = 2 * (1 - cdf_val)

    reject_null = p_value < 0.05

    return TestResult(statistic=f_stat, p_value=p_value, df=float(df1), reject_null=reject_null)


def kolmogorov_smirnov(data: list[float], cdf_func) -> TestResult:
    """
    Kolmogorov-Smirnov test for goodness of fit.

    Args:
        data: Sample data.
        cdf_func: CDF function to test against (takes x and returns probability).

    Returns:
        TestResult with KS statistic, p-value, and degrees of freedom (None).

    Raises:
        InsufficientDataError: If data is empty.
    """
    if not data:
        raise InsufficientDataError("Data cannot be empty")

    sorted_data = sorted(data)
    n = len(sorted_data)

    ks_stat = 0
    for i, x in enumerate(sorted_data):
        cdf_val = cdf_func(x)
        d_plus = (i + 1) / n - cdf_val
        d_minus = cdf_val - i / n
        ks_stat = max(ks_stat, d_plus, d_minus)

    p_value = math.exp(-2 * n * ks_stat**2)

    reject_null = p_value < 0.05

    return TestResult(statistic=ks_stat, p_value=p_value, df=None, reject_null=reject_null)


def one_way_anova(groups: list[list[float]]) -> TestResult:
    """
    One-way ANOVA test.

    Args:
        groups: List of groups (each group is a list of values).

    Returns:
        TestResult with F statistic, p-value, and degrees of freedom.

    Raises:
        ValueError: If less than 2 groups or groups are invalid.
        InsufficientDataError: If any group is empty.
    """
    if len(groups) < 2:
        raise ValueError("Need at least 2 groups")

    if any(not g for g in groups):
        raise InsufficientDataError("No group can be empty")

    k = len(groups)
    n = sum(len(g) for g in groups)
    grand_mean = sum(sum(g) for g in groups) / n

    ss_between = sum(len(g) * (desc.mean(g) - grand_mean) ** 2 for g in groups)
    ss_within = sum(sum((x - desc.mean(g)) ** 2 for x in g) for g in groups)

    df_between = k - 1
    df_within = n - k

    if df_within == 0:
        raise ValueError("Insufficient degrees of freedom")

    ms_between = ss_between / df_between
    ms_within = ss_within / df_within

    if ms_within == 0:
        f_stat = 0 if ms_between == 0 else float("inf")
    else:
        f_stat = ms_between / ms_within

    p_value = 1 - dist.f_cdf(f_stat, df_between, df_within)
    reject_null = p_value < 0.05

    return TestResult(statistic=f_stat, p_value=p_value, df=float(df_between), reject_null=reject_null)
