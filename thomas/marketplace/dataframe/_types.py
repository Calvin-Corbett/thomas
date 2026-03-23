"""Type system and enumerations for the DataFrame library."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class DType(Enum):
    """Data type enumeration for DataFrame columns."""

    INT = auto()
    FLOAT = auto()
    STRING = auto()
    BOOL = auto()
    DATETIME = auto()
    NULL = auto()

    def __repr__(self) -> str:
        return f"<{self.name}>"


class SortOrder(Enum):
    """Sort order enumeration."""

    ASC = auto()
    DESC = auto()


class JoinType(Enum):
    """Join type enumeration."""

    INNER = auto()
    LEFT = auto()
    RIGHT = auto()
    OUTER = auto()
    CROSS = auto()


class AggFunc(Enum):
    """Aggregation function enumeration."""

    SUM = auto()
    MEAN = auto()
    COUNT = auto()
    MIN = auto()
    MAX = auto()
    STD = auto()
    VAR = auto()
    FIRST = auto()
    LAST = auto()
    NUNIQUE = auto()


class IndexType(Enum):
    """Index type enumeration."""

    INTEGER = auto()
    LABEL = auto()
    DATETIME = auto()


@dataclass
class ColumnInfo:
    """Metadata about a DataFrame column.

    Attributes:
        name: Column name
        dtype: Data type of the column
        null_count: Number of null values
        unique_count: Number of unique values
        min_val: Minimum value (for numeric types)
        max_val: Maximum value (for numeric types)
    """

    name: str
    dtype: DType
    null_count: int = 0
    unique_count: int = 0
    min_val: Any | None = None
    max_val: Any | None = None

    def __repr__(self) -> str:
        return (
            f"ColumnInfo(name={self.name!r}, dtype={self.dtype}, "
            f"null_count={self.null_count}, unique_count={self.unique_count})"
        )


def infer_dtype(value: Any) -> DType:
    """Infer the DType of a Python value.

    Args:
        value: A Python value

    Returns:
        The inferred DType
    """
    if value is None:
        return DType.NULL
    if isinstance(value, bool):
        return DType.BOOL
    if isinstance(value, int):
        return DType.INT
    if isinstance(value, float):
        return DType.FLOAT
    if isinstance(value, str):
        return DType.STRING
    return DType.STRING


def promote_dtype(dtype1: DType, dtype2: DType) -> DType:
    """Promote two dtypes to a common dtype.

    Args:
        dtype1: First dtype
        dtype2: Second dtype

    Returns:
        The promoted dtype (more general type)
    """
    if dtype1 == dtype2:
        return dtype1
    if dtype1 == DType.NULL:
        return dtype2
    if dtype2 == DType.NULL:
        return dtype1
    if {dtype1, dtype2} == {DType.INT, DType.FLOAT}:
        return DType.FLOAT
    if {dtype1, dtype2} == {DType.INT, DType.BOOL}:
        return DType.INT
    if {dtype1, dtype2} == {DType.FLOAT, DType.BOOL}:
        return DType.FLOAT
    return DType.STRING


def can_compare(dtype1: DType, dtype2: DType) -> bool:
    """Check if two dtypes can be compared.

    Args:
        dtype1: First dtype
        dtype2: Second dtype

    Returns:
        True if the types can be compared
    """
    if dtype1 == DType.NULL or dtype2 == DType.NULL:
        return True
    if dtype1 == dtype2:
        return True
    numeric_types = {DType.INT, DType.FLOAT}
    if dtype1 in numeric_types and dtype2 in numeric_types:
        return True
    return False


def default_value(dtype: DType) -> Any:
    """Get the default value for a DType.

    Args:
        dtype: The data type

    Returns:
        The default value for that type
    """
    if dtype == DType.INT:
        return 0
    if dtype == DType.FLOAT:
        return 0.0
    if dtype == DType.BOOL:
        return False
    if dtype == DType.STRING:
        return ""
    if dtype == DType.DATETIME:
        return None
    return None
