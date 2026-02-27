"""
2D geometry operations and algorithms.

Includes line-circle intersection, point-in-polygon testing, convex hull
computation, polygon offsetting, and other 2D geometric utilities.
"""

from __future__ import annotations

import math

from ._exceptions import GeometryError
from ._types import Arc, Circle, Line, Point2D, Polygon, Vector2D

EPSILON = 1e-10


def line_line_intersection(line1: Line, line2: Line) -> Point2D | None:
    """
    Find intersection point of two line segments.

    Uses parametric line representation and solves the resulting linear system.

    Args:
        line1: First line segment
        line2: Second line segment

    Returns:
        Intersection point if found, None if parallel or non-intersecting
    """
    p1, p2 = line1.start, line1.end
    p3, p4 = line2.start, line2.end

    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

    if abs(denom) < EPSILON:
        return None

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 <= t <= 1 and 0 <= u <= 1:
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return Point2D(x, y)

    return None


def line_circle_intersection(line: Line, circle: Circle) -> list[Point2D]:
    """
    Find intersection points between line segment and circle.

    Solves the quadratic equation resulting from substituting the line
    parametric equation into the circle equation.

    Args:
        line: Line segment
        circle: Circle

    Returns:
        List of intersection points (0, 1, or 2)
    """
    x1, y1 = line.start.x, line.start.y
    x2, y2 = line.end.x, line.end.y
    cx, cy = circle.center.x, circle.center.y
    r = circle.radius

    dx = x2 - x1
    dy = y2 - y1
    fx = x1 - cx
    fy = y1 - cy

    a = dx * dx + dy * dy
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r

    discriminant = b * b - 4 * a * c

    if discriminant < 0:
        return []

    if abs(a) < EPSILON:
        return []

    sqrt_disc = math.sqrt(discriminant)
    t1 = (-b - sqrt_disc) / (2 * a)
    t2 = (-b + sqrt_disc) / (2 * a)

    points = []
    for t in [t1, t2]:
        if 0 <= t <= 1:
            x = x1 + t * dx
            y = y1 + t * dy
            points.append(Point2D(x, y))

    return points


def circle_circle_intersection(circle1: Circle, circle2: Circle) -> list[Point2D]:
    """
    Find intersection points between two circles.

    Uses distance formula and solves for intersection points.

    Args:
        circle1: First circle
        circle2: Second circle

    Returns:
        List of intersection points (0, 1, or 2)
    """
    d = circle1.center.distance_to(circle2.center)
    r1 = circle1.radius
    r2 = circle2.radius

    if d > r1 + r2 or d < abs(r1 - r2) or d < EPSILON:
        return []

    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(r1 * r1 - a * a)

    x2 = circle1.center.x + a * (circle2.center.x - circle1.center.x) / d
    y2 = circle1.center.y + a * (circle2.center.y - circle1.center.y) / d

    px1 = x2 + h * (circle2.center.y - circle1.center.y) / d
    py1 = y2 - h * (circle2.center.x - circle1.center.x) / d

    px2 = x2 - h * (circle2.center.y - circle1.center.y) / d
    py2 = y2 + h * (circle2.center.x - circle1.center.x) / d

    points = [Point2D(px1, py1), Point2D(px2, py2)]

    if abs(px1 - px2) < EPSILON and abs(py1 - py2) < EPSILON:
        return [points[0]]

    return points


def point_on_line_distance(point: Point2D, line: Line) -> float:
    """
    Compute perpendicular distance from point to line.

    Uses the formula: distance = |ax + by + c| / sqrt(a^2 + b^2)

    Args:
        point: Test point
        line: Line segment

    Returns:
        Perpendicular distance
    """
    x0, y0 = point.x, point.y
    x1, y1 = line.start.x, line.start.y
    x2, y2 = line.end.x, line.end.y

    num = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denom = math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)

    if denom < EPSILON:
        return point.distance_to(line.start)

    return num / denom


def point_on_line(point: Point2D, line: Line, tolerance: float = EPSILON) -> bool:
    """
    Test if point lies on line segment within tolerance.

    Args:
        point: Test point
        line: Line segment
        tolerance: Distance tolerance

    Returns:
        True if point is on the line
    """
    dist = point_on_line_distance(point, line)
    if dist > tolerance:
        return False

    t = (
        (point.x - line.start.x) * (line.end.x - line.start.x) + (point.y - line.start.y) * (line.end.y - line.start.y)
    ) / (line.length() ** 2)

    return -tolerance <= t <= 1 + tolerance


def angle_between_lines(line1: Line, line2: Line) -> float:
    """
    Compute angle between two lines in radians.

    Args:
        line1: First line
        line2: Second line

    Returns:
        Angle in radians (0 to pi/2)
    """
    dir1 = line1.direction()
    dir2 = line2.direction()

    cos_angle = dir1.dot(dir2)
    cos_angle = max(-1.0, min(1.0, cos_angle))

    angle = math.acos(cos_angle)
    return min(angle, math.pi - angle)


def polygon_area(polygon: Polygon) -> float:
    """
    Compute polygon area using Shoelace formula.

    Args:
        polygon: Input polygon

    Returns:
        Area (always positive)
    """
    if len(polygon.points) < 3:
        return 0.0

    area = 0.0
    for i in range(len(polygon.points)):
        j = (i + 1) % len(polygon.points)
        area += polygon.points[i].x * polygon.points[j].y
        area -= polygon.points[j].x * polygon.points[i].y

    return abs(area) / 2.0


def polygon_centroid(polygon: Polygon) -> Point2D:
    """
    Compute polygon centroid.

    Uses weighted average for accurate centroid calculation.

    Args:
        polygon: Input polygon

    Returns:
        Centroid point
    """
    if len(polygon.points) == 0:
        return Point2D(0.0, 0.0)

    if len(polygon.points) == 1:
        return polygon.points[0]

    cx, cy, area_sum = 0.0, 0.0, 0.0

    for i in range(len(polygon.points)):
        j = (i + 1) % len(polygon.points)
        p1 = polygon.points[i]
        p2 = polygon.points[j]

        cross = p1.x * p2.y - p2.x * p1.y
        cx += (p1.x + p2.x) * cross
        cy += (p1.y + p2.y) * cross
        area_sum += cross

    if abs(area_sum) < EPSILON:
        cx = sum(p.x for p in polygon.points) / len(polygon.points)
        cy = sum(p.y for p in polygon.points) / len(polygon.points)
        return Point2D(cx, cy)

    return Point2D(cx / (3.0 * area_sum), cy / (3.0 * area_sum))


def convex_hull(points: list[Point2D]) -> list[Point2D]:
    """
    Compute convex hull using Graham scan algorithm.

    Args:
        points: Input points

    Returns:
        Points on the convex hull in counterclockwise order
    """
    if len(points) <= 2:
        return sorted(points, key=lambda p: (p.x, p.y))

    # Remove duplicates by comparing coordinates
    unique_points = []
    seen = set()
    for p in points:
        key = (round(p.x, 10), round(p.y, 10))
        if key not in seen:
            unique_points.append(p)
            seen.add(key)

    points = sorted(unique_points, key=lambda p: (p.x, p.y))

    def cross(o: Point2D, a: Point2D, b: Point2D) -> float:
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def point_in_polygon(point: Point2D, polygon: Polygon) -> bool:
    """
    Test if point is inside polygon using ray casting.

    Casts a ray from the point to infinity and counts boundary crossings.

    Args:
        point: Test point
        polygon: Polygon

    Returns:
        True if point is inside
    """
    if len(polygon.points) < 3:
        return False

    inside = False
    x, y = point.x, point.y
    p1x, p1y = polygon.points[0].x, polygon.points[0].y

    for i in range(1, len(polygon.points) + 1):
        p2x, p2y = polygon.points[i % len(polygon.points)].x, polygon.points[i % len(polygon.points)].y

        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside

        p1x, p1y = p2x, p2y

    return inside


def offset_polygon(polygon: Polygon, offset: float, resolution: int = 32) -> Polygon:
    """
    Create offset polygon (parallel offset).

    Offsets each edge outward and joins with arc fillets.

    Args:
        polygon: Input polygon
        offset: Offset distance (positive = outward)
        resolution: Arc resolution for corners

    Returns:
        Offset polygon
    """
    if len(polygon.points) < 3:
        return polygon

    offset_points: list[Point2D] = []

    for i in range(len(polygon.points)):
        p1 = polygon.points[i]
        p0 = polygon.points[(i - 1) % len(polygon.points)]
        p2 = polygon.points[(i + 1) % len(polygon.points)]

        edge1 = p1 - p0
        edge2 = p2 - p1

        if edge1.magnitude() < EPSILON or edge2.magnitude() < EPSILON:
            continue

        edge1 = edge1.normalize()
        edge2 = edge2.normalize()

        perp1 = edge1.perpendicular() * offset
        perp2 = edge2.perpendicular() * offset

        pt1 = p1 + perp1
        pt2 = p1 + perp2

        if abs(perp1.x * perp2.y - perp1.y * perp2.x) > EPSILON:
            denom = (pt2.x - pt1.x) * (edge1.y) - (pt2.y - pt1.y) * (-edge1.x)
            if abs(denom) > EPSILON:
                t = ((p1.x - pt1.x) * edge1.y - (p1.y - pt1.y) * (-edge1.x)) / denom
                offset_points.append(Point2D(pt1.x + t * (pt2.x - pt1.x), pt1.y + t * (pt2.y - pt1.y)))
            else:
                offset_points.append(pt1)
        else:
            offset_points.append(pt1)

    return Polygon(offset_points)


def fillet_lines(line1: Line, line2: Line, radius: float) -> tuple[Line, Line, Arc]:
    """
    Create fillet (rounded corner) between two lines.

    Generates two shortened lines and connecting arc.

    Args:
        line1: First line
        line2: Second line
        radius: Fillet radius

    Returns:
        Tuple of (shortened_line1, shortened_line2, arc)
    """
    dir1 = line1.direction()
    dir2 = line2.direction()

    cross = dir1.x * dir2.y - dir1.y * dir2.x

    if abs(cross) < EPSILON:
        raise GeometryError("Lines are parallel, cannot fillet")

    angle = math.atan2(dir2.y, dir2.x) - math.atan2(dir1.y, dir1.x)
    if angle < 0:
        angle += 2 * math.pi

    dist_along_1 = radius / math.tan(angle / 2)

    new_end_1 = line1.end + dir1 * (-dist_along_1) if dist_along_1 > 0 else line1.end
    new_start_2 = line2.start + dir2 * (dist_along_1) if dist_along_1 > 0 else line2.start

    corner = line1.end

    offset_vec = Vector2D(-dir1.y, dir1.x).normalize() * radius

    arc_center = corner + offset_vec

    start_angle = math.atan2((new_end_1.y - arc_center.y), (new_end_1.x - arc_center.x))
    end_angle = math.atan2((new_start_2.y - arc_center.y), (new_start_2.x - arc_center.x))

    arc_obj = Arc(arc_center, radius, start_angle, end_angle)

    return Line(line1.start, new_end_1), Line(new_start_2, line2.end), arc_obj


def chamfer_corner(line1: Line, line2: Line, size: float) -> tuple[Line, Line, Line]:
    """
    Create chamfer (beveled corner) between two lines.

    Args:
        line1: First line
        line2: Second line
        size: Chamfer size

    Returns:
        Tuple of (shortened_line1, chamfer_line, shortened_line2)
    """
    dir1 = line1.direction()
    dir2 = line2.direction()

    pt1 = line1.end + dir1 * (-size)
    pt2 = line2.start + dir2 * (size)

    chamfer_line = Line(pt1, pt2)

    return Line(line1.start, pt1), chamfer_line, Line(pt2, line2.end)


def triangle_area(p1: Point2D, p2: Point2D, p3: Point2D) -> float:
    """
    Compute triangle area.

    Args:
        p1, p2, p3: Triangle vertices

    Returns:
        Area
    """
    return abs((p2.x - p1.x) * (p3.y - p1.y) - (p3.x - p1.x) * (p2.y - p1.y)) / 2.0


def minimum_distance(geom1: object, geom2: object) -> float:
    """
    Compute minimum distance between two geometric objects.

    Supports Point2D, Line, Circle, Polygon.

    Args:
        geom1: First geometry
        geom2: Second geometry

    Returns:
        Minimum distance
    """
    if isinstance(geom1, Point2D) and isinstance(geom2, Point2D):
        return geom1.distance_to(geom2)

    if isinstance(geom1, Point2D) and isinstance(geom2, Line):
        return point_on_line_distance(geom1, geom2)

    if isinstance(geom1, Point2D) and isinstance(geom2, Circle):
        return abs(geom1.distance_to(geom2.center) - geom2.radius)

    raise GeometryError(f"Distance not implemented for {type(geom1).__name__}, {type(geom2).__name__}")
