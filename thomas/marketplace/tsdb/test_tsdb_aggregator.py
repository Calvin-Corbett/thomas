"""Tests for aggregation engine.

Tests all aggregation types, streaming aggregation, and percentiles.
"""

import pytest

from . import (
    AggregationEngine,
    PercentileAggregator,
    StreamingAggregationEngine,
)


class TestBasicAggregations:
    """Tests for basic aggregation functions."""

    @pytest.fixture
    def engine(self):
        """Provide aggregation engine."""
        return AggregationEngine()

    def test_sum(self, engine):
        """Test sum aggregation."""
        values = [10.0, 20.0, 30.0]
        result = engine.aggregate("sum", values)
        assert result == 60.0

    def test_avg(self, engine):
        """Test average aggregation."""
        values = [10.0, 20.0, 30.0]
        result = engine.aggregate("avg", values)
        assert result == 20.0

    def test_min(self, engine):
        """Test minimum aggregation."""
        values = [10.0, 5.0, 30.0, 2.0]
        result = engine.aggregate("min", values)
        assert result == 2.0

    def test_max(self, engine):
        """Test maximum aggregation."""
        values = [10.0, 5.0, 30.0, 2.0]
        result = engine.aggregate("max", values)
        assert result == 30.0

    def test_count(self, engine):
        """Test count aggregation."""
        values = [10.0, 20.0, 30.0]
        result = engine.aggregate("count", values)
        assert result == 3.0

    def test_stddev(self, engine):
        """Test standard deviation aggregation."""
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        result = engine.aggregate("stddev", values)
        assert result is not None
        assert result > 0
        # Sample stddev should be approximately 2.14
        assert 2.0 < result < 2.5

    def test_empty_list(self, engine):
        """Test aggregation on empty list."""
        result = engine.aggregate("sum", [])
        assert result is None

    def test_single_value(self, engine):
        """Test aggregation on single value."""
        result_sum = engine.aggregate("sum", [42.0])
        assert result_sum == 42.0

        result_avg = engine.aggregate("avg", [42.0])
        assert result_avg == 42.0

    def test_negative_values(self, engine):
        """Test aggregations with negative values."""
        values = [-10.0, -5.0, 0.0, 5.0, 10.0]

        sum_result = engine.aggregate("sum", values)
        assert sum_result == 0.0

        avg_result = engine.aggregate("avg", values)
        assert avg_result == 0.0

        min_result = engine.aggregate("min", values)
        assert min_result == -10.0

        max_result = engine.aggregate("max", values)
        assert max_result == 10.0


class TestPercentileAggregation:
    """Tests for percentile computation."""

    def test_percentile_50(self):
        """Test 50th percentile (median)."""
        agg = PercentileAggregator(50)
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = agg.aggregate(values)
        assert result == 3.0

    def test_percentile_25(self):
        """Test 25th percentile (Q1)."""
        agg = PercentileAggregator(25)
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = agg.aggregate(values)
        assert result == pytest.approx(2.0)

    def test_percentile_75(self):
        """Test 75th percentile (Q3)."""
        agg = PercentileAggregator(75)
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = agg.aggregate(values)
        assert result == pytest.approx(4.0)

    def test_percentile_95(self):
        """Test 95th percentile."""
        agg = PercentileAggregator(95)
        values = list(range(1, 101))  # 1-100
        result = agg.aggregate([float(v) for v in values])
        assert 95.0 <= result <= 100.0

    def test_percentile_0(self):
        """Test 0th percentile (minimum)."""
        agg = PercentileAggregator(0)
        values = [10.0, 20.0, 30.0]
        result = agg.aggregate(values)
        assert result == 10.0

    def test_percentile_100(self):
        """Test 100th percentile (maximum)."""
        agg = PercentileAggregator(100)
        values = [10.0, 20.0, 30.0]
        result = agg.aggregate(values)
        assert result == 30.0

    def test_percentile_invalid_range(self):
        """Test that invalid percentiles raise error."""
        with pytest.raises(ValueError):
            PercentileAggregator(-1)

        with pytest.raises(ValueError):
            PercentileAggregator(101)

    def test_percentile_single_value(self):
        """Test percentile with single value."""
        agg = PercentileAggregator(50)
        result = agg.aggregate([42.0])
        assert result == 42.0

    def test_percentile_empty(self):
        """Test percentile on empty list."""
        agg = PercentileAggregator(50)
        result = agg.aggregate([])
        assert result is None


class TestStreamingAggregation:
    """Tests for streaming aggregation engine."""

    def test_streaming_sum(self):
        """Test streaming sum."""
        engine = StreamingAggregationEngine()
        for value in [10.0, 20.0, 30.0]:
            engine.add_value(value)

        assert engine.get_sum() == 60.0

    def test_streaming_avg(self):
        """Test streaming average."""
        engine = StreamingAggregationEngine()
        for value in [10.0, 20.0, 30.0]:
            engine.add_value(value)

        assert engine.get_avg() == 20.0

    def test_streaming_min_max(self):
        """Test streaming min and max."""
        engine = StreamingAggregationEngine()
        values = [10.0, 5.0, 30.0, 2.0, 25.0]
        for value in values:
            engine.add_value(value)

        assert engine.get_min() == 2.0
        assert engine.get_max() == 30.0

    def test_streaming_count(self):
        """Test streaming count."""
        engine = StreamingAggregationEngine()
        for i in range(10):
            engine.add_value(float(i))

        assert engine.get_count() == 10

    def test_streaming_stddev(self):
        """Test streaming standard deviation."""
        engine = StreamingAggregationEngine()
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        for value in values:
            engine.add_value(value)

        stddev = engine.get_stddev()
        assert stddev is not None
        assert 2.0 < stddev < 2.5

    def test_streaming_percentile(self):
        """Test streaming percentile."""
        engine = StreamingAggregationEngine()
        for i in range(1, 11):
            engine.add_value(float(i))

        percentile_50 = engine.get_percentile(50)
        assert percentile_50 is not None
        assert 5.0 <= percentile_50 <= 6.0

    def test_streaming_delta(self):
        """Test streaming delta."""
        engine = StreamingAggregationEngine()
        engine.add_value(10.0)
        engine.add_value(25.0)

        delta = engine.get_delta()
        assert delta == 15.0

    def test_streaming_rate(self):
        """Test streaming rate calculation."""
        engine = StreamingAggregationEngine()
        engine.add_value(100.0)
        engine.add_value(110.0)

        # Rate calculation depends on interval
        rate = engine.get_rate(3600000)  # 1 hour
        assert rate is not None
        assert rate > 0

    def test_streaming_single_value(self):
        """Test streaming with single value."""
        engine = StreamingAggregationEngine()
        engine.add_value(42.0)

        assert engine.get_count() == 1
        assert engine.get_sum() == 42.0
        assert engine.get_avg() == 42.0
        assert engine.get_min() == 42.0
        assert engine.get_max() == 42.0


class TestIntervalAggregation:
    """Tests for aggregating by time intervals."""

    def test_aggregate_by_interval(self):
        """Test aggregating data into intervals."""
        engine = AggregationEngine()

        timestamps = [1000, 2000, 3000, 4000, 5000]
        values = [10.0, 20.0, 30.0, 40.0, 50.0]

        results = engine.aggregate_by_interval(timestamps, values, 2000, "avg")

        assert len(results) > 0
        assert all(r.count > 0 for r in results)

    def test_interval_aggregation_min_max(self):
        """Test min/max aggregation by interval."""
        engine = AggregationEngine()

        timestamps = [1000, 2000, 3000, 4000, 5000]
        values = [10.0, 20.0, 30.0, 40.0, 50.0]

        results = engine.aggregate_by_interval(timestamps, values, 2000, "min")

        # Min values in each interval should be recorded
        assert all(r.min_value is not None for r in results)

    def test_interval_aggregation_empty(self):
        """Test interval aggregation with no data."""
        engine = AggregationEngine()

        results = engine.aggregate_by_interval([], [], 1000, "avg")
        assert results == []

    def test_interval_aggregation_mismatched_lengths(self):
        """Test interval aggregation with mismatched lengths."""
        engine = AggregationEngine()

        timestamps = [1000, 2000, 3000]
        values = [10.0, 20.0]  # Different length

        with pytest.raises(ValueError):
            engine.aggregate_by_interval(timestamps, values, 1000, "avg")


class TestGroupBy:
    """Tests for group-by aggregation."""

    def test_group_by_single_tag(self):
        """Test grouping by single tag."""
        engine = AggregationEngine()

        timestamps = [1000, 2000, 3000, 4000]
        values = [10.0, 20.0, 30.0, 40.0]
        tags_list = [
            {"host": "web1"},
            {"host": "web1"},
            {"host": "web2"},
            {"host": "web2"},
        ]

        results = engine.group_by(timestamps, values, tags_list, "host", "sum")

        assert "web1" in results
        assert "web2" in results
        assert results["web1"] == 30.0  # 10 + 20
        assert results["web2"] == 70.0  # 30 + 40

    def test_group_by_multiple_values(self):
        """Test group-by with multiple aggregations per group."""
        engine = AggregationEngine()

        timestamps = [1000, 2000, 3000, 4000, 5000, 6000]
        values = [10.0, 20.0, 5.0, 15.0, 25.0, 30.0]
        tags_list = [
            {"type": "a"},
            {"type": "a"},
            {"type": "b"},
            {"type": "b"},
            {"type": "c"},
            {"type": "c"},
        ]

        results = engine.group_by(timestamps, values, tags_list, "type", "avg")

        assert len(results) == 3
        assert results["a"] == 15.0  # (10 + 20) / 2
        assert results["b"] == 10.0  # (5 + 15) / 2
        assert results["c"] == 27.5  # (25 + 30) / 2

    def test_group_by_unknown_tag(self):
        """Test group-by with missing tag key."""
        engine = AggregationEngine()

        timestamps = [1000, 2000]
        values = [10.0, 20.0]
        tags_list = [{"host": "web1"}, {"datacenter": "us-east"}]

        results = engine.group_by(timestamps, values, tags_list, "region", "sum")

        # Both should map to "unknown" since tag key is missing
        assert "unknown" in results


class TestAggregationErrors:
    """Tests for error handling in aggregations."""

    def test_unknown_aggregation_type(self):
        """Test that unknown aggregation type raises error."""
        engine = AggregationEngine()

        with pytest.raises(ValueError):
            engine.aggregate("unknown_agg", [1.0, 2.0, 3.0])

    def test_percentile_aggregation_by_name(self):
        """Test percentile aggregation by name pattern."""
        engine = AggregationEngine()

        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = engine.aggregate("percentile_75", values)

        assert result is not None
        assert 3.5 <= result <= 5.0

    def test_rate_aggregation(self):
        """Test rate aggregation."""
        engine = AggregationEngine()

        values = [100.0, 120.0]
        result = engine.aggregate("rate", values)

        assert result is not None

    def test_delta_aggregation(self):
        """Test delta aggregation."""
        engine = AggregationEngine()

        values = [100.0, 125.0]
        result = engine.aggregate("delta", values)

        assert result == 25.0
