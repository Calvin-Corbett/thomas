"""Exploratory Data Analysis tools for profiling and statistical analysis."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any


@dataclass
class ColumnProfile:
    """Statistical profile of a column."""

    name: str
    dtype: str
    non_null: int
    null_count: int
    unique: int
    min_val: Any | None = None
    max_val: Any | None = None
    mean: float | None = None
    median: float | None = None
    std_dev: float | None = None
    percentile_25: float | None = None
    percentile_75: float | None = None
    distinct_values: list[Any] | None = None


class DataProfiler:
    """Profile datasets for exploratory analysis."""

    def __init__(self):
        self.data: list[dict[str, Any]] = []
        self.column_names: list[str] = []

    def load_data(self, data: list[dict[str, Any]]) -> None:
        """Load data to analyze."""
        self.data = data
        if data:
            self.column_names = list(data[0].keys())

    def profile_column(self, column_name: str) -> ColumnProfile | None:
        """Generate profile for a single column."""
        if column_name not in self.column_names:
            return None

        values = [row.get(column_name) for row in self.data]
        non_null = [v for v in values if v is not None]
        null_count = len(values) - len(non_null)

        # Determine dtype
        dtype = "object"
        if non_null:
            if all(isinstance(v, bool) for v in non_null):
                dtype = "bool"
            elif all(isinstance(v, int) for v in non_null):
                dtype = "int64"
            elif all(isinstance(v, (int, float)) for v in non_null):
                dtype = "float64"
            elif all(isinstance(v, str) for v in non_null):
                dtype = "string"

        # Statistics for numeric columns
        numeric_vals = []
        if dtype in ("int64", "float64"):
            numeric_vals = [float(v) for v in non_null]

        profile = ColumnProfile(
            name=column_name,
            dtype=dtype,
            non_null=len(non_null),
            null_count=null_count,
            unique=len(set(non_null)),
            distinct_values=sorted(set(non_null))[:10] if non_null else None,
        )

        if numeric_vals:
            profile.min_val = min(numeric_vals)
            profile.max_val = max(numeric_vals)
            profile.mean = statistics.mean(numeric_vals)
            if len(numeric_vals) > 1:
                profile.median = statistics.median(numeric_vals)
                profile.std_dev = statistics.stdev(numeric_vals)

                sorted_vals = sorted(numeric_vals)
                n = len(sorted_vals)
                profile.percentile_25 = sorted_vals[int(n * 0.25)]
                profile.percentile_75 = sorted_vals[int(n * 0.75)]

        return profile

    def profile_all(self) -> dict[str, ColumnProfile]:
        """Profile all columns."""
        profiles = {}
        for col in self.column_names:
            profile = self.profile_column(col)
            if profile:
                profiles[col] = profile
        return profiles

    def get_summary_stats(self) -> dict[str, Any]:
        """Get summary statistics for the dataset."""
        return {
            "rows": len(self.data),
            "columns": len(self.column_names),
            "memory_usage": sum(len(str(v)) for row in self.data for v in row.values()),
            "dtypes": self._count_dtypes(),
        }

    def _count_dtypes(self) -> dict[str, int]:
        """Count data types."""
        profiles = self.profile_all()
        counts: dict[str, int] = {}
        for prof in profiles.values():
            counts[prof.dtype] = counts.get(prof.dtype, 0) + 1
        return counts


class DistributionAnalyzer:
    """Analyze value distributions."""

    def __init__(self, data: list[dict[str, Any]]):
        self.data = data

    def value_counts(self, column_name: str, top_n: int = 10) -> dict[Any, int]:
        """Count unique values."""
        counts: dict[Any, int] = {}
        for row in self.data:
            val = row.get(column_name)
            if val is not None:
                counts[val] = counts.get(val, 0) + 1

        # Sort and limit
        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_counts[:top_n])

    def histogram(self, column_name: str, bins: int = 10) -> dict[str, Any]:
        """Create histogram for numeric column."""
        values = [row.get(column_name) for row in self.data if row.get(column_name) is not None]
        numeric_vals = [float(v) for v in values if isinstance(v, (int, float))]

        if not numeric_vals:
            return {"error": "No numeric values"}

        min_val = min(numeric_vals)
        max_val = max(numeric_vals)
        bin_width = (max_val - min_val) / bins if max_val != min_val else 1

        bin_edges = [min_val + i * bin_width for i in range(bins + 1)]
        bin_counts = [0] * bins

        for val in numeric_vals:
            bin_idx = min(int((val - min_val) / bin_width), bins - 1)
            bin_counts[bin_idx] += 1

        return {"bins": bins, "bin_edges": bin_edges, "bin_counts": bin_counts, "min": min_val, "max": max_val}


class CorrelationAnalyzer:
    """Analyze correlations between columns."""

    def __init__(self, data: list[dict[str, Any]]):
        self.data = data

    def numeric_columns(self) -> list[str]:
        """Get numeric column names."""
        if not self.data:
            return []

        numeric = []
        for col in self.data[0].keys():
            values = [row.get(col) for row in self.data if row.get(col) is not None]
            if all(isinstance(v, (int, float)) for v in values):
                numeric.append(col)

        return numeric

    def pearson_correlation(self, col1: str, col2: str) -> float | None:
        """Calculate Pearson correlation between two numeric columns."""
        vals1 = []
        vals2 = []

        for row in self.data:
            v1 = row.get(col1)
            v2 = row.get(col2)
            if v1 is not None and v2 is not None and isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                vals1.append(float(v1))
                vals2.append(float(v2))

        if len(vals1) < 2:
            return None

        mean1 = statistics.mean(vals1)
        mean2 = statistics.mean(vals2)

        numerator = sum((vals1[i] - mean1) * (vals2[i] - mean2) for i in range(len(vals1)))
        denom1 = sum((vals1[i] - mean1) ** 2 for i in range(len(vals1))) ** 0.5
        denom2 = sum((vals2[i] - mean2) ** 2 for i in range(len(vals2))) ** 0.5

        if denom1 == 0 or denom2 == 0:
            return None

        return numerator / (denom1 * denom2)

    def correlation_matrix(self) -> dict[str, dict[str, float]]:
        """Generate correlation matrix for all numeric columns."""
        cols = self.numeric_columns()
        matrix: dict[str, dict[str, float]] = {}

        for col1 in cols:
            matrix[col1] = {}
            for col2 in cols:
                if col1 == col2:
                    matrix[col1][col2] = 1.0
                else:
                    corr = self.pearson_correlation(col1, col2)
                    matrix[col1][col2] = corr if corr is not None else 0.0

        return matrix


class OutlierDetector:
    """Detect outliers using statistical methods."""

    def __init__(self, data: list[dict[str, Any]]):
        self.data = data

    def iqr_outliers(self, column_name: str, multiplier: float = 1.5) -> list[tuple[int, Any]]:
        """Detect outliers using Interquartile Range method."""
        values = []
        indices = []

        for idx, row in enumerate(self.data):
            val = row.get(column_name)
            if val is not None and isinstance(val, (int, float)):
                values.append(float(val))
                indices.append(idx)

        if len(values) < 4:
            return []

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[int(n * 0.25)]
        q3 = sorted_vals[int(n * 0.75)]
        iqr = q3 - q1

        lower_bound = q1 - multiplier * iqr
        upper_bound = q3 + multiplier * iqr

        outliers = []
        for i, val in enumerate(values):
            if val < lower_bound or val > upper_bound:
                outliers.append((indices[i], val))

        return outliers

    def zscore_outliers(self, column_name: str, threshold: float = 3.0) -> list[tuple[int, Any]]:
        """Detect outliers using Z-score method."""
        values = []
        indices = []

        for idx, row in enumerate(self.data):
            val = row.get(column_name)
            if val is not None and isinstance(val, (int, float)):
                values.append(float(val))
                indices.append(idx)

        if len(values) < 2:
            return []

        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0

        if stdev == 0:
            return []

        outliers = []
        for i, val in enumerate(values):
            zscore = abs((val - mean) / stdev)
            if zscore > threshold:
                outliers.append((indices[i], val))

        return outliers


class DataReport:
    """Generate comprehensive data analysis report."""

    def __init__(self, data: list[dict[str, Any]]):
        self.data = data
        self.profiler = DataProfiler()
        self.profiler.load_data(data)

    def generate_report(self) -> dict[str, Any]:
        """Generate full analysis report."""
        return {
            "summary": self.profiler.get_summary_stats(),
            "column_profiles": {
                name: self._profile_to_dict(prof) for name, prof in self.profiler.profile_all().items()
            },
            "correlations": CorrelationAnalyzer(self.data).correlation_matrix() if self.data else {},
        }

    def _profile_to_dict(self, prof: ColumnProfile) -> dict[str, Any]:
        """Convert profile to dictionary."""
        return {
            "dtype": prof.dtype,
            "non_null": prof.non_null,
            "null_count": prof.null_count,
            "unique": prof.unique,
            "min": prof.min_val,
            "max": prof.max_val,
            "mean": prof.mean,
            "median": prof.median,
            "std_dev": prof.std_dev,
            "percentile_25": prof.percentile_25,
            "percentile_75": prof.percentile_75,
        }
