"""Thomas Visualization Library - Data visualization and charting library."""

from thomas.visualization._exceptions import (
    InvalidDataError,
    InvalidScaleError,
    RenderError,
    VisualizationError,
)
from thomas.visualization._types import (
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
from thomas.visualization.bar_chart import BarChart
from thomas.visualization.heatmap import Heatmap
from thomas.visualization.interactive import InteractiveChart
from thomas.visualization.layout import ChartLayout
from thomas.visualization.line_chart import LineChart
from thomas.visualization.pie_chart import PieChart
from thomas.visualization.scales import (
    CategoricalScale,
    LinearScale,
    LogarithmicScale,
    PowerScale,
    QuantizeScale,
    TimeScale,
)
from thomas.visualization.scatter import ScatterPlot
from thomas.visualization.svg_renderer import SVGRenderer

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
