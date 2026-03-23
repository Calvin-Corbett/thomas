"""
CAD (Computer-Aided Design) Engine.

A comprehensive geometric modeling library supporting 2D/3D geometry, curves,
surfaces, constraints, and CAD file I/O.
"""

from ._exceptions import (
    CADError,
    ConstraintError,
    GeometryError,
)
from ._exceptions import (
    IOError as CADIOError,
)
from ._types import (
    Arc,
    BezierCurve,
    BSplineCurve,
    Circle,
    Dimension,
    DrawingUnit,
    Edge,
    Ellipse,
    Face,
    Layer,
    Line,
    Material,
    NURBSSurface,
    Point2D,
    Point3D,
    Polygon,
    Polyline,
    Solid,
    Tolerance,
    Vector2D,
    Vector3D,
    Vertex,
)

__version__ = "1.0.0"
__all__ = [
    "Point2D",
    "Point3D",
    "Vector2D",
    "Vector3D",
    "Line",
    "Arc",
    "Circle",
    "Ellipse",
    "Polyline",
    "Polygon",
    "BSplineCurve",
    "BezierCurve",
    "NURBSSurface",
    "Solid",
    "Face",
    "Edge",
    "Vertex",
    "Layer",
    "DrawingUnit",
    "Dimension",
    "Tolerance",
    "Material",
    "CADError",
    "GeometryError",
    "ConstraintError",
    "CADIOError",
]
