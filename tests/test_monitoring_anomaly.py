"""
Tests for anomaly detection module.
"""

from datetime import datetime

from thomas.marketplace.monitoring._types import MetricSample
from thomas.marketplace.monitoring.anomaly import Anomaly, AnomalyDetector


class TestAnomalyDetector:
    """Test AnomalyDetector."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.detector = AnomalyDetector()

    def test_zscore_normal_data(self) -> None:
        """Test Z-score with normal data."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]

        anomalies = self.detector.zscore_anomalies(samples, threshold=3.0)
        assert len(anomalies) == 0

    def test_zscore_with_outlier(self) -> None:
        """Test Z-score detects outliers."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]
        samples.append(MetricSample(timestamp=100.0, value=100.0))

        anomalies = self.detector.zscore_anomalies(samples, threshold=3.0)
        assert len(anomalies) > 0

    def test_mad_anomalies(self) -> None:
        """Test MAD anomaly detection."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]
        samples.append(MetricSample(timestamp=100.0, value=50.0))

        anomalies = self.detector.mad_anomalies(samples, threshold=3.0)
        assert isinstance(anomalies, list)

    def test_ewma_anomalies(self) -> None:
        """Test EWMA anomaly detection."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]

        anomalies = self.detector.ewma_anomalies(samples, alpha=0.3)
        assert isinstance(anomalies, list)

    def test_holt_winters_anomalies(self) -> None:
        """Test Holt-Winters anomaly detection."""
        # Create seasonal data
        samples = []
        for cycle in range(3):
            for i in range(12):
                value = 10.0 + 5.0 * ((i + 1) % 3)
                samples.append(
                    MetricSample(
                        timestamp=float(cycle * 12 + i),
                        value=value,
                    )
                )

        anomalies = self.detector.holt_winters_anomalies(samples, season_length=12)
        assert isinstance(anomalies, list)

    def test_cusum_anomalies(self) -> None:
        """Test CUSUM change point detection."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(50)]
        samples.extend([MetricSample(timestamp=float(50 + i), value=20.0) for i in range(50)])

        anomalies = self.detector.cusum_anomalies(samples, threshold=5.0)
        assert isinstance(anomalies, list)

    def test_dynamic_threshold_anomalies(self) -> None:
        """Test dynamic threshold anomaly detection."""
        samples = [MetricSample(timestamp=float(i), value=10.0 + i % 5) for i in range(100)]
        samples.append(MetricSample(timestamp=100.0, value=1000.0))

        anomalies = self.detector.dynamic_threshold_anomalies(samples)
        assert len(anomalies) > 0

    def test_correlation_analysis(self) -> None:
        """Test correlation analysis."""
        series1 = [MetricSample(timestamp=float(i), value=float(i)) for i in range(100)]
        series2 = [MetricSample(timestamp=float(i), value=float(i) * 2) for i in range(100)]

        correlations = self.detector.correlation_analysis(
            {
                "series1": series1,
                "series2": series2,
            }
        )

        assert isinstance(correlations, dict)
        if ("series1", "series2") in correlations:
            corr_val = correlations[("series1", "series2")]
            assert isinstance(corr_val, float)

    def test_rank_anomalies(self) -> None:
        """Test ranking anomalies."""
        anomalies = [
            Anomaly(
                timestamp=datetime.utcnow(),
                series_key="series1",
                value=100.0,
                expected_value=10.0,
                deviation=90.0,
                score=0.9,
                method="zscore",
            ),
            Anomaly(
                timestamp=datetime.utcnow(),
                series_key="series2",
                value=20.0,
                expected_value=10.0,
                deviation=10.0,
                score=0.1,
                method="zscore",
            ),
        ]

        ranked = self.detector.rank_anomalies(anomalies)
        assert ranked[0].score > ranked[1].score

    def test_filter_anomalies(self) -> None:
        """Test filtering anomalies by score."""
        anomalies = [
            Anomaly(
                timestamp=datetime.utcnow(),
                series_key="series1",
                value=100.0,
                expected_value=10.0,
                deviation=90.0,
                score=0.9,
                method="zscore",
            ),
            Anomaly(
                timestamp=datetime.utcnow(),
                series_key="series2",
                value=20.0,
                expected_value=10.0,
                deviation=10.0,
                score=0.1,
                method="zscore",
            ),
        ]

        filtered = self.detector.filter_anomalies(anomalies, min_score=0.5)
        assert len(filtered) == 1
        assert filtered[0].score >= 0.5


class TestAnomalyType:
    """Test Anomaly type."""

    def test_create_anomaly(self) -> None:
        """Test creating anomaly."""
        anomaly = Anomaly(
            timestamp=datetime.utcnow(),
            series_key="cpu_usage",
            value=95.0,
            expected_value=50.0,
            deviation=45.0,
            score=0.85,
            method="zscore",
            severity="critical",
        )

        assert anomaly.series_key == "cpu_usage"
        assert anomaly.value == 95.0
        assert anomaly.score == 0.85

    def test_anomaly_score_bounds(self) -> None:
        """Test anomaly score is between 0 and 1."""
        anomaly = Anomaly(
            timestamp=datetime.utcnow(),
            series_key="metric",
            value=10.0,
            expected_value=5.0,
            deviation=5.0,
            score=0.5,
            method="test",
        )

        assert 0 <= anomaly.score <= 1

    def test_anomaly_severity_levels(self) -> None:
        """Test anomaly severity levels."""
        for severity in ["info", "warning", "critical"]:
            anomaly = Anomaly(
                timestamp=datetime.utcnow(),
                series_key="metric",
                value=10.0,
                expected_value=5.0,
                deviation=5.0,
                score=0.5,
                method="test",
                severity=severity,
            )

            assert anomaly.severity == severity


class TestAnomalyMethods:
    """Test different anomaly detection methods."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.detector = AnomalyDetector()

    def test_zscore_threshold_parameter(self) -> None:
        """Test Z-score with different thresholds."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]
        samples.append(MetricSample(timestamp=100.0, value=100.0))

        # With high threshold, no anomalies
        anomalies_high = self.detector.zscore_anomalies(samples, threshold=10.0)

        # With low threshold, should detect
        anomalies_low = self.detector.zscore_anomalies(samples, threshold=1.0)

        assert len(anomalies_high) <= len(anomalies_low)

    def test_ewma_alpha_parameter(self) -> None:
        """Test EWMA with different alpha values."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]

        anomalies_low_alpha = self.detector.ewma_anomalies(samples, alpha=0.1)
        anomalies_high_alpha = self.detector.ewma_anomalies(samples, alpha=0.9)

        assert isinstance(anomalies_low_alpha, list)
        assert isinstance(anomalies_high_alpha, list)

    def test_dynamic_threshold_percentiles(self) -> None:
        """Test dynamic threshold with different percentiles."""
        samples = [MetricSample(timestamp=float(i), value=10.0 + i % 5) for i in range(100)]

        anomalies = self.detector.dynamic_threshold_anomalies(
            samples,
            percentile_lower=5,
            percentile_upper=95,
        )

        assert isinstance(anomalies, list)

    def test_cusum_drift_parameter(self) -> None:
        """Test CUSUM with drift parameter."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]

        anomalies = self.detector.cusum_anomalies(samples, drift=0.5)
        assert isinstance(anomalies, list)


class TestEdgeCases:
    """Test edge cases in anomaly detection."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.detector = AnomalyDetector()

    def test_empty_samples(self) -> None:
        """Test with empty samples."""
        samples = []

        anomalies = self.detector.zscore_anomalies(samples)
        assert len(anomalies) == 0

    def test_single_sample(self) -> None:
        """Test with single sample."""
        samples = [MetricSample(timestamp=0.0, value=10.0)]

        anomalies = self.detector.zscore_anomalies(samples)
        assert len(anomalies) == 0

    def test_all_same_values(self) -> None:
        """Test with all identical values."""
        samples = [MetricSample(timestamp=float(i), value=10.0) for i in range(100)]

        anomalies = self.detector.zscore_anomalies(samples)
        assert len(anomalies) == 0

    def test_correlation_single_series(self) -> None:
        """Test correlation with single series."""
        series = [MetricSample(timestamp=float(i), value=float(i)) for i in range(10)]

        correlations = self.detector.correlation_analysis({"series": series})
        assert len(correlations) == 0

    def test_empty_correlation_series(self) -> None:
        """Test correlation with empty series."""
        correlations = self.detector.correlation_analysis({})
        assert len(correlations) == 0
