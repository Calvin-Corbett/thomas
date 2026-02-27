"""Bar chart implementation with grouping, stacking, and variants."""

from dataclasses import dataclass

from thomas.visualization._exceptions import InvalidDataError
from thomas.visualization._types import Color, Series
from thomas.visualization.scales import BaseScale, CategoricalScale


@dataclass
class BarGeometry:
    """Bar rectangle geometry."""

    x: float
    y: float
    width: float
    height: float
    fill: Color
    stroke_width: float = 1.0


class BarChart:
    """Bar chart renderer with grouping and stacking modes."""

    def __init__(self) -> None:
        """Initialize bar chart."""
        self.mode = "vertical"
        self.group_mode = "grouped"
        self.bar_width_ratio = 0.8

    def set_orientation(self, mode: str) -> None:
        """Set bar orientation.

        Args:
            mode: Orientation mode (vertical or horizontal)

        Raises:
            InvalidDataError: If mode is invalid
        """
        if mode not in ("vertical", "horizontal"):
            raise InvalidDataError(f"Invalid orientation: {mode}")
        self.mode = mode

    def set_group_mode(self, mode: str) -> None:
        """Set bar grouping mode.

        Args:
            mode: Grouping mode (grouped, stacked, or stacked_100)

        Raises:
            InvalidDataError: If mode is invalid
        """
        if mode not in ("grouped", "stacked", "stacked_100"):
            raise InvalidDataError(f"Invalid group mode: {mode}")
        self.group_mode = mode

    def set_bar_width_ratio(self, ratio: float) -> None:
        """Set bar width as ratio of available space.

        Args:
            ratio: Width ratio (0.0-1.0)

        Raises:
            InvalidDataError: If ratio is out of range
        """
        if not 0.0 < ratio <= 1.0:
            raise InvalidDataError(f"Bar width ratio must be between 0 and 1, got {ratio}")
        self.bar_width_ratio = ratio

    def generate_bars(
        self,
        series_list: list[Series],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[BarGeometry]:
        """Generate bar geometries for rendering.

        Args:
            series_list: List of data series
            x_scale: X-axis scale (typically categorical)
            y_scale: Y-axis scale (typically linear)
            height: Chart height

        Returns:
            List of bar geometries
        """
        if self.group_mode == "grouped":
            return self._generate_grouped_bars(series_list, x_scale, y_scale, height)
        elif self.group_mode == "stacked":
            return self._generate_stacked_bars(series_list, x_scale, y_scale, height, False)
        elif self.group_mode == "stacked_100":
            return self._generate_stacked_bars(series_list, x_scale, y_scale, height, True)
        else:
            return self._generate_grouped_bars(series_list, x_scale, y_scale, height)

    def _generate_grouped_bars(
        self,
        series_list: list[Series],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[BarGeometry]:
        """Generate side-by-side grouped bars.

        Args:
            series_list: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            Bar geometries
        """
        bars = []
        num_series = len(series_list)

        if num_series == 0:
            return bars

        categories = self._extract_categories(series_list)

        for cat_idx, category in enumerate(categories):
            cat_pixel = x_scale.map_value(category)

            if isinstance(x_scale, CategoricalScale):
                cat_width = (x_scale.range[1] - x_scale.range[0]) / max(1, len(categories))
                cat_width *= 1 - x_scale.padding
            else:
                cat_width = 40.0

            bar_width = cat_width * self.bar_width_ratio / num_series
            start_offset = (cat_width * self.bar_width_ratio - num_series * bar_width) / 2

            for series_idx, series in enumerate(series_list):
                if cat_idx >= len(series.points):
                    continue

                point = series.points[cat_idx]
                bar_x = cat_pixel - cat_width / 2 + start_offset + series_idx * bar_width
                bar_height = y_scale.map_value(point.y)
                bar_y = height - bar_height

                bars.append(
                    BarGeometry(
                        x=bar_x,
                        y=bar_y,
                        width=bar_width,
                        height=bar_height,
                        fill=point.color or series.color,
                    )
                )

        return bars

    def _generate_stacked_bars(
        self,
        series_list: list[Series],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
        normalize: bool = False,
    ) -> list[BarGeometry]:
        """Generate stacked bars.

        Args:
            series_list: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height
            normalize: If True, normalize to 100%

        Returns:
            Bar geometries
        """
        bars = []
        categories = self._extract_categories(series_list)

        for cat_idx, category in enumerate(categories):
            cat_pixel = x_scale.map_value(category)

            if isinstance(x_scale, CategoricalScale):
                cat_width = (x_scale.range[1] - x_scale.range[0]) / max(1, len(categories))
                cat_width *= 1 - x_scale.padding
            else:
                cat_width = 40.0

            bar_width = cat_width * self.bar_width_ratio
            bar_x = cat_pixel - bar_width / 2

            values = []
            colors = []
            for series in series_list:
                if cat_idx < len(series.points):
                    values.append(series.points[cat_idx].y)
                    colors.append(series.points[cat_idx].color or series.color)
                else:
                    values.append(0.0)
                    colors.append(series.color)

            total = sum(values) if not normalize else 1.0
            if total == 0:
                total = 1.0

            if normalize:
                total_value = sum(values)
                values = [v / total_value * 100 if total_value > 0 else 0 for v in values]

            stack_height = 0.0
            for idx, (value, color) in enumerate(zip(values, colors)):
                if normalize and value == 0:
                    continue

                segment_height = y_scale.map_value(value) if not normalize else y_scale.map_value(value)

                bar_y = height - stack_height - segment_height
                bars.append(
                    BarGeometry(
                        x=bar_x,
                        y=bar_y,
                        width=bar_width,
                        height=segment_height,
                        fill=color,
                    )
                )

                stack_height += segment_height

        return bars

    def generate_bar_labels(
        self,
        bars: list[BarGeometry],
        height: float,
    ) -> list[tuple[float, float, str]]:
        """Generate labels for bars.

        Args:
            bars: Bar geometries
            height: Chart height

        Returns:
            List of (x, y, text) label positions
        """
        labels = []
        for bar in bars:
            label_x = bar.x + bar.width / 2
            label_y = bar.y - 5

            if label_y < 10:
                label_y = bar.y + bar.height + 15

            value = int(bar.height) if bar.height == int(bar.height) else f"{bar.height:.1f}"
            labels.append((label_x, label_y, str(value)))

        return labels

    def generate_error_bars(
        self,
        bars: list[BarGeometry],
        errors: list[tuple[float, float]],
        y_scale: BaseScale,
        height: float,
    ) -> list[tuple[float, float, float, float]]:
        """Generate error bar paths.

        Args:
            bars: Bar geometries
            errors: List of (lower_error, upper_error) tuples
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            List of (x1, y1, x2, y2) line coordinates
        """
        error_lines = []

        for bar, (lower, upper) in zip(bars, errors):
            center_x = bar.x + bar.width / 2

            lower_pixel = y_scale.map_value(lower)
            upper_pixel = y_scale.map_value(upper)

            lower_y = height - lower_pixel
            upper_y = height - upper_pixel

            error_lines.append((center_x - 3, lower_y, center_x + 3, lower_y))
            error_lines.append((center_x, lower_y, center_x, upper_y))
            error_lines.append((center_x - 3, upper_y, center_x + 3, upper_y))

        return error_lines

    def generate_waterfall_bars(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[BarGeometry]:
        """Generate waterfall chart bars.

        Args:
            series: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            Bar geometries
        """
        bars = []
        running_total = 0.0
        categories = self._extract_categories([series])

        for idx, point in enumerate(series.points):
            cat_pixel = x_scale.map_value(categories[idx] if idx < len(categories) else idx)

            if isinstance(x_scale, CategoricalScale):
                cat_width = (x_scale.range[1] - x_scale.range[0]) / max(1, len(categories))
                cat_width *= 1 - x_scale.padding
            else:
                cat_width = 40.0

            bar_width = cat_width * self.bar_width_ratio
            bar_x = cat_pixel - bar_width / 2

            bar_value = point.y
            bar_height = y_scale.map_value(abs(bar_value))

            if bar_value >= 0:
                bar_y = height - y_scale.map_value(running_total + bar_value)
                color = Color(100, 200, 100)
                running_total += bar_value
            else:
                bar_y = height - y_scale.map_value(running_total)
                color = Color(200, 100, 100)
                running_total += bar_value

            bars.append(
                BarGeometry(
                    x=bar_x,
                    y=bar_y,
                    width=bar_width,
                    height=bar_height,
                    fill=color,
                )
            )

        return bars

    def generate_histogram_bins(
        self,
        data: list[float],
        num_bins: int,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> tuple[list[BarGeometry], list[float]]:
        """Generate histogram bars from raw data.

        Args:
            data: Raw data values
            num_bins: Number of bins
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            Tuple of (bar geometries, bin edges)
        """
        if not data:
            return ([], [])

        min_val = min(data)
        max_val = max(data)
        bin_width = (max_val - min_val) / num_bins if num_bins > 0 else 1.0

        if bin_width == 0:
            bin_width = 1.0

        bins = [0] * num_bins
        bin_edges = [min_val + i * bin_width for i in range(num_bins + 1)]

        for value in data:
            bin_idx = min(int((value - min_val) / bin_width), num_bins - 1)
            if 0 <= bin_idx < num_bins:
                bins[bin_idx] += 1

        bars = []
        scale_width = x_scale.range[1] - x_scale.range[0]
        bar_width = scale_width / num_bins * 0.9

        for idx, count in enumerate(bins):
            bar_x = x_scale.range[0] + idx * scale_width / num_bins + (scale_width / num_bins - bar_width) / 2
            bar_height = y_scale.map_value(count)
            bar_y = height - bar_height

            bars.append(
                BarGeometry(
                    x=bar_x,
                    y=bar_y,
                    width=bar_width,
                    height=bar_height,
                    fill=Color(70, 130, 180),
                )
            )

        return (bars, bin_edges)

    @staticmethod
    def _extract_categories(series_list: list[Series]) -> list[str]:
        """Extract unique categories from series.

        Args:
            series_list: List of series

        Returns:
            List of unique category names
        """
        categories = []
        seen = set()

        for series in series_list:
            for i, point in enumerate(series.points):
                cat = str(point.label or point.x or str(i))
                if cat not in seen:
                    categories.append(cat)
                    seen.add(cat)

        return categories
