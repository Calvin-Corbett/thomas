"""OLAP engine for multi-dimensional analysis.

Provides OLAP cube implementation, dimensions, measures,
MDX-like query processing, and drill-down operations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AggregationFunction(Enum):
    """OLAP aggregation functions."""

    SUM = "sum"
    COUNT = "count"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    STDDEV = "stddev"
    DISTINCT_COUNT = "distinct_count"


@dataclass
class HierarchyLevel:
    """Hierarchy level definition."""

    name: str
    description: str
    members: list[str] = field(default_factory=list)


@dataclass
class Hierarchy:
    """Dimension hierarchy."""

    name: str
    dimension_name: str
    levels: list[HierarchyLevel] = field(default_factory=list)

    def add_level(self, level: HierarchyLevel) -> None:
        """Add level to hierarchy."""
        self.levels.append(level)


@dataclass
class Dimension:
    """OLAP dimension."""

    name: str
    description: str
    members: list[str] = field(default_factory=list)
    hierarchies: dict[str, Hierarchy] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    def add_hierarchy(self, hierarchy: Hierarchy) -> None:
        """Add hierarchy to dimension."""
        self.hierarchies[hierarchy.name] = hierarchy

    def add_member(self, member: str) -> None:
        """Add member to dimension."""
        if member not in self.members:
            self.members.append(member)


@dataclass
class Measure:
    """OLAP measure."""

    name: str
    description: str
    aggregation: AggregationFunction
    data_type: str = "float"
    format_string: str = "#,##0.00"

    def aggregate(self, values: list[float]) -> float:
        """Aggregate values using configured function."""
        if not values:
            return 0.0

        if self.aggregation == AggregationFunction.SUM:
            return sum(values)
        elif self.aggregation == AggregationFunction.COUNT:
            return float(len(values))
        elif self.aggregation == AggregationFunction.AVERAGE:
            return sum(values) / len(values)
        elif self.aggregation == AggregationFunction.MIN:
            return min(values)
        elif self.aggregation == AggregationFunction.MAX:
            return max(values)
        elif self.aggregation == AggregationFunction.DISTINCT_COUNT:
            return float(len(set(values)))
        else:
            return sum(values)


@dataclass
class CellValue:
    """OLAP cell value."""

    coordinates: dict[str, str]  # Dimension -> Member mapping
    measures: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class OLAPCube:
    """OLAP hypercube for multi-dimensional analysis."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.dimensions: dict[str, Dimension] = {}
        self.measures: dict[str, Measure] = {}
        self.cells: dict[tuple, CellValue] = {}
        self.created_at = datetime.utcnow()

    def add_dimension(self, dimension: Dimension) -> None:
        """Add dimension to cube."""
        self.dimensions[dimension.name] = dimension

    def add_measure(self, measure: Measure) -> None:
        """Add measure to cube."""
        self.measures[measure.name] = measure

    def insert_cell(self, coordinates: dict[str, str], measures: dict[str, float]) -> None:
        """Insert cell value into cube."""
        key = tuple(sorted(coordinates.items()))
        self.cells[key] = CellValue(coordinates=coordinates, measures=measures)

    def get_cell(self, coordinates: dict[str, str]) -> CellValue | None:
        """Retrieve cell value."""
        key = tuple(sorted(coordinates.items()))
        return self.cells.get(key)

    def slice(self, dimension: str, member: str) -> dict[str, CellValue]:
        """Slice cube by dimension member."""
        result = {}
        for key, cell in self.cells.items():
            coord_dict = dict(key)
            if coord_dict.get(dimension) == member:
                result[str(key)] = cell
        return result

    def dice(self, filters: dict[str, list[str]]) -> dict[str, CellValue]:
        """Dice cube with multiple dimension filters."""
        result = {}
        for key, cell in self.cells.items():
            coord_dict = dict(key)
            matches = all(coord_dict.get(dim) in members for dim, members in filters.items())
            if matches:
                result[str(key)] = cell
        return result

    def rollup(self, dimension: str, from_level: str, to_level: str) -> dict[str, float]:
        """Roll up dimension to coarser level."""
        # Simplified rollup - aggregate measures
        aggregated = {}
        for key, cell in self.cells.items():
            coord_dict = dict(key)
            agg_key = tuple((k, v) for k, v in sorted(coord_dict.items()) if k != dimension)
            if agg_key not in aggregated:
                aggregated[agg_key] = {}

            for measure_name, value in cell.measures.items():
                if measure_name not in aggregated[agg_key]:
                    aggregated[agg_key][measure_name] = []
                aggregated[agg_key][measure_name].append(value)

        result = {}
        for agg_key, measures in aggregated.items():
            for measure_name, values in measures.items():
                if measure_name in self.measures:
                    measure = self.measures[measure_name]
                    result[f"{agg_key}:{measure_name}"] = measure.aggregate(values)

        return result

    def drilldown(self, dimension: str, parent_member: str, target_level: str) -> dict[str, CellValue]:
        """Drill down from higher to lower level."""
        # Get all members under parent in hierarchy
        if dimension not in self.dimensions:
            return {}

        dim = self.dimensions[dimension]
        # Simplified drill-down
        result = self.slice(dimension, parent_member)
        return result

    def pivot(self, row_dimensions: list[str], column_dimensions: list[str], measure: str) -> dict[str, Any]:
        """Pivot data into cross-tabular format."""
        pivot_data = {}

        for key, cell in self.cells.items():
            coord_dict = dict(key)
            row_key = tuple(coord_dict.get(d) for d in row_dimensions)
            col_key = tuple(coord_dict.get(d) for d in column_dimensions)

            if row_key not in pivot_data:
                pivot_data[row_key] = {}

            pivot_data[row_key][col_key] = cell.measures.get(measure, 0)

        return pivot_data

    def get_aggregated_value(self, measure: str, filters: dict[str, str] | None = None) -> float:
        """Get aggregated measure value across cells."""
        values = []

        for key, cell in self.cells.items():
            if filters:
                coord_dict = dict(key)
                if not all(coord_dict.get(k) == v for k, v in filters.items()):
                    continue

            values.append(cell.measures.get(measure, 0))

        if measure in self.measures and values:
            return self.measures[measure].aggregate(values)

        return 0.0

    def get_statistics(self) -> dict[str, Any]:
        """Get cube statistics."""
        return {
            "name": self.name,
            "dimensions": len(self.dimensions),
            "measures": len(self.measures),
            "cells": len(self.cells),
            "created_at": self.created_at.isoformat(),
        }
