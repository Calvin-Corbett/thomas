"""Statistical operations for DataFrames."""

import math
from typing import Any

try:
    from ._exceptions import DataFrameError
    from ._types import DType
    from .frame import DataFrame
    from .series import Series
except ImportError:
    from _exceptions import DataFrameError
    from _types import DType
    from frame import DataFrame
    from series import Series


class StatisticalFunctions:
    """Statistical analysis functions."""

    @staticmethod
    def correlation(df: DataFrame) -> DataFrame:
        """Compute correlation matrix.

        Args:
            df: DataFrame with numeric columns

        Returns:
            Correlation matrix DataFrame
        """
        numeric_cols = [col for col in df.columns if df[col].dtype in (DType.INT, DType.FLOAT)]

        if not numeric_cols:
            raise DataFrameError("No numeric columns found")

        corr_data = {}
        for col1 in numeric_cols:
            corr_data[col1] = []
            for col2 in numeric_cols:
                corr = StatisticalFunctions._pearson_correlation(df[col1], df[col2])
                corr_data[col1].append(corr)

        return DataFrame(corr_data, index=numeric_cols)

    @staticmethod
    def _pearson_correlation(s1: Series, s2: Series) -> float | None:
        """Compute Pearson correlation coefficient."""
        if len(s1) != len(s2):
            return None

        # Get non-null pairs
        pairs = [(s1[i], s2[i]) for i in range(len(s1)) if s1[i] is not None and s2[i] is not None]

        if len(pairs) < 2:
            return None

        x_vals, y_vals = zip(*pairs)

        mean_x = sum(x_vals) / len(x_vals)
        mean_y = sum(y_vals) / len(y_vals)

        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals)) / len(pairs)
        std_x = math.sqrt(sum((x - mean_x) ** 2 for x in x_vals) / len(x_vals))
        std_y = math.sqrt(sum((y - mean_y) ** 2 for y in y_vals) / len(y_vals))

        if std_x == 0 or std_y == 0:
            return 0.0

        return cov / (std_x * std_y)

    @staticmethod
    def covariance(df: DataFrame) -> DataFrame:
        """Compute covariance matrix.

        Args:
            df: DataFrame with numeric columns

        Returns:
            Covariance matrix DataFrame
        """
        numeric_cols = [col for col in df.columns if df[col].dtype in (DType.INT, DType.FLOAT)]

        if not numeric_cols:
            raise DataFrameError("No numeric columns found")

        cov_data = {}
        for col1 in numeric_cols:
            cov_data[col1] = []
            for col2 in numeric_cols:
                cov = StatisticalFunctions._covariance(df[col1], df[col2])
                cov_data[col1].append(cov)

        return DataFrame(cov_data, index=numeric_cols)

    @staticmethod
    def _covariance(s1: Series, s2: Series) -> float | None:
        """Compute covariance."""
        if len(s1) != len(s2):
            return None

        pairs = [(s1[i], s2[i]) for i in range(len(s1)) if s1[i] is not None and s2[i] is not None]

        if not pairs:
            return None

        mean_x = sum(x for x, _ in pairs) / len(pairs)
        mean_y = sum(y for _, y in pairs) / len(pairs)

        return sum((x - mean_x) * (y - mean_y) for x, y in pairs) / len(pairs)

    @staticmethod
    def quantile(series: Series, q: float | list[float]) -> float | dict[float, float]:
        """Compute quantile(s).

        Args:
            series: The Series
            q: Quantile value(s) between 0 and 1

        Returns:
            Quantile value(s)
        """
        non_null = [v for v in series if v is not None]
        if not non_null:
            return None

        non_null.sort()

        if isinstance(q, float):
            if q < 0 or q > 1:
                raise ValueError("q must be between 0 and 1")
            idx = q * (len(non_null) - 1)
            lower = int(idx)
            upper = lower + 1
            if upper >= len(non_null):
                return float(non_null[-1])
            weight = idx - lower
            return non_null[lower] * (1 - weight) + non_null[upper] * weight
        else:
            result = {}
            for q_val in q:
                idx = q_val * (len(non_null) - 1)
                lower = int(idx)
                upper = lower + 1
                if upper >= len(non_null):
                    result[q_val] = float(non_null[-1])
                else:
                    weight = idx - lower
                    result[q_val] = non_null[lower] * (1 - weight) + non_null[upper] * weight
            return result

    @staticmethod
    def percentile(series: Series, p: int | list[int]) -> float | dict[int, float]:
        """Compute percentile(s).

        Args:
            series: The Series
            p: Percentile value(s) (0-100)

        Returns:
            Percentile value(s)
        """
        if isinstance(p, int):
            return StatisticalFunctions.quantile(series, p / 100.0)
        else:
            return StatisticalFunctions.quantile(series, [x / 100.0 for x in p])

    @staticmethod
    def skewness(series: Series) -> float | None:
        """Compute skewness (third moment).

        Args:
            series: The Series

        Returns:
            Skewness value
        """
        non_null = [v for v in series if v is not None]
        if len(non_null) < 3:
            return None

        mean = sum(non_null) / len(non_null)
        std = math.sqrt(sum((x - mean) ** 2 for x in non_null) / len(non_null))

        if std == 0:
            return 0.0

        m3 = sum((x - mean) ** 3 for x in non_null) / len(non_null)
        return m3 / (std**3)

    @staticmethod
    def kurtosis(series: Series) -> float | None:
        """Compute kurtosis (fourth moment).

        Args:
            series: The Series

        Returns:
            Kurtosis value (Fisher definition, excess kurtosis)
        """
        non_null = [v for v in series if v is not None]
        if len(non_null) < 4:
            return None

        mean = sum(non_null) / len(non_null)
        std = math.sqrt(sum((x - mean) ** 2 for x in non_null) / len(non_null))

        if std == 0:
            return 0.0

        m4 = sum((x - mean) ** 4 for x in non_null) / len(non_null)
        return (m4 / (std**4)) - 3.0

    @staticmethod
    def zscore(series: Series) -> Series:
        """Compute z-scores (standardized scores).

        Args:
            series: The Series

        Returns:
            Series of z-scores
        """
        mean = series.mean()
        std = series.std()

        if mean is None or std is None or std == 0:
            return Series([None] * len(series), name=series.name, dtype=DType.FLOAT)

        result = []
        for val in series:
            if val is None:
                result.append(None)
            else:
                result.append((val - mean) / std)

        return Series(result, name=series.name, dtype=DType.FLOAT)

    @staticmethod
    def binning(
        series: Series, bins: int | list[float], labels: list[str] | None = None, strategy: str = "equal_width"
    ) -> Series:
        """Bin continuous values.

        Args:
            series: The Series to bin
            bins: Number of bins or bin edges
            labels: Labels for bins
            strategy: 'equal_width' or 'equal_frequency'

        Returns:
            Series with bin labels
        """
        non_null_vals = [v for v in series if v is not None]
        if not non_null_vals:
            return Series([None] * len(series), name=series.name)

        if isinstance(bins, int):
            if strategy == "equal_width":
                min_val = min(non_null_vals)
                max_val = max(non_null_vals)
                bin_edges = [min_val + (max_val - min_val) * i / bins for i in range(bins + 1)]
            else:  # equal_frequency
                sorted_vals = sorted(non_null_vals)
                bin_edges = []
                for i in range(bins + 1):
                    idx = int(i * len(sorted_vals) / bins)
                    if idx >= len(sorted_vals):
                        idx = len(sorted_vals) - 1
                    if not bin_edges or bin_edges[-1] != sorted_vals[idx]:
                        bin_edges.append(sorted_vals[idx])
        else:
            bin_edges = bins

        result = []
        for val in series:
            if val is None:
                result.append(None)
            else:
                bin_idx = 0
                for i in range(len(bin_edges) - 1):
                    if val >= bin_edges[i] and val < bin_edges[i + 1]:
                        bin_idx = i
                        break
                    elif val >= bin_edges[i + 1]:
                        bin_idx = i + 1

                if labels:
                    result.append(labels[min(bin_idx, len(labels) - 1)])
                else:
                    result.append(bin_idx)

        return Series(result, name=series.name)

    @staticmethod
    def value_frequency_analysis(series: Series) -> dict[Any, dict[str, Any]]:
        """Analyze frequency distribution.

        Args:
            series: The Series

        Returns:
            Dictionary with frequency statistics
        """
        value_counts = series.value_counts()
        total = sum(value_counts.values())

        result = {}
        for val, count in sorted(value_counts.items(), key=lambda x: -x[1]):
            result[val] = {
                "count": count,
                "frequency": count / total if total > 0 else 0,
                "percentage": (count / total * 100) if total > 0 else 0,
            }

        return result
