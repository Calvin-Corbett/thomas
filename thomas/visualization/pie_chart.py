"""Pie chart and hierarchical chart implementations."""

import math
from dataclasses import dataclass

from thomas.visualization._exceptions import InvalidDataError
from thomas.visualization._types import Color, Series


@dataclass
class PieSlice:
    """Pie chart slice geometry."""

    start_angle: float
    end_angle: float
    inner_radius: float
    outer_radius: float
    color: Color
    label: str
    value: float
    center_x: float
    center_y: float


class PieChart:
    """Pie and donut chart renderer."""

    def __init__(self) -> None:
        """Initialize pie chart."""
        self.inner_radius = 0.0
        self.start_angle = -math.pi / 2
        self.label_distance = 1.3

    def set_donut_radius(self, inner_radius: float) -> None:
        """Set inner radius for donut chart.

        Args:
            inner_radius: Inner radius as fraction of outer radius (0.0-1.0)

        Raises:
            InvalidDataError: If radius is invalid
        """
        if not 0.0 <= inner_radius < 1.0:
            raise InvalidDataError(f"Inner radius must be 0.0-1.0, got {inner_radius}")
        self.inner_radius = inner_radius

    def set_start_angle(self, angle: float) -> None:
        """Set starting angle in radians.

        Args:
            angle: Start angle (0 = right, pi/2 = bottom, pi = left, -pi/2 = top)
        """
        self.start_angle = angle

    def set_label_distance(self, distance: float) -> None:
        """Set label distance from center.

        Args:
            distance: Distance as fraction of outer radius (>1.0)
        """
        self.label_distance = max(1.0, distance)

    def generate_slices(
        self,
        series: Series,
        center_x: float,
        center_y: float,
        radius: float,
    ) -> list[PieSlice]:
        """Generate pie slices from series.

        Args:
            series: Data series with one point per slice
            center_x: Center X coordinate
            center_y: Center Y coordinate
            radius: Outer radius

        Returns:
            List of PieSlice objects
        """
        valid_points = [p for p in series.points if isinstance(p.y, (int, float)) and p.y > 0]

        if not valid_points:
            return []

        total = sum(p.y for p in valid_points)
        if total <= 0:
            return []

        slices = []
        current_angle = self.start_angle

        for point in valid_points:
            value = point.y
            fraction = value / total
            slice_angle = fraction * 2 * math.pi

            end_angle = current_angle + slice_angle

            slice_obj = PieSlice(
                start_angle=current_angle,
                end_angle=end_angle,
                inner_radius=self.inner_radius * radius,
                outer_radius=radius,
                color=point.color or series.color,
                label=point.label or str(value),
                value=value,
                center_x=center_x,
                center_y=center_y,
            )
            slices.append(slice_obj)

            current_angle = end_angle

        return slices

    def generate_slice_path(self, slice_obj: PieSlice) -> str:
        """Generate SVG path for pie slice.

        Args:
            slice_obj: Slice to render

        Returns:
            SVG path data string
        """
        x = slice_obj.center_x
        y = slice_obj.center_y
        r_outer = slice_obj.outer_radius
        r_inner = slice_obj.inner_radius
        start = slice_obj.start_angle
        end = slice_obj.end_angle

        x1_outer = x + r_outer * math.cos(start)
        y1_outer = y + r_outer * math.sin(start)
        x2_outer = x + r_outer * math.cos(end)
        y2_outer = y + r_outer * math.sin(end)

        large_arc = 1 if (end - start) > math.pi else 0

        path_data = f"M {x1_outer:.2f} {y1_outer:.2f}"
        path_data += f" A {r_outer:.2f} {r_outer:.2f} 0 {large_arc} 1 {x2_outer:.2f} {y2_outer:.2f}"

        if r_inner > 0:
            x2_inner = x + r_inner * math.cos(end)
            y2_inner = y + r_inner * math.sin(end)
            x1_inner = x + r_inner * math.cos(start)
            y1_inner = y + r_inner * math.sin(start)

            path_data += f" L {x2_inner:.2f} {y2_inner:.2f}"
            path_data += f" A {r_inner:.2f} {r_inner:.2f} 0 {large_arc} 0 {x1_inner:.2f} {y1_inner:.2f}"
        else:
            path_data += f" L {x:.2f} {y:.2f}"

        path_data += " Z"

        return path_data

    def generate_slice_labels(self, slices: list[PieSlice]) -> list[tuple[float, float, str, float]]:
        """Generate label positions for slices.

        Args:
            slices: Pie slices

        Returns:
            List of (x, y, label, angle) tuples
        """
        labels = []

        for slice_obj in slices:
            mid_angle = (slice_obj.start_angle + slice_obj.end_angle) / 2

            label_radius = slice_obj.outer_radius * self.label_distance
            label_x = slice_obj.center_x + label_radius * math.cos(mid_angle)
            label_y = slice_obj.center_y + label_radius * math.sin(mid_angle)

            percentage = (slice_obj.value / sum(s.value for s in slices)) * 100
            label_text = f"{percentage:.1f}%"

            labels.append((label_x, label_y, label_text, math.degrees(mid_angle)))

        return labels

    def generate_exploded_slices(
        self,
        slices: list[PieSlice],
        explode_indices: list[int],
        offset_distance: float = 20.0,
    ) -> list[PieSlice]:
        """Offset specified slices outward (explode effect).

        Args:
            slices: Original slices
            explode_indices: Indices of slices to explode
            offset_distance: Distance to offset in pixels

        Returns:
            Modified slices with offset centers
        """
        exploded = []

        for idx, slice_obj in enumerate(slices):
            if idx in explode_indices:
                mid_angle = (slice_obj.start_angle + slice_obj.end_angle) / 2
                offset_x = offset_distance * math.cos(mid_angle)
                offset_y = offset_distance * math.sin(mid_angle)

                new_slice = PieSlice(
                    start_angle=slice_obj.start_angle,
                    end_angle=slice_obj.end_angle,
                    inner_radius=slice_obj.inner_radius,
                    outer_radius=slice_obj.outer_radius,
                    color=slice_obj.color,
                    label=slice_obj.label,
                    value=slice_obj.value,
                    center_x=slice_obj.center_x + offset_x,
                    center_y=slice_obj.center_y + offset_y,
                )
                exploded.append(new_slice)
            else:
                exploded.append(slice_obj)

        return exploded


class SunburstChart:
    """Sunburst (hierarchical pie) chart renderer."""

    def __init__(self) -> None:
        """Initialize sunburst chart."""
        self.start_angle = -math.pi / 2

    def generate_rings(
        self,
        hierarchy: list[tuple[str, float, int]],
        center_x: float,
        center_y: float,
        max_radius: float,
    ) -> list[tuple[str, float, float, float, float, Color]]:
        """Generate sunburst rings from hierarchical data.

        Args:
            hierarchy: List of (label, value, level) tuples
            center_x: Center X coordinate
            center_y: Center Y coordinate
            max_radius: Maximum radius

        Returns:
            List of ring paths
        """
        rings = []
        colors = self._generate_color_palette(len(hierarchy))

        total = sum(v for _, v, _ in hierarchy if _ == 0)
        if total <= 0:
            return rings

        ring_width = max_radius / 3

        for idx, (label, value, level) in enumerate(hierarchy):
            fraction = value / total
            angle = fraction * 2 * math.pi

            inner_r = level * ring_width
            outer_r = (level + 1) * ring_width

            rings.append((label, inner_r, outer_r, angle, value, colors[idx % len(colors)]))

        return rings


class TreemapChart:
    """Treemap chart renderer using squarified algorithm."""

    def __init__(self) -> None:
        """Initialize treemap chart."""
        pass

    def generate_rects(
        self,
        series: Series,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> list[tuple[float, float, float, float, Color, str]]:
        """Generate treemap rectangles using squarified algorithm.

        Args:
            series: Data series with sizes
            x: X position
            y: Y position
            width: Available width
            height: Available height

        Returns:
            List of (x, y, width, height, color, label) tuples
        """
        valid_points = [p for p in series.points if isinstance(p.y, (int, float)) and p.y > 0]

        if not valid_points:
            return []

        total = sum(p.y for p in valid_points)
        if total <= 0:
            return []

        normalized = [(p.y / total, p.label or str(p.y), p.color or series.color) for p in valid_points]
        rects = self._squarify(normalized, x, y, width, height)

        return rects

    def _squarify(
        self,
        values: list[tuple[float, str, Color]],
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> list[tuple[float, float, float, float, Color, str]]:
        """Squarified treemap algorithm.

        Args:
            values: List of (normalized_value, label, color)
            x: X position
            y: Y position
            width: Available width
            height: Available height

        Returns:
            List of rectangle specs
        """
        rects = []

        if width <= 0 or height <= 0 or not values:
            return rects

        if width >= height:
            row = []
            row_sum = 0.0
            row_idx = 0

            for value, label, color in values:
                row.append((value, label, color))
                row_sum += value

                if row_sum >= 0.3 or row_idx == len(values) - 1:
                    row_height = row_sum * height
                    row_rects = self._layout_row(row, x, y, width, row_height)
                    rects.extend(row_rects)

                    y += row_height
                    height -= row_height
                    row = []
                    row_sum = 0.0

                row_idx += 1
        else:
            col = []
            col_sum = 0.0
            col_idx = 0

            for value, label, color in values:
                col.append((value, label, color))
                col_sum += value

                if col_sum >= 0.3 or col_idx == len(values) - 1:
                    col_width = col_sum * width
                    col_rects = self._layout_column(col, x, y, col_width, height)
                    rects.extend(col_rects)

                    x += col_width
                    width -= col_width
                    col = []
                    col_sum = 0.0

                col_idx += 1

        return rects

    @staticmethod
    def _layout_row(
        values: list[tuple[float, str, Color]],
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> list[tuple[float, float, float, float, Color, str]]:
        """Layout row of rectangles.

        Args:
            values: List of (value, label, color)
            x: X position
            y: Y position
            width: Available width
            height: Row height

        Returns:
            Rectangle specs
        """
        rects = []
        total = sum(v for v, _, _ in values)

        if total > 0:
            for value, label, color in values:
                rect_width = (value / total) * width
                rects.append((x, y, rect_width, height, color, label))
                x += rect_width

        return rects

    @staticmethod
    def _layout_column(
        values: list[tuple[float, str, Color]],
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> list[tuple[float, float, float, float, Color, str]]:
        """Layout column of rectangles.

        Args:
            values: List of (value, label, color)
            x: X position
            y: Y position
            width: Column width
            height: Available height

        Returns:
            Rectangle specs
        """
        rects = []
        total = sum(v for v, _, _ in values)

        if total > 0:
            for value, label, color in values:
                rect_height = (value / total) * height
                rects.append((x, y, width, rect_height, color, label))
                y += rect_height

        return rects
