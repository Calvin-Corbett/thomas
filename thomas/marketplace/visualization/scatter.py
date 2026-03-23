"""Scatter plot implementation with bubble charts and density estimation."""

import math

from thomas.marketplace.visualization._exceptions import InvalidDataError
from thomas.marketplace.visualization._types import Color, Series
from thomas.marketplace.visualization.scales import BaseScale


class ScatterPlot:
    """Scatter plot renderer with bubble and density variants."""

    def __init__(self) -> None:
        """Initialize scatter plot."""
        self.jitter_strength = 0.0
        self.alpha_transparency = 1.0

    @staticmethod
    def _is_finite_number(value: object) -> bool:
        """Return True when value is a finite int/float."""
        return isinstance(value, (int, float)) and math.isfinite(float(value))

    def set_jitter(self, strength: float) -> None:
        """Set jitter strength for overlapping points.

        Args:
            strength: Jitter strength (0.0-1.0)

        Raises:
            InvalidDataError: If strength is out of range
        """
        if not 0.0 <= strength <= 1.0:
            raise InvalidDataError(f"Jitter strength must be 0.0-1.0, got {strength}")
        self.jitter_strength = strength

    def set_alpha(self, alpha: float) -> None:
        """Set transparency for all points.

        Args:
            alpha: Transparency (0.0-1.0)

        Raises:
            InvalidDataError: If alpha is out of range
        """
        if not 0.0 <= alpha <= 1.0:
            raise InvalidDataError(f"Alpha must be 0.0-1.0, got {alpha}")
        self.alpha_transparency = alpha

    def generate_points(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> list[tuple[float, float, float, Color]]:
        """Generate scatter points with coordinates and colors.

        Args:
            series: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            List of (x, y, size, color) tuples
        """
        points = []

        for point in series.points:
            try:
                if not self._is_finite_number(point.x) or not self._is_finite_number(point.y):
                    continue

                px = x_scale.map_value(point.x)
                py = height - y_scale.map_value(point.y)

                if self.jitter_strength > 0:
                    px += (self._pseudo_random(point.x, point.y, 0) - 0.5) * self.jitter_strength * 4
                    py += (self._pseudo_random(point.x, point.y, 1) - 0.5) * self.jitter_strength * 4

                size = point.size or 5.0
                color = point.color or series.color

                color = Color(color.r, color.g, color.b, self.alpha_transparency)

                points.append((px, py, size, color))

            except (TypeError, ValueError):
                continue

        return points

    def generate_bubble_points(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        size_scale: BaseScale,
        height: float,
    ) -> list[tuple[float, float, float, Color]]:
        """Generate bubble chart points with size-encoded values.

        Args:
            series: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            size_scale: Scale for point sizes
            height: Chart height

        Returns:
            List of (x, y, size, color) tuples
        """
        points = []
        sizes = [
            p.size if p.size is not None else p.y
            for p in series.points
            if self._is_finite_number(p.y) and (p.size is None or self._is_finite_number(p.size))
        ]

        if not sizes:
            return points

        min_size = min(sizes)
        max_size = max(sizes)
        size_range = max_size - min_size if max_size > min_size else 1.0

        for point in series.points:
            try:
                if not self._is_finite_number(point.x) or not self._is_finite_number(point.y):
                    continue
                if point.size is not None and not self._is_finite_number(point.size):
                    continue

                px = x_scale.map_value(point.x)
                py = height - y_scale.map_value(point.y)

                if point.size is not None:
                    normalized = (point.size - min_size) / size_range
                else:
                    normalized = (point.y - min_size) / size_range

                normalized = max(0.0, min(1.0, normalized))
                size = 5.0 + normalized * 30.0

                color = point.color or series.color
                color = Color(color.r, color.g, color.b, self.alpha_transparency)

                points.append((px, py, size, color))

            except (TypeError, ValueError):
                continue

        return points

    def estimate_density_2d(
        self,
        series: Series,
        grid_size: int = 50,
    ) -> tuple[list[list[float]], tuple[float, float, float, float]]:
        """Estimate 2D density using Gaussian kernel.

        Args:
            series: Data series
            grid_size: Grid resolution for density estimation

        Returns:
            Tuple of (density grid, bounds (min_x, max_x, min_y, max_y))
        """
        valid_points = [
            (p.x, p.y) for p in series.points if self._is_finite_number(p.x) and self._is_finite_number(p.y)
        ]

        if not valid_points:
            return ([], (0, 1, 0, 1))

        xs = [p[0] for p in valid_points]
        ys = [p[1] for p in valid_points]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        pad_x = (max_x - min_x) * 0.1 if max_x > min_x else 1.0
        pad_y = (max_y - min_y) * 0.1 if max_y > min_y else 1.0

        min_x -= pad_x
        max_x += pad_x
        min_y -= pad_y
        max_y += pad_y

        grid = [[0.0] * grid_size for _ in range(grid_size)]
        bandwidth = max((max_x - min_x) / grid_size, (max_y - min_y) / grid_size) * 2

        for i in range(grid_size):
            for j in range(grid_size):
                grid_x = min_x + (i + 0.5) * (max_x - min_x) / grid_size
                grid_y = min_y + (j + 0.5) * (max_y - min_y) / grid_size

                density = 0.0
                for x, y in valid_points:
                    dist_sq = (grid_x - x) ** 2 + (grid_y - y) ** 2
                    kernel_val = math.exp(-dist_sq / (2 * bandwidth**2))
                    density += kernel_val

                grid[i][j] = density / len(valid_points)

        return (grid, (min_x, max_x, min_y, max_y))

    def generate_contour_paths(
        self,
        density_grid: list[list[float]],
        bounds: tuple[float, float, float, float],
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
        num_levels: int = 5,
    ) -> list[str]:
        """Generate contour line paths from density grid.

        Args:
            density_grid: 2D density grid
            bounds: Data bounds (min_x, max_x, min_y, max_y)
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height
            num_levels: Number of contour levels

        Returns:
            List of SVG path strings
        """
        if not density_grid or not density_grid[0]:
            return []

        flat_values = [v for row in density_grid for v in row]
        if not flat_values:
            return []

        max_val = max(flat_values)
        if max_val == 0:
            return []

        paths = []
        min_x, max_x, min_y, max_y = bounds

        for level in range(1, num_levels + 1):
            threshold = (level / num_levels) * max_val
            path_data = self._march_contour(density_grid, bounds, threshold, x_scale, y_scale, height)
            if path_data:
                paths.append(path_data)

        return paths

    def _march_contour(
        self,
        grid: list[list[float]],
        bounds: tuple[float, float, float, float],
        threshold: float,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> str:
        """March contours using simple threshold method.

        Args:
            grid: Density grid
            bounds: Data bounds
            threshold: Contour threshold
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            SVG path string
        """
        path_data = []
        min_x, max_x, min_y, max_y = bounds
        rows = len(grid)
        cols = len(grid[0]) if rows > 0 else 0

        visited = [[False] * cols for _ in range(rows)]

        for i in range(rows):
            for j in range(cols):
                if grid[i][j] >= threshold and not visited[i][j]:
                    contour = self._trace_contour(grid, i, j, threshold, visited)
                    for x, y in contour:
                        px = x_scale.map_value(min_x + (x / cols) * (max_x - min_x))
                        py = height - y_scale.map_value(min_y + (y / rows) * (max_y - min_y))

                        if not path_data:
                            path_data.append(f"M {px:.2f} {py:.2f}")
                        else:
                            path_data.append(f"L {px:.2f} {py:.2f}")

        return " ".join(path_data) if path_data else ""

    def _trace_contour(
        self,
        grid: list[list[float]],
        start_i: int,
        start_j: int,
        threshold: float,
        visited: list[list[bool]],
    ) -> list[tuple[float, float]]:
        """Trace single contour line.

        Args:
            grid: Density grid
            start_i: Starting row
            start_j: Starting column
            threshold: Contour threshold
            visited: Visited tracking grid

        Returns:
            List of (x, y) contour points
        """
        contour = []
        stack = [(start_i, start_j)]
        rows = len(grid)
        cols = len(grid[0]) if rows > 0 else 0

        while stack:
            i, j = stack.pop()
            if i < 0 or i >= rows or j < 0 or j >= cols:
                continue
            if visited[i][j]:
                continue

            if grid[i][j] >= threshold:
                visited[i][j] = True
                contour.append((j, i))

                for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    ni, nj = i + di, j + dj
                    if 0 <= ni < rows and 0 <= nj < cols and not visited[ni][nj]:
                        stack.append((ni, nj))

        return contour

    def generate_hexbin_grid(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
        hexbin_size: float = 20.0,
    ) -> list[tuple[float, float, int, Color]]:
        """Generate hexagonal binning for large datasets.

        Args:
            series: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height
            hexbin_size: Size of hexagons

        Returns:
            List of (x, y, count, color) tuples
        """
        valid_points = [
            (p.x, p.y) for p in series.points if self._is_finite_number(p.x) and self._is_finite_number(p.y)
        ]

        if not valid_points:
            return []

        hex_dict = {}
        for x, y in valid_points:
            px = x_scale.map_value(x)
            py = height - y_scale.map_value(y)

            hex_x = int(px / hexbin_size)
            hex_y = int(py / hexbin_size)

            key = (hex_x, hex_y)
            hex_dict[key] = hex_dict.get(key, 0) + 1

        counts = list(hex_dict.values())
        max_count = max(counts) if counts else 1

        hexbins = []
        for (hex_x, hex_y), count in hex_dict.items():
            cx = hex_x * hexbin_size + hexbin_size / 2
            cy = hex_y * hexbin_size + hexbin_size / 2

            normalized = count / max_count
            intensity = int(255 * normalized)
            color = Color(intensity, 100, 255 - intensity)

            hexbins.append((cx, cy, count, color))

        return hexbins

    def generate_regression_line(
        self,
        series: Series,
        x_scale: BaseScale,
        y_scale: BaseScale,
        height: float,
    ) -> str:
        """Generate linear regression line overlay.

        Args:
            series: Data series
            x_scale: X-axis scale
            y_scale: Y-axis scale
            height: Chart height

        Returns:
            SVG path string
        """
        valid_points = [
            (p.x, p.y) for p in series.points if self._is_finite_number(p.x) and self._is_finite_number(p.y)
        ]

        if len(valid_points) < 2:
            return ""

        n = len(valid_points)
        sum_x = sum(p[0] for p in valid_points)
        sum_y = sum(p[1] for p in valid_points)
        sum_xx = sum(p[0] ** 2 for p in valid_points)
        sum_xy = sum(p[0] * p[1] for p in valid_points)

        denominator = n * sum_xx - sum_x**2
        if denominator == 0:
            return ""

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        x_min = min(p[0] for p in valid_points)
        x_max = max(p[0] for p in valid_points)

        y_start = slope * x_min + intercept
        y_end = slope * x_max + intercept

        px_start = x_scale.map_value(x_min)
        py_start = height - y_scale.map_value(y_start)
        px_end = x_scale.map_value(x_max)
        py_end = height - y_scale.map_value(y_end)

        return f"M {px_start:.2f} {py_start:.2f} L {px_end:.2f} {py_end:.2f}"

    @staticmethod
    def _pseudo_random(x: float, y: float, seed: int) -> float:
        """Generate pseudo-random number from coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            seed: Random seed

        Returns:
            Pseudo-random value (0.0-1.0)
        """
        val = math.sin((x + y * 73.0) * 12.9898 + seed * 78.233) * 43758.5453
        return val - int(val)
