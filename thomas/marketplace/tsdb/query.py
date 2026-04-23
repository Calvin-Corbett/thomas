"""Query engine for the Thomas TSDB.

Parses and executes time-series queries with support for filtering,
aggregation, downsampling, and grouping.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._exceptions import QueryError
from ._types import TagFilter, TimeRange


class JoinType(Enum):
    """Types of joins for multi-metric queries."""

    INNER = "inner"
    OUTER = "outer"
    LEFT = "left"
    RIGHT = "right"


@dataclass
class Query:
    """Represents a parsed TSDB query."""

    metric_names: list[str]
    aggregations: list[str]
    time_range: TimeRange | None = None
    tag_filters: list[TagFilter] = None
    group_by_tags: list[str] = None
    downsample_interval_ms: int | None = None
    fill_policy: str = "null"
    limit: int = 10000

    def __post_init__(self) -> None:
        """Validate query after initialization."""
        if not self.metric_names:
            raise ValueError("Query must specify at least one metric")
        if not self.aggregations:
            raise ValueError("Query must specify at least one aggregation")
        if self.tag_filters is None:
            self.tag_filters = []
        if self.group_by_tags is None:
            self.group_by_tags = []


@dataclass
class QueryResult:
    """Result of a query execution."""

    query: Query
    metric_name: str
    timestamps: list[int]
    values: list[float | None]
    tags: dict[str, str] = None
    aggregation: str = ""
    execution_time_ms: float = 0.0

    def __post_init__(self) -> None:
        """Validate result."""
        if self.tags is None:
            self.tags = {}

        if len(self.timestamps) != len(self.values):
            raise ValueError("Timestamps and values must have same length")


class QueryParser:
    """Parses query strings into Query objects.

    Supports syntax like:
    SELECT avg(cpu), max(cpu) FROM metrics
    WHERE host='web1' AND datacenter='us-east'
    AND time > now()-1h
    GROUP BY host
    DOWNSAMPLE 5m
    """

    def parse(self, query_string: str) -> Query:
        """Parse a query string.

        Args:
            query_string: Query string to parse

        Returns:
            Parsed Query object

        Raises:
            QueryError: If query is invalid
        """
        try:
            query_string = query_string.strip()

            # Parse SELECT clause
            select_match = re.match(r"SELECT\s+(.+?)\s+FROM", query_string, re.IGNORECASE)
            if not select_match:
                raise ValueError("Invalid query: missing SELECT...FROM")

            aggregations = self._parse_aggregations(select_match.group(1))

            # Parse FROM clause
            from_match = re.search(r"FROM\s+(\w+(?:\s*,\s*\w+)*)", query_string, re.IGNORECASE)
            if not from_match:
                raise ValueError("Invalid query: missing FROM")

            metric_names = [m.strip() for m in from_match.group(1).split(",")]

            # Parse WHERE clause
            where_match = re.search(r"WHERE\s+(.+?)(?:GROUP|DOWNSAMPLE|$)", query_string, re.IGNORECASE)
            tag_filters: list[TagFilter] = []
            time_range: TimeRange | None = None

            if where_match:
                conditions = where_match.group(1)
                tag_filters, time_range = self._parse_where(conditions)

            # Parse GROUP BY clause
            group_by_tags: list[str] = []
            group_match = re.search(r"GROUP\s+BY\s+(\w+(?:\s*,\s*\w+)*)", query_string, re.IGNORECASE)
            if group_match:
                group_by_tags = [t.strip() for t in group_match.group(1).split(",")]

            # Parse DOWNSAMPLE clause
            downsample_interval_ms: int | None = None
            downsample_match = re.search(r"DOWNSAMPLE\s+(\d+)([smhd])", query_string, re.IGNORECASE)
            if downsample_match:
                value = int(downsample_match.group(1))
                unit = downsample_match.group(2).lower()
                downsample_interval_ms = self._convert_to_ms(value, unit)

            # Parse FILL clause
            fill_policy = "null"
            fill_match = re.search(r"FILL\s+(\w+)", query_string, re.IGNORECASE)
            if fill_match:
                fill_policy = fill_match.group(1).lower()

            return Query(
                metric_names=metric_names,
                aggregations=aggregations,
                time_range=time_range,
                tag_filters=tag_filters,
                group_by_tags=group_by_tags,
                downsample_interval_ms=downsample_interval_ms,
                fill_policy=fill_policy,
            )

        except Exception as e:
            raise QueryError(query_string, str(e))

    def _parse_aggregations(self, agg_string: str) -> list[str]:
        """Parse aggregation functions from SELECT clause.

        Args:
            agg_string: Aggregation string (e.g., "avg(cpu), max(cpu)")

        Returns:
            List of aggregation expressions
        """
        # Match patterns like: avg(metric), sum(metric), percentile_95(metric)
        pattern = r"(\w+)\s*\(\s*(\w+)\s*\)"
        matches = re.findall(pattern, agg_string)

        if not matches:
            raise ValueError("No valid aggregations found in SELECT")

        aggregations = [f"{func}({metric})" for func, metric in matches]
        return aggregations

    def _parse_where(self, where_clause: str) -> tuple[list[TagFilter], TimeRange | None]:
        """Parse WHERE clause into tag filters and time range.

        Args:
            where_clause: WHERE clause content

        Returns:
            Tuple of (tag_filters, time_range)
        """
        tag_filters: list[TagFilter] = []
        time_range: TimeRange | None = None

        # Split by AND
        conditions = [c.strip() for c in re.split(r"\s+AND\s+", where_clause, flags=re.IGNORECASE)]

        for condition in conditions:
            if "time" in condition.lower():
                # Parse time condition
                time_range = self._parse_time_condition(condition)
            else:
                # Parse tag filter
                tag_filter = self._parse_tag_filter(condition)
                if tag_filter:
                    tag_filters.append(tag_filter)

        return tag_filters, time_range

    def _parse_tag_filter(self, condition: str) -> TagFilter | None:
        """Parse a single tag filter condition.

        Args:
            condition: Condition string (e.g., "host='web1'")

        Returns:
            TagFilter or None if not a tag condition
        """
        # Match: key = value, key != value, key in (val1, val2), etc.
        patterns = [
            (r"(\w+)\s*=\s*['\"]?(\w+)['\"]?", "="),
            (r"(\w+)\s*!=\s*['\"]?(\w+)['\"]?", "!="),
            (r"(\w+)\s*>\s*['\"]?(\w+)['\"]?", ">"),
            (r"(\w+)\s*<\s*['\"]?(\w+)['\"]?", "<"),
            (r"(\w+)\s*>=\s*['\"]?(\w+)['\"]?", ">="),
            (r"(\w+)\s*<=\s*['\"]?(\w+)['\"]?", "<="),
        ]

        for pattern, operator in patterns:
            match = re.match(pattern, condition)
            if match:
                key, value = match.groups()
                return TagFilter(key=key, operator=operator, value=value)

        return None

    def _parse_time_condition(self, condition: str) -> TimeRange | None:
        """Parse a time condition.

        Args:
            condition: Time condition (e.g., "time > now()-1h")

        Returns:
            TimeRange or None
        """
        import time

        now_ms = int(time.time() * 1000)

        # Match: time > now()-1h, time < now(), etc.
        pattern = r"time\s*([><]=?)\s*now\s*\(\s*\)\s*(?:([+-])\s*(\d+)\s*([smhd])\s*)?"
        match = re.search(pattern, condition, re.IGNORECASE)

        if not match:
            return None

        operator, sign, value_str, unit = match.groups()

        offset_ms = 0
        if value_str and unit:
            value = int(value_str)
            offset_ms = self._convert_to_ms(value, unit.lower())
            if sign == "-":
                offset_ms = -offset_ms

        if operator in [">", ">="]:
            # time > now() - 1h means: start_time = now - 1h
            start_time = now_ms + offset_ms
            end_time = now_ms
        else:  # < or <=
            # time < now() means: end_time = now()
            start_time = now_ms + offset_ms
            end_time = now_ms

        if start_time >= end_time:
            start_time, end_time = end_time, start_time

        return TimeRange(start_time=start_time, end_time=end_time)

    @staticmethod
    def _convert_to_ms(value: int, unit: str) -> int:
        """Convert time value to milliseconds.

        Args:
            value: Numeric value
            unit: Unit (s, m, h, d)

        Returns:
            Value in milliseconds
        """
        multipliers = {
            "s": 1000,
            "m": 60 * 1000,
            "h": 60 * 60 * 1000,
            "d": 24 * 60 * 60 * 1000,
        }

        if unit not in multipliers:
            raise ValueError(f"Unknown time unit: {unit}")

        return value * multipliers[unit]


class QueryOptimizer:
    """Optimizes queries for better execution."""

    def optimize(self, query: Query) -> Query:
        """Optimize a query.

        Args:
            query: Query to optimize

        Returns:
            Optimized query (may be same object)
        """
        # Push down time range to storage layer (already in query)
        # Select best downsample level based on time range
        # Reorder tag filters by selectivity (most selective first)

        if query.tag_filters:
            # Sort by potential selectivity (rough heuristic)
            query.tag_filters.sort(key=lambda f: (f.operator != "=", f.value))

        return query


class QueryExecutor:
    """Executes queries against TSDB data.

    This is a placeholder - actual execution depends on engine implementation.
    """

    def __init__(self, engine: Any) -> None:
        """Initialize executor.

        Args:
            engine: Reference to TSDB engine
        """
        self.engine = engine

    def execute(self, query: Query) -> list[QueryResult]:
        """Execute a query.

        Args:
            query: Query to execute

        Returns:
            List of QueryResult objects

        Raises:
            QueryError: If execution fails
        """
        import time

        start_time = time.time()

        try:
            results: list[QueryResult] = []

            for metric_name in query.metric_names:
                # Query the engine
                # This is where actual data retrieval happens
                # For now, return empty results
                result = QueryResult(
                    query=query,
                    metric_name=metric_name,
                    timestamps=[],
                    values=[],
                )

                execution_time_ms = (time.time() - start_time) * 1000
                result.execution_time_ms = execution_time_ms

                results.append(result)

            return results

        except Exception as e:
            raise QueryError(str(query), str(e))


class FillPolicy:
    """Handles missing value fill policies."""

    @staticmethod
    def fill_gaps(
        timestamps: list[int],
        values: list[float | None],
        policy: str = "null",
    ) -> list[float | None]:
        """Fill gaps in time-series data according to policy.

        Args:
            timestamps: List of timestamps
            values: List of values (may contain None)
            policy: Fill policy (null, zero, linear, previous)

        Returns:
            Filled values

        Raises:
            ValueError: If policy is unknown
        """
        if policy == "null":
            return values

        if policy == "zero":
            return [v if v is not None else 0.0 for v in values]

        if policy == "previous":
            filled = []
            last_value = None
            for v in values:
                if v is not None:
                    last_value = v
                filled.append(v if v is not None else last_value)
            return filled

        if policy == "linear":
            return FillPolicy._fill_linear(timestamps, values)

        raise ValueError(f"Unknown fill policy: {policy}")

    @staticmethod
    def _fill_linear(timestamps: list[int], values: list[float | None]) -> list[float | None]:
        """Linear interpolation fill.

        Args:
            timestamps: List of timestamps
            values: List of values (may contain None)

        Returns:
            Interpolated values
        """
        filled = list(values)

        # Find gaps
        i = 0
        while i < len(filled):
            if filled[i] is None:
                # Find start of gap
                gap_start = i - 1
                # Find end of gap
                gap_end = i
                while gap_end < len(filled) and filled[gap_end] is None:
                    gap_end += 1

                # Interpolate if we have boundaries
                if gap_start >= 0 and gap_end < len(filled):
                    start_value = filled[gap_start]
                    end_value = filled[gap_end]
                    gap_size = gap_end - gap_start

                    for j in range(gap_start + 1, gap_end):
                        fraction = (j - gap_start) / gap_size
                        filled[j] = start_value + (end_value - start_value) * fraction

                i = gap_end
            else:
                i += 1

        return filled
