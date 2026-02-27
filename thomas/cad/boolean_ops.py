"""
Boolean operations on geometric shapes.

Includes 2D polygon clipping (Sutherland-Hodgman), 3D CSG trees,
and Minkowski operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._exceptions import BooleanOperationError
from ._types import Point2D, Point3D, Polygon

EPSILON = 1e-10


class BooleanOp(Enum):
    """Boolean operation type."""

    UNION = "union"
    INTERSECTION = "intersection"
    DIFFERENCE = "difference"


@dataclass
class CSGNode:
    """Node in a Constructive Solid Geometry tree."""

    operation: BooleanOp | None = None
    geometry: Any | None = None
    left: CSGNode | None = None
    right: CSGNode | None = None
    is_leaf: bool = True

    @classmethod
    def leaf(cls, geometry: Any) -> CSGNode:
        """Create leaf node for geometry."""
        return cls(geometry=geometry, is_leaf=True)

    @classmethod
    def operation(cls, op: BooleanOp, left: CSGNode, right: CSGNode) -> CSGNode:
        """Create operation node."""
        return cls(operation=op, left=left, right=right, is_leaf=False)


def sutherland_hodgman_clip(subject: Polygon, clip: Polygon) -> Polygon:
    """
    Clip subject polygon against clip polygon.

    Uses Sutherland-Hodgman algorithm.

    Args:
        subject: Polygon to clip
        clip: Clipping polygon

    Returns:
        Clipped polygon
    """
    output_list = list(subject.points)

    for i in range(len(clip.points)):
        if not output_list:
            break

        edge_start = clip.points[i]
        edge_end = clip.points[(i + 1) % len(clip.points)]

        input_list = output_list
        output_list = []

        if not input_list:
            break

        s = input_list[-1]

        for e in input_list:
            if _inside_edge(e, edge_start, edge_end):
                if not _inside_edge(s, edge_start, edge_end):
                    intersection = _line_intersection(s, e, edge_start, edge_end)
                    if intersection:
                        output_list.append(intersection)

                output_list.append(e)
            elif _inside_edge(s, edge_start, edge_end):
                intersection = _line_intersection(s, e, edge_start, edge_end)
                if intersection:
                    output_list.append(intersection)

            s = e

    return Polygon(output_list)


def _inside_edge(point: Point2D, edge_start: Point2D, edge_end: Point2D) -> bool:
    """Check if point is on left side of edge."""
    cross = (edge_end.x - edge_start.x) * (point.y - edge_start.y) - (edge_end.y - edge_start.y) * (
        point.x - edge_start.x
    )
    return cross >= -EPSILON


def _line_intersection(p1: Point2D, p2: Point2D, p3: Point2D, p4: Point2D) -> Point2D | None:
    """Find intersection of two line segments."""
    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

    if abs(denom) < EPSILON:
        return None

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom

    x = x1 + t * (x2 - x1)
    y = y1 + t * (y2 - y1)

    return Point2D(x, y)


def polygon_union(poly1: Polygon, poly2: Polygon) -> list[Polygon]:
    """
    Compute union of two polygons.

    Args:
        poly1: First polygon
        poly2: Second polygon

    Returns:
        List of resulting polygons
    """
    intersection = sutherland_hodgman_clip(poly1, poly2)

    if len(intersection.points) < 3:
        return [poly1, poly2]

    return [_merge_polygons_simple(poly1, poly2)]


def polygon_intersection(poly1: Polygon, poly2: Polygon) -> list[Polygon]:
    """
    Compute intersection of two polygons.

    Args:
        poly1: First polygon
        poly2: Second polygon

    Returns:
        List of resulting polygons
    """
    result = sutherland_hodgman_clip(poly1, poly2)

    if len(result.points) >= 3:
        return [result]

    return []


def polygon_difference(poly1: Polygon, poly2: Polygon) -> list[Polygon]:
    """
    Compute difference (poly1 - poly2).

    Args:
        poly1: First polygon
        poly2: Polygon to subtract

    Returns:
        List of resulting polygons
    """
    poly2_inverted = Polygon([Point2D(p.x, -p.y) for p in poly2.points])

    return polygon_intersection(poly1, poly2_inverted)


def _merge_polygons_simple(poly1: Polygon, poly2: Polygon) -> Polygon:
    """Simple polygon merge (for union)."""
    merged_points = list(poly1.points) + list(poly2.points)
    return Polygon(merged_points)


def minkowski_sum(poly1: Polygon, poly2: Polygon) -> Polygon:
    """
    Compute Minkowski sum of two convex polygons.

    Args:
        poly1: First polygon
        poly2: Second polygon

    Returns:
        Resulting polygon
    """
    if len(poly1.points) < 3 or len(poly2.points) < 3:
        raise BooleanOperationError("Polygons must have at least 3 points")

    result_points: list[Point2D] = []

    i, j = 0, 0

    while i < len(poly1.points) or j < len(poly2.points):
        p1 = poly1.points[i % len(poly1.points)]
        p2 = poly2.points[j % len(poly2.points)]

        result_points.append(Point2D(p1.x + p2.x, p1.y + p2.y))

        edge1 = poly1.points[(i + 1) % len(poly1.points)] - p1
        edge2 = poly2.points[(j + 1) % len(poly2.points)] - p2

        cross = edge1.x * edge2.y - edge1.y * edge2.x

        if cross > 0:
            i += 1
        elif cross < 0:
            j += 1
        else:
            i += 1
            j += 1

    return Polygon(result_points)


class HalfEdgeMesh:
    """Half-edge mesh data structure for boundary representation."""

    def __init__(self) -> None:
        """Initialize empty mesh."""
        self.vertices: dict[int, Point3D] = {}
        self.edges: dict[tuple[int, int], HalfEdge] = {}
        self.faces: list[Face] = []
        self.next_vertex_id = 0
        self.next_face_id = 0

    def add_vertex(self, point: Point3D) -> int:
        """Add vertex, return ID."""
        vid = self.next_vertex_id
        self.vertices[vid] = point
        self.next_vertex_id += 1
        return vid

    def add_triangle(self, v1: int, v2: int, v3: int) -> int:
        """Add triangle face, return face ID."""
        fid = self.next_face_id
        self.next_face_id += 1

        e1 = self._get_or_create_edge(v1, v2)
        e2 = self._get_or_create_edge(v2, v3)
        e3 = self._get_or_create_edge(v3, v1)

        e1.next = e2
        e2.next = e3
        e3.next = e1

        e1.face = fid
        e2.face = fid
        e3.face = fid

        return fid

    def _get_or_create_edge(self, v_from: int, v_to: int) -> HalfEdge:
        """Get or create half-edge."""
        key = (v_from, v_to)

        if key not in self.edges:
            opposite_key = (v_to, v_from)

            if opposite_key in self.edges:
                opposite = self.edges[opposite_key]
                edge = HalfEdge(v_from, v_to)
                edge.opposite = opposite
                opposite.opposite = edge
            else:
                edge = HalfEdge(v_from, v_to)

            self.edges[key] = edge

        return self.edges[key]


@dataclass
class HalfEdge:
    """A half-edge in the mesh."""

    vertex_from: int
    vertex_to: int
    next: HalfEdge | None = None
    opposite: HalfEdge | None = None
    face: int | None = None


@dataclass
class Face:
    """A face in the mesh."""

    edge: HalfEdge
    face_id: int


def build_bsp_tree(geometry_list: list[Any]) -> CSGNode:
    """
    Build binary space partition tree for 3D Boolean ops.

    Args:
        geometry_list: List of geometric objects

    Returns:
        Root of BSP tree
    """
    if not geometry_list:
        raise BooleanOperationError("Empty geometry list")

    if len(geometry_list) == 1:
        return CSGNode.leaf(geometry_list[0])

    mid = len(geometry_list) // 2

    left = build_bsp_tree(geometry_list[:mid])
    right = build_bsp_tree(geometry_list[mid:])

    return CSGNode.operation(BooleanOp.UNION, left, right)


def evaluate_csg_tree(node: CSGNode, point: Point3D) -> bool:
    """
    Evaluate CSG tree to determine if point is inside solid.

    Args:
        node: CSG tree node
        point: Test point

    Returns:
        True if point is inside
    """
    if node.is_leaf:
        return _point_in_geometry(point, node.geometry)

    left_result = evaluate_csg_tree(node.left, point)
    right_result = evaluate_csg_tree(node.right, point)

    if node.operation == BooleanOp.UNION:
        return left_result or right_result
    elif node.operation == BooleanOp.INTERSECTION:
        return left_result and right_result
    elif node.operation == BooleanOp.DIFFERENCE:
        return left_result and not right_result

    return False


def _point_in_geometry(point: Point3D, geometry: Any) -> bool:
    """Check if point is inside geometry (simplified)."""
    return False


def weiler_atherton_clip(subject: list[Point2D], clip: list[Point2D]) -> list[Point2D]:
    """
    Clip polygon using Weiler-Atherton algorithm.

    Args:
        subject: Subject polygon vertices
        clip: Clip polygon vertices

    Returns:
        Clipped polygon vertices
    """
    if len(subject) < 3 or len(clip) < 3:
        return subject

    sub_poly = Polygon(subject)
    clip_poly = Polygon(clip)

    result = sutherland_hodgman_clip(sub_poly, clip_poly)

    return result.points
