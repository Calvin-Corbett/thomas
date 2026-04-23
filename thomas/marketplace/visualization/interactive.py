"""Interactive features for charts including tooltips, zoom, and linked charts."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from thomas.marketplace.visualization._exceptions import InteractionError
from thomas.marketplace.visualization._types import DataPoint, Figure, Series
from thomas.marketplace.visualization.scales import BaseScale


@dataclass
class EventData:
    """Data passed to event handlers."""

    event_type: str
    x: float
    y: float
    data_point: DataPoint | None = None
    series: Series | None = None
    metadata: dict[str, Any] = None


class InteractiveChart:
    """Interactive chart features manager."""

    def __init__(self, figure: Figure) -> None:
        """Initialize interactive features.

        Args:
            figure: Figure to make interactive
        """
        self.figure = figure
        self.event_handlers: dict[str, list[Callable]] = {
            "click": [],
            "hover": [],
            "brush": [],
            "zoom": [],
            "pan": [],
        }
        self.zoom_level = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.selection: tuple[float, float, float, float] | None = None

    def register_event(self, event_type: str, handler: Callable[[EventData], None]) -> None:
        """Register event handler.

        Args:
            event_type: Type of event (click, hover, brush, zoom, pan)
            handler: Callback function

        Raises:
            InteractionError: If event type is invalid
        """
        if event_type not in self.event_handlers:
            raise InteractionError(f"Unknown event type: {event_type}")

        self.event_handlers[event_type].append(handler)

    def generate_tooltip(
        self,
        point: DataPoint,
        series: Series,
        x: float,
        y: float,
        width: int = 200,
        height: int = 100,
    ) -> str:
        """Generate tooltip HTML content.

        Args:
            point: Data point being hovered
            series: Series containing point
            x: Tooltip X position
            y: Tooltip Y position
            width: Tooltip width
            height: Tooltip height

        Returns:
            HTML content for tooltip
        """
        html = f'<div style="background: white; border: 1px solid #ccc; padding: 8px; width: {width}px;">\n'
        html += f"  <strong>{series.name}</strong><br/>\n"

        if point.label:
            html += f"  {point.label}<br/>\n"

        if isinstance(point.x, (int, float)):
            html += f"  X: {point.x:.2f}<br/>\n"
        else:
            html += f"  X: {point.x}<br/>\n"

        html += f"  Y: {point.y:.2f}<br/>\n"

        if point.metadata:
            for key, value in point.metadata.items():
                html += f"  {key}: {value}<br/>\n"

        html += "</div>"

        return html

    def find_nearest_point(
        self,
        pixel_x: float,
        pixel_y: float,
        x_scale: BaseScale,
        y_scale: BaseScale,
        tolerance: float = 10.0,
    ) -> tuple[DataPoint, Series, float] | None:
        """Find nearest data point to cursor.

        Args:
            pixel_x: Pixel X coordinate
            pixel_y: Pixel Y coordinate
            x_scale: X-axis scale
            y_scale: Y-axis scale
            tolerance: Search tolerance in pixels

        Returns:
            Tuple of (point, series, distance) or None
        """
        nearest = None
        min_distance = tolerance

        for series in self.figure.series_list:
            for point in series.points:
                try:
                    if not isinstance(point.x, (int, float)) or not isinstance(point.y, (int, float)):
                        continue

                    px = x_scale.map_value(point.x)
                    py = y_scale.map_value(point.y)

                    distance = ((px - pixel_x) ** 2 + (py - pixel_y) ** 2) ** 0.5

                    if distance < min_distance:
                        min_distance = distance
                        nearest = (point, series, distance)

                except (TypeError, ValueError):
                    continue

        return nearest

    def apply_zoom(
        self,
        zoom_factor: float,
        center_x: float,
        center_y: float,
    ) -> None:
        """Apply zoom transformation.

        Args:
            zoom_factor: Zoom factor (>1 to zoom in, <1 to zoom out)
            center_x: Zoom center X
            center_y: Zoom center Y
        """
        if zoom_factor <= 0:
            raise InteractionError("Zoom factor must be positive")

        self.zoom_level *= zoom_factor

        self.zoom_level = max(0.1, min(10.0, self.zoom_level))

    def apply_pan(self, dx: float, dy: float) -> None:
        """Apply pan transformation.

        Args:
            dx: X offset
            dy: Y offset
        """
        self.pan_x += dx
        self.pan_y += dy

    def apply_brush_selection(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        x_scale: BaseScale,
        y_scale: BaseScale,
    ) -> list[tuple[DataPoint, Series]]:
        """Apply rectangular brush selection.

        Args:
            x1: Selection start X
            y1: Selection start Y
            x2: Selection end X
            y2: Selection end Y
            x_scale: X-axis scale
            y_scale: Y-axis scale

        Returns:
            List of selected (point, series) tuples
        """
        self.selection = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

        selected = []
        min_x, min_y, max_x, max_y = self.selection

        for series in self.figure.series_list:
            for point in series.points:
                try:
                    if not isinstance(point.x, (int, float)) or not isinstance(point.y, (int, float)):
                        continue

                    px = x_scale.map_value(point.x)
                    py = y_scale.map_value(point.y)

                    if min_x <= px <= max_x and min_y <= py <= max_y:
                        selected.append((point, series))

                except (TypeError, ValueError):
                    continue

        return selected

    def get_crosshair_coordinates(
        self,
        pixel_x: float,
        pixel_y: float,
        x_scale: BaseScale,
        y_scale: BaseScale,
        width: float,
        height: float,
    ) -> tuple[float, float]:
        """Get data coordinates for crosshair.

        Args:
            pixel_x: Pixel X position
            pixel_y: Pixel Y position
            x_scale: X-axis scale
            y_scale: Y-axis scale
            width: Chart width
            height: Chart height

        Returns:
            Tuple of (data_x, data_y)
        """
        try:
            data_x = x_scale.invert(pixel_x)
            data_y = y_scale.invert(height - pixel_y)
            return (data_x, data_y)
        except Exception:
            return (0.0, 0.0)

    def generate_crosshair_paths(
        self,
        pixel_x: float,
        pixel_y: float,
        width: float,
        height: float,
    ) -> tuple[str, str]:
        """Generate SVG paths for crosshair.

        Args:
            pixel_x: Cursor X position
            pixel_y: Cursor Y position
            width: Chart width
            height: Chart height

        Returns:
            Tuple of (vertical_path, horizontal_path)
        """
        vertical = f"M {pixel_x:.2f} 0 L {pixel_x:.2f} {height:.2f}"
        horizontal = f"M 0 {pixel_y:.2f} L {width:.2f} {pixel_y:.2f}"

        return (vertical, horizontal)

    def generate_selection_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> tuple[float, float, float, float]:
        """Generate rectangle for selection display.

        Args:
            x1: Start X
            y1: Start Y
            x2: End X
            y2: End Y

        Returns:
            Tuple of (x, y, width, height)
        """
        x = min(x1, x2)
        y = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)

        return (x, y, width, height)

    def export_to_svg(self, filepath: str) -> None:
        """Export interactive chart to SVG file.

        Args:
            filepath: Output file path

        Raises:
            InteractionError: If export fails
        """
        try:
            from thomas.marketplace.visualization.svg_renderer import SVGRenderer

            renderer = SVGRenderer(self.figure.width, self.figure.height)
            renderer.create_document()

            with open(filepath, "w") as f:
                f.write(renderer.to_svg_string())

        except Exception as e:
            raise InteractionError(f"Export failed: {str(e)}")

    def export_via_canvas(self) -> str:
        """Generate canvas-compatible export description.

        Returns:
            Canvas draw commands as string
        """
        commands = []
        commands.append(f"canvas.width = {self.figure.width}")
        commands.append(f"canvas.height = {self.figure.height}")
        commands.append("ctx.fillStyle = 'white'")
        commands.append(f"ctx.fillRect(0, 0, {self.figure.width}, {self.figure.height})")

        return "\n".join(commands)

    def create_linked_selection(
        self,
        selected_indices: list[int],
    ) -> dict[str, Any]:
        """Create linked selection across multiple charts.

        Args:
            selected_indices: Indices of selected points

        Returns:
            Selection descriptor for linking
        """
        return {
            "type": "linked_selection",
            "indices": selected_indices,
            "timestamp": None,
            "metadata": {},
        }

    def apply_linked_selection(self, selection: dict[str, Any]) -> None:
        """Apply linked selection from another chart.

        Args:
            selection: Selection descriptor from linked chart
        """
        if selection.get("type") != "linked_selection":
            raise InteractionError("Invalid selection format")

        indices = selection.get("indices", [])

        for series_idx, series in enumerate(self.figure.series_list):
            for point_idx, point in enumerate(series.points):
                global_idx = series_idx * len(series.points) + point_idx
                point.metadata["selected"] = global_idx in indices

    def generate_export_options_menu(self) -> dict[str, Callable[[], str]]:
        """Generate export options menu.

        Returns:
            Dictionary of export options and their functions
        """
        return {
            "SVG": self._export_svg_string,
            "Canvas": self.export_via_canvas,
            "HTML": self._export_html_string,
        }

    def _export_svg_string(self) -> str:
        """Export as SVG string.

        Returns:
            SVG content
        """
        from thomas.marketplace.visualization.svg_renderer import SVGRenderer

        renderer = SVGRenderer(self.figure.width, self.figure.height)
        renderer.create_document()

        return renderer.to_svg_string()

    def _export_html_string(self) -> str:
        """Export as HTML document.

        Returns:
            HTML content
        """
        svg_content = self._export_svg_string()

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Chart</title>
</head>
<body>
    {svg_content}
</body>
</html>"""

        return html

    def create_dashboard_layout(
        self,
        charts: list[tuple[str, Figure]],
        columns: int = 2,
    ) -> dict[str, Any]:
        """Create multi-chart dashboard layout.

        Args:
            charts: List of (name, figure) tuples
            columns: Number of columns in grid

        Returns:
            Dashboard layout descriptor
        """
        rows = (len(charts) + columns - 1) // columns

        layout = {
            "type": "grid",
            "columns": columns,
            "rows": rows,
            "charts": [],
        }

        for idx, (name, figure) in enumerate(charts):
            row = idx // columns
            col = idx % columns

            layout["charts"].append(
                {
                    "name": name,
                    "row": row,
                    "col": col,
                    "width": figure.width,
                    "height": figure.height,
                }
            )

        return layout
