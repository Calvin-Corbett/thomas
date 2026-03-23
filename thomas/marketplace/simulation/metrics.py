"""
Simulation metrics collection and analysis.

Provides time-series recording, warm-up detection, steady-state estimation,
confidence intervals, and sensitivity analysis.
"""

import math
from dataclasses import dataclass, field

from ._exceptions import MetricsError
from ._types import MetricSample


@dataclass
class BatchMean:
    """Statistics for batch means analysis."""

    batch_means: list[float] = field(default_factory=list)
    overall_mean: float = 0.0
    std_error: float = 0.0
    confidence_interval: tuple[float, float] = (0.0, 0.0)
    num_batches: int = 0


class MetricsCollector:
    """Collect and aggregate simulation metrics."""

    def __init__(self, warmup_time: float = 0.0) -> None:
        """
        Initialize metrics collector.

        Args:
            warmup_time: Transient period before collecting metrics
        """
        self.warmup_time = warmup_time
        self.samples: list[MetricSample] = []
        self.metrics: dict[str, list[float]] = {}

    def record(
        self,
        metric_name: str,
        value: float,
        time: float,
        agent_id: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        """
        Record metric sample.

        Args:
            metric_name: Name of metric
            value: Measured value
            time: Simulation time
            agent_id: Associated agent (optional)
            metadata: Additional context
        """
        if time < self.warmup_time:
            return

        sample = MetricSample(
            metric_name=metric_name,
            value=value,
            time=time,
            agent_id=agent_id,
            metadata=metadata or {},
        )

        self.samples.append(sample)

        if metric_name not in self.metrics:
            self.metrics[metric_name] = []

        self.metrics[metric_name].append(value)

    def get_samples(self, metric_name: str | None = None) -> list[MetricSample]:
        """Get recorded samples."""
        if metric_name is None:
            return self.samples

        return [s for s in self.samples if s.metric_name == metric_name]

    def get_timeseries(self, metric_name: str) -> list[tuple[float, float]]:
        """Get (time, value) pairs for metric."""
        return [(s.time, s.value) for s in self.samples if s.metric_name == metric_name]

    def compute_statistics(self, metric_name: str) -> dict[str, float]:
        """Compute summary statistics for metric."""
        values = self.metrics.get(metric_name, [])

        if not values:
            raise MetricsError(f"No data for metric: {metric_name}")

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = math.sqrt(variance)

        return {
            "mean": mean,
            "std_dev": std_dev,
            "min": min(values),
            "max": max(values),
            "count": float(len(values)),
            "sum": float(sum(values)),
            "median": sorted(values)[len(values) // 2],
        }


class BatchMeansAnalysis:
    """
    Batch means method for analyzing correlated data.

    Divides observations into batches to reduce correlation
    and compute valid confidence intervals.
    """

    def __init__(self, batch_size: int = 100, confidence_level: float = 0.95) -> None:
        """
        Initialize batch means analysis.

        Args:
            batch_size: Number of observations per batch
            confidence_level: Confidence level for intervals
        """
        self.batch_size = batch_size
        self.confidence_level = confidence_level

    def analyze(self, data: list[float]) -> BatchMean:
        """
        Perform batch means analysis.

        Args:
            data: Time series of observations

        Returns:
            Batch means statistics

        Raises:
            MetricsError: If insufficient data
        """
        if len(data) < self.batch_size:
            raise MetricsError(f"Need at least {self.batch_size} observations, got {len(data)}")

        # Compute batch means
        batch_means = []
        num_batches = len(data) // self.batch_size

        for i in range(num_batches):
            start = i * self.batch_size
            end = start + self.batch_size
            batch_data = data[start:end]
            batch_mean = sum(batch_data) / self.batch_size
            batch_means.append(batch_mean)

        # Compute overall mean and std error
        overall_mean = sum(batch_means) / len(batch_means)
        batch_variance = sum((bm - overall_mean) ** 2 for bm in batch_means) / len(batch_means)
        std_error = math.sqrt(batch_variance / len(batch_means))

        # Confidence interval (t-distribution)
        df = len(batch_means) - 1
        t_critical = 1.96 if df > 30 else self._t_value(df, self.confidence_level)
        margin = t_critical * std_error

        ci = (overall_mean - margin, overall_mean + margin)

        return BatchMean(
            batch_means=batch_means,
            overall_mean=overall_mean,
            std_error=std_error,
            confidence_interval=ci,
            num_batches=len(batch_means),
        )

    @staticmethod
    def _t_value(df: int, confidence_level: float) -> float:
        """Approximate t-critical value."""
        alpha = 1 - confidence_level

        if df >= 30:
            return 1.96

        t_values = {
            1: 12.706,
            2: 4.303,
            3: 3.182,
            4: 2.776,
            5: 2.571,
            10: 2.228,
            20: 2.086,
            30: 2.042,
        }

        return t_values.get(df, 2.0)


class WarmupDetection:
    """
    Detect transient period (warm-up) in simulation.

    Uses Welch's graphical method to identify steady-state region.
    """

    @staticmethod
    def welch_graphical_method(
        data: list[float],
        batch_size: int = 100,
        threshold: float = 0.1,
    ) -> int:
        """
        Detect warm-up period via Welch's method.

        Args:
            data: Complete time series
            batch_size: Initial batch size
            threshold: Relative change threshold

        Returns:
            Estimated warm-up length
        """
        if len(data) < batch_size * 2:
            return 0

        num_batches = len(data) // batch_size
        batch_means = []

        for i in range(num_batches):
            start = i * batch_size
            end = start + batch_size
            batch_data = data[start:end]
            batch_mean = sum(batch_data) / batch_size
            batch_means.append(batch_mean)

        # Compute cumulative average of batch means
        cumulative_means = []
        for i in range(len(batch_means)):
            cum_mean = sum(batch_means[: i + 1]) / (i + 1)
            cumulative_means.append(cum_mean)

        # Find point where mean stabilizes
        final_mean = cumulative_means[-1]
        tolerance = threshold * final_mean

        warmup_batch = 0
        for i in range(len(cumulative_means)):
            if abs(cumulative_means[i] - final_mean) > tolerance:
                warmup_batch = i

        return (warmup_batch + 1) * batch_size

    @staticmethod
    def sliding_window_variance(
        data: list[float],
        window_size: int = 100,
    ) -> list[float]:
        """
        Compute sliding window variance.

        Can indicate convergence when variance stabilizes.

        Args:
            data: Time series
            window_size: Sliding window size

        Returns:
            Variance at each window position
        """
        variances = []

        for i in range(len(data) - window_size + 1):
            window = data[i : i + window_size]
            mean = sum(window) / window_size
            variance = sum((x - mean) ** 2 for x in window) / window_size
            variances.append(variance)

        return variances


class ConfidenceIntervals:
    """Compute confidence intervals for point estimates."""

    @staticmethod
    def normal_ci(
        mean: float,
        std_dev: float,
        n: int,
        confidence_level: float = 0.95,
    ) -> tuple[float, float]:
        """
        Confidence interval assuming normal distribution.

        Args:
            mean: Sample mean
            std_dev: Sample standard deviation
            n: Sample size
            confidence_level: Confidence level

        Returns:
            (lower, upper) confidence interval
        """
        z = 1.96 if confidence_level == 0.95 else 2.576
        se = std_dev / math.sqrt(n)
        margin = z * se

        return (mean - margin, mean + margin)

    @staticmethod
    def percentile_ci(
        samples: list[float],
        confidence_level: float = 0.95,
    ) -> tuple[float, float]:
        """
        Confidence interval via percentile method.

        Args:
            samples: Sample values
            confidence_level: Confidence level

        Returns:
            (lower, upper) confidence interval
        """
        if not samples:
            raise MetricsError("No samples")

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        alpha = 1 - confidence_level
        lower_idx = int(n * (alpha / 2))
        upper_idx = int(n * (1 - alpha / 2))

        return (sorted_samples[lower_idx], sorted_samples[upper_idx])


class MultipleReplications:
    """Analyze results from multiple independent simulation runs."""

    def __init__(self) -> None:
        """Initialize replication tracker."""
        self.replications: dict[int, dict[str, list[float]]] = {}

    def record_replication(
        self,
        rep_id: int,
        metric_name: str,
        values: list[float],
    ) -> None:
        """Record metric values from a replication."""
        if rep_id not in self.replications:
            self.replications[rep_id] = {}

        self.replications[rep_id][metric_name] = values

    def aggregate_metric(self, metric_name: str, confidence_level: float = 0.95) -> dict[str, float]:
        """
        Aggregate metric across replications.

        Args:
            metric_name: Name of metric
            confidence_level: Confidence level for CI

        Returns:
            Aggregated statistics
        """
        rep_means = []

        for rep_id, metrics in self.replications.items():
            if metric_name in metrics:
                values = metrics[metric_name]
                rep_mean = sum(values) / len(values)
                rep_means.append(rep_mean)

        if not rep_means:
            raise MetricsError(f"No data for metric: {metric_name}")

        overall_mean = sum(rep_means) / len(rep_means)
        variance = sum((x - overall_mean) ** 2 for x in rep_means) / len(rep_means)
        std_dev = math.sqrt(variance)

        ci = ConfidenceIntervals.normal_ci(overall_mean, std_dev, len(rep_means), confidence_level)

        return {
            "mean": overall_mean,
            "std_dev": std_dev,
            "confidence_interval": ci,
            "num_replications": len(rep_means),
        }


class SensitivityAnalysis:
    """Analyze effect of parameter changes on outputs."""

    def __init__(self) -> None:
        """Initialize sensitivity analyzer."""
        self.results: dict[str, dict[float, float]] = {}

    def record_result(
        self,
        parameter_name: str,
        parameter_value: float,
        output_value: float,
    ) -> None:
        """Record output for parameter value."""
        if parameter_name not in self.results:
            self.results[parameter_name] = {}

        self.results[parameter_name][parameter_value] = output_value

    def compute_elasticity(self, parameter_name: str) -> float:
        """
        Compute elasticity: % change in output / % change in parameter.

        Args:
            parameter_name: Name of parameter

        Returns:
            Elasticity value
        """
        if parameter_name not in self.results:
            raise MetricsError(f"No data for parameter: {parameter_name}")

        param_values = sorted(self.results[parameter_name].keys())

        if len(param_values) < 2:
            raise MetricsError("Need at least 2 parameter values")

        p1, p2 = param_values[0], param_values[-1]
        y1 = self.results[parameter_name][p1]
        y2 = self.results[parameter_name][p2]

        pct_change_param = (p2 - p1) / p1 * 100 if p1 != 0 else 100
        pct_change_output = (y2 - y1) / y1 * 100 if y1 != 0 else 100

        if pct_change_param == 0:
            return 0.0

        return pct_change_output / pct_change_param

    def rank_parameters(self, output_metric: str = "sensitivity") -> list[tuple[str, float]]:
        """
        Rank parameters by sensitivity.

        Args:
            output_metric: Label for sensitivity measure

        Returns:
            List of (parameter_name, sensitivity) sorted by impact
        """
        elasticities = []

        for param_name in self.results.keys():
            try:
                elasticity = abs(self.compute_elasticity(param_name))
                elasticities.append((param_name, elasticity))
            except MetricsError:
                pass

        return sorted(elasticities, key=lambda x: x[1], reverse=True)
