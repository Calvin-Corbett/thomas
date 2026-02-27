"""SVG rendering engine for outputting charts as SVG documents."""

from typing import Any
from xml.sax.saxutils import escape

from thomas.visualization._exceptions import RenderError
from thomas.visualization._types import Color, Stroke


class SVGElement:
    """Base class for SVG elements."""

    def __init__(self, tag: str, **kwargs: Any) -> None:
        """Initialize SVG element.

        Args:
            tag: HTML/SVG tag name
            **kwargs: Element attributes
        """
        self.tag = tag
        self.attributes = kwargs
        self.children: list[SVGElement] = []
        self.text = ""

    def add_child(self, child: "SVGElement") -> None:
        """Add child element.

        Args:
            child: Child element
        """
        self.children.append(child)

    def set_text(self, text: str) -> None:
        """Set element text content.

        Args:
            text: Text content
        """
        self.text = escape(str(text))

    def to_svg(self, indent: int = 0) -> str:
        """Convert element to SVG string.

        Args:
            indent: Indentation level

        Returns:
            SVG string representation
        """
        indent_str = "  " * indent
        attr_str = " ".join(f'{k}="{v}"' for k, v in self.attributes.items())

        if not self.children and not self.text and self.tag != "svg":
            if attr_str:
                return f"{indent_str}<{self.tag} {attr_str} />\n"
            else:
                return f"{indent_str}<{self.tag} />\n"

        if attr_str:
            opening = f"{indent_str}<{self.tag} {attr_str}>\n"
        else:
            opening = f"{indent_str}<{self.tag}>\n"

        content = ""
        if self.text:
            content += f'{"  " * (indent + 1)}{self.text}\n'

        for child in self.children:
            content += child.to_svg(indent + 1)

        closing = f"{indent_str}</{self.tag}>\n"

        return opening + content + closing


class SVGRenderer:
    """SVG document generator and shape renderer."""

    def __init__(self, width: float, height: float) -> None:
        """Initialize SVG renderer.

        Args:
            width: SVG viewport width
            height: SVG viewport height
        """
        self.width = width
        self.height = height
        self.root: SVGElement | None = None

    def create_document(self) -> SVGElement:
        """Create SVG document root.

        Returns:
            SVG root element
        """
        self.root = SVGElement(
            "svg",
            xmlns="http://www.w3.org/2000/svg",
            width=str(self.width),
            height=str(self.height),
            viewBox=f"0 0 {self.width} {self.height}",
        )
        return self.root

    def add_background(self, color: Color) -> SVGElement:
        """Add background rectangle.

        Args:
            color: Background color

        Returns:
            Background element
        """
        if not self.root:
            raise RenderError("SVG document not created")

        bg = self.create_rect(0, 0, self.width, self.height, color)
        self.root.add_child(bg)
        return bg

    def create_group(self, **kwargs: Any) -> SVGElement:
        """Create group element for transforms.

        Args:
            **kwargs: Group attributes

        Returns:
            Group element
        """
        return SVGElement("g", **kwargs)

    def create_rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        fill: Color = None,
        stroke: Stroke = None,
    ) -> SVGElement:
        """Create rectangle element.

        Args:
            x: X position
            y: Y position
            width: Rectangle width
            height: Rectangle height
            fill: Fill color
            stroke: Stroke style

        Returns:
            Rectangle element
        """
        rect = SVGElement("rect", x=str(x), y=str(y), width=str(width), height=str(height))

        if fill:
            rect.attributes["fill"] = fill.to_hex() if fill.a == 1.0 else fill.to_rgba_string()
        if stroke:
            rect.attributes.update(stroke.to_css())

        return rect

    def create_circle(
        self,
        cx: float,
        cy: float,
        r: float,
        fill: Color = None,
        stroke: Stroke = None,
    ) -> SVGElement:
        """Create circle element.

        Args:
            cx: Center X
            cy: Center Y
            r: Radius
            fill: Fill color
            stroke: Stroke style

        Returns:
            Circle element
        """
        circle = SVGElement("circle", cx=str(cx), cy=str(cy), r=str(r))

        if fill:
            circle.attributes["fill"] = fill.to_hex() if fill.a == 1.0 else fill.to_rgba_string()
        if stroke:
            circle.attributes.update(stroke.to_css())

        return circle

    def create_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        stroke: Stroke = None,
    ) -> SVGElement:
        """Create line element.

        Args:
            x1: Start X
            y1: Start Y
            x2: End X
            y2: End Y
            stroke: Stroke style

        Returns:
            Line element
        """
        line = SVGElement("line", x1=str(x1), y1=str(y1), x2=str(x2), y2=str(y2))

        if stroke:
            line.attributes.update(stroke.to_css())
        else:
            line.attributes["stroke"] = "#000000"
            line.attributes["stroke-width"] = "1"

        return line

    def create_polyline(
        self,
        points: list[tuple[float, float]],
        stroke: Stroke = None,
        fill: Color | None = None,
    ) -> SVGElement:
        """Create polyline element.

        Args:
            points: List of (x, y) points
            stroke: Stroke style
            fill: Fill color (usually None for lines)

        Returns:
            Polyline element
        """
        points_str = " ".join(f"{x},{y}" for x, y in points)
        polyline = SVGElement("polyline", points=points_str)

        if fill:
            polyline.attributes["fill"] = fill.to_hex() if fill.a == 1.0 else fill.to_rgba_string()
        else:
            polyline.attributes["fill"] = "none"

        if stroke:
            polyline.attributes.update(stroke.to_css())

        return polyline

    def create_polygon(
        self,
        points: list[tuple[float, float]],
        fill: Color = None,
        stroke: Stroke = None,
    ) -> SVGElement:
        """Create polygon element.

        Args:
            points: List of (x, y) points
            fill: Fill color
            stroke: Stroke style

        Returns:
            Polygon element
        """
        points_str = " ".join(f"{x},{y}" for x, y in points)
        polygon = SVGElement("polygon", points=points_str)

        if fill:
            polygon.attributes["fill"] = fill.to_hex() if fill.a == 1.0 else fill.to_rgba_string()
        if stroke:
            polygon.attributes.update(stroke.to_css())

        return polygon

    def create_path(
        self,
        path_data: str,
        fill: Color | None = None,
        stroke: Stroke = None,
    ) -> SVGElement:
        """Create path element.

        Args:
            path_data: SVG path data string
            fill: Fill color
            stroke: Stroke style

        Returns:
            Path element
        """
        path = SVGElement("path", d=path_data)

        if fill:
            path.attributes["fill"] = fill.to_hex() if fill.a == 1.0 else fill.to_rgba_string()
        else:
            path.attributes["fill"] = "none"

        if stroke:
            path.attributes.update(stroke.to_css())

        return path

    def create_text(
        self,
        x: float,
        y: float,
        text: str,
        font_size: int = 12,
        font_family: str = "Arial",
        color: Color = None,
        text_anchor: str = "middle",
        angle: float = 0.0,
    ) -> SVGElement:
        """Create text element.

        Args:
            x: X position
            y: Y position
            text: Text content
            font_size: Font size
            font_family: Font family
            color: Text color
            text_anchor: Text anchor (start, middle, end)
            angle: Rotation angle in degrees

        Returns:
            Text element
        """
        text_elem = SVGElement(
            "text",
            x=str(x),
            y=str(y),
            **{"font-size": str(font_size), "font-family": font_family, "text-anchor": text_anchor},
        )

        if color:
            text_elem.attributes["fill"] = color.to_hex()

        if angle != 0:
            text_elem.attributes["transform"] = f"rotate({angle} {x} {y})"

        text_elem.set_text(text)

        return text_elem

    def create_group_with_transform(
        self,
        translate: tuple[float, float] | None = None,
        rotate: float | None = None,
        scale: tuple[float, float] | None = None,
    ) -> SVGElement:
        """Create group with transforms.

        Args:
            translate: (tx, ty) translation
            rotate: Rotation angle in degrees
            scale: (sx, sy) scale factors

        Returns:
            Group element
        """
        transforms = []

        if translate:
            transforms.append(f"translate({translate[0]} {translate[1]})")
        if rotate:
            transforms.append(f"rotate({rotate})")
        if scale:
            transforms.append(f"scale({scale[0]} {scale[1]})")

        transform_str = " ".join(transforms) if transforms else None
        group = self.create_group(transform=transform_str) if transform_str else self.create_group()

        return group

    def create_style(self, css: str) -> SVGElement:
        """Create style element with CSS.

        Args:
            css: CSS rules

        Returns:
            Style element
        """
        style = SVGElement("style")
        style.set_text(css)
        return style

    def to_svg_string(self) -> str:
        """Export SVG document as string.

        Returns:
            Complete SVG document string
        """
        if not self.root:
            raise RenderError("SVG document not created")

        svg_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
        svg_str += self.root.to_svg()

        return svg_str

    def add_axis(
        self,
        position: str,
        start: tuple[float, float],
        end: tuple[float, float],
        ticks: list[tuple[float, float, str]],
        label: str | None = None,
    ) -> SVGElement:
        """Add axis to document.

        Args:
            position: Axis position (left, right, top, bottom)
            start: Starting coordinate
            end: Ending coordinate
            ticks: List of (position, offset, label) tuples
            label: Axis label

        Returns:
            Group element containing axis
        """
        if not self.root:
            raise RenderError("SVG document not created")

        axis_group = self.create_group()

        axis_line = self.create_line(start[0], start[1], end[0], end[1], Stroke(width=1))
        axis_group.add_child(axis_line)

        for tick_x, tick_y, tick_label in ticks:
            if position in ("top", "bottom"):
                tick_line = self.create_line(tick_x, tick_y - 3, tick_x, tick_y + 3)
                label_y = tick_y + 15
            else:
                tick_line = self.create_line(tick_x - 3, tick_y, tick_x + 3, tick_y)
                label_y = tick_y

            axis_group.add_child(tick_line)

            if tick_label:
                tick_text = self.create_text(tick_x, label_y, tick_label, font_size=10)
                axis_group.add_child(tick_text)

        if label:
            if position == "bottom":
                label_x = (start[0] + end[0]) / 2
                label_y = end[1] + 30
            elif position == "left":
                label_x = start[0] - 40
                label_y = (start[1] + end[1]) / 2
            else:
                label_x = (start[0] + end[0]) / 2
                label_y = start[1] - 10

            label_elem = self.create_text(label_x, label_y, label, font_size=12)
            axis_group.add_child(label_elem)

        self.root.add_child(axis_group)

        return axis_group

    def add_legend(
        self,
        items: list[tuple[str, Color]],
        x: float,
        y: float,
    ) -> SVGElement:
        """Add legend to document.

        Args:
            items: List of (label, color) tuples
            x: Legend X position
            y: Legend Y position

        Returns:
            Group element containing legend
        """
        if not self.root:
            raise RenderError("SVG document not created")

        legend_group = self.create_group()

        bg_height = len(items) * 20 + 10
        bg = self.create_rect(x - 5, y - 5, 150, bg_height, Color(255, 255, 255), Stroke(width=1))
        legend_group.add_child(bg)

        for idx, (label, color) in enumerate(items):
            item_y = y + idx * 20

            color_box = self.create_rect(x, item_y, 12, 12, color)
            legend_group.add_child(color_box)

            label_text = self.create_text(x + 18, item_y + 10, label, font_size=11, text_anchor="start")
            legend_group.add_child(label_text)

        self.root.add_child(legend_group)

        return legend_group

    def add_title(self, text: str, x: float, y: float) -> SVGElement:
        """Add title to document.

        Args:
            text: Title text
            x: X position
            y: Y position

        Returns:
            Text element
        """
        if not self.root:
            raise RenderError("SVG document not created")

        title_elem = self.create_text(x, y, text, font_size=16)
        title_elem.attributes["font-weight"] = "bold"
        self.root.add_child(title_elem)

        return title_elem

    def add_grid_lines(
        self,
        direction: str,
        positions: list[float],
        length: float,
        start_offset: float,
    ) -> SVGElement:
        """Add grid lines to chart.

        Args:
            direction: Grid direction (horizontal or vertical)
            positions: List of grid line positions
            length: Length of each grid line
            start_offset: Starting offset for lines

        Returns:
            Group element containing grid lines
        """
        if not self.root:
            raise RenderError("SVG document not created")

        grid_group = self.create_group()
        grid_stroke = Stroke(width=0.5, color=Color(200, 200, 200))

        for pos in positions:
            if direction == "horizontal":
                line = self.create_line(start_offset, pos, start_offset + length, pos, grid_stroke)
            else:
                line = self.create_line(pos, start_offset, pos, start_offset + length, grid_stroke)

            grid_group.add_child(line)

        self.root.add_child(grid_group)

        return grid_group
