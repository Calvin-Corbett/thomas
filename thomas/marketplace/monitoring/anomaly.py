"""
Anomaly detection system.

Statistical methods including Z-score, MAD, EWMA, Holt-Winters,
dynamic thresholds, change point detection, and correlation analysis.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime

from thomas.marketplace.monitoring._types import MetricSample


@dataclass
class Anomaly:
    """An detected anomaly."""

    timestamp: datetime
    series_key: str
    value: float
    expected_value: float
    deviation: float
    score: float  # 0-1, higher = more anomalous
    method: str  # zscore, mad, ewma, cusum, etc
    severity: str = "warning"  # info, warning, critical


class AnomalyDetector:
    """Detects anomalies in time series data."""

    def __init__(self) -> None:
        self._window_size = 100
        self._ewma_alpha = 0.3
        self._mad_threshold = 3.0
        self._zscore_threshold = 3.0

    def zscore_anomalies(self, samples: list[MetricSample], threshold: float = 3.0) -> list[Anomaly]:
        """Detect anomalies using Z-score method."""
        if len(samples) < 2:
            return []

        values = [s.value for s in samples]
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0

        anomalies = []
        if stdev > 0:
            for sample in samples:
                zscore = abs((sample.value - mean) / stdev)
                if zscore > threshold:
                    score = min(1.0, zscore / (threshold * 2))
                    anomalies.append(
                        Anomaly(
                            timestamp=datetime.fromtimestamp(sample.timestamp),
                            series_key="",
                            value=sample.value,
                            expected_value=mean,
                            deviation=abs(sample.value - mean),
                            score=score,
                            method="zscore",
                        )
                    )

        return anomalies

    def mad_anomalies(self, samples: list[MetricSample], threshold: float = 3.0) -> list[Anomaly]:
        """Detect anomalies using Modified Z-score with Median Absolute Deviation."""
        if len(samples) < 2:
            return []

        values = [s.value for s in samples]
        median = statistics.median(values)
        deviations = [abs(v - median) for v in values]
        mad = statistics.median(deviations) if deviations else 0

        anomalies = []
        if mad > 0:
            for sample in samples:
                mod_zscore = 0.6745 * (sample.value - median) / mad if mad > 0 else 0
                if abs(mod_zscore) > threshold:
                    score = min(1.0, abs(mod_zscore) / (threshold * 2))
                    anomalies.append(
                        Anomaly(
                            timestamp=datetime.fromtimestamp(sample.timestamp),
                            series_key="",
                            value=sample.value,
                            expected_value=median,
                            deviation=abs(sample.value - median),
                            score=score,
                            method="mad",
                        )
                    )

        return anomalies

    def ewma_anomalies(
        self,
        samples: list[MetricSample],
        alpha: float = 0.3,
        band_width: float = 2.0,
    ) -> list[Anomaly]:
        """Detect anomalies using Exponential Weighted Moving Average with bands."""
        if len(samples) < 2:
            return []

        values = [s.value for s in samples]

        # Calculate EWMA
        ewma = [values[0]]
        for i in range(1, len(values)):
            ewma_val = alpha * values[i] + (1 - alpha) * ewma[i - 1]
            ewma.append(ewma_val)

        # Calculate residuals
        residuals = [values[i] - ewma[i] for i in range(len(values))]
        residual_stdev = statistics.stdev(residuals) if len(residuals) > 1 else 0

        anomalies = []
        for i, sample in enumerate(samples):
            residual = residuals[i]
            bands = band_width * residual_stdev

            if abs(residual) > bands:
                score = min(1.0, abs(residual) / (bands * 2))
                anomalies.append(
                    Anomaly(
                        timestamp=datetime.fromtimestamp(sample.timestamp),
                        series_key="",
                        value=sample.value,
                        expected_value=ewma[i],
                        deviation=abs(residual),
                        score=score,
                        method="ewma",
                    )
                )

        return anomalies

    def holt_winters_anomalies(
        self,
        samples: list[MetricSample],
        season_length: int = 12,
        alpha: float = 0.3,
        beta: float = 0.1,
    ) -> list[Anomaly]:
        """Detect anomalies using Holt-Winters seasonal method."""
        if len(samples) < season_length * 2:
            return []

        values = [s.value for s in samples]

        # Initialize level and trend
        level = statistics.mean(values[:season_length])
        trend = (
            statistics.mean(values[season_length : 2 * season_length]) - statistics.mean(values[:season_length])
        ) / season_length

        # Initialize seasonal component
        seasonal = [0] * season_length
        for i in range(season_length):
            seasonal[i] = values[i] - level

        # Forecast and detect
        anomalies = []
        for i in range(len(values)):
            season_idx = i % season_length

            # Forecast
            forecast = level + trend + seasonal[season_idx]

            # Update components
            if i < season_length:
                level = alpha * (values[i] - seasonal[season_idx]) + (1 - alpha) * (level + trend)
            else:
                level = alpha * (values[i] - seasonal[season_idx]) + (1 - alpha) * (level + trend)

            trend = beta * (level - level) + (1 - beta) * trend
            seasonal[season_idx] = (1 - alpha) * seasonal[season_idx] + alpha * (values[i] - level)

            # Check if anomalous
            residual = abs(values[i] - forecast)
            if i >= season_length and residual > 3 * statistics.stdev(values):
                score = min(1.0, residual / (3 * statistics.stdev(values)))
                anomalies.append(
                    Anomaly(
                        timestamp=datetime.fromtimestamp(samples[i].timestamp),
                        series_key="",
                        value=values[i],
                        expected_value=forecast,
                        deviation=residual,
                        score=score,
                        method="holt_winters",
                    )
                )

        return anomalies

    def cusum_anomalies(
        self,
        samples: list[MetricSample],
        threshold: float = 5.0,
        drift: float = 0.0,
    ) -> list[Anomaly]:
        """Detect change points using CUSUM (Cumulative Sum) algorithm."""
        if len(samples) < 10:
            return []

        values = [s.value for s in samples]
        mean = statistics.mean(values[:10])
        stdev = statistics.stdev(values[:10])

        cusum_pos = 0
        cusum_neg = 0
        anomalies = []

        for i, sample in enumerate(samples):
            # Normalized value
            z_score = (sample.value - mean) / stdev if stdev > 0 else 0

            # CUSUM update
            cusum_pos = max(0, cusum_pos + z_score - drift)
            cusum_neg = min(0, cusum_neg + z_score + drift)

            # Detect changes
            if cusum_pos > threshold or cusum_neg < -threshold:
                score = min(1.0, (abs(cusum_pos) + abs(cusum_neg)) / (threshold * 2))
                anomalies.append(
                    Anomaly(
                        timestamp=datetime.fromtimestamp(sample.timestamp),
                        series_key="",
                        value=sample.value,
                        expected_value=mean,
                        deviation=abs(sample.value - mean),
                        score=score,
                        method="cusum",
                    )
                )

                # Reset CUSUM
                if cusum_pos > threshold:
                    cusum_pos = 0
                if cusum_neg < -threshold:
                    cusum_neg = 0

        return anomalies

    def dynamic_threshold_anomalies(
        self,
        samples: list[MetricSample],
        percentile_lower: float = 10,
        percentile_upper: float = 90,
    ) -> list[Anomaly]:
        """Detect anomalies using dynamic percentile-based thresholds."""
        if len(samples) < 10:
            return []

        values = sorted([s.value for s in samples])
        n = len(values)

        lower_idx = int(n * percentile_lower / 100)
        upper_idx = int(n * percentile_upper / 100)

        lower_threshold = values[lower_idx]
        upper_threshold = values[upper_idx]

        anomalies = []
        for sample in samples:
            if sample.value < lower_threshold or sample.value > upper_threshold:
                if sample.value > upper_threshold:
                    deviation = sample.value - upper_threshold
                    expected = upper_threshold
                else:
                    deviation = lower_threshold - sample.value
                    expected = lower_threshold

                score = min(1.0, deviation / ((upper_threshold - lower_threshold) * 0.5))
                anomalies.append(
                    Anomaly(
                        timestamp=datetime.fromtimestamp(sample.timestamp),
                        series_key="",
                        value=sample.value,
                        expected_value=expected,
                        deviation=deviation,
                        score=score,
                        method="dynamic_threshold",
                    )
                )

        return anomalies

    def correlation_analysis(
        self,
        series_data: dict[str, list[MetricSample]],
    ) -> dict[tuple[str, str], float]:
        """Analyze correlation between series."""
        correlations = {}

        series_keys = list(series_data.keys())
        for i, key1 in enumerate(series_keys):
            for key2 in series_keys[i + 1 :]:
                samples1 = series_data[key1]
                samples2 = series_data[key2]

                if len(samples1) < 2 or len(samples2) < 2:
                    continue

                # Align timestamps
                ts_set = {s.timestamp for s in samples1} & {s.timestamp for s in samples2}

                if len(ts_set) < 2:
                    continue

                values1 = [s.value for s in samples1 if s.timestamp in ts_set]
                values2 = [s.value for s in samples2 if s.timestamp in ts_set]

                if len(values1) == len(values2) and len(values1) > 1:
                    corr = self._pearson_correlation(values1, values2)
                    correlations[(key1, key2)] = corr

        return correlations

    def _pearson_correlation(self, x: list[float], y: list[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)

        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))

        stdev_x = statistics.stdev(x) if len(x) > 1 else 0
        stdev_y = statistics.stdev(y) if len(y) > 1 else 0

        if stdev_x == 0 or stdev_y == 0:
            return 0.0

        denominator = stdev_x * stdev_y * len(x)

        return numerator / denominator if denominator != 0 else 0.0

    def rank_anomalies(self, anomalies: list[Anomaly]) -> list[Anomaly]:
        """Rank anomalies by severity score."""
        return sorted(anomalies, key=lambda a: a.score, reverse=True)

    def filter_anomalies(self, anomalies: list[Anomaly], min_score: float = 0.5) -> list[Anomaly]:
        """Filter anomalies by minimum score."""
        return [a for a in anomalies if a.score >= min_score]
