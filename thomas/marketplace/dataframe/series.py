"""Series class: single-column data structure with typed storage."""

import math
from collections.abc import Callable
from datetime import datetime
from typing import Any, Union

try:
    from ._exceptions import DataFrameError, ShapeError
    from ._types import DType, default_value, infer_dtype, promote_dtype
except ImportError:
    from _exceptions import DataFrameError, ShapeError
    from _types import DType, default_value, infer_dtype, promote_dtype


class Series:
    """A one-dimensional labeled array.

    Represents a single column of data with a specific dtype.

    Attributes:
        name: Column name
        _data: Internal data storage (list)
        _dtype: Data type of the series
        _null_mask: Boolean mask for null values
    """

    def __init__(self, data: list[Any] | None = None, name: str = "", dtype: DType | None = None) -> None:
        """Initialize a Series.

        Args:
            data: List of values
            name: Name of the series
            dtype: Data type (inferred if not provided)

        Raises:
            ShapeError: If data is not a list
        """
        self.name = name
        self._null_mask: list[bool] = []

        if data is None:
            data = []

        if not isinstance(data, list):
            raise ShapeError((0,), (len(data),))

        # Infer dtype if not provided
        if dtype is None:
            dtype = self._infer_dtype_from_data(data)

        self._dtype = dtype
        self._data: list[Any] = []
        self._null_mask = []

        # Convert and store data
        for value in data:
            if value is None:
                self._null_mask.append(True)
                self._data.append(default_value(dtype))
            else:
                self._null_mask.append(False)
                self._data.append(self._convert_value(value, dtype))

    def _infer_dtype_from_data(self, data: list[Any]) -> DType:
        """Infer dtype from data list."""
        if not data:
            return DType.NULL
        non_null = [v for v in data if v is not None]
        if not non_null:
            return DType.NULL
        inferred = infer_dtype(non_null[0])
        for val in non_null[1:]:
            inferred = promote_dtype(inferred, infer_dtype(val))
        return inferred

    def _convert_value(self, value: Any, dtype: DType) -> Any:
        """Convert a value to the target dtype."""
        if value is None:
            return default_value(dtype)
        if dtype == DType.INT:
            return int(value)
        if dtype == DType.FLOAT:
            return float(value)
        if dtype == DType.BOOL:
            return bool(value)
        if dtype == DType.STRING:
            return str(value)
        if dtype == DType.DATETIME:
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value))
        return value

    @property
    def dtype(self) -> DType:
        """Get the data type."""
        return self._dtype

    @property
    def shape(self) -> tuple[int]:
        """Get the shape (length,)."""
        return (len(self._data),)

    def __len__(self) -> int:
        """Get the length."""
        return len(self._data)

    def __getitem__(self, key: int | slice) -> Any:
        """Get element or slice."""
        if isinstance(key, int):
            if key < 0:
                key += len(self._data)
            if key < 0 or key >= len(self._data):
                raise IndexError(f"Index {key} out of range")
            if self._null_mask[key]:
                return None
            return self._data[key]
        elif isinstance(key, slice):
            indices = range(*key.indices(len(self._data)))
            return Series([self[i] for i in indices], name=self.name, dtype=self._dtype)
        raise TypeError(f"Invalid index type: {type(key)}")

    def __setitem__(self, key: int, value: Any) -> None:
        """Set an element."""
        if key < 0:
            key += len(self._data)
        if key < 0 or key >= len(self._data):
            raise IndexError(f"Index {key} out of range")
        if value is None:
            self._null_mask[key] = True
            self._data[key] = default_value(self._dtype)
        else:
            self._null_mask[key] = False
            self._data[key] = self._convert_value(value, self._dtype)

    def __repr__(self) -> str:
        """String representation."""
        lines = [f"Series(name={self.name!r}, dtype={self._dtype})"]
        for i, (val, is_null) in enumerate(zip(self._data, self._null_mask)):
            display = "None" if is_null else repr(val)
            lines.append(f"  {i}: {display}")
        return "\n".join(lines)

    def __add__(self, other: Union["Series", int, float]) -> "Series":
        """Element-wise addition."""
        return self._binary_op(other, lambda a, b: a + b, "+")

    def __sub__(self, other: Union["Series", int, float]) -> "Series":
        """Element-wise subtraction."""
        return self._binary_op(other, lambda a, b: a - b, "-")

    def __mul__(self, other: Union["Series", int, float]) -> "Series":
        """Element-wise multiplication."""
        return self._binary_op(other, lambda a, b: a * b, "*")

    def __truediv__(self, other: Union["Series", int, float]) -> "Series":
        """Element-wise division."""
        return self._binary_op(other, lambda a, b: a / b, "/")

    def __floordiv__(self, other: Union["Series", int, float]) -> "Series":
        """Element-wise floor division."""
        return self._binary_op(other, lambda a, b: a // b, "//")

    def __mod__(self, other: Union["Series", int, float]) -> "Series":
        """Element-wise modulo."""
        return self._binary_op(other, lambda a, b: a % b, "%")

    def __pow__(self, other: Union["Series", int, float]) -> "Series":
        """Element-wise power."""
        return self._binary_op(other, lambda a, b: a**b, "**")

    def _binary_op(self, other: Union["Series", int, float], op: Callable[[Any, Any], Any], op_name: str) -> "Series":
        """Apply a binary operation."""
        if isinstance(other, Series):
            if len(self) != len(other):
                raise ShapeError(self.shape, other.shape)
            result = []
            for i in range(len(self)):
                v1 = self[i]
                v2 = other[i]
                if v1 is None or v2 is None:
                    result.append(None)
                else:
                    result.append(op(v1, v2))
            return Series(result, name=self.name)
        else:
            result = []
            for i in range(len(self)):
                v = self[i]
                if v is None:
                    result.append(None)
                else:
                    result.append(op(v, other))
            return Series(result, name=self.name)

    def __eq__(self, other: Union["Series", Any]) -> "Series":  # type: ignore
        """Element-wise equality."""
        if isinstance(other, Series):
            if len(self) != len(other):
                raise ShapeError(self.shape, other.shape)
            result = []
            for i in range(len(self)):
                v1, v2 = self[i], other[i]
                result.append(None if (v1 is None or v2 is None) else v1 == v2)
            return Series(result, name=self.name, dtype=DType.BOOL)
        else:
            result = []
            for i in range(len(self)):
                v = self[i]
                result.append(None if v is None else v == other)
            return Series(result, name=self.name, dtype=DType.BOOL)

    def __ne__(self, other: Union["Series", Any]) -> "Series":  # type: ignore
        """Element-wise inequality."""
        if isinstance(other, Series):
            if len(self) != len(other):
                raise ShapeError(self.shape, other.shape)
            result = []
            for i in range(len(self)):
                v1, v2 = self[i], other[i]
                result.append(None if (v1 is None or v2 is None) else v1 != v2)
            return Series(result, name=self.name, dtype=DType.BOOL)
        else:
            result = []
            for i in range(len(self)):
                v = self[i]
                result.append(None if v is None else v != other)
            return Series(result, name=self.name, dtype=DType.BOOL)

    def __lt__(self, other: Union["Series", Any]) -> "Series":  # type: ignore
        """Element-wise less than."""
        return self._compare_op(other, lambda a, b: a < b)

    def __le__(self, other: Union["Series", Any]) -> "Series":  # type: ignore
        """Element-wise less than or equal."""
        return self._compare_op(other, lambda a, b: a <= b)

    def __gt__(self, other: Union["Series", Any]) -> "Series":  # type: ignore
        """Element-wise greater than."""
        return self._compare_op(other, lambda a, b: a > b)

    def __ge__(self, other: Union["Series", Any]) -> "Series":  # type: ignore
        """Element-wise greater than or equal."""
        return self._compare_op(other, lambda a, b: a >= b)

    def _compare_op(self, other: Union["Series", Any], op: Callable[[Any, Any], bool]) -> "Series":
        """Apply a comparison operation."""
        if isinstance(other, Series):
            if len(self) != len(other):
                raise ShapeError(self.shape, other.shape)
            result = []
            for i in range(len(self)):
                v1, v2 = self[i], other[i]
                result.append(None if (v1 is None or v2 is None) else op(v1, v2))
            return Series(result, name=self.name, dtype=DType.BOOL)
        else:
            result = []
            for i in range(len(self)):
                v = self[i]
                result.append(None if v is None else op(v, other))
            return Series(result, name=self.name, dtype=DType.BOOL)

    # String methods
    def lower(self) -> "Series":
        """Convert strings to lowercase."""
        if self._dtype != DType.STRING:
            raise DataFrameError("lower() only works on STRING dtype")
        result = []
        for val in self._data:
            result.append(val.lower() if val else val)
        return Series(result, name=self.name, dtype=DType.STRING)

    def upper(self) -> "Series":
        """Convert strings to uppercase."""
        if self._dtype != DType.STRING:
            raise DataFrameError("upper() only works on STRING dtype")
        result = []
        for val in self._data:
            result.append(val.upper() if val else val)
        return Series(result, name=self.name, dtype=DType.STRING)

    def contains(self, pattern: str) -> "Series":
        """Check if strings contain a pattern."""
        if self._dtype != DType.STRING:
            raise DataFrameError("contains() only works on STRING dtype")
        result = []
        for i, val in enumerate(self._data):
            if self._null_mask[i]:
                result.append(None)
            else:
                result.append(pattern in val)
        return Series(result, name=self.name, dtype=DType.BOOL)

    def replace(self, old: str, new: str) -> "Series":
        """Replace substring in strings."""
        if self._dtype != DType.STRING:
            raise DataFrameError("replace() only works on STRING dtype")
        result = []
        for val in self._data:
            result.append(val.replace(old, new) if val else val)
        return Series(result, name=self.name, dtype=DType.STRING)

    def split(self, sep: str) -> "Series":
        """Split strings by separator."""
        if self._dtype != DType.STRING:
            raise DataFrameError("split() only works on STRING dtype")
        result = []
        for i, val in enumerate(self._data):
            if self._null_mask[i]:
                result.append(None)
            else:
                result.append(val.split(sep))
        return Series(result, name=self.name)

    # DateTime methods
    def year(self) -> "Series":
        """Extract year from datetime."""
        if self._dtype != DType.DATETIME:
            raise DataFrameError("year() only works on DATETIME dtype")
        result = []
        for i, val in enumerate(self._data):
            if self._null_mask[i]:
                result.append(None)
            else:
                result.append(val.year)
        return Series(result, name=self.name, dtype=DType.INT)

    def month(self) -> "Series":
        """Extract month from datetime."""
        if self._dtype != DType.DATETIME:
            raise DataFrameError("month() only works on DATETIME dtype")
        result = []
        for i, val in enumerate(self._data):
            if self._null_mask[i]:
                result.append(None)
            else:
                result.append(val.month)
        return Series(result, name=self.name, dtype=DType.INT)

    def day(self) -> "Series":
        """Extract day from datetime."""
        if self._dtype != DType.DATETIME:
            raise DataFrameError("day() only works on DATETIME dtype")
        result = []
        for i, val in enumerate(self._data):
            if self._null_mask[i]:
                result.append(None)
            else:
                result.append(val.day)
        return Series(result, name=self.name, dtype=DType.INT)

    def hour(self) -> "Series":
        """Extract hour from datetime."""
        if self._dtype != DType.DATETIME:
            raise DataFrameError("hour() only works on DATETIME dtype")
        result = []
        for i, val in enumerate(self._data):
            if self._null_mask[i]:
                result.append(None)
            else:
                result.append(val.hour)
        return Series(result, name=self.name, dtype=DType.INT)

    # Null handling
    def isna(self) -> "Series":
        """Return boolean Series indicating null values."""
        result = [is_null for is_null in self._null_mask]
        return Series(result, name=self.name, dtype=DType.BOOL)

    def fillna(self, value: Any) -> "Series":
        """Fill null values with a scalar."""
        result = []
        for i, (val, is_null) in enumerate(zip(self._data, self._null_mask)):
            if is_null:
                result.append(self._convert_value(value, self._dtype))
            else:
                result.append(val)
        series = Series(result, name=self.name, dtype=self._dtype)
        return series

    def dropna(self) -> "Series":
        """Remove null values."""
        result = []
        for i, (val, is_null) in enumerate(zip(self._data, self._null_mask)):
            if not is_null:
                result.append(val)
        return Series(result, name=self.name, dtype=self._dtype)

    # Aggregations
    def sum(self) -> int | float | None:
        """Sum all non-null values."""
        total = 0
        count = 0
        for val, is_null in zip(self._data, self._null_mask):
            if not is_null:
                total += val
                count += 1
        return total if count > 0 else None

    def mean(self) -> float | None:
        """Mean of all non-null values."""
        total = 0
        count = 0
        for val, is_null in zip(self._data, self._null_mask):
            if not is_null:
                total += val
                count += 1
        return total / count if count > 0 else None

    def std(self) -> float | None:
        """Standard deviation of non-null values."""
        m = self.mean()
        if m is None:
            return None
        count = 0
        sum_sq_diff = 0.0
        for val, is_null in zip(self._data, self._null_mask):
            if not is_null:
                sum_sq_diff += (val - m) ** 2
                count += 1
        if count <= 1:
            return None
        return math.sqrt(sum_sq_diff / (count - 1))

    def min(self) -> Any | None:
        """Minimum non-null value."""
        min_val = None
        for val, is_null in zip(self._data, self._null_mask):
            if not is_null:
                if min_val is None or val < min_val:
                    min_val = val
        return min_val

    def max(self) -> Any | None:
        """Maximum non-null value."""
        max_val = None
        for val, is_null in zip(self._data, self._null_mask):
            if not is_null:
                if max_val is None or val > max_val:
                    max_val = val
        return max_val

    def count(self) -> int:
        """Count of non-null values."""
        return sum(1 for is_null in self._null_mask if not is_null)

    def nunique(self) -> int:
        """Count of unique values (excluding nulls)."""
        seen = set()
        for val, is_null in zip(self._data, self._null_mask):
            if not is_null:
                seen.add(val)
        return len(seen)

    def value_counts(self) -> dict[Any, int]:
        """Return dictionary of value counts."""
        counts: dict[Any, int] = {}
        for val, is_null in zip(self._data, self._null_mask):
            if not is_null:
                counts[val] = counts.get(val, 0) + 1
        return counts

    def apply(self, func: Callable[[Any], Any]) -> "Series":
        """Apply a function to each non-null element."""
        result = []
        for val, is_null in zip(self._data, self._null_mask):
            if is_null:
                result.append(None)
            else:
                result.append(func(val))
        return Series(result, name=self.name)

    def map(self, mapping: dict[Any, Any]) -> "Series":
        """Map values using a dictionary."""
        result = []
        for val, is_null in zip(self._data, self._null_mask):
            if is_null:
                result.append(None)
            else:
                result.append(mapping.get(val))
        return Series(result, name=self.name)
