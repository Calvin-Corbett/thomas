"""
Tests for CAD file I/O.
"""

import os
import tempfile

import pytest

from thomas.marketplace.cad._exceptions import IOError as CADIOError
from thomas.marketplace.cad._exceptions import UnsupportedFormatError
from thomas.marketplace.cad._types import Point2D, Point3D, Polygon, Vector3D
from thomas.marketplace.cad.io_formats import (
    DXFWriter,
    STEPWriter,
    STLWriter,
    SVGExporter,
    detect_format,
    unit_conversion,
)


class TestFormatDetection:
    """Tests for file format detection."""

    def test_detect_dxf(self) -> None:
        """Test DXF format detection."""
        assert detect_format("drawing.dxf") == "dxf"

    def test_detect_svg(self) -> None:
        """Test SVG format detection."""
        assert detect_format("image.svg") == "svg"

    def test_detect_stl(self) -> None:
        """Test STL format detection."""
        assert detect_format("model.stl") == "stl"

    def test_detect_step(self) -> None:
        """Test STEP format detection."""
        assert detect_format("model.step") == "step"
        assert detect_format("model.stp") == "step"

    def test_detect_unknown_format(self) -> None:
        """Test unknown format detection."""
        with pytest.raises(UnsupportedFormatError):
            detect_format("file.xyz")

    def test_detect_case_insensitive(self) -> None:
        """Test case-insensitive format detection."""
        assert detect_format("DRAWING.DXF") == "dxf"
        assert detect_format("Image.SVG") == "svg"


class TestDXFWriter:
    """Tests for DXF writer."""

    def test_dxf_writer_creation(self) -> None:
        """Test DXF writer creation."""
        writer = DXFWriter("test.dxf")
        assert writer.filename == "test.dxf"

    def test_dxf_add_line(self) -> None:
        """Test adding line to DXF."""
        writer = DXFWriter("test.dxf")

        start = Point2D(0, 0)
        end = Point2D(10, 0)

        writer.add_line(start, end)

        assert len(writer.entities) > 0

    def test_dxf_add_circle(self) -> None:
        """Test adding circle to DXF."""
        writer = DXFWriter("test.dxf")

        center = Point2D(5, 5)
        radius = 3.0

        writer.add_circle(center, radius)

        assert len(writer.entities) > 0

    def test_dxf_add_polyline(self) -> None:
        """Test adding polyline to DXF."""
        writer = DXFWriter("test.dxf")

        points = [Point2D(0, 0), Point2D(5, 0), Point2D(5, 5)]

        writer.add_polyline(points)

        assert len(writer.entities) > 0

    def test_dxf_write_file(self) -> None:
        """Test writing DXF file."""
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            filename = f.name

        try:
            writer = DXFWriter(filename)
            writer.add_line(Point2D(0, 0), Point2D(10, 0))
            writer.write()

            assert os.path.exists(filename)
            assert os.path.getsize(filename) > 0
        finally:
            if os.path.exists(filename):
                os.remove(filename)


class TestSVGExporter:
    """Tests for SVG exporter."""

    def test_svg_exporter_creation(self) -> None:
        """Test SVG exporter creation."""
        exporter = SVGExporter("test.svg")
        assert exporter.filename == "test.svg"
        assert exporter.width == 800
        assert exporter.height == 600

    def test_svg_add_line(self) -> None:
        """Test adding line to SVG."""
        exporter = SVGExporter("test.svg")

        start = Point2D(0, 0)
        end = Point2D(100, 100)

        exporter.add_line(start, end)

        assert len(exporter.elements) > 0

    def test_svg_add_circle(self) -> None:
        """Test adding circle to SVG."""
        exporter = SVGExporter("test.svg")

        center = Point2D(50, 50)
        radius = 25.0

        exporter.add_circle(center, radius)

        assert len(exporter.elements) > 0

    def test_svg_add_polygon(self) -> None:
        """Test adding polygon to SVG."""
        exporter = SVGExporter("test.svg")

        polygon = Polygon(
            [
                Point2D(0, 0),
                Point2D(100, 0),
                Point2D(100, 100),
                Point2D(0, 100),
            ]
        )

        exporter.add_polygon(polygon)

        assert len(exporter.elements) > 0

    def test_svg_write_file(self) -> None:
        """Test writing SVG file."""
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            filename = f.name

        try:
            exporter = SVGExporter(filename)
            exporter.add_circle(Point2D(100, 100), 50)
            exporter.write()

            assert os.path.exists(filename)
            assert os.path.getsize(filename) > 0

            with open(filename) as f:
                content = f.read()
                assert "<svg" in content
                assert "circle" in content
        finally:
            if os.path.exists(filename):
                os.remove(filename)


class TestSTLWriter:
    """Tests for STL writer."""

    def test_stl_writer_creation(self) -> None:
        """Test STL writer creation."""
        writer = STLWriter("test.stl")
        assert writer.filename == "test.stl"

    def test_stl_add_triangle(self) -> None:
        """Test adding triangle to STL."""
        writer = STLWriter("test.stl")

        normal = Vector3D(0, 0, 1)
        v1 = Point3D(0, 0, 0)
        v2 = Point3D(1, 0, 0)
        v3 = Point3D(0, 1, 0)

        writer.add_triangle(normal, v1, v2, v3)

        assert len(writer.triangles) == 1

    def test_stl_write_file(self) -> None:
        """Test writing STL file."""
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            filename = f.name

        try:
            writer = STLWriter(filename)

            normal = Vector3D(0, 0, 1).normalize()
            v1 = Point3D(0, 0, 0)
            v2 = Point3D(1, 0, 0)
            v3 = Point3D(0, 1, 0)

            writer.add_triangle(normal, v1, v2, v3)
            writer.write()

            assert os.path.exists(filename)

            with open(filename) as f:
                content = f.read()
                assert "facet normal" in content
                assert "vertex" in content
        finally:
            if os.path.exists(filename):
                os.remove(filename)


class TestSTEPWriter:
    """Tests for STEP writer."""

    def test_step_writer_creation(self) -> None:
        """Test STEP writer creation."""
        writer = STEPWriter("test.stp")
        assert writer.filename == "test.stp"

    def test_step_add_point(self) -> None:
        """Test adding point to STEP."""
        writer = STEPWriter("test.stp")

        point = Point3D(1, 2, 3)
        eid = writer.add_point(point)

        assert eid > 0
        assert len(writer.entities) > 0

    def test_step_add_line(self) -> None:
        """Test adding line to STEP."""
        writer = STEPWriter("test.stp")

        start = Point3D(0, 0, 0)
        end = Point3D(1, 1, 1)

        eid = writer.add_line(start, end)

        assert eid > 0

    def test_step_write_file(self) -> None:
        """Test writing STEP file."""
        with tempfile.NamedTemporaryFile(suffix=".stp", delete=False) as f:
            filename = f.name

        try:
            writer = STEPWriter(filename)
            writer.add_point(Point3D(0, 0, 0))
            writer.add_line(Point3D(0, 0, 0), Point3D(1, 1, 1))
            writer.write()

            assert os.path.exists(filename)

            with open(filename) as f:
                content = f.read()
                assert "ISO-10303-21" in content
        finally:
            if os.path.exists(filename):
                os.remove(filename)


class TestUnitConversion:
    """Tests for unit conversion."""

    def test_convert_mm_to_cm(self) -> None:
        """Test mm to cm conversion."""
        result = unit_conversion(10.0, "mm", "cm")
        assert result == pytest.approx(1.0)

    def test_convert_mm_to_inch(self) -> None:
        """Test mm to inch conversion."""
        result = unit_conversion(25.4, "mm", "inch")
        assert result == pytest.approx(1.0)

    def test_convert_inch_to_mm(self) -> None:
        """Test inch to mm conversion."""
        result = unit_conversion(1.0, "inch", "mm")
        assert result == pytest.approx(25.4)

    def test_convert_same_unit(self) -> None:
        """Test conversion to same unit."""
        result = unit_conversion(100.0, "mm", "mm")
        assert result == 100.0

    def test_convert_unsupported(self) -> None:
        """Test unsupported conversion."""
        with pytest.raises(CADIOError):
            unit_conversion(1.0, "mm", "parsecs")

    def test_convert_chain(self) -> None:
        """Test chained conversions."""
        mm_to_cm = unit_conversion(10.0, "mm", "cm")
        cm_to_m = unit_conversion(mm_to_cm, "cm", "m")

        assert cm_to_m == pytest.approx(0.1)


class TestIOErrors:
    """Tests for I/O error handling."""

    def test_write_nonexistent_directory(self) -> None:
        """Test writing to nonexistent directory."""
        writer = DXFWriter("/nonexistent/path/file.dxf")

        with pytest.raises(Exception):
            writer.write()
