"""Built-in functions for TSDB queries.

Includes mathematical, transformation, and predictive functions.
"""

import math


class MathFunctions:
    """Mathematical functions for time-series data."""

    @staticmethod
    def abs(values: list[float]) -> list[float]:
        """Return absolute values.

        Args:
            values: List of float values

        Returns:
            List of absolute values
        """
        return [abs(v) for v in values]

    @staticmethod
    def ceil(values: list[float]) -> list[float]:
        """Round up to nearest integer.

        Args:
            values: List of float values

        Returns:
            List of ceiling values
        """
        return [math.ceil(v) for v in values]

    @staticmethod
    def floor(values: list[float]) -> list[float]:
        """Round down to nearest integer.

        Args:
            values: List of float values

        Returns:
            List of floor values
        """
        return [math.floor(v) for v in values]

    @staticmethod
    def log(values: list[float], base: float = math.e) -> list[float]:
        """Compute logarithm.

        Args:
            values: List of float values
            base: Logarithm base (default e for natural log)

        Returns:
            List of log values

        Raises:
            ValueError: If any value is <= 0
        """
        if any(v <= 0 for v in values):
            raise ValueError("Cannot take log of non-positive values")
        return [math.log(v, base) for v in values]

    @staticmethod
    def exp(values: list[float]) -> list[float]:
        """Compute e^x.

        Args:
            values: List of float values

        Returns:
            List of exponential values
        """
        return [math.exp(v) for v in values]

    @staticmethod
    def pow(values: list[float], exponent: float) -> list[float]:
        """Raise to a power.

        Args:
            values: List of float values
            exponent: Power to raise to

        Returns:
            List of powered values
        """
        return [v**exponent for v in values]

    @staticmethod
    def sqrt(values: list[float]) -> list[float]:
        """Compute square root.

        Args:
            values: List of float values

        Returns:
            List of square roots

        Raises:
            ValueError: If any value is negative
        """
        if any(v < 0 for v in values):
            raise ValueError("Cannot take sqrt of negative values")
        return [math.sqrt(v) for v in values]


class TransformFunctions:
    """Transformation functions for time-series data."""

    @staticmethod
    def derivative(timestamps: list[int], values: list[float]) -> list[tuple[int, float]]:
        """Compute rate of change (derivative).

        Args:
            timestamps: List of timestamps in milliseconds
            values: List of values

        Returns:
            List of (timestamp, derivative) tuples

        Raises:
            ValueError: If fewer than 2 points
        """
        if len(values) < 2:
            raise ValueError("Need at least 2 points for derivative")

        result = []
        for i in range(1, len(values)):
            time_diff = (timestamps[i] - timestamps[i - 1]) / 1000.0  # Convert to seconds
            value_diff = values[i] - values[i - 1]
            derivative = value_diff / time_diff if time_diff > 0 else 0
            result.append((timestamps[i], derivative))

        return result

    @staticmethod
    def integral(timestamps: list[int], values: list[float]) -> float:
        """Compute approximate integral using trapezoidal rule.

        Args:
            timestamps: List of timestamps in milliseconds
            values: List of values

        Returns:
            Approximate integral

        Raises:
            ValueError: If fewer than 2 points
        """
        if len(values) < 2:
            raise ValueError("Need at least 2 points for integral")

        total = 0.0
        for i in range(1, len(values)):
            time_diff = (timestamps[i] - timestamps[i - 1]) / 1000.0  # Convert to seconds
            avg_value = (values[i] + values[i - 1]) / 2
            total += avg_value * time_diff

        return total

    @staticmethod
    def non_negative_derivative(timestamps: list[int], values: list[float]) -> list[tuple[int, float]]:
        """Compute derivative, treating decreases as zero (for counters).

        Args:
            timestamps: List of timestamps in milliseconds
            values: List of values (assumed to be monotonically increasing)

        Returns:
            List of (timestamp, rate) tuples
        """
        result = []
        for i in range(1, len(values)):
            time_diff = (timestamps[i] - timestamps[i - 1]) / 1000.0
            value_diff = values[i] - values[i - 1]

            # Treat resets as zero
            if value_diff < 0:
                rate = 0.0
            else:
                rate = value_diff / time_diff if time_diff > 0 else 0

            result.append((timestamps[i], rate))

        return result

    @staticmethod
    def scale(values: list[float], factor: float) -> list[float]:
        """Scale values by a factor.

        Args:
            values: List of float values
            factor: Multiplication factor

        Returns:
            Scaled values
        """
        return [v * factor for v in values]

    @staticmethod
    def offset(values: list[float], offset: float) -> list[float]:
        """Add offset to values.

        Args:
            values: List of float values
            offset: Value to add

        Returns:
            Offset values
        """
        return [v + offset for v in values]


class WindowFunctions:
    """Window/rolling functions for time-series data."""

    @staticmethod
    def moving_average(values: list[float], window_size: int) -> list[float | None]:
        """Compute moving average.

        Args:
            values: List of float values
            window_size: Size of moving window

        Returns:
            List of moving averages (None for first window_size-1 points)

        Raises:
            ValueError: If window size is invalid
        """
        if window_size < 1:
            raise ValueError("Window size must be >= 1")

        result: list[float | None] = []

        for i in range(len(values)):
            if i < window_size - 1:
                result.append(None)
            else:
                window = values[i - window_size + 1 : i + 1]
                result.append(sum(window) / window_size)

        return result

    @staticmethod
    def moving_stddev(values: list[float], window_size: int) -> list[float | None]:
        """Compute moving standard deviation.

        Args:
            values: List of float values
            window_size: Size of moving window

        Returns:
            List of moving standard deviations (None for first window_size-1 points)

        Raises:
            ValueError: If window size is invalid
        """
        if window_size < 2:
            raise ValueError("Window size must be >= 2")

        result: list[float | None] = []

        for i in range(len(values)):
            if i < window_size - 1:
                result.append(None)
            else:
                window = values[i - window_size + 1 : i + 1]
                mean = sum(window) / len(window)
                variance = sum((v - mean) ** 2 for v in window) / (len(window) - 1)
                result.append(math.sqrt(variance))

        return result

    @staticmethod
    def moving_sum(values: list[float], window_size: int) -> list[float | None]:
        """Compute moving sum.

        Args:
            values: List of float values
            window_size: Size of moving window

        Returns:
            List of moving sums (None for first window_size-1 points)
        """
        if window_size < 1:
            raise ValueError("Window size must be >= 1")

        result: list[float | None] = []

        for i in range(len(values)):
            if i < window_size - 1:
                result.append(None)
            else:
                window = values[i - window_size + 1 : i + 1]
                result.append(sum(window))

        return result

    @staticmethod
    def moving_min(values: list[float], window_size: int) -> list[float | None]:
        """Compute moving minimum.

        Args:
            values: List of float values
            window_size: Size of moving window

        Returns:
            List of moving minimums (None for first window_size-1 points)
        """
        if window_size < 1:
            raise ValueError("Window size must be >= 1")

        result: list[float | None] = []

        for i in range(len(values)):
            if i < window_size - 1:
                result.append(None)
            else:
                window = values[i - window_size + 1 : i + 1]
                result.append(min(window))

        return result

    @staticmethod
    def moving_max(values: list[float], window_size: int) -> list[float | None]:
        """Compute moving maximum.

        Args:
            values: List of float values
            window_size: Size of moving window

        Returns:
            List of moving maximums (None for first window_size-1 points)
        """
        if window_size < 1:
            raise ValueError("Window size must be >= 1")

        result: list[float | None] = []

        for i in range(len(values)):
            if i < window_size - 1:
                result.append(None)
            else:
                window = values[i - window_size + 1 : i + 1]
                result.append(max(window))

        return result


class PredictiveFunctions:
    """Predictive functions for forecasting."""

    @staticmethod
    def linear_regression(timestamps: list[int], values: list[float]) -> tuple[float, float]:
        """Fit linear regression model: value = slope * time + intercept.

        Args:
            timestamps: List of timestamps in milliseconds
            values: List of values

        Returns:
            Tuple of (slope, intercept)

        Raises:
            ValueError: If fewer than 2 points
        """
        if len(values) < 2:
            raise ValueError("Need at least 2 points for regression")

        n = len(values)
        # Convert timestamps to seconds and shift to start at 0
        t = [(ts - timestamps[0]) / 1000.0 for ts in timestamps]

        sum_t = sum(t)
        sum_v = sum(values)
        sum_tv = sum(a * b for a, b in zip(t, values))
        sum_t2 = sum(a**2 for a in t)

        # Least squares formulas
        denominator = n * sum_t2 - sum_t**2
        if denominator == 0:
            return (0.0, sum_v / n)  # All timestamps are the same

        slope = (n * sum_tv - sum_t * sum_v) / denominator
        intercept = (sum_v - slope * sum_t) / n

        return (slope, intercept)

    @staticmethod
    def predict_linear(timestamps: list[int], values: list[float], future_timestamp: int) -> float:
        """Predict value at future timestamp using linear regression.

        Args:
            timestamps: List of timestamps in milliseconds
            values: List of values
            future_timestamp: Timestamp to predict for in milliseconds

        Returns:
            Predicted value

        Raises:
            ValueError: If fewer than 2 points
        """
        slope, intercept = PredictiveFunctions.linear_regression(timestamps, values)
        t = (future_timestamp - timestamps[0]) / 1000.0
        return slope * t + intercept

    @staticmethod
    def holt_winters_simple(values: list[float], alpha: float = 0.3, beta: float = 0.1) -> list[float]:
        """Simple Holt-Winters smoothing (exponential smoothing with trend).

        Args:
            values: List of float values
            alpha: Smoothing factor for level (0-1)
            beta: Smoothing factor for trend (0-1)

        Returns:
            Smoothed values

        Raises:
            ValueError: If fewer than 2 points
        """
        if len(values) < 2:
            raise ValueError("Need at least 2 points for Holt-Winters")

        if not (0 <= alpha <= 1):
            raise ValueError("Alpha must be between 0 and 1")
        if not (0 <= beta <= 1):
            raise ValueError("Beta must be between 0 and 1")

        result = [values[0]]
        level = values[0]
        trend = values[1] - values[0]

        for i in range(1, len(values)):
            prev_level = level
            level = alpha * values[i] + (1 - alpha) * (prev_level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            result.append(level)

        return result
