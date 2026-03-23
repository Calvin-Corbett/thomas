"""Core type definitions for the visualization library."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ChartType(Enum):
    """Enumeration of supported chart types."""

    LINE = "line"
    AREA = "area"
    STACKED_AREA = "stacked_area"
    BAR = "bar"
    HORIZONTAL_BAR = "horizontal_bar"
    GROUPED_BAR = "grouped_bar"
    STACKED_BAR = "stacked_bar"
    SCATTER = "scatter"
    BUBBLE = "bubble"
    PIE = "pie"
    DONUT = "donut"
    SUNBURST = "sunburst"
    TREEMAP = "treemap"
    HEATMAP = "heatmap"
    HISTOGRAM = "histogram"
    WATERFALL = "waterfall"
    GANTT = "gantt"
    HEXBIN = "hexbin"
    CONTOUR = "contour"


class ScaleType(Enum):
    """Enumeration of scale types."""

    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"
    CATEGORICAL = "categorical"
    TIME = "time"
    POWER = "power"
    QUANTIZE = "quantize"


@dataclass
class Color:
    """RGB color representation.

    Attributes:
        r: Red channel (0-255)
        g: Green channel (0-255)
        b: Blue channel (0-255)
        a: Alpha channel (0.0-1.0)
    """

    r: int
    g: int
    b: int
    a: float = 1.0

    def to_hex(self) -> str:
        """Convert color to hexadecimal string.

        Returns:
            Hex color string (e.g., '#FF00FF')
        """
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"

    def to_rgb_string(self) -> str:
        """Convert color to CSS RGB string.

        Returns:
            CSS RGB string (e.g., 'rgb(255, 0, 255)')
        """
        return f"rgb({self.r}, {self.g}, {self.b})"

    def to_rgba_string(self) -> str:
        """Convert color to CSS RGBA string.

        Returns:
            CSS RGBA string (e.g., 'rgba(255, 0, 255, 0.5)')
        """
        return f"rgba({self.r}, {self.g}, {self.b}, {self.a})"

    @staticmethod
    def from_hex(hex_color: str) -> "Color":
        """Create Color from hexadecimal string.

        Args:
            hex_color: Hex color string (e.g., '#FF00FF' or 'FF00FF')

        Returns:
            Color instance
        """
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return Color(r, g, b)


@dataclass
class Font:
    """Font styling for text elements.

    Attributes:
        family: Font family name
        size: Font size in pixels
        weight: Font weight (normal, bold, or numeric 100-900)
        style: Font style (normal or italic)
        color: Text color
    """

    family: str = "Arial"
    size: int = 12
    weight: str | int = "normal"
    style: str = "normal"
    color: Color = field(default_factory=lambda: Color(0, 0, 0))

    def to_css(self) -> str:
        """Convert font to CSS string.

        Returns:
            CSS font declaration
        """
        weight = self.weight if isinstance(self.weight, str) else str(self.weight)
        return f"font-family: {self.family}; font-size: {self.size}px; font-weight: {weight}; font-style: {self.style};"


@dataclass
class Stroke:
    """Stroke styling for shapes.

    Attributes:
        width: Stroke width in pixels
        color: Stroke color
        dasharray: Dash pattern (e.g., "5,5" for dashed)
        linecap: Line cap style (butt, round, square)
        linejoin: Line join style (miter, round, bevel)
    """

    width: float = 1.0
    color: Color = field(default_factory=lambda: Color(0, 0, 0))
    dasharray: str | None = None
    linecap: str = "butt"
    linejoin: str = "miter"

    def to_css(self) -> dict[str, str]:
        """Convert stroke to CSS properties.

        Returns:
            Dictionary of CSS properties
        """
        css = {
            "stroke": self.color.to_hex(),
            "stroke-width": str(self.width),
            "stroke-linecap": self.linecap,
            "stroke-linejoin": self.linejoin,
        }
        if self.dasharray:
            css["stroke-dasharray"] = self.dasharray
        return css


@dataclass
class Fill:
    """Fill styling for shapes.

    Attributes:
        color: Fill color
        opacity: Fill opacity (0.0-1.0)
        pattern: Pattern identifier for advanced fills
    """

    color: Color = field(default_factory=lambda: Color(255, 255, 255))
    opacity: float = 1.0
    pattern: str | None = None

    def to_css(self) -> dict[str, str]:
        """Convert fill to CSS properties.

        Returns:
            Dictionary of CSS properties
        """
        css = {
            "fill": self.color.to_rgba_string() if self.opacity < 1.0 else self.color.to_hex(),
            "opacity": str(self.opacity),
        }
        return css


@dataclass
class Marker:
    """Marker styling for data points.

    Attributes:
        shape: Marker shape (circle, square, triangle, diamond, cross, plus)
        size: Marker size in pixels
        color: Marker color
        stroke: Marker stroke styling
        opacity: Marker opacity
    """

    shape: str = "circle"
    size: float = 5.0
    color: Color = field(default_factory=lambda: Color(0, 0, 255))
    stroke: Stroke = field(default_factory=Stroke)
    opacity: float = 1.0

    def to_svg_dict(self) -> dict[str, Any]:
        """Convert marker to SVG properties dictionary.

        Returns:
            Dictionary with marker properties
        """
        return {
            "shape": self.shape,
            "size": self.size,
            "color": self.color.to_hex(),
            "stroke": self.stroke.to_css(),
            "opacity": self.opacity,
        }


@dataclass
class DataPoint:
    """Single data point in a series.

    Attributes:
        x: X-axis value
        y: Y-axis value
        label: Optional label for the point
        color: Optional color override
        size: Optional size override
        metadata: Optional additional data
    """

    x: float | str | datetime
    y: float
    label: str | None = None
    color: Color | None = None
    size: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Series:
    """A data series containing multiple points.

    Attributes:
        name: Series name for legends
        points: List of data points
        color: Series color
        stroke: Line stroke styling
        marker: Marker styling for points
        opacity: Series opacity
    """

    name: str
    points: list[DataPoint]
    color: Color = field(default_factory=lambda: Color(0, 0, 255))
    stroke: Stroke = field(default_factory=Stroke)
    marker: Marker = field(default_factory=Marker)
    opacity: float = 1.0


@dataclass
class Padding:
    """Padding specification.

    Attributes:
        top: Top padding
        right: Right padding
        bottom: Bottom padding
        left: Left padding
    """

    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0

    def to_tuple(self) -> tuple[float, float, float, float]:
        """Convert to tuple (top, right, bottom, left).

        Returns:
            Tuple representation
        """
        return (self.top, self.right, self.bottom, self.left)


@dataclass
class Size:
    """Size specification.

    Attributes:
        width: Width in pixels or percentage
        height: Height in pixels or percentage
    """

    width: float | str
    height: float | str


@dataclass
class Tick:
    """Axis tick configuration.

    Attributes:
        value: Tick value
        label: Tick label text
        position: Tick position (0.0-1.0 normalized)
    """

    value: float | str | datetime
    label: str
    position: float


@dataclass
class GridLine:
    """Grid line configuration.

    Attributes:
        value: Grid line position value
        stroke: Grid line stroke styling
        axis: Which axis (x or y)
    """

    value: float | str | datetime
    stroke: Stroke = field(default_factory=lambda: Stroke(width=0.5, color=Color(200, 200, 200)))
    axis: str = "y"


@dataclass
class Label:
    """Text label configuration.

    Attributes:
        text: Label text
        position: Label position (x, y) in pixels
        font: Font styling
        angle: Text rotation angle in degrees
        anchor: Text anchor point (start, middle, end)
    """

    text: str
    position: tuple[float, float]
    font: Font = field(default_factory=Font)
    angle: float = 0.0
    anchor: str = "middle"


@dataclass
class Title:
    """Chart title configuration.

    Attributes:
        text: Title text
        font: Title font styling
        position: Title position (top, bottom, inside)
        offset: Offset from chart area in pixels
    """

    text: str
    font: Font = field(default_factory=lambda: Font(size=16, weight="bold"))
    position: str = "top"
    offset: float = 10.0


@dataclass
class Legend:
    """Legend configuration.

    Attributes:
        position: Legend position (top, bottom, left, right, inside)
        orientation: Legend orientation (vertical, horizontal)
        x_offset: Horizontal offset from position
        y_offset: Vertical offset from position
        show: Whether to show legend
        columns: Number of columns for horizontal layout
    """

    position: str = "right"
    orientation: str = "vertical"
    x_offset: float = 10.0
    y_offset: float = 10.0
    show: bool = True
    columns: int = 1

    def is_inside(self) -> bool:
        """Check if legend is inside chart area.

        Returns:
            True if position is 'inside'
        """
        return self.position == "inside"


@dataclass
class Annotation:
    """Chart annotation (text, arrow, etc.).

    Attributes:
        text: Annotation text
        x: X position or value
        y: Y position or value
        style: Annotation style (text, arrow, box)
        color: Annotation color
        font: Font for text
    """

    text: str
    x: float | str | datetime
    y: float
    style: str = "text"
    color: Color = field(default_factory=lambda: Color(0, 0, 0))
    font: Font = field(default_factory=Font)


@dataclass
class Axis:
    """Axis configuration.

    Attributes:
        name: Axis name/label
        scale: Scale for the axis
        ticks: Tick positions and labels
        grid_lines: Grid line configuration
        label: Axis label
        min: Minimum value
        max: Maximum value
        visible: Whether axis is visible
    """

    name: str
    scale: "Scale"
    ticks: list[Tick] = field(default_factory=list)
    grid_lines: list[GridLine] = field(default_factory=list)
    label: Label | None = None
    min: float | datetime | None = None
    max: float | datetime | None = None
    visible: bool = True


@dataclass
class Scale:
    """Base scale class for data mapping.

    Attributes:
        scale_type: Type of scale
        domain: Input data range [min, max]
        range: Output pixel range [min, max]
    """

    scale_type: ScaleType
    domain: tuple[float | datetime, float | datetime]
    range: tuple[float, float]

    def map_value(self, value: float | str | datetime) -> float:
        """Map a value from domain to range.

        Args:
            value: Input value

        Returns:
            Mapped value in range

        Raises:
            NotImplementedError: Subclasses must implement
        """
        raise NotImplementedError("Subclasses must implement map_value")


@dataclass
class ColorMap:
    """Color mapping for data values.

    Attributes:
        name: ColorMap name
        colors: List of colors
        value_range: Data value range for color mapping
        type: Type of color map (sequential, diverging, categorical)
    """

    name: str
    colors: list[Color]
    value_range: tuple[float, float]
    type: str = "sequential"

    def get_color(self, value: float) -> Color:
        """Get color for a data value.

        Args:
            value: Data value (should be in value_range)

        Returns:
            Color for the value
        """
        if len(self.colors) == 0:
            return Color(0, 0, 0)
        if len(self.colors) == 1:
            return self.colors[0]

        min_val, max_val = self.value_range
        if min_val == max_val:
            return self.colors[len(self.colors) // 2]

        normalized = (value - min_val) / (max_val - min_val)
        normalized = max(0.0, min(1.0, normalized))

        index = normalized * (len(self.colors) - 1)
        lower_idx = int(index)
        upper_idx = min(lower_idx + 1, len(self.colors) - 1)

        if lower_idx == upper_idx:
            return self.colors[lower_idx]

        fraction = index - lower_idx
        lower_color = self.colors[lower_idx]
        upper_color = self.colors[upper_idx]

        r = int(lower_color.r * (1 - fraction) + upper_color.r * fraction)
        g = int(lower_color.g * (1 - fraction) + upper_color.g * fraction)
        b = int(lower_color.b * (1 - fraction) + upper_color.b * fraction)

        return Color(r, g, b)


@dataclass
class Figure:
    """Top-level figure/chart container.

    Attributes:
        title: Figure title
        width: Figure width in pixels
        height: Figure height in pixels
        padding: Figure padding
        background_color: Background color
        axes: Dictionary of axes
        series_list: List of data series
        legend: Legend configuration
        annotations: List of annotations
    """

    title: Title | None = None
    width: float = 800.0
    height: float = 600.0
    padding: Padding = field(default_factory=Padding)
    background_color: Color = field(default_factory=lambda: Color(255, 255, 255))
    axes: dict[str, Axis] = field(default_factory=dict)
    series_list: list[Series] = field(default_factory=list)
    legend: Legend = field(default_factory=Legend)
    annotations: list[Annotation] = field(default_factory=list)

    def add_series(self, series: Series) -> None:
        """Add a series to the figure.

        Args:
            series: Series to add
        """
        self.series_list.append(series)

    def add_axis(self, name: str, axis: Axis) -> None:
        """Add an axis to the figure.

        Args:
            name: Axis identifier
            axis: Axis configuration
        """
        self.axes[name] = axis

    def get_data_bounds(self) -> tuple[float, float, float, float]:
        """Get bounding box of all data points.

        Returns:
            Tuple of (min_x, max_x, min_y, max_y)
        """
        if not self.series_list:
            return (0.0, 1.0, 0.0, 1.0)

        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")

        for series in self.series_list:
            for point in series.points:
                if isinstance(point.x, (int, float)):
                    min_x = min(min_x, point.x)
                    max_x = max(max_x, point.x)
                min_y = min(min_y, point.y)
                max_y = max(max_y, point.y)

        return (min_x, max_x, min_y, max_y)
