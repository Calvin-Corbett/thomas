"""Thomas Visualization Library - Data visualization and charting library."""

from thomas.marketplace.visualization._exceptions import (
    InvalidDataError,
    InvalidScaleError,
    RenderError,
    VisualizationError,
)
from thomas.marketplace.visualization._types import (
    ChartType,
    Color,
    ColorMap,
    DataPoint,
    Figure,
    Fill,
    Font,
    GridLine,
    Label,
    Legend,
    Marker,
    Padding,
    Scale,
    Series,
    Size,
    Stroke,
    Tick,
    Title,
)
from thomas.marketplace.visualization.bar_chart import BarChart
from thomas.marketplace.visualization.heatmap import Heatmap
from thomas.marketplace.visualization.interactive import InteractiveChart
from thomas.marketplace.visualization.layout import ChartLayout
from thomas.marketplace.visualization.line_chart import LineChart
from thomas.marketplace.visualization.pie_chart import PieChart
from thomas.marketplace.visualization.scales import (
    CategoricalScale,
    LinearScale,
    LogarithmicScale,
    PowerScale,
    QuantizeScale,
    TimeScale,
)
from thomas.marketplace.visualization.scatter import ScatterPlot
from thomas.marketplace.visualization.svg_renderer import SVGRenderer

__version__ = "0.1.0"
__all__ = [
    "ChartType",
    "Color",
    "ColorMap",
    "DataPoint",
    "Figure",
    "Fill",
    "Font",
    "GridLine",
    "Label",
    "Legend",
    "Marker",
    "Padding",
    "Scale",
    "Series",
    "Size",
    "Stroke",
    "Tick",
    "Title",
    "VisualizationError",
    "InvalidScaleError",
    "InvalidDataError",
    "RenderError",
    "LinearScale",
    "LogarithmicScale",
    "CategoricalScale",
    "TimeScale",
    "PowerScale",
    "QuantizeScale",
    "ChartLayout",
    "LineChart",
    "BarChart",
    "ScatterPlot",
    "PieChart",
    "Heatmap",
    "SVGRenderer",
    "InteractiveChart",
]
