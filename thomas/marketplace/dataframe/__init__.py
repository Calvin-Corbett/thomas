"""Thomas DataFrame Library.

A lightweight, from-scratch implementation of a DataFrame library with no pandas dependency.

Provides:
- Series: Single-column data structure with typed storage
- DataFrame: Two-dimensional tabular data
- GroupBy: Grouped operations
- Joins: Merge/join operations
- Window functions: Rolling, expanding, cumulative operations
- Reshaping: Pivot, melt, transpose, explode
- Statistics: Correlation, covariance, quantiles, z-scores
- I/O: CSV, JSON, Markdown table output
"""

from ._exceptions import ColumnNotFoundError, DataFrameError, MergeError, ShapeError, TypeMismatchError
from ._types import (
    AggFunc,
    ColumnInfo,
    DType,
    IndexType,
    JoinType,
    SortOrder,
    can_compare,
    default_value,
    infer_dtype,
    promote_dtype,
)
from .frame import DataFrame
from .groupby import GroupBy
from .ioutils import CSVReader, CSVWriter, JSONHandler, MarkdownTable
from .joins import JoinOperation
from .reshape import ReshapeOperations
from .selection import ILoc, Loc, QueryParser, boolean_indexing
from .series import Series
from .stats import StatisticalFunctions
from .window import WindowFunctions

__all__ = [
    # Types and enums
    "DType",
    "SortOrder",
    "JoinType",
    "AggFunc",
    "IndexType",
    "ColumnInfo",
    "infer_dtype",
    "promote_dtype",
    "can_compare",
    "default_value",
    # Exceptions
    "DataFrameError",
    "ColumnNotFoundError",
    "TypeMismatchError",
    "ShapeError",
    "MergeError",
    # Main classes
    "Series",
    "DataFrame",
    "GroupBy",
    # Selection
    "Loc",
    "ILoc",
    "QueryParser",
    "boolean_indexing",
    # Operations
    "JoinOperation",
    "WindowFunctions",
    "ReshapeOperations",
    "StatisticalFunctions",
    # I/O
    "CSVReader",
    "CSVWriter",
    "JSONHandler",
    "MarkdownTable",
]

__version__ = "0.1.0"
