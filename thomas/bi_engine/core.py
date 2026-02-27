"""Business Intelligence Engine with OLAP cubes, pivots, and dashboards.

Implements a BI system with multidimensional analysis, pivoting, and reporting.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AggregationFunction(str, Enum):
    """Aggregation functions for measures."""

    SUM = "sum"
    AVG = "avg"
    COUNT = "count"
    MIN = "min"
    MAX = "max"
    DISTINCT_COUNT = "distinct_count"


@dataclass
class Dimension:
    """A dimension in the OLAP cube."""

    name: str
    members: list[str] = field(default_factory=list)
    hierarchy_levels: list[str] = field(default_factory=list)

    def add_member(self, member: str) -> None:
        """Add a member to the dimension."""
        if member not in self.members:
            self.members.append(member)

    def add_hierarchy(self, level: str) -> None:
        """Add a hierarchy level."""
        if level not in self.hierarchy_levels:
            self.hierarchy_levels.append(level)


@dataclass
class Measure:
    """A measure (metric) in the OLAP cube."""

    name: str
    aggregation: AggregationFunction = AggregationFunction.SUM
    description: str = ""
    data_type: str = "numeric"


@dataclass
class Fact:
    """A fact record in the OLAP cube."""

    dimensions: dict[str, str]
    measures: dict[str, Any]
    timestamp: str | None = None


class OLAPCube:
    """Multidimensional OLAP cube."""

    def __init__(self, name: str):
        self.name = name
        self.dimensions: dict[str, Dimension] = {}
        self.measures: dict[str, Measure] = {}
        self.facts: list[Fact] = []
        self.indices: dict[str, set[str]] = defaultdict(set)

    def add_dimension(self, dimension: Dimension) -> None:
        """Add a dimension to the cube."""
        self.dimensions[dimension.name] = dimension

    def add_measure(self, measure: Measure) -> None:
        """Add a measure to the cube."""
        self.measures[measure.name] = measure

    def add_fact(self, fact: Fact) -> None:
        """Add a fact to the cube."""
        self.facts.append(fact)
        # Build indices for fast lookup
        for dim_name, dim_value in fact.dimensions.items():
            self.indices[f"{dim_name}={dim_value}"].add(len(self.facts) - 1)

    def slice(self, dimension: str, value: str) -> list[Fact]:
        """Slice the cube along a dimension."""
        key = f"{dimension}={value}"
        indices = self.indices.get(key, set())
        return [self.facts[i] for i in indices]

    def dice(self, constraints: dict[str, str]) -> list[Fact]:
        """Dice the cube with multiple constraints."""
        result = list(range(len(self.facts)))

        for dim, value in constraints.items():
            key = f"{dim}={value}"
            indices = self.indices.get(key, set())
            result = [i for i in result if i in indices]

        return [self.facts[i] for i in result]

    def drill_down(self, dimension: str, current_level: int = 0) -> list[dict[str, Any]]:
        """Drill down in a dimension hierarchy."""
        dim = self.dimensions.get(dimension)
        if not dim or current_level >= len(dim.hierarchy_levels):
            return []

        next_level = dim.hierarchy_levels[current_level + 1]
        results = []
        for member in dim.members:
            results.append({"member": member, "level": next_level, "count": len(self.slice(dimension, member))})
        return results

    def roll_up(self, dimension: str, target_level: int = 0) -> list[dict[str, Any]]:
        """Roll up in a dimension hierarchy."""
        dim = self.dimensions.get(dimension)
        if not dim or target_level < 0:
            return []

        level = dim.hierarchy_levels[target_level] if target_level < len(dim.hierarchy_levels) else "all"
        return [{"level": level, "members": dim.members, "total": len(self.facts)}]

    def get_cube_stats(self) -> dict[str, Any]:
        """Get cube statistics."""
        return {
            "name": self.name,
            "fact_count": len(self.facts),
            "dimension_count": len(self.dimensions),
            "measure_count": len(self.measures),
            "dimensions": list(self.dimensions.keys()),
            "measures": list(self.measures.keys()),
        }


class PivotTable:
    """Pivot table for multidimensional analysis."""

    def __init__(self, cube: OLAPCube):
        self.cube = cube
        self.row_dimensions: list[str] = []
        self.column_dimensions: list[str] = []
        self.measures: list[str] = []
        self.filters: dict[str, str] = {}
        self.data: dict[tuple, Any] = {}

    def set_row_dimensions(self, dimensions: list[str]) -> None:
        """Set row dimensions."""
        self.row_dimensions = dimensions

    def set_column_dimensions(self, dimensions: list[str]) -> None:
        """Set column dimensions."""
        self.column_dimensions = dimensions

    def set_measures(self, measures: list[str]) -> None:
        """Set measures to display."""
        self.measures = measures

    def add_filter(self, dimension: str, value: str) -> None:
        """Add a filter constraint."""
        self.filters[dimension] = value

    def generate(self) -> dict[str, Any]:
        """Generate the pivot table."""
        # Get filtered facts
        facts = self.cube.dice(self.filters) if self.filters else self.cube.facts

        # Aggregate data
        pivot_data = defaultdict(lambda: defaultdict(list))

        for fact in facts:
            row_key = tuple(fact.dimensions.get(d, "Total") for d in self.row_dimensions)
            col_key = tuple(fact.dimensions.get(d, "Total") for d in self.column_dimensions)

            for measure in self.measures:
                if measure in fact.measures:
                    key = (row_key, col_key, measure)
                    pivot_data[key].append(fact.measures[measure])

        # Format output
        result = {
            "row_dimensions": self.row_dimensions,
            "column_dimensions": self.column_dimensions,
            "measures": self.measures,
            "data": {},
        }

        for key, values in pivot_data.items():
            result["data"][str(key)] = self._aggregate(values, key[2])

        return result

    def _aggregate(self, values: list[Any], measure_name: str) -> Any:
        """Aggregate values based on measure aggregation function."""
        if not values:
            return None

        measure = self.cube.measures.get(measure_name)
        if not measure:
            return sum(values) if values else None

        if measure.aggregation == AggregationFunction.SUM:
            return sum(v for v in values if isinstance(v, (int, float)))
        elif measure.aggregation == AggregationFunction.AVG:
            nums = [v for v in values if isinstance(v, (int, float))]
            return sum(nums) / len(nums) if nums else None
        elif measure.aggregation == AggregationFunction.COUNT:
            return len(values)
        elif measure.aggregation == AggregationFunction.DISTINCT_COUNT:
            return len(set(values))
        elif measure.aggregation == AggregationFunction.MIN:
            nums = [v for v in values if isinstance(v, (int, float))]
            return min(nums) if nums else None
        elif measure.aggregation == AggregationFunction.MAX:
            nums = [v for v in values if isinstance(v, (int, float))]
            return max(nums) if nums else None

        return values[0] if values else None


class Dashboard:
    """BI Dashboard for displaying reports and metrics."""

    def __init__(self, name: str):
        self.name = name
        self.widgets: dict[str, dict[str, Any]] = {}
        self.layout: list[str] = []
        self.filters: dict[str, str] = {}
        self.refresh_interval: int = 300  # seconds

    def add_widget(self, widget_id: str, widget_config: dict[str, Any]) -> None:
        """Add a widget to the dashboard."""
        self.widgets[widget_id] = widget_config
        self.layout.append(widget_id)

    def remove_widget(self, widget_id: str) -> bool:
        """Remove a widget from the dashboard."""
        if widget_id in self.widgets:
            del self.widgets[widget_id]
            if widget_id in self.layout:
                self.layout.remove(widget_id)
            return True
        return False

    def set_filter(self, dimension: str, value: str) -> None:
        """Set a dashboard-wide filter."""
        self.filters[dimension] = value

    def get_widget_config(self, widget_id: str) -> dict[str, Any] | None:
        """Get widget configuration."""
        return self.widgets.get(widget_id)

    def get_layout(self) -> list[str]:
        """Get the dashboard layout."""
        return self.layout

    def export_config(self) -> dict[str, Any]:
        """Export dashboard configuration."""
        return {
            "name": self.name,
            "widgets": self.widgets,
            "layout": self.layout,
            "filters": self.filters,
            "refresh_interval": self.refresh_interval,
        }

    def import_config(self, config: dict[str, Any]) -> None:
        """Import dashboard configuration."""
        self.name = config.get("name", self.name)
        self.widgets = config.get("widgets", {})
        self.layout = config.get("layout", [])
        self.filters = config.get("filters", {})
        self.refresh_interval = config.get("refresh_interval", 300)


class BIEngine:
    """Main Business Intelligence Engine."""

    def __init__(self, name: str = "bi_engine"):
        self.name = name
        self.cubes: dict[str, OLAPCube] = {}
        self.dashboards: dict[str, Dashboard] = {}
        self.pivot_tables: dict[str, PivotTable] = {}

    def create_cube(self, name: str) -> OLAPCube:
        """Create a new OLAP cube."""
        cube = OLAPCube(name)
        self.cubes[name] = cube
        return cube

    def get_cube(self, name: str) -> OLAPCube | None:
        """Get a cube by name."""
        return self.cubes.get(name)

    def create_pivot(self, cube_name: str) -> PivotTable:
        """Create a pivot table for a cube."""
        cube = self.cubes.get(cube_name)
        if not cube:
            raise ValueError(f"Cube not found: {cube_name}")

        pivot = PivotTable(cube)
        self.pivot_tables[f"{cube_name}_pivot"] = pivot
        return pivot

    def create_dashboard(self, name: str) -> Dashboard:
        """Create a new dashboard."""
        dashboard = Dashboard(name)
        self.dashboards[name] = dashboard
        return dashboard

    def get_dashboard(self, name: str) -> Dashboard | None:
        """Get a dashboard by name."""
        return self.dashboards.get(name)

    def get_engine_stats(self) -> dict[str, Any]:
        """Get engine statistics."""
        return {
            "name": self.name,
            "cubes": len(self.cubes),
            "dashboards": len(self.dashboards),
            "pivot_tables": len(self.pivot_tables),
            "total_facts": sum(len(cube.facts) for cube in self.cubes.values()),
        }
