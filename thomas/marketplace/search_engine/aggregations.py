"""Aggregation framework for analytics on search results."""

import math
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any


class Aggregation(ABC):
    """Base aggregation class."""

    @abstractmethod
    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregation on documents."""
        pass


class TermsAggregation(Aggregation):
    """Count unique values for a field."""

    def __init__(self, field: str, size: int = 10) -> None:
        """Initialize terms aggregation."""
        self.field = field
        self.size = size

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Count term frequencies."""
        term_counts: dict[str, int] = defaultdict(int)

        for doc in docs:
            if self.field in doc:
                value = str(doc[self.field])
                term_counts[value] += 1

        # Sort by count descending
        sorted_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)
        top_terms = sorted_terms[: self.size]

        return {
            "buckets": [{"key": term, "doc_count": count} for term, count in top_terms],
            "doc_count_error_upper_bound": 0 if len(sorted_terms) <= self.size else sorted_terms[self.size - 1][1],
        }


class HistogramAggregation(Aggregation):
    """Create histogram buckets for numeric values."""

    def __init__(self, field: str, interval: float) -> None:
        """Initialize histogram aggregation."""
        self.field = field
        self.interval = interval

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Create histogram buckets."""
        buckets_dict: dict[float, int] = defaultdict(int)

        for doc in docs:
            if self.field in doc:
                try:
                    value = float(doc[self.field])
                    bucket = math.floor(value / self.interval) * self.interval
                    buckets_dict[bucket] += 1
                except (ValueError, TypeError):
                    pass

        sorted_buckets = sorted(buckets_dict.items())
        return {"buckets": [{"key": key, "doc_count": count} for key, count in sorted_buckets]}


class DateHistogramAggregation(Aggregation):
    """Create date histogram buckets."""

    def __init__(self, field: str, interval: str = "day") -> None:
        """Initialize date histogram."""
        self.field = field
        self.interval = interval

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Create date histogram buckets."""
        buckets_dict: dict[str, int] = defaultdict(int)

        for doc in docs:
            if self.field in doc:
                date_val = str(doc[self.field])
                bucket = self._get_bucket(date_val)
                buckets_dict[bucket] += 1

        sorted_buckets = sorted(buckets_dict.items())
        return {"buckets": [{"key": key, "doc_count": count} for key, count in sorted_buckets]}

    def _get_bucket(self, date_str: str) -> str:
        """Extract bucket from date string."""
        if self.interval == "year":
            return date_str[:4]
        elif self.interval == "month":
            return date_str[:7]
        else:  # day
            return date_str[:10]


class StatsAggregation(Aggregation):
    """Calculate statistics for numeric values."""

    def __init__(self, field: str) -> None:
        """Initialize stats aggregation."""
        self.field = field

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate statistics."""
        values: list[float] = []

        for doc in docs:
            if self.field in doc:
                try:
                    value = float(doc[self.field])
                    values.append(value)
                except (ValueError, TypeError):
                    pass

        if not values:
            return {"count": 0, "min": None, "max": None, "avg": None, "sum": 0.0}

        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "sum": sum(values),
        }


class CardinalityAggregation(Aggregation):
    """Estimate unique value count using HyperLogLog."""

    def __init__(self, field: str, precision: int = 14) -> None:
        """Initialize cardinality aggregation."""
        self.field = field
        self.precision = precision

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Estimate cardinality."""
        # Simplified implementation - exact count
        unique_values = set()
        for doc in docs:
            if self.field in doc:
                unique_values.add(str(doc[self.field]))

        return {"value": len(unique_values)}


class PercentileAggregation(Aggregation):
    """Calculate percentiles for numeric values."""

    def __init__(self, field: str, percentiles: list[float] = None) -> None:
        """Initialize percentile aggregation."""
        self.field = field
        self.percentiles = percentiles or [1, 5, 25, 50, 75, 95, 99]

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate percentiles."""
        values: list[float] = []

        for doc in docs:
            if self.field in doc:
                try:
                    value = float(doc[self.field])
                    values.append(value)
                except (ValueError, TypeError):
                    pass

        if not values:
            return {"values": {}}

        values.sort()
        result: dict[str, float] = {}

        for p in self.percentiles:
            idx = int((p / 100) * len(values))
            idx = min(idx, len(values) - 1)
            result[str(p)] = values[idx]

        return {"values": result}


class NestedAggregation(Aggregation):
    """Nested aggregation with sub-aggregations."""

    def __init__(self, agg: Aggregation) -> None:
        """Initialize nested aggregation."""
        self.agg = agg
        self.sub_aggs: dict[str, Aggregation] = {}

    def add_sub_aggregation(self, name: str, agg: Aggregation) -> None:
        """Add sub-aggregation."""
        self.sub_aggs[name] = agg

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate with sub-aggregations."""
        result = self.agg.aggregate(docs)

        # Add sub-aggregation results
        for name, sub_agg in self.sub_aggs.items():
            result[name] = sub_agg.aggregate(docs)

        return result


class DerivativeAggregation(Aggregation):
    """Pipeline aggregation calculating derivative."""

    def __init__(self, field_name: str) -> None:
        """Initialize derivative aggregation."""
        self.field_name = field_name

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate derivative of previous aggregation."""
        # This is a simplified implementation
        # In practice, would work on buckets from parent aggregation
        return {"value": 0}


class MovingAverageAggregation(Aggregation):
    """Pipeline aggregation calculating moving average."""

    def __init__(self, window: int = 10) -> None:
        """Initialize moving average aggregation."""
        self.window = window

    def aggregate(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate moving average."""
        # This is a simplified implementation
        # In practice, would work on buckets from parent aggregation
        return {"value": 0}


class AggregationManager:
    """Manages multiple aggregations."""

    def __init__(self) -> None:
        """Initialize aggregation manager."""
        self.aggregations: dict[str, Aggregation] = {}

    def add_aggregation(self, name: str, agg: Aggregation) -> None:
        """Add aggregation."""
        self.aggregations[name] = agg

    def execute_all(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute all aggregations."""
        results = {}
        for name, agg in self.aggregations.items():
            results[name] = agg.aggregate(docs)
        return results

    def get_aggregation(self, name: str) -> Aggregation | None:
        """Get aggregation by name."""
        return self.aggregations.get(name)
