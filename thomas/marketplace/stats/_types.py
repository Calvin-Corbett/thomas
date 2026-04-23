"""Type definitions and data classes for the statistics module."""

from dataclasses import dataclass


@dataclass
class DescriptiveStats:
    """Summary of descriptive statistics for a dataset."""

    mean: float
    median: float
    mode: float | None
    std: float
    variance: float
    min: float
    max: float
    range: float
    q1: float
    q3: float
    iqr: float
    skewness: float | None
    kurtosis: float | None
    count: int


@dataclass
class DistributionParams:
    """Parameters of a probability distribution."""

    params: dict
    log_likelihood: float
    aic: float
    bic: float


@dataclass
class TestResult:
    """Result of a statistical hypothesis test."""

    statistic: float
    p_value: float
    df: float | None
    reject_null: bool


@dataclass
class ConfidenceInterval:
    """Confidence interval with bounds and coverage level."""

    lower: float
    upper: float
    center: float
    level: float


@dataclass
class CorrelationResult:
    """Result of correlation analysis between two variables."""

    coefficient: float
    p_value: float
    n: int
    method: str


@dataclass
class RegressionResult:
    """Result of regression analysis."""

    coefficients: list[float]
    intercept: float
    r_squared: float
    adj_r_squared: float
    residuals: list[float]
    fitted_values: list[float]
    std_errors: list[float]
    t_stats: list[float]
    p_values: list[float]
    f_statistic: float
    f_p_value: float
    aic: float
    bic: float
    observations: int


@dataclass
class SampleStats:
    """Statistics of a sample."""

    mean: float
    std: float
    n: int
    se: float
