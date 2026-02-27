"""
Tests for metrics module.
"""

import pytest

from thomas.monitoring._exceptions import MetricError
from thomas.monitoring.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    Summary,
    TDigest,
)


class TestCounter:
    """Test Counter metric."""

    def test_counter_increment(self) -> None:
        """Test counter increments correctly."""
        counter = Counter("test_counter", "Test counter")
        counter.inc()
        counter.inc(5.0)

        results = counter.collect()
        assert len(results) == 1
        assert results[0][1] == 6.0

    def test_counter_with_labels(self) -> None:
        """Test counter with labels."""
        counter = Counter("test_counter", "Test", labelnames=["method", "status"])
        counter.inc(labels={"method": "GET", "status": "200"})
        counter.inc(2.0, labels={"method": "POST", "status": "201"})

        results = counter.collect()
        assert len(results) == 2

    def test_counter_cannot_decrease(self) -> None:
        """Test counter rejects negative increments."""
        counter = Counter("test_counter", "Test")
        with pytest.raises(MetricError):
            counter.inc(-1.0)

    def test_counter_thread_safety(self) -> None:
        """Test counter is thread-safe."""
        import threading

        counter = Counter("test_counter", "Test")

        def increment():
            for _ in range(100):
                counter.inc()

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        results = counter.collect()
        assert results[0][1] == 1000.0


class TestGauge:
    """Test Gauge metric."""

    def test_gauge_set(self) -> None:
        """Test gauge set operation."""
        gauge = Gauge("test_gauge", "Test gauge")
        gauge.set(42.0)

        results = gauge.collect()
        assert results[0][1] == 42.0

    def test_gauge_inc_dec(self) -> None:
        """Test gauge increment and decrement."""
        gauge = Gauge("test_gauge", "Test")
        gauge.set(10.0)
        gauge.inc(5.0)
        gauge.dec(3.0)

        results = gauge.collect()
        assert results[0][1] == 12.0

    def test_gauge_with_labels(self) -> None:
        """Test gauge with labels."""
        gauge = Gauge("test_gauge", "Test", labelnames=["instance"])
        gauge.set(10.0, labels={"instance": "host1"})
        gauge.set(20.0, labels={"instance": "host2"})

        results = gauge.collect()
        assert len(results) == 2

    def test_gauge_negative_values(self) -> None:
        """Test gauge accepts negative values."""
        gauge = Gauge("test_gauge", "Test")
        gauge.set(-5.0)
        gauge.dec(10.0)

        results = gauge.collect()
        assert results[0][1] == -15.0


class TestHistogram:
    """Test Histogram metric."""

    def test_histogram_observe(self) -> None:
        """Test histogram observation."""
        histogram = Histogram("test_histogram", "Test")
        histogram.observe(0.5)
        histogram.observe(1.5)
        histogram.observe(5.0)

        results = histogram.collect()
        assert len(results) == 1
        labels, buckets, sum_val, count = results[0]
        assert count == 3
        assert sum_val == 7.0

    def test_histogram_buckets(self) -> None:
        """Test histogram bucket counting."""
        histogram = Histogram("test_histogram", "Test", buckets=[1.0, 5.0, 10.0])
        for val in [0.5, 2.0, 7.0, 15.0]:
            histogram.observe(val)

        results = histogram.collect()
        labels, buckets, sum_val, count = results[0]

        assert buckets[0].count == 1  # <=1.0
        assert buckets[1].count == 2  # <=5.0
        assert buckets[2].count == 3  # <=10.0
        assert buckets[3].count == 4  # +Inf

    def test_histogram_with_labels(self) -> None:
        """Test histogram with labels."""
        histogram = Histogram("test_histogram", "Test", labelnames=["endpoint"])
        histogram.observe(0.1, labels={"endpoint": "/api"})
        histogram.observe(0.5, labels={"endpoint": "/health"})

        results = histogram.collect()
        assert len(results) == 2


class TestSummary:
    """Test Summary metric."""

    def test_summary_observe(self) -> None:
        """Test summary observation."""
        summary = Summary("test_summary", "Test")
        for val in [1.0, 2.0, 3.0, 4.0, 5.0]:
            summary.observe(val)

        results = summary.collect()
        assert len(results) == 1
        labels, percentiles, sum_val, count = results[0]
        assert count == 5
        assert sum_val == 15.0

    def test_summary_percentiles(self) -> None:
        """Test summary percentiles."""
        summary = Summary("test_summary", "Test", percentiles=[0.5, 0.9, 0.99])
        for val in range(1, 101):
            summary.observe(float(val))

        results = summary.collect()
        labels, percentiles, sum_val, count = results[0]

        assert 0.5 in percentiles
        assert 0.9 in percentiles
        assert 0.99 in percentiles

    def test_summary_with_labels(self) -> None:
        """Test summary with labels."""
        summary = Summary("test_summary", "Test", labelnames=["method"])
        summary.observe(0.1, labels={"method": "GET"})
        summary.observe(0.2, labels={"method": "POST"})

        results = summary.collect()
        assert len(results) == 2


class TestTDigest:
    """Test T-Digest algorithm."""

    def test_tdigest_basic(self) -> None:
        """Test basic T-Digest operations."""
        digest = TDigest()
        for i in range(100):
            digest.add(float(i))

        assert digest.quantile(0.5) > 40.0
        assert digest.quantile(0.5) < 60.0

    def test_tdigest_percentiles(self) -> None:
        """Test T-Digest percentile accuracy."""
        digest = TDigest()
        for i in range(1, 1001):
            digest.add(float(i))

        p50 = digest.quantile(0.5)
        p95 = digest.quantile(0.95)
        p99 = digest.quantile(0.99)

        assert 450 < p50 < 550
        assert 900 < p95 < 960
        assert 980 < p99 < 1000

    def test_tdigest_compression(self) -> None:
        """Test T-Digest compression."""
        digest = TDigest(max_size=50)
        initial_size = len(digest.centroids)

        for i in range(1000):
            digest.add(float(i))

        # Should be compressed
        assert len(digest.centroids) <= 50 * 1.5


class TestMetricsRegistry:
    """Test metrics registry."""

    def test_registry_counter(self) -> None:
        """Test registering counter."""
        registry = MetricsRegistry()
        counter = registry.counter("test_counter", "Test")
        assert counter is not None

        # Get same instance
        counter2 = registry.counter("test_counter", "Test")
        assert counter is counter2

    def test_registry_gauge(self) -> None:
        """Test registering gauge."""
        registry = MetricsRegistry()
        gauge = registry.gauge("test_gauge", "Test")
        assert gauge is not None

    def test_registry_histogram(self) -> None:
        """Test registering histogram."""
        registry = MetricsRegistry()
        histogram = registry.histogram("test_histogram", "Test")
        assert histogram is not None

    def test_registry_summary(self) -> None:
        """Test registering summary."""
        registry = MetricsRegistry()
        summary = registry.summary("test_summary", "Test")
        assert summary is not None

    def test_registry_type_mismatch(self) -> None:
        """Test type mismatch detection."""
        registry = MetricsRegistry()
        registry.counter("test_metric", "Test")

        with pytest.raises(MetricError):
            registry.gauge("test_metric", "Test")

    def test_registry_unregister(self) -> None:
        """Test unregistering metrics."""
        registry = MetricsRegistry()
        registry.counter("test_counter", "Test")

        assert registry.unregister("test_counter")
        assert not registry.unregister("test_counter")

    def test_registry_lookup(self) -> None:
        """Test metric lookup."""
        registry = MetricsRegistry()
        counter = registry.counter("test_counter", "Test")

        found = registry.lookup("test_counter")
        assert found is counter

    def test_exposition_format(self) -> None:
        """Test Prometheus exposition format."""
        registry = MetricsRegistry()
        counter = registry.counter("test_counter", "Test counter")
        counter.inc()

        output = registry.exposition_format()
        assert "# HELP test_counter" in output
        assert "# TYPE test_counter counter" in output
        assert "test_counter 1" in output

    def test_exposition_with_labels(self) -> None:
        """Test exposition format with labels."""
        registry = MetricsRegistry()
        gauge = registry.gauge("test_gauge", "Test", labelnames=["host"])
        gauge.set(42.0, labels={"host": "server1"})

        output = registry.exposition_format()
        assert 'host="server1"' in output
        assert "42" in output

    def test_exposition_histogram(self) -> None:
        """Test exposition format for histogram."""
        registry = MetricsRegistry()
        histogram = registry.histogram("test_histogram", "Test")
        histogram.observe(5.0)

        output = registry.exposition_format()
        assert "test_histogram_bucket" in output
        assert "test_histogram_sum" in output
        assert "test_histogram_count" in output

    def test_exposition_summary(self) -> None:
        """Test exposition format for summary."""
        registry = MetricsRegistry()
        summary = registry.summary("test_summary", "Test")
        summary.observe(5.0)

        output = registry.exposition_format()
        assert "test_summary" in output
        assert "test_summary_sum" in output
        assert "test_summary_count" in output

    def test_cardinality_limit(self) -> None:
        """Test cardinality limits."""
        registry = MetricsRegistry(max_cardinality=10)
        counter = registry.counter("test_counter", "Test")

        # Should work up to limit
        for i in range(10):
            counter.inc(labels={"index": str(i)})

    def test_get_all_metrics(self) -> None:
        """Test getting all metrics."""
        registry = MetricsRegistry()
        registry.counter("counter1", "Test")
        registry.gauge("gauge1", "Test")
        registry.histogram("histogram1", "Test")

        all_metrics = registry.get_all()
        assert len(all_metrics) == 3
        assert "counter1" in all_metrics
        assert "gauge1" in all_metrics
        assert "histogram1" in all_metrics
