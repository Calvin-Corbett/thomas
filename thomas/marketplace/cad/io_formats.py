"""
CAD file I/O: readers and writers for DXF, SVG, STL, and STEP formats.
"""

from __future__ import annotations

from typing import Any

from ._exceptions import IOError as CADIOError
from ._exceptions import UnsupportedFormatError
from ._types import (
    Point2D,
    Point3D,
    Polygon,
    Solid,
    Vector3D,
)

EPSILON = 1e-10


def detect_format(filename: str) -> str:
    """
    Detect CAD file format from extension.

    Args:
        filename: File path

    Returns:
        Format string: "dxf", "svg", "stl", "step"
    """
    ext = filename.lower().split(".")[-1]

    format_map = {
        "dxf": "dxf",
        "svg": "svg",
        "stl": "stl",
        "step": "step",
        "stp": "step",
    }

    if ext not in format_map:
        raise UnsupportedFormatError(f"Unknown format: {ext}")

    return format_map[ext]


class DXFReader:
    """DXF (Drawing Exchange Format) reader."""

    def __init__(self, filename: str) -> None:
        """
        Initialize DXF reader.

        Args:
            filename: DXF file path
        """
        self.filename = filename
        self.sections: dict[str, list[str]] = {}
        self.entities: list[dict[str, Any]] = []

    def read(self) -> dict[str, Any]:
        """
        Read DXF file.

        Args:
            Returns dictionary with parsed data
        """
        with open(self.filename) as f:
            lines = f.readlines()

        self._parse_sections(lines)
        self._parse_entities()

        return {
            "entities": self.entities,
            "sections": self.sections,
        }

    def _parse_sections(self, lines: list[str]) -> None:
        """Parse DXF sections."""

        for line in lines:
            line = line.strip()

            if line == "SECTION":
                pass
            elif line.startswith("$"):
                pass

        self.sections = {}

    def _parse_entities(self) -> None:
        """Parse ENTITIES section."""
        entities_section = self.sections.get("ENTITIES", [])

        i = 0
        while i < len(entities_section):
            line = entities_section[i].strip()

            if line in ["LINE", "CIRCLE", "ARC", "POLYLINE", "TEXT"]:
                entity_type = line
                entity_data = {"type": entity_type}

                i += 1
                while i < len(entities_section):
                    group_code_line = entities_section[i].strip()
                    value_line = entities_section[i + 1].strip() if i + 1 < len(entities_section) else ""

                    try:
                        group_code = int(group_code_line)
                    except ValueError:
                        break

                    self._parse_group_code(entity_data, group_code, value_line)

                    i += 2

                self.entities.append(entity_data)
            else:
                i += 1

    def _parse_group_code(self, entity: dict[str, Any], code: int, value: str) -> None:
        """Parse DXF group code."""
        if code == 8:
            entity["layer"] = value
        elif code == 10:
            entity["x"] = float(value)
        elif code == 20:
            entity["y"] = float(value)
        elif code == 40:
            entity["radius"] = float(value)
        elif code == 1:
            entity["text"] = value

    def to_polygons(self) -> list[Polygon]:
        """Convert DXF to polygon list."""
        polygons: list[Polygon] = []

        for entity in self.entities:
            if entity["type"] == "POLYLINE":
                points = entity.get("points", [])
                if len(points) >= 3:
                    polygon = Polygon([Point2D(p[0], p[1]) for p in points])
                    polygons.append(polygon)

        return polygons


class DXFWriter:
    """DXF writer."""

    def __init__(self, filename: str) -> None:
        """
        Initialize DXF writer.

        Args:
            filename: Output file path
        """
        self.filename = filename
        self.entities: list[str] = []

    def add_line(self, start: Point2D, end: Point2D, layer: str = "0") -> None:
        """Add line entity."""
        self.entities.append(f"0\nLINE\n8\n{layer}\n")
        self.entities.append(f"10\n{start.x}\n20\n{start.y}\n")
        self.entities.append(f"11\n{end.x}\n21\n{end.y}\n")

    def add_circle(self, center: Point2D, radius: float, layer: str = "0") -> None:
        """Add circle entity."""
        self.entities.append(f"0\nCIRCLE\n8\n{layer}\n")
        self.entities.append(f"10\n{center.x}\n20\n{center.y}\n")
        self.entities.append(f"40\n{radius}\n")

    def add_polyline(self, points: list[Point2D], layer: str = "0") -> None:
        """Add polyline entity."""
        self.entities.append(f"0\nPOLYLINE\n8\n{layer}\n")
        for point in points:
            self.entities.append(f"10\n{point.x}\n20\n{point.y}\n")

    def write(self) -> None:
        """Write DXF file."""
        with open(self.filename, "w") as f:
            f.write("0\nSECTION\n9\n$ACADVER\n1\nAC1015\n")
            f.write("0\nENDSEC\n")
            f.write("0\nSECTION\n2\nENTITIES\n")

            for entity in self.entities:
                f.write(entity)

            f.write("0\nENDSEC\n")
            f.write("0\nEOF\n")


class SVGExporter:
    """SVG (Scalable Vector Graphics) exporter."""

    def __init__(self, filename: str, width: float = 800, height: float = 600) -> None:
        """
        Initialize SVG exporter.

        Args:
            filename: Output file path
            width: SVG canvas width
            height: SVG canvas height
        """
        self.filename = filename
        self.width = width
        self.height = height
        self.elements: list[str] = []

    def add_line(self, start: Point2D, end: Point2D, stroke: str = "black", width: float = 1) -> None:
        """Add line to SVG."""
        svg = f'<line x1="{start.x}" y1="{start.y}" x2="{end.x}" y2="{end.y}" '
        svg += f'stroke="{stroke}" stroke-width="{width}" />'
        self.elements.append(svg)

    def add_circle(self, center: Point2D, radius: float, fill: str = "none", stroke: str = "black") -> None:
        """Add circle to SVG."""
        svg = f'<circle cx="{center.x}" cy="{center.y}" r="{radius}" '
        svg += f'fill="{fill}" stroke="{stroke}" />'
        self.elements.append(svg)

    def add_polygon(self, polygon: Polygon, fill: str = "lightblue", stroke: str = "black") -> None:
        """Add polygon to SVG."""
        points_str = " ".join([f"{p.x},{p.y}" for p in polygon.points])
        svg = f'<polygon points="{points_str}" fill="{fill}" stroke="{stroke}" />'
        self.elements.append(svg)

    def add_path(self, points: list[Point2D], fill: str = "none", stroke: str = "black") -> None:
        """Add path to SVG."""
        if not points:
            return

        path_data = f"M {points[0].x} {points[0].y}"
        for p in points[1:]:
            path_data += f" L {p.x} {p.y}"

        svg = f'<path d="{path_data}" fill="{fill}" stroke="{stroke}" />'
        self.elements.append(svg)

    def write(self) -> None:
        """Write SVG file."""
        with open(self.filename, "w") as f:
            f.write(f'<svg width="{self.width}" height="{self.height}" ')
            f.write('xmlns="http://www.w3.org/2000/svg">\n')

            for element in self.elements:
                f.write(f"  {element}\n")

            f.write("</svg>\n")


class STLWriter:
    """STL (Stereolithography) ASCII writer."""

    def __init__(self, filename: str) -> None:
        """
        Initialize STL writer.

        Args:
            filename: Output file path
        """
        self.filename = filename
        self.triangles: list[tuple[Vector3D, Point3D, Point3D, Point3D]] = []

    def add_triangle(self, normal: Vector3D, v1: Point3D, v2: Point3D, v3: Point3D) -> None:
        """
        Add triangle to STL.

        Args:
            normal: Triangle normal
            v1, v2, v3: Triangle vertices
        """
        self.triangles.append((normal, v1, v2, v3))

    def add_solid(self, solid: Solid) -> None:
        """
        Add solid to STL by triangulating faces.

        Args:
            solid: Solid object
        """
        for face in solid.faces:
            if len(face.vertices) < 3:
                continue

            normal = face.normal()

            for i in range(1, len(face.vertices) - 1):
                v0 = face.vertices[0].point
                v1 = face.vertices[i].point
                v2 = face.vertices[i + 1].point

                self.add_triangle(normal, v0, v1, v2)

    def write(self) -> None:
        """Write ASCII STL file."""
        with open(self.filename, "w") as f:
            f.write("solid\n")

            for normal, v1, v2, v3 in self.triangles:
                f.write(f"  facet normal {normal.x} {normal.y} {normal.z}\n")
                f.write("    outer loop\n")
                f.write(f"      vertex {v1.x} {v1.y} {v1.z}\n")
                f.write(f"      vertex {v2.x} {v2.y} {v2.z}\n")
                f.write(f"      vertex {v3.x} {v3.y} {v3.z}\n")
                f.write("    endloop\n")
                f.write("  endfacet\n")

            f.write("endsolid\n")


class STEPWriter:
    """STEP (Standard for the Exchange of Product model data) writer."""

    def __init__(self, filename: str) -> None:
        """
        Initialize STEP writer.

        Args:
            filename: Output file path
        """
        self.filename = filename
        self.entities: dict[int, str] = {}
        self.entity_counter = 1

    def add_point(self, point: Point3D) -> int:
        """
        Add point to STEP file.

        Args:
            point: 3D point

        Returns:
            Entity ID
        """
        eid = self.entity_counter
        self.entity_counter += 1

        self.entities[eid] = f"#{eid} = CARTESIAN_POINT ( 'POINT', ( {point.x}, {point.y}, {point.z} ) ) ;"

        return eid

    def add_line(self, start: Point3D, end: Point3D) -> int:
        """Add line segment."""
        start_id = self.add_point(start)
        end_id = self.add_point(end)

        eid = self.entity_counter
        self.entity_counter += 1

        self.entities[eid] = f"#{eid} = LINE ( 'LINE', #{start_id}, #{end_id} ) ;"

        return eid

    def write(self) -> None:
        """Write STEP file."""
        with open(self.filename, "w") as f:
            f.write("ISO-10303-21 ;\n")
            f.write("HEADER ;\n")
            f.write("FILE_DESCRIPTION ( ( 'CAD Model' ), '2' ) ;\n")
            f.write("FILE_NAME ( 'model.stp', 2024-01-01T00:00:00, ( '' ), ( '' ), '', '', '' ) ;\n")
            f.write("FILE_SCHEMA ( ( 'IFC2X3' ) ) ;\n")
            f.write("ENDSEC ;\n")
            f.write("DATA ;\n")

            for entity in self.entities.values():
                f.write(f"{entity}\n")

            f.write("ENDSEC ;\n")
            f.write("END-ISO-10303-21 ;\n")


def unit_conversion(value: float, from_unit: str, to_unit: str) -> float:
    """
    Convert between drawing units.

    Args:
        value: Value to convert
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted value
    """
    conversions = {
        ("mm", "cm"): 0.1,
        ("mm", "m"): 0.001,
        ("mm", "inch"): 1 / 25.4,
        ("cm", "mm"): 10.0,
        ("cm", "m"): 0.1,
        ("m", "cm"): 10.0,
        ("m", "mm"): 1000.0,
        ("inch", "mm"): 25.4,
    }

    from_norm = from_unit.lower()
    to_norm = to_unit.lower()

    if from_norm == to_norm:
        return value

    key = (from_norm, to_norm)
    if key in conversions:
        return value * conversions[key]

    key_reverse = (to_norm, from_norm)
    if key_reverse in conversions:
        return value / conversions[key_reverse]

    raise CADIOError(f"Cannot convert between {from_unit} and {to_unit}")
