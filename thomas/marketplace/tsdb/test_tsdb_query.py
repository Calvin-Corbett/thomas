"""Tests for query parsing and execution.

Tests query string parsing, optimization, and execution.
"""

import pytest

from . import (
    Query,
    QueryError,
    QueryOptimizer,
    QueryParser,
    TagFilter,
)


class TestQueryParsing:
    """Tests for query string parsing."""

    @pytest.fixture
    def parser(self):
        """Provide query parser."""
        return QueryParser()

    def test_parse_basic_query(self, parser):
        """Test parsing basic SELECT query."""
        query_str = "SELECT avg(cpu) FROM metrics"
        query = parser.parse(query_str)

        assert query.metric_names == ["metrics"]
        assert "avg(cpu)" in query.aggregations

    def test_parse_multiple_aggregations(self, parser):
        """Test parsing multiple aggregations."""
        query_str = "SELECT avg(cpu), max(cpu), min(cpu) FROM metrics"
        query = parser.parse(query_str)

        assert len(query.aggregations) == 3
        assert "avg(cpu)" in query.aggregations
        assert "max(cpu)" in query.aggregations
        assert "min(cpu)" in query.aggregations

    def test_parse_multiple_metrics(self, parser):
        """Test parsing multiple metrics."""
        query_str = "SELECT avg(value) FROM cpu, memory, disk"
        query = parser.parse(query_str)

        assert query.metric_names == ["cpu", "memory", "disk"]

    def test_parse_with_time_range(self, parser):
        """Test parsing time range."""
        query_str = "SELECT avg(cpu) FROM metrics WHERE time > now()-1h"
        query = parser.parse(query_str)

        assert query.time_range is not None
        assert query.time_range.start_time < query.time_range.end_time

    def test_parse_with_tag_filters(self, parser):
        """Test parsing tag filters."""
        query_str = "SELECT avg(cpu) FROM metrics WHERE host='web1'"
        query = parser.parse(query_str)

        assert len(query.tag_filters) == 1
        assert query.tag_filters[0].key == "host"
        assert query.tag_filters[0].value == "web1"

    def test_parse_with_multiple_tag_filters(self, parser):
        """Test parsing multiple tag filters."""
        query_str = "SELECT avg(cpu) FROM metrics WHERE host='web1' AND datacenter='us-east'"
        query = parser.parse(query_str)

        assert len(query.tag_filters) == 2

    def test_parse_with_group_by(self, parser):
        """Test parsing GROUP BY clause."""
        query_str = "SELECT avg(cpu) FROM metrics GROUP BY host"
        query = parser.parse(query_str)

        assert query.group_by_tags == ["host"]

    def test_parse_with_multiple_group_by(self, parser):
        """Test parsing multiple GROUP BY tags."""
        query_str = "SELECT avg(cpu) FROM metrics GROUP BY host, datacenter"
        query = parser.parse(query_str)

        assert "host" in query.group_by_tags
        assert "datacenter" in query.group_by_tags

    def test_parse_with_downsample(self, parser):
        """Test parsing DOWNSAMPLE clause."""
        query_str = "SELECT avg(cpu) FROM metrics DOWNSAMPLE 5m"
        query = parser.parse(query_str)

        assert query.downsample_interval_ms == 5 * 60 * 1000

    def test_parse_downsample_units(self, parser):
        """Test various downsample time units."""
        test_cases = [
            ("DOWNSAMPLE 1s", 1000),
            ("DOWNSAMPLE 5m", 5 * 60 * 1000),
            ("DOWNSAMPLE 1h", 60 * 60 * 1000),
            ("DOWNSAMPLE 1d", 24 * 60 * 60 * 1000),
        ]

        for downsample_str, expected_ms in test_cases:
            query_str = f"SELECT avg(cpu) FROM metrics {downsample_str}"
            query = parser.parse(query_str)
            assert query.downsample_interval_ms == expected_ms

    def test_parse_with_fill_policy(self, parser):
        """Test parsing FILL policy."""
        query_str = "SELECT avg(cpu) FROM metrics FILL linear"
        query = parser.parse(query_str)

        assert query.fill_policy == "linear"

    def test_parse_case_insensitive(self, parser):
        """Test that parsing is case insensitive."""
        query_str = "select avg(cpu) from metrics where host='web1' group by datacenter"
        query = parser.parse(query_str)

        assert query.metric_names == ["metrics"]
        assert len(query.tag_filters) > 0

    def test_parse_complex_query(self, parser):
        """Test parsing complex query with all clauses."""
        query_str = """
            SELECT avg(cpu), max(cpu), percentile_95(cpu)
            FROM metrics
            WHERE host='web1' AND datacenter='us-east' AND time > now()-24h
            GROUP BY host, region
            DOWNSAMPLE 1h
            FILL linear
        """
        query = parser.parse(query_str)

        assert len(query.aggregations) == 3
        assert query.metric_names == ["metrics"]
        assert len(query.tag_filters) == 2
        assert len(query.group_by_tags) == 2
        assert query.downsample_interval_ms == 60 * 60 * 1000
        assert query.fill_policy == "linear"

    def test_parse_invalid_query_no_select(self, parser):
        """Test that invalid query raises error."""
        with pytest.raises(QueryError):
            parser.parse("FROM metrics")

    def test_parse_invalid_query_no_aggregation(self, parser):
        """Test query with no aggregations raises error."""
        with pytest.raises(QueryError):
            parser.parse("SELECT FROM metrics")


class TestTimeRangeNow:
    """Tests for NOW() time range parsing."""

    @pytest.fixture
    def parser(self):
        """Provide query parser."""
        return QueryParser()

    def test_parse_time_now_minus(self, parser):
        """Test parsing 'now()-1h' syntax."""
        query_str = "SELECT avg(cpu) FROM metrics WHERE time > now()-1h"
        query = parser.parse(query_str)

        assert query.time_range is not None

    def test_parse_time_now_plus(self, parser):
        """Test parsing 'now()+1h' syntax."""
        query_str = "SELECT avg(cpu) FROM metrics WHERE time > now()+1h"
        query = parser.parse(query_str)

        assert query.time_range is not None

    def test_parse_time_comparison_operators(self, parser):
        """Test different time comparison operators."""
        test_cases = [
            "time > now()-1h",
            "time >= now()-1h",
            "time < now()",
            "time <= now()+1h",
        ]

        for condition in test_cases:
            query_str = f"SELECT avg(cpu) FROM metrics WHERE {condition}"
            query = parser.parse(query_str)
            assert query.time_range is not None


class TestTagFiltering:
    """Tests for tag filter parsing."""

    @pytest.fixture
    def parser(self):
        """Provide query parser."""
        return QueryParser()

    def test_parse_equality_filter(self, parser):
        """Test parsing equality filter."""
        query_str = "SELECT avg(cpu) FROM metrics WHERE host='web1'"
        query = parser.parse(query_str)

        assert query.tag_filters[0].operator == "="
        assert query.tag_filters[0].value == "web1"

    def test_parse_inequality_filter(self, parser):
        """Test parsing inequality filter."""
        query_str = "SELECT avg(cpu) FROM metrics WHERE host!='db1'"
        query = parser.parse(query_str)

        assert query.tag_filters[0].operator == "!="

    def test_parse_comparison_filters(self, parser):
        """Test parsing comparison operators."""
        test_cases = [
            ("port>'8000'", ">"),
            ("port<'9000'", "<"),
            ("port>='8000'", ">="),
            ("port<='9000'", "<="),
        ]

        for condition, expected_op in test_cases:
            query_str = f"SELECT avg(cpu) FROM metrics WHERE {condition}"
            query = parser.parse(query_str)
            if query.tag_filters:
                assert query.tag_filters[0].operator == expected_op


class TestQueryOptimization:
    """Tests for query optimization."""

    @pytest.fixture
    def optimizer(self):
        """Provide query optimizer."""
        return QueryOptimizer()

    def test_optimize_basic_query(self, optimizer):
        """Test optimizing basic query."""
        query = Query(
            metric_names=["metrics"],
            aggregations=["avg"],
            tag_filters=[
                TagFilter(key="host", operator="=", value="web1"),
                TagFilter(key="type", operator="=", value="web"),
            ],
        )

        optimized = optimizer.optimize(query)
        assert optimized is not None

    def test_optimize_reorders_filters(self, optimizer):
        """Test that optimizer reorders filters."""
        query = Query(
            metric_names=["metrics"],
            aggregations=["avg"],
            tag_filters=[
                TagFilter(key="type", operator="!=", value="unknown"),
                TagFilter(key="host", operator="=", value="web1"),
            ],
        )

        optimized = optimizer.optimize(query)
        # Equality filters should come before inequality
        assert optimized.tag_filters[0].operator == "="


class TestQueryResult:
    """Tests for query results."""

    def test_query_result_creation(self):
        """Test creating a query result."""
        from . import QueryResult

        result = QueryResult(
            query=None,
            metric_name="cpu",
            timestamps=[1000, 2000, 3000],
            values=[10.0, 20.0, 30.0],
        )

        assert result.metric_name == "cpu"
        assert len(result.timestamps) == 3
        assert len(result.values) == 3

    def test_query_result_validation(self):
        """Test that mismatched lengths raise error."""
        from . import QueryResult

        with pytest.raises(ValueError):
            QueryResult(
                query=None,
                metric_name="cpu",
                timestamps=[1000, 2000],
                values=[10.0],  # Mismatch
            )


class TestFillPolicy:
    """Tests for fill policy."""

    def test_fill_null_policy(self):
        """Test NULL fill policy."""
        from .query import FillPolicy

        values = [10.0, None, 20.0, None, 30.0]
        filled = FillPolicy.fill_gaps([1000, 2000, 3000, 4000, 5000], values, "null")

        assert filled == values

    def test_fill_zero_policy(self):
        """Test ZERO fill policy."""
        from .query import FillPolicy

        values = [10.0, None, 20.0]
        filled = FillPolicy.fill_gaps([1000, 2000, 3000], values, "zero")

        assert filled[0] == 10.0
        assert filled[1] == 0.0
        assert filled[2] == 20.0

    def test_fill_previous_policy(self):
        """Test PREVIOUS fill policy."""
        from .query import FillPolicy

        values = [10.0, None, None, 20.0]
        filled = FillPolicy.fill_gaps([1000, 2000, 3000, 4000], values, "previous")

        assert filled[0] == 10.0
        assert filled[1] == 10.0
        assert filled[2] == 10.0
        assert filled[3] == 20.0

    def test_fill_linear_policy(self):
        """Test LINEAR fill policy."""
        from .query import FillPolicy

        values = [10.0, None, None, 20.0]
        filled = FillPolicy.fill_gaps([1000, 2000, 3000, 4000], values, "linear")

        assert filled[0] == 10.0
        assert filled[1] is not None
        assert filled[2] is not None
        assert filled[3] == 20.0
        # Linear interpolation: 10 + (20-10)*1/3 = 13.33
        assert 13.0 < filled[1] < 14.0
        # 10 + (20-10)*2/3 = 16.67
        assert 16.0 < filled[2] < 17.0

    def test_fill_invalid_policy(self):
        """Test that invalid policy raises error."""
        from .query import FillPolicy

        with pytest.raises(ValueError):
            FillPolicy.fill_gaps([1000, 2000], [10.0, None], "invalid")
