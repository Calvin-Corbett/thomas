"""Line chart implementation with interpolation and area rendering."""

import math

from thomas.marketplace.visualization._exceptions import InvalidDataError
from thomas.marketplace.visualization._types import (
    DataPoint,
    Figure,
    Fill,
    Series,
)
from thomas.marketplace.visualization.scales import BaseScale


class LineChart:
    """Line chart renderer with various interpolation modes."""

    def __init__(self, figure: Figure) -> None:
        """Initialize line chart.

        Args:
            figure: Figure containing series data
        """
        self.figure = figure
        self.interpolation = "linear"
        self.area_fill: Fill | None = None

    def set_interpolation(self, mode: str) -> None:
        """Set line interpolation method.

        Args:
            mode: Interpolation mode (linear, step, monotone)

        Raises:
            InvalidDataError: If mode is invalid
        """
        valid_modes = {"linear", "step", "monotone"}
        if mode not in valid_modes:
            raise InvalidDataError(f"Invalid interpolation mode: {mode}. Must be one of {valid_modes}")
        self.interpolation = mode

    def set_area_fill(self, fill: Fill | None) -> None:
        """Set area fill for chart.

        Args:
            fill: Fill configuration or None for no fill
        """
        self.area_fill = fill

    def generate_path_data(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> str:
        """Generate SVG path data for line series.

        Args:
            series: Data series to render
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height for y-coordinate flip

        Returns:
            SVG path data string
        """
        if not series.points:
            return ""

        points = self._filter_valid_points(series.points)
        if len(points) < 2:
            return ""

        path_data = []
        interpolated_points = self._interpolate_points(points, x_scale, y_scale, height)

        for i, (x, y) in enumerate(interpolated_points):
            if i == 0:
                path_data.append(f"M {x:.2f} {y:.2f}")
            else:
                path_data.append(f"L {x:.2f} {y:.2f}")

        return " ".join(path_data)

    def generate_area_path_data(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        width: float,
        height: float,
        baseline: float,
    ) -> str:
        """Generate SVG path data for filled area.

        Args:
            series: Data series to render
            x_scale: X-axis scale
            y_scale: Y-axis scale
            width: Chart width
            height: Chart height
            baseline: Y value for baseline

        Returns:
            SVG path data string
        """
        if not series.points:
            return ""

        points = self._filter_valid_points(series.points)
        if len(points) < 2:
            return ""

        path_data = []
        interpolated_points = self._interpolate_points(points, x_scale, y_scale, height)

        baseline_pixel = y_scale.map_value(baseline)
        baseline_y = height - baseline_pixel

        for i, (x, y) in enumerate(interpolated_points):
            if i == 0:
                path_data.append(f"M {x:.2f} {y:.2f}")
            else:
                path_data.append(f"L {x:.2f} {y:.2f}")

        path_data.append(f"L {interpolated_points[-1][0]:.2f} {baseline_y:.2f}")

        for x, _ in reversed(interpolated_points):
            path_data.append(f"L {x:.2f} {baseline_y:.2f}")

        path_data.append("Z")

        return " ".join(path_data)

    def generate_confidence_band(
        self,
        series: Series,
        upper_series: Series,
        lower_series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> str:
        """Generate SVG path for confidence band.

        Args:
            series: Main data series
            upper_series: Upper bound series
            lower_series: Lower bound series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            SVG path data string
        """
        main_points = self._filter_valid_points(series.points)
        upper_points = self._filter_valid_points(upper_series.points)
        lower_points = self._filter_valid_points(lower_series.points)

        if not main_points or len(main_points) < 2:
            return ""

        path_data = []
        upper_interpolated = self._interpolate_points(upper_points, x_scale, y_scale, height)
        lower_interpolated = self._interpolate_points(lower_points, x_scale, y_scale, height)

        for i, (x, y) in enumerate(upper_interpolated):
            if i == 0:
                path_data.append(f"M {x:.2f} {y:.2f}")
            else:
                path_data.append(f"L {x:.2f} {y:.2f}")

        for x, y in reversed(lower_interpolated):
            path_data.append(f"L {x:.2f} {y:.2f}")

        path_data.append("Z")

        return " ".join(path_data)

    def _interpolate_points(
        self,
        points: list[tuple[float, float]],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[tuple[float, float]]:
        """Interpolate points using selected method.

        Args:
            points: List of (x, y) data points
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            List of interpolated pixel coordinates
        """
        if self.interpolation == "linear":
            return self._linear_interpolation(points, x_scale, y_scale, height)
        elif self.interpolation == "step":
            return self._step_interpolation(points, x_scale, y_scale, height)
        elif self.interpolation == "monotone":
            return self._monotone_cubic_interpolation(points, x_scale, y_scale, height)
        else:
            return self._linear_interpolation(points, x_scale, y_scale, height)

    def _linear_interpolation(
        self,
        points: list[tuple[float, float]],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[tuple[float, float]]:
        """Linear interpolation between points.

        Args:
            points: Data points
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            Pixel coordinates
        """
        pixel_points = []
        for x, y in points:
            px = x_scale.map_value(x)
            py = height - y_scale.map_value(y)
            pixel_points.append((px, py))
        return pixel_points

    def _step_interpolation(
        self,
        points: list[tuple[float, float]],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[tuple[float, float]]:
        """Step interpolation (stairs pattern).

        Args:
            points: Data points
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            Pixel coordinates
        """
        pixel_points = []
        for i, (x, y) in enumerate(points):
            px = x_scale.map_value(x)
            py = height - y_scale.map_value(y)

            if i > 0:
                prev_px, prev_py = pixel_points[-1]
                pixel_points.append((px, prev_py))

            pixel_points.append((px, py))

        return pixel_points

    def _monotone_cubic_interpolation(
        self,
        points: list[tuple[float, float]],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[tuple[float, float]]:
        """Monotone cubic spline interpolation for smooth curves.

        Args:
            points: Data points
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            Pixel coordinates with interpolated points
        """
        if len(points) < 2:
            return []

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        n = len(xs)
        ms = [0.0] * n

        for i in range(n):
            if i == 0:
                ms[i] = (ys[1] - ys[0]) / (xs[1] - xs[0]) if xs[1] != xs[0] else 0.0
            elif i == n - 1:
                ms[i] = (ys[n - 1] - ys[n - 2]) / (xs[n - 1] - xs[n - 2]) if xs[n - 1] != xs[n - 2] else 0.0
            else:
                dx_left = xs[i] - xs[i - 1]
                dx_right = xs[i + 1] - xs[i]
                dy_left = ys[i] - ys[i - 1]
                dy_right = ys[i + 1] - ys[i]

                if dx_left == 0 or dx_right == 0:
                    ms[i] = 0.0
                else:
                    m_left = dy_left / dx_left
                    m_right = dy_right / dx_right

                    if m_left * m_right <= 0:
                        ms[i] = 0.0
                    else:
                        ms[i] = 2.0 / (1.0 / m_left + 1.0 / m_right)

        pixel_points = []
        samples_per_segment = 20

        for i in range(n - 1):
            x0, y0 = xs[i], ys[i]
            x1, y1 = xs[i + 1], ys[i + 1]
            m0, m1 = ms[i], ms[i + 1]

            dx = x1 - x0
            if dx == 0:
                continue

            for t in [j / samples_per_segment for j in range(samples_per_segment + 1)]:
                t2 = t * t
                t3 = t2 * t

                h00 = 2 * t3 - 3 * t2 + 1
                h10 = t3 - 2 * t2 + t
                h01 = -2 * t3 + 3 * t2
                h11 = t3 - t2

                x = h00 * x0 + h10 * dx * m0 + h01 * x1 + h11 * dx * m1
                y = h00 * y0 + h10 * dx * m0 + h01 * y1 + h11 * dx * m1

                px = x_scale.map_value(x)
                py = height - y_scale.map_value(y)
                pixel_points.append((px, py))

        return pixel_points

    def _filter_valid_points(self, points: list[DataPoint]) -> list[tuple[float, float]]:
        """Filter out points with invalid values.

        Args:
            points: Data points

        Returns:
            List of valid (x, y) tuples
        """
        valid_points = []
        for point in points:
            try:
                if isinstance(point.x, (int, float)) and isinstance(point.y, (int, float)):
                    if math.isfinite(point.x) and math.isfinite(point.y):
                        valid_points.append((point.x, point.y))
            except (TypeError, ValueError):
                continue

        return valid_points

    def generate_reference_line(
        self,
        value: float,
        axis: str,
        x_scale: BaseScale,
        y_scale: BaseScale,
        width: float,
        height: float,
    ) -> tuple[str, str]:
        """Generate reference line path data.

        Args:
            value: Reference value
            axis: Axis for reference (x or y)
            x_scale: X-axis scale
            y_scale: Y-axis scale
            width: Chart width
            height: Chart height

        Returns:
            Tuple of (path_data, stroke_style)
        """
        if axis == "y":
            pixel_y = height - y_scale.map_value(value)
            path_data = f"M 0 {pixel_y:.2f} L {width:.2f} {pixel_y:.2f}"
        else:
            pixel_x = x_scale.map_value(value)
            path_data = f"M {pixel_x:.2f} 0 L {pixel_x:.2f} {height:.2f}"

        stroke = "stroke: #999; stroke-width: 1; stroke-dasharray: 5,5;"
        return (path_data, stroke)

    def generate_trend_line(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> str:
        """Generate linear regression trend line.

        Args:
            series: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            SVG path data for trend line
        """
        points = self._filter_valid_points(series.points)
        if len(points) < 2:
            return ""

        n = len(points)
        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        sum_xx = sum(p[0] ** 2 for p in points)
        sum_xy = sum(p[0] * p[1] for p in points)

        denominator = n * sum_xx - sum_x**2
        if denominator == 0:
            return ""

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        x_min = min(p[0] for p in points)
        x_max = max(p[0] for p in points)

        y_start = slope * x_min + intercept
        y_end = slope * x_max + intercept

        px_start = x_scale.map_value(x_min)
        py_start = height - y_scale.map_value(y_start)
        px_end = x_scale.map_value(x_max)
        py_end = height - y_scale.map_value(y_end)

        return f"M {px_start:.2f} {py_start:.2f} L {px_end:.2f} {py_end:.2f}"
