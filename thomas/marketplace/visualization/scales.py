"""Scale implementations for data-to-pixel mapping."""

import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from thomas.marketplace.visualization._exceptions import InvalidScaleError
from thomas.marketplace.visualization._types import Tick


class BaseScale(ABC):
    """Abstract base class for scales."""

    def __init__(
        self,
        domain: tuple[float | datetime, float | datetime],
        range_vals: tuple[float, float],
    ) -> None:
        """Initialize scale.

        Args:
            domain: Input domain [min, max]
            range_vals: Output range [min, max]

        Raises:
            InvalidScaleError: If domain or range is invalid
        """
        if not domain or len(domain) != 2:
            raise InvalidScaleError("Domain must be a tuple of two values")
        if not range_vals or len(range_vals) != 2:
            raise InvalidScaleError("Range must be a tuple of two values")

        self.domain = domain
        self.range = range_vals

    @abstractmethod
    def map_value(self, value: float | str | datetime) -> float:
        """Map value from domain to range.

        Args:
            value: Input value

        Returns:
            Mapped value in range
        """
        pass

    @abstractmethod
    def invert(self, pixel_value: float) -> float | datetime:
        """Invert mapping from range to domain.

        Args:
            pixel_value: Output value in range

        Returns:
            Corresponding input value
        """
        pass

    @abstractmethod
    def generate_ticks(self, count: int = 10) -> list[Tick]:
        """Generate tick positions and labels.

        Args:
            count: Approximate number of ticks

        Returns:
            List of Tick objects
        """
        pass


class LinearScale(BaseScale):
    """Linear scale with direct proportional mapping."""

    def map_value(self, value: float | str | datetime) -> float:
        """Map value from domain to range using linear interpolation.

        Args:
            value: Input value

        Returns:
            Mapped value in range
        """
        if not isinstance(value, (int, float)):
            raise InvalidScaleError(f"LinearScale expects numeric value, got {type(value)}")

        d_min, d_max = self.domain
        if not isinstance(d_min, (int, float)):
            raise InvalidScaleError("LinearScale domain must be numeric")

        if d_min == d_max:
            return (self.range[0] + self.range[1]) / 2.0

        normalized = (value - d_min) / (d_max - d_min)
        r_min, r_max = self.range
        return r_min + normalized * (r_max - r_min)

    def invert(self, pixel_value: float) -> float:
        """Invert pixel value to data value.

        Args:
            pixel_value: Output value in range

        Returns:
            Corresponding input value
        """
        r_min, r_max = self.range
        if r_min == r_max:
            d_min, d_max = self.domain
            return (d_min + d_max) / 2.0

        normalized = (pixel_value - r_min) / (r_max - r_min)
        d_min, d_max = self.domain
        return d_min + normalized * (d_max - d_min)

    def generate_ticks(self, count: int = 10) -> list[Tick]:
        """Generate ticks with nice numbers.

        Args:
            count: Approximate number of ticks

        Returns:
            List of Tick objects
        """
        d_min, d_max = self.domain
        if not isinstance(d_min, (int, float)) or not isinstance(d_max, (int, float)):
            return []

        if d_min == d_max:
            return [Tick(d_min, str(d_min), 0.5)]

        nice_ticks = self._calculate_nice_ticks(d_min, d_max, count)
        r_min, r_max = self.range

        ticks = []
        for tick_val in nice_ticks:
            if d_min <= tick_val <= d_max:
                position = self.map_value(tick_val) - r_min
                if r_max > r_min:
                    position = position / (r_max - r_min)
                else:
                    position = 0.5

                label = self._format_tick_label(tick_val)
                ticks.append(Tick(tick_val, label, position))

        return ticks

    @staticmethod
    def _calculate_nice_ticks(
        d_min: float,
        d_max: float,
        count: int,
    ) -> list[float]:
        """Calculate nice tick values using Wilkinson's algorithm.

        Args:
            d_min: Domain minimum
            d_max: Domain maximum
            count: Target number of ticks

        Returns:
            List of tick values
        """
        range_val = d_max - d_min
        if range_val <= 0:
            return [d_min]

        z = math.ceil(math.log10(range_val))
        unit = 10 ** (z - 1)

        steps = [1, 2, 5]
        best_ticks = []
        best_score = float("inf")

        for step in steps:
            tick_unit = step * unit
            tick_min = math.floor(d_min / tick_unit) * tick_unit
            tick_max = math.ceil(d_max / tick_unit) * tick_unit

            ticks = []
            current = tick_min
            while current <= tick_max + tick_unit * 0.0001:
                if current >= d_min - tick_unit * 0.0001:
                    ticks.append(current)
                current += tick_unit

            if len(ticks) > 0:
                score = abs(len(ticks) - count)
                if score < best_score:
                    best_score = score
                    best_ticks = ticks

        return best_ticks if best_ticks else [d_min, d_max]

    @staticmethod
    def _format_tick_label(value: float) -> str:
        """Format tick value as label.

        Args:
            value: Tick value

        Returns:
            Formatted label string
        """
        if abs(value) < 0.001 and value != 0:
            return f"{value:.2e}"
        elif value == int(value):
            return str(int(value))
        else:
            return f"{value:.2f}".rstrip("0").rstrip(".")


class LogarithmicScale(BaseScale):
    """Logarithmic scale for exponential data."""

    def __init__(
        self,
        domain: tuple[float, float],
        range_vals: tuple[float, float],
        base: float = 10.0,
    ) -> None:
        """Initialize logarithmic scale.

        Args:
            domain: Input domain [min, max]
            range_vals: Output range [min, max]
            base: Logarithm base (10, 2, or e)

        Raises:
            InvalidScaleError: If domain contains non-positive values
        """
        if domain[0] <= 0 or domain[1] <= 0:
            raise InvalidScaleError("LogarithmicScale domain must be positive")
        super().__init__(domain, range_vals)
        if base not in (2, 10, math.e):
            raise InvalidScaleError(f"Logarithm base must be 2, 10, or e, got {base}")
        self.base = base

    def map_value(self, value: float | str | datetime) -> float:
        """Map value using logarithmic transformation.

        Args:
            value: Input value (must be positive)

        Returns:
            Mapped value in range
        """
        if not isinstance(value, (int, float)) or value <= 0:
            raise InvalidScaleError(f"LogarithmicScale requires positive numeric value, got {value}")

        d_min, d_max = self.domain
        log_min = math.log(d_min, self.base)
        log_max = math.log(d_max, self.base)
        log_val = math.log(value, self.base)

        if log_min == log_max:
            return (self.range[0] + self.range[1]) / 2.0

        normalized = (log_val - log_min) / (log_max - log_min)
        r_min, r_max = self.range
        return r_min + normalized * (r_max - r_min)

    def invert(self, pixel_value: float) -> float:
        """Invert pixel value to data value.

        Args:
            pixel_value: Output value in range

        Returns:
            Corresponding input value
        """
        r_min, r_max = self.range
        if r_min == r_max:
            return math.sqrt(self.domain[0] * self.domain[1])

        normalized = (pixel_value - r_min) / (r_max - r_min)
        d_min, d_max = self.domain
        log_min = math.log(d_min, self.base)
        log_max = math.log(d_max, self.base)
        log_val = log_min + normalized * (log_max - log_min)

        return self.base**log_val

    def generate_ticks(self, count: int = 10) -> list[Tick]:
        """Generate logarithmic ticks.

        Args:
            count: Approximate number of ticks

        Returns:
            List of Tick objects
        """
        d_min, d_max = self.domain
        log_min = math.log(d_min, self.base)
        log_max = math.log(d_max, self.base)

        linear_scale = LinearScale((log_min, log_max), self.range)
        log_ticks = linear_scale.generate_ticks(count)

        ticks = []
        for tick in log_ticks:
            data_val = self.base**tick.value
            ticks.append(Tick(data_val, f"{data_val:.2g}", tick.position))

        return ticks


class CategoricalScale(BaseScale):
    """Categorical scale for discrete categories."""

    def __init__(
        self,
        domain: tuple[str, ...],
        range_vals: tuple[float, float],
        padding: float = 0.1,
    ) -> None:
        """Initialize categorical scale.

        Args:
            domain: Tuple of category names
            range_vals: Output range [min, max]
            padding: Padding between categories (0.0-1.0)
        """
        if not isinstance(domain, (tuple, list)):
            raise InvalidScaleError("CategoricalScale domain must be a sequence")
        self.categories = tuple(str(c) for c in domain)
        self.padding = max(0.0, min(1.0, padding))
        # Store in parent without validation check
        self.domain = self.categories
        self.range = range_vals

    def map_value(self, value: float | str | datetime) -> float:
        """Map category to pixel value.

        Args:
            value: Category name

        Returns:
            Pixel position
        """
        str_val = str(value)
        try:
            index = self.categories.index(str_val)
        except ValueError:
            raise InvalidScaleError(f"Unknown category: {str_val}")

        range_size = self.range[1] - self.range[0]
        num_categories = len(self.categories)

        if num_categories == 0:
            return (self.range[0] + self.range[1]) / 2.0

        usable_range = range_size * (1 - self.padding)
        band_width = usable_range / num_categories
        padding_total = range_size * self.padding
        start = self.range[0] + padding_total / 2

        return start + (index + 0.5) * band_width

    def invert(self, pixel_value: float) -> str:
        """Invert pixel value to category.

        Args:
            pixel_value: Output value in range

        Returns:
            Corresponding category
        """
        range_size = self.range[1] - self.range[0]
        num_categories = len(self.categories)

        if num_categories == 0:
            raise InvalidScaleError("No categories defined")

        usable_range = range_size * (1 - self.padding)
        band_width = usable_range / num_categories
        padding_total = range_size * self.padding
        start = self.range[0] + padding_total / 2

        normalized_pos = (pixel_value - start) / band_width - 0.5
        index = max(0, min(num_categories - 1, int(normalized_pos)))

        return self.categories[index]

    def generate_ticks(self, count: int = 10) -> list[Tick]:
        """Generate category ticks.

        Args:
            count: Ignored for categorical scale

        Returns:
            List of Tick objects
        """
        ticks = []
        for i, category in enumerate(self.categories):
            position = (i + 0.5) / max(1, len(self.categories))
            ticks.append(Tick(category, category, position))

        return ticks


class TimeScale(BaseScale):
    """Time scale for datetime values with automatic interval selection."""

    def __init__(
        self,
        domain: tuple[datetime, datetime],
        range_vals: tuple[float, float],
    ) -> None:
        """Initialize time scale.

        Args:
            domain: Time range [start, end]
            range_vals: Output range [min, max]

        Raises:
            InvalidScaleError: If domain is invalid
        """
        if not isinstance(domain[0], datetime) or not isinstance(domain[1], datetime):
            raise InvalidScaleError("TimeScale domain must contain datetime objects")
        if domain[0] >= domain[1]:
            raise InvalidScaleError("TimeScale domain must have start < end")
        super().__init__(domain, range_vals)

    def map_value(self, value: float | str | datetime) -> float:
        """Map datetime to pixel value.

        Args:
            value: Datetime value

        Returns:
            Pixel position
        """
        if not isinstance(value, datetime):
            raise InvalidScaleError(f"TimeScale requires datetime, got {type(value)}")

        d_min, d_max = self.domain
        total_seconds = (d_max - d_min).total_seconds()

        if total_seconds == 0:
            return (self.range[0] + self.range[1]) / 2.0

        elapsed_seconds = (value - d_min).total_seconds()
        normalized = elapsed_seconds / total_seconds
        r_min, r_max = self.range

        return r_min + normalized * (r_max - r_min)

    def invert(self, pixel_value: float) -> datetime:
        """Invert pixel value to datetime.

        Args:
            pixel_value: Output value in range

        Returns:
            Corresponding datetime
        """
        r_min, r_max = self.range
        if r_min == r_max:
            d_min, d_max = self.domain
            return d_min + (d_max - d_min) / 2

        normalized = (pixel_value - r_min) / (r_max - r_min)
        d_min, d_max = self.domain
        delta = d_max - d_min

        return d_min + timedelta(seconds=delta.total_seconds() * normalized)

    def generate_ticks(self, count: int = 10) -> list[Tick]:
        """Generate time ticks with appropriate intervals.

        Args:
            count: Approximate number of ticks

        Returns:
            List of Tick objects
        """
        d_min, d_max = self.domain
        total_seconds = (d_max - d_min).total_seconds()

        intervals = [
            (1, "%H:%M:%S"),
            (60, "%H:%M"),
            (3600, "%H:00"),
            (86400, "%m-%d"),
            (604800, "%Y-%m-%d"),
            (2592000, "%B"),
            (31536000, "%Y"),
        ]

        target_interval = total_seconds / max(1, count - 1)
        selected_interval, fmt = intervals[0]

        for interval, format_str in intervals:
            if interval >= target_interval:
                selected_interval, fmt = interval, format_str
                break

        ticks = []
        current = d_min
        tick_delta = timedelta(seconds=selected_interval)

        while current <= d_max:
            label = current.strftime(fmt)
            position = self.map_value(current)
            r_min, r_max = self.range
            if r_max > r_min:
                position = (position - r_min) / (r_max - r_min)
            ticks.append(Tick(current, label, position))
            current += tick_delta

        return ticks


class PowerScale(BaseScale):
    """Power scale (exponential) for data with power relationship."""

    def __init__(
        self,
        domain: tuple[float, float],
        range_vals: tuple[float, float],
        exponent: float = 2.0,
    ) -> None:
        """Initialize power scale.

        Args:
            domain: Input domain [min, max]
            range_vals: Output range [min, max]
            exponent: Power exponent (e.g., 0.5 for sqrt, 2 for square)

        Raises:
            InvalidScaleError: If exponent is invalid
        """
        if exponent == 0:
            raise InvalidScaleError("Exponent cannot be zero")
        super().__init__(domain, range_vals)
        self.exponent = exponent

    def map_value(self, value: float | str | datetime) -> float:
        """Map value using power transformation.

        Args:
            value: Input value

        Returns:
            Mapped value in range
        """
        if not isinstance(value, (int, float)):
            raise InvalidScaleError(f"PowerScale expects numeric value, got {type(value)}")

        d_min, d_max = self.domain

        if d_min >= 0 and d_max >= 0:
            if d_min == d_max:
                return (self.range[0] + self.range[1]) / 2.0

            p_min = d_min**self.exponent
            p_max = d_max**self.exponent
            p_val = value**self.exponent

            normalized = (p_val - p_min) / (p_max - p_min) if p_max > p_min else 0.5
        else:
            linear = LinearScale(self.domain, self.range)
            return linear.map_value(value)

        r_min, r_max = self.range
        return r_min + normalized * (r_max - r_min)

    def invert(self, pixel_value: float) -> float:
        """Invert pixel value to data value.

        Args:
            pixel_value: Output value in range

        Returns:
            Corresponding input value
        """
        r_min, r_max = self.range
        if r_min == r_max:
            return (self.domain[0] + self.domain[1]) / 2.0

        normalized = (pixel_value - r_min) / (r_max - r_min)
        d_min, d_max = self.domain

        if d_min >= 0 and d_max >= 0:
            p_min = d_min**self.exponent
            p_max = d_max**self.exponent
            p_val = p_min + normalized * (p_max - p_min)
            return p_val ** (1.0 / self.exponent)
        else:
            linear = LinearScale(self.domain, self.range)
            return linear.invert(pixel_value)

    def generate_ticks(self, count: int = 10) -> list[Tick]:
        """Generate power scale ticks.

        Args:
            count: Approximate number of ticks

        Returns:
            List of Tick objects
        """
        d_min, d_max = self.domain

        if d_min >= 0 and d_max >= 0:
            p_min = d_min**self.exponent
            p_max = d_max**self.exponent
            linear = LinearScale((p_min, p_max), self.range)
            p_ticks = linear.generate_ticks(count)

            ticks = []
            for p_tick in p_ticks:
                data_val = p_tick.value ** (1.0 / self.exponent)
                ticks.append(Tick(data_val, f"{data_val:.2g}", p_tick.position))
            return ticks
        else:
            linear = LinearScale(self.domain, self.range)
            return linear.generate_ticks(count)


class QuantizeScale(BaseScale):
    """Quantize scale for discretizing continuous data into bins."""

    def __init__(
        self,
        domain: tuple[float, float],
        range_vals: tuple[float, float],
        thresholds: list[float] | None = None,
    ) -> None:
        """Initialize quantize scale.

        Args:
            domain: Input domain [min, max]
            range_vals: Output range [min, max]
            thresholds: Bin boundaries (optional)
        """
        super().__init__(domain, range_vals)
        self.thresholds = sorted(thresholds) if thresholds else []

    def map_value(self, value: float | str | datetime) -> float:
        """Map value to nearest quantized value.

        Args:
            value: Input value

        Returns:
            Quantized value
        """
        if not isinstance(value, (int, float)):
            raise InvalidScaleError(f"QuantizeScale expects numeric value, got {type(value)}")

        index = 0
        for threshold in self.thresholds:
            if value >= threshold:
                index += 1

        num_bins = len(self.thresholds) + 1
        r_min, r_max = self.range
        return r_min + (index / num_bins) * (r_max - r_min)

    def invert(self, pixel_value: float) -> float:
        """Invert pixel value to quantized bucket index.

        Args:
            pixel_value: Output value in range

        Returns:
            Bucket index
        """
        r_min, r_max = self.range
        normalized = (pixel_value - r_min) / (r_max - r_min) if r_max > r_min else 0.5
        num_bins = len(self.thresholds) + 1

        return int(normalized * num_bins)

    def generate_ticks(self, count: int = 10) -> list[Tick]:
        """Generate quantize scale ticks.

        Args:
            count: Approximate number of ticks

        Returns:
            List of Tick objects
        """
        d_min, d_max = self.domain
        linear = LinearScale((d_min, d_max), self.range)

        return linear.generate_ticks(count)
