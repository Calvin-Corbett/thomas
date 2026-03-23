"""Chart layout engine for positioning elements and calculating dimensions."""

from dataclasses import dataclass

from thomas.marketplace.visualization._exceptions import LayoutError
from thomas.marketplace.visualization._types import Axis, Figure


@dataclass
class SubplotLayout:
    """Layout information for a single subplot."""

    x: float
    y: float
    width: float
    height: float
    plot_x: float
    plot_y: float
    plot_width: float
    plot_height: float


@dataclass
class AxisLayout:
    """Layout information for an axis."""

    position: str
    x: float
    y: float
    length: float
    label_offset: float
    tick_positions: list[tuple[float, float]]


class ChartLayout:
    """Layout engine for chart positioning and responsive sizing."""

    def __init__(self, figure: Figure) -> None:
        """Initialize layout engine.

        Args:
            figure: Figure to layout
        """
        self.figure = figure
        self.subplots: dict[str, SubplotLayout] = {}
        self.axes_layout: dict[str, AxisLayout] = {}

    def calculate_layout(self) -> dict[str, any]:
        """Calculate complete layout for the figure.

        Returns:
            Dictionary containing layout information
        """
        layout_info = {
            "figure": self._calculate_figure_layout(),
            "axes": self._calculate_axes_layout(),
            "subplots": self._calculate_subplots_layout(),
            "legend": self._calculate_legend_layout(),
        }
        return layout_info

    def _calculate_figure_layout(self) -> dict[str, float]:
        """Calculate overall figure layout.

        Returns:
            Figure layout dimensions
        """
        width = self.figure.width
        height = self.figure.height
        padding = self.figure.padding

        content_x = padding.left
        content_y = padding.top
        content_width = width - padding.left - padding.right
        content_height = height - padding.top - padding.bottom

        if content_width <= 0 or content_height <= 0:
            raise LayoutError("Insufficient space for chart after padding")

        return {
            "width": width,
            "height": height,
            "content_x": content_x,
            "content_y": content_y,
            "content_width": content_width,
            "content_height": content_height,
        }

    def _calculate_axes_layout(self) -> dict[str, AxisLayout]:
        """Calculate layout for all axes.

        Returns:
            Dictionary of axis layouts
        """
        axes_layout = {}
        figure_layout = self._calculate_figure_layout()

        content_x = figure_layout["content_x"]
        content_y = figure_layout["content_y"]
        content_width = figure_layout["content_width"]
        content_height = figure_layout["content_height"]

        left_axis_width = self._estimate_axis_width("left")
        right_axis_width = self._estimate_axis_width("right")
        top_axis_height = self._estimate_axis_height("top")
        bottom_axis_height = self._estimate_axis_height("bottom")

        plot_x = content_x + left_axis_width
        plot_y = content_y + top_axis_height
        plot_width = content_width - left_axis_width - right_axis_width
        plot_height = content_height - top_axis_height - bottom_axis_height

        if plot_width <= 0 or plot_height <= 0:
            plot_width = max(1, plot_width)
            plot_height = max(1, plot_height)

        for axis_name, axis in self.figure.axes.items():
            if axis.position == "left":
                axes_layout[axis_name] = AxisLayout(
                    position="left",
                    x=content_x,
                    y=plot_y,
                    length=plot_height,
                    label_offset=left_axis_width,
                    tick_positions=self._calculate_tick_positions(axis, plot_height),
                )
            elif axis.position == "right":
                axes_layout[axis_name] = AxisLayout(
                    position="right",
                    x=plot_x + plot_width,
                    y=plot_y,
                    length=plot_height,
                    label_offset=right_axis_width,
                    tick_positions=self._calculate_tick_positions(axis, plot_height),
                )
            elif axis.position == "top":
                axes_layout[axis_name] = AxisLayout(
                    position="top",
                    x=plot_x,
                    y=content_y,
                    length=plot_width,
                    label_offset=top_axis_height,
                    tick_positions=self._calculate_tick_positions(axis, plot_width),
                )
            elif axis.position == "bottom":
                axes_layout[axis_name] = AxisLayout(
                    position="bottom",
                    x=plot_x,
                    y=plot_y + plot_height,
                    length=plot_width,
                    label_offset=bottom_axis_height,
                    tick_positions=self._calculate_tick_positions(axis, plot_width),
                )

        return axes_layout

    def _estimate_axis_width(self, position: str) -> float:
        """Estimate width needed for axis.

        Args:
            position: Axis position (left, right, top, bottom)

        Returns:
            Estimated width in pixels
        """
        axis_found = any(ax.position == position for ax in self.figure.axes.values())
        if not axis_found:
            return 0.0

        if position in ("left", "right"):
            return 60.0
        return 0.0

    def _estimate_axis_height(self, position: str) -> float:
        """Estimate height needed for axis.

        Args:
            position: Axis position (left, right, top, bottom)

        Returns:
            Estimated height in pixels
        """
        axis_found = any(ax.position == position for ax in self.figure.axes.values())
        if not axis_found:
            return 0.0

        if position in ("top", "bottom"):
            return 40.0
        return 0.0

    def _calculate_tick_positions(
        self,
        axis: Axis,
        available_space: float,
    ) -> list[tuple[float, float]]:
        """Calculate positions for axis ticks.

        Args:
            axis: Axis configuration
            available_space: Space available for ticks (width or height)

        Returns:
            List of (position, label_offset) tuples
        """
        positions = []
        ticks = axis.scale.generate_ticks()

        for tick in ticks:
            positions.append((tick.position * available_space, 5.0))

        return positions

    def _calculate_subplots_layout(self) -> dict[str, SubplotLayout]:
        """Calculate layout for subplots.

        Returns:
            Dictionary of subplot layouts
        """
        figure_layout = self._calculate_figure_layout()
        axes_layout = self._calculate_axes_layout()

        subplot_layout = SubplotLayout(
            x=figure_layout["content_x"],
            y=figure_layout["content_y"],
            width=figure_layout["content_width"],
            height=figure_layout["content_height"],
            plot_x=min(al.x for al in axes_layout.values()) if axes_layout else figure_layout["content_x"],
            plot_y=min(al.y for al in axes_layout.values()) if axes_layout else figure_layout["content_y"],
            plot_width=figure_layout["content_width"] * 0.8,
            plot_height=figure_layout["content_height"] * 0.8,
        )

        self.subplots["main"] = subplot_layout
        return {"main": subplot_layout}

    def _calculate_legend_layout(self) -> dict[str, float]:
        """Calculate legend position and size.

        Returns:
            Legend layout information
        """
        legend = self.figure.legend
        figure_layout = self._calculate_figure_layout()

        content_x = figure_layout["content_x"]
        content_y = figure_layout["content_y"]
        content_width = figure_layout["content_width"]
        content_height = figure_layout["content_height"]

        legend_width = self._estimate_legend_width()
        legend_height = self._estimate_legend_height()

        if legend.position == "top":
            return {
                "x": content_x + legend.x_offset,
                "y": content_y + legend.y_offset,
                "width": legend_width,
                "height": legend_height,
            }
        elif legend.position == "bottom":
            return {
                "x": content_x + legend.x_offset,
                "y": content_y + content_height - legend_height - legend.y_offset,
                "width": legend_width,
                "height": legend_height,
            }
        elif legend.position == "left":
            return {
                "x": content_x + legend.x_offset,
                "y": content_y + legend.y_offset,
                "width": legend_width,
                "height": legend_height,
            }
        elif legend.position == "right":
            return {
                "x": content_x + content_width - legend_width - legend.x_offset,
                "y": content_y + legend.y_offset,
                "width": legend_width,
                "height": legend_height,
            }
        else:
            return {
                "x": content_x + content_width - legend_width - 10,
                "y": content_y + 10,
                "width": legend_width,
                "height": legend_height,
            }

    def _estimate_legend_width(self) -> float:
        """Estimate legend width.

        Returns:
            Estimated width in pixels
        """
        if not self.figure.legend.show or not self.figure.series_list:
            return 0.0

        max_name_len = max(len(s.name) for s in self.figure.series_list) if self.figure.series_list else 0
        return 20 + max_name_len * 8 + 20

    def _estimate_legend_height(self) -> float:
        """Estimate legend height.

        Returns:
            Estimated height in pixels
        """
        if not self.figure.legend.show or not self.figure.series_list:
            return 0.0

        num_items = len(self.figure.series_list)
        if self.figure.legend.orientation == "horizontal":
            return 25.0
        else:
            return 10 + num_items * 20 + 10

    def get_plot_area(self) -> tuple[float, float, float, float]:
        """Get plot area dimensions.

        Returns:
            Tuple of (x, y, width, height)
        """
        axes_layout = self._calculate_axes_layout()
        if "bottom" in [al.position for al in axes_layout.values()]:
            bottom_axis = [al for al in axes_layout.values() if al.position == "bottom"][0]
            plot_y = min(al.y for al in axes_layout.values() if al.position != "bottom")
        else:
            plot_y = min([al.y for al in axes_layout.values()]) if axes_layout else 0

        if "top" in [al.position for al in axes_layout.values()]:
            top_axis = [al for al in axes_layout.values() if al.position == "top"][0]
            plot_y = top_axis.y + self._estimate_axis_height("top")

        plot_height = 0.0
        plot_width = 0.0

        if axes_layout:
            for al in axes_layout.values():
                if al.position in ("left", "right"):
                    plot_height = max(plot_height, al.length)
                elif al.position in ("top", "bottom"):
                    plot_width = max(plot_width, al.length)

        figure_layout = self._calculate_figure_layout()
        plot_x = figure_layout["content_x"] + self._estimate_axis_width("left")

        return (plot_x, plot_y, plot_width, plot_height)

    def calculate_responsive_dimensions(
        self,
        container_width: float,
        container_height: float,
        aspect_ratio: float | None = None,
    ) -> tuple[float, float]:
        """Calculate responsive dimensions preserving aspect ratio.

        Args:
            container_width: Available container width
            container_height: Available container height
            aspect_ratio: Target aspect ratio (width/height)

        Returns:
            Tuple of (width, height)
        """
        if aspect_ratio is None:
            return (container_width, container_height)

        current_ratio = container_width / max(1, container_height)

        if current_ratio > aspect_ratio:
            width = container_height * aspect_ratio
            height = container_height
        else:
            width = container_width
            height = container_width / aspect_ratio

        return (width, height)
