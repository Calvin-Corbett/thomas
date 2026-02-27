"""
Dimensioning and annotation system.

Supports linear, angular, radial dimensions, tolerance annotations,
and GD&T (Geometric Dimensioning & Tolerancing) symbols.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._types import Layer, Point2D, Tolerance, Vector2D


class DimensionType(Enum):
    """Types of dimensions."""

    LINEAR = "linear"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    ALIGNED = "aligned"
    ANGULAR = "angular"
    RADIAL = "radial"
    DIAMETER = "diameter"
    ORDINATE = "ordinate"


class ToleranceType(Enum):
    """Types of tolerance specifications."""

    BILATERAL = "bilateral"
    UNILATERAL_UPPER = "unilateral_upper"
    UNILATERAL_LOWER = "unilateral_lower"
    LIMIT = "limit"
    SYMMETRIC = "symmetric"


class GDTSymbol(Enum):
    """GD&T symbols."""

    STRAIGHTNESS = "straightness"
    FLATNESS = "flatness"
    CIRCULARITY = "circularity"
    CYLINDRICITY = "cylindricity"
    PERPENDICULAR = "perpendicular"
    PARALLEL = "parallel"
    ANGULARITY = "angularity"
    POSITION = "position"
    CONCENTRICITY = "concentricity"
    SYMMETRY = "symmetry"
    RUNOUT = "runout"
    PROFILE = "profile"


@dataclass
class LinearDimension:
    """Linear dimension (horizontal, vertical, or aligned)."""

    dimension_type: DimensionType
    start_point: Point2D
    end_point: Point2D
    value: float
    dimension_line_distance: float = 10.0
    tolerance: Tolerance | None = None
    layer: Layer | None = None

    def offset_distance(self) -> float:
        """Distance between point and dimension line."""
        return self.dimension_line_distance

    def angle(self) -> float:
        """Angle of dimension line (in radians)."""
        if self.dimension_type == DimensionType.HORIZONTAL:
            return 0.0
        elif self.dimension_type == DimensionType.VERTICAL:
            return 3.14159 / 2
        else:
            dx = self.end_point.x - self.start_point.x
            dy = self.end_point.y - self.start_point.y
            return __import__("math").atan2(dy, dx)

    def leader_start(self) -> Point2D:
        """Get leader line start point."""
        direction = self._perpendicular_direction()
        offset = self.offset_distance()
        return self.start_point + direction * offset

    def leader_end(self) -> Point2D:
        """Get leader line end point."""
        direction = self._perpendicular_direction()
        offset = self.offset_distance()
        return self.end_point + direction * offset

    def _perpendicular_direction(self) -> Vector2D:
        """Get perpendicular direction to dimension line."""
        dx = self.end_point.x - self.start_point.x
        dy = self.end_point.y - self.start_point.y
        length = __import__("math").sqrt(dx * dx + dy * dy)

        if length < 1e-10:
            return Vector2D(0, 1)

        perp = Vector2D(-dy / length, dx / length)
        return perp

    def __repr__(self) -> str:
        return f"LinearDimension({self.value}, {self.dimension_type.value})"


@dataclass
class AngularDimension:
    """Angular dimension."""

    vertex: Point2D
    ray1_direction: Vector2D
    ray2_direction: Vector2D
    value: float
    arc_radius: float = 15.0
    tolerance: Tolerance | None = None
    layer: Layer | None = None

    def arc_center(self) -> Point2D:
        """Center of arc for dimension."""
        return self.vertex

    def arc_radius_value(self) -> float:
        """Radius of arc."""
        return self.arc_radius

    def __repr__(self) -> str:
        return f"AngularDimension({self.value}°)"


@dataclass
class RadialDimension:
    """Radial dimension (radius or diameter)."""

    center: Point2D
    point_on_circle: Point2D
    radius: float
    is_diameter: bool = False
    tolerance: Tolerance | None = None
    layer: Layer | None = None

    def dimension_value(self) -> float:
        """Get dimension value (radius or diameter)."""
        return self.radius * 2 if self.is_diameter else self.radius

    def dimension_type_str(self) -> str:
        """Get dimension type string."""
        return "Diameter" if self.is_diameter else "Radius"

    def __repr__(self) -> str:
        dim_type = "Ø" if self.is_diameter else "R"
        return f"{dim_type}{self.radius}"


@dataclass
class OrdinateDimension:
    """Ordinate dimension (single-axis reference)."""

    reference_point: Point2D
    measured_points: list[Point2D]
    is_vertical: bool = True
    tolerance: Tolerance | None = None
    layer: Layer | None = None

    def values(self) -> list[float]:
        """Get ordinate values."""
        if self.is_vertical:
            return [p.y - self.reference_point.y for p in self.measured_points]
        else:
            return [p.x - self.reference_point.x for p in self.measured_points]

    def __repr__(self) -> str:
        axis = "Y" if self.is_vertical else "X"
        return f"OrdinateDimension({axis})"


@dataclass
class GDTAnnotation:
    """GD&T (Geometric Dimensioning & Tolerancing) annotation."""

    symbol: GDTSymbol
    value: float
    datum_reference: str | None = None
    position: Point2D | None = None
    layer: Layer | None = None

    def __repr__(self) -> str:
        datum_str = f", {self.datum_reference}" if self.datum_reference else ""
        return f"GDT({self.symbol.value}{datum_str}): {self.value}"


class DimensionStyle:
    """Dimension style (fonts, sizes, formats)."""

    def __init__(
        self,
        name: str = "Standard",
        text_height: float = 2.5,
        arrow_size: float = 3.0,
        gap: float = 1.0,
        decimal_places: int = 2,
        prefix: str = "",
        suffix: str = "",
    ) -> None:
        """
        Initialize dimension style.

        Args:
            name: Style name
            text_height: Height of dimension text
            arrow_size: Size of dimension arrows
            gap: Gap between text and dimension line
            decimal_places: Decimal places for values
            prefix: Text prefix (e.g., "Ø" for diameter)
            suffix: Text suffix (e.g., "mm")
        """
        self.name = name
        self.text_height = text_height
        self.arrow_size = arrow_size
        self.gap = gap
        self.decimal_places = decimal_places
        self.prefix = prefix
        self.suffix = suffix

    def format_value(self, value: float) -> str:
        """Format numeric value according to style."""
        format_str = f"{{:.{self.decimal_places}f}}"
        return f"{self.prefix}{format_str.format(value)}{self.suffix}"

    def __repr__(self) -> str:
        return f"DimensionStyle('{self.name}')"


class DimensionPlacement:
    """Helper for dimension placement and leader routing."""

    @staticmethod
    def compute_leader_path(
        dimension_point: Point2D, text_position: Point2D, obstacles: list[tuple] = None
    ) -> list[Point2D]:
        """
        Compute dimension leader path (with possible obstacles).

        Args:
            dimension_point: Point being dimensioned
            text_position: Position of dimension text
            obstacles: List of (x, y, width, height) obstacles

        Returns:
            List of points forming leader path
        """
        obstacles = obstacles or []

        path = [dimension_point]

        dx = text_position.x - dimension_point.x
        dy = text_position.y - dimension_point.y

        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return path

        intermediate = Point2D(dimension_point.x + dx * 0.3, dimension_point.y)
        path.append(intermediate)

        path.append(text_position)

        return path

    @staticmethod
    def auto_position_text(
        dimension_bbox: tuple, dimension_line_point: Point2D, preferred_offset: float = 10.0
    ) -> Point2D:
        """
        Auto-position dimension text.

        Args:
            dimension_bbox: (x, y, width, height) of dimension line area
            dimension_line_point: Point on dimension line
            preferred_offset: Preferred offset from dimension line

        Returns:
            Text position
        """
        return Point2D(dimension_line_point.x, dimension_line_point.y + preferred_offset)


def create_standard_styles() -> dict[str, DimensionStyle]:
    """Create standard dimension styles."""
    return {
        "ANSI": DimensionStyle(name="ANSI", text_height=2.5, arrow_size=3.0, suffix='"', decimal_places=3),
        "ISO": DimensionStyle(name="ISO", text_height=3.5, arrow_size=4.0, suffix=" mm", decimal_places=1),
        "Metric": DimensionStyle(name="Metric", text_height=3.5, suffix=" mm", decimal_places=1),
        "Imperial": DimensionStyle(name="Imperial", suffix='"', decimal_places=2),
    }


def tolerance_from_limit(upper: float, lower: float) -> Tolerance:
    """Create tolerance from limit values."""
    nominal = (upper + lower) / 2
    return Tolerance(value=nominal, bilateral=False, upper=upper - nominal, lower=lower - nominal)


def tolerance_from_bilateral(nominal: float, deviation: float) -> Tolerance:
    """Create bilateral tolerance."""
    return Tolerance(value=nominal, bilateral=True)
