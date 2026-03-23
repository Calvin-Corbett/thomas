"""OLAP engine for multi-dimensional analysis.

Provides OLAP cubes, dimensions, measures, MDX-like queries,
drill-down, rollup, slice, dice, and pivot operations.
"""

from .core import (
    AggregationFunction,
    CellValue,
    Dimension,
    Hierarchy,
    HierarchyLevel,
    Measure,
    OLAPCube,
)

__all__ = [
    "AggregationFunction",
    "HierarchyLevel",
    "Hierarchy",
    "Dimension",
    "Measure",
    "CellValue",
    "OLAPCube",
]

__version__ = "1.0.0"
