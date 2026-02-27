"""Tests for SVG rendering."""

import pytest

from thomas.visualization._exceptions import RenderError
from thomas.visualization._types import Color, Stroke
from thomas.visualization.svg_renderer import SVGElement, SVGRenderer


class TestSVGElement:
    """Tests for SVG elements."""

    def test_svg_element_creation(self) -> None:
        """Test basic SVG element creation."""
        elem = SVGElement("rect", x="10", y="20", width="100", height="50")

        assert elem.tag == "rect"
        assert elem.attributes["x"] == "10"
        assert elem.attributes["width"] == "100"

    def test_svg_element_with_children(self) -> None:
        """Test SVG element with child elements."""
        parent = SVGElement("g")
        child1 = SVGElement("circle", cx="50", cy="50", r="25")
        child2 = SVGElement("rect", x="10", y="10", width="30", height="30")

        parent.add_child(child1)
        parent.add_child(child2)

        assert len(parent.children) == 2

    def test_svg_element_text_content(self) -> None:
        """Test SVG element with text content."""
        elem = SVGElement("text", x="50", y="50")
        elem.set_text("Hello <World>")

        assert "Hello &lt;World&gt;" in elem.to_svg()

    def test_svg_element_to_string_empty(self) -> None:
        """Test converting empty element to SVG string."""
        elem = SVGElement("circle", cx="50", cy="50", r="25")

        svg_str = elem.to_svg()

        assert "<circle" in svg_str
        assert "/>" in svg_str

    def test_svg_element_to_string_with_children(self) -> None:
        """Test converting element with children to SVG string."""
        parent = SVGElement("g")
        child = SVGElement("rect", x="10", y="10", width="30", height="30")
        parent.add_child(child)

        svg_str = parent.to_svg()

        assert "<g>" in svg_str
        assert "<rect" in svg_str
        assert "</g>" in svg_str


class TestSVGRenderer:
    """Tests for SVG renderer."""

    def test_renderer_initialization(self) -> None:
        """Test renderer initialization."""
        renderer = SVGRenderer(800.0, 600.0)

        assert renderer.width == 800.0
        assert renderer.height == 600.0
        assert renderer.root is None

    def test_create_document(self) -> None:
        """Test SVG document creation."""
        renderer = SVGRenderer(800.0, 600.0)
        root = renderer.create_document()

        assert root is not None
        assert root.tag == "svg"
        assert renderer.root == root

    def test_add_background(self) -> None:
        """Test adding background."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        color = Color(255, 255, 255)
        bg = renderer.add_background(color)

        assert bg is not None

    def test_add_background_without_document(self) -> None:
        """Test that adding background without document raises error."""
        renderer = SVGRenderer(800.0, 600.0)

        color = Color(255, 255, 255)
        with pytest.raises(RenderError):
            renderer.add_background(color)

    def test_create_rectangle(self) -> None:
        """Test creating rectangle."""
        renderer = SVGRenderer(800.0, 600.0)

        rect = renderer.create_rect(10.0, 20.0, 100.0, 150.0, Color(100, 100, 100))

        assert rect.tag == "rect"
        assert rect.attributes["x"] == "10.0"
        assert rect.attributes["width"] == "100.0"

    def test_create_circle(self) -> None:
        """Test creating circle."""
        renderer = SVGRenderer(800.0, 600.0)

        circle = renderer.create_circle(100.0, 100.0, 25.0, Color(0, 0, 255))

        assert circle.tag == "circle"
        assert circle.attributes["cx"] == "100.0"
        assert circle.attributes["r"] == "25.0"

    def test_create_line(self) -> None:
        """Test creating line."""
        renderer = SVGRenderer(800.0, 600.0)

        line = renderer.create_line(0.0, 0.0, 100.0, 100.0)

        assert line.tag == "line"
        assert line.attributes["x1"] == "0.0"
        assert line.attributes["x2"] == "100.0"

    def test_create_polyline(self) -> None:
        """Test creating polyline."""
        renderer = SVGRenderer(800.0, 600.0)

        points = [(0.0, 0.0), (50.0, 50.0), (100.0, 0.0)]
        polyline = renderer.create_polyline(points)

        assert polyline.tag == "polyline"
        assert "points" in polyline.attributes

    def test_create_polygon(self) -> None:
        """Test creating polygon."""
        renderer = SVGRenderer(800.0, 600.0)

        points = [(50.0, 0.0), (100.0, 50.0), (50.0, 100.0), (0.0, 50.0)]
        polygon = renderer.create_polygon(points, Color(100, 100, 100))

        assert polygon.tag == "polygon"

    def test_create_path(self) -> None:
        """Test creating path."""
        renderer = SVGRenderer(800.0, 600.0)

        path = renderer.create_path("M 10 10 L 100 100")

        assert path.tag == "path"
        assert path.attributes["d"] == "M 10 10 L 100 100"

    def test_create_text(self) -> None:
        """Test creating text element."""
        renderer = SVGRenderer(800.0, 600.0)

        text = renderer.create_text(50.0, 50.0, "Hello", font_size=14, color=Color(0, 0, 0))

        assert text.tag == "text"
        assert "Hello" in text.text

    def test_create_text_with_rotation(self) -> None:
        """Test creating rotated text."""
        renderer = SVGRenderer(800.0, 600.0)

        text = renderer.create_text(50.0, 50.0, "Rotated", angle=45.0)

        assert "rotate(45" in text.attributes.get("transform", "")

    def test_create_group(self) -> None:
        """Test creating group element."""
        renderer = SVGRenderer(800.0, 600.0)

        group = renderer.create_group()

        assert group.tag == "g"

    def test_create_group_with_transform(self) -> None:
        """Test creating group with transform."""
        renderer = SVGRenderer(800.0, 600.0)

        group = renderer.create_group_with_transform(translate=(50.0, 50.0), rotate=45.0, scale=(2.0, 2.0))

        transform = group.attributes.get("transform", "")
        assert "translate" in transform
        assert "rotate" in transform
        assert "scale" in transform

    def test_create_style(self) -> None:
        """Test creating style element."""
        renderer = SVGRenderer(800.0, 600.0)

        style = renderer.create_style("circle { fill: red; }")

        assert style.tag == "style"

    def test_to_svg_string_no_document(self) -> None:
        """Test exporting SVG without document raises error."""
        renderer = SVGRenderer(800.0, 600.0)

        with pytest.raises(RenderError):
            renderer.to_svg_string()

    def test_to_svg_string_basic(self) -> None:
        """Test exporting basic SVG document."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        svg_str = renderer.to_svg_string()

        assert "<?xml" in svg_str
        assert "<svg" in svg_str
        assert "</svg>" in svg_str

    def test_add_axis(self) -> None:
        """Test adding axis to document."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        ticks = [(100.0, 300.0, "10"), (200.0, 300.0, "20")]
        axis = renderer.add_axis("bottom", (0.0, 300.0), (400.0, 300.0), ticks, "X Axis")

        assert axis is not None

    def test_add_axis_without_document(self) -> None:
        """Test adding axis without document raises error."""
        renderer = SVGRenderer(800.0, 600.0)

        ticks = []
        with pytest.raises(RenderError):
            renderer.add_axis("bottom", (0.0, 0.0), (400.0, 0.0), ticks)

    def test_add_legend(self) -> None:
        """Test adding legend."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        items = [("Series A", Color(255, 0, 0)), ("Series B", Color(0, 255, 0))]
        legend = renderer.add_legend(items, 700.0, 50.0)

        assert legend is not None

    def test_add_title(self) -> None:
        """Test adding title."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        title = renderer.add_title("Chart Title", 400.0, 30.0)

        assert title is not None

    def test_add_grid_lines(self) -> None:
        """Test adding grid lines."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        positions = [100.0, 200.0, 300.0]
        grid = renderer.add_grid_lines("vertical", positions, 600.0, 0.0)

        assert grid is not None

    def test_svg_with_colors_and_strokes(self) -> None:
        """Test SVG generation with colors and strokes."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        color = Color(100, 150, 200)
        stroke = Stroke(width=2.0, color=Color(0, 0, 0))

        rect = renderer.create_rect(10.0, 10.0, 100.0, 100.0, color, stroke)
        renderer.root.add_child(rect)

        svg_str = renderer.to_svg_string()

        assert "fill=" in svg_str
        assert "stroke" in svg_str

    def test_nested_groups_and_elements(self) -> None:
        """Test nested SVG groups and elements."""
        renderer = SVGRenderer(800.0, 600.0)
        renderer.create_document()

        group = renderer.create_group()
        circle1 = renderer.create_circle(50.0, 50.0, 25.0, Color(255, 0, 0))
        circle2 = renderer.create_circle(150.0, 150.0, 25.0, Color(0, 255, 0))

        group.add_child(circle1)
        group.add_child(circle2)
        renderer.root.add_child(group)

        svg_str = renderer.to_svg_string()

        assert svg_str.count("<circle") == 2
