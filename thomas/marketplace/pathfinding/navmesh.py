"""
Navigation mesh pathfinding algorithms.

This module implements polygon-based navigation meshes, funnel algorithm for string-pulling,
and point-in-polygon testing.
"""

import math
import time
from collections import deque

from thomas.marketplace.pathfinding._types import (
    NavigationMesh,
    NavMeshPolygon,
    Obstacle,
    Path,
    PathResult,
    Portal,
)


def build_navmesh(
    obstacles: list[Obstacle],
    mesh_width: float = 100.0,
    mesh_height: float = 100.0,
    cell_size: float = 10.0,
) -> NavigationMesh:
    """
    Build a navigation mesh from a list of obstacles.

    Uses a grid-based approach to generate walkable polygons.

    Args:
        obstacles: List of rectangular obstacles.
        mesh_width: Width of the mesh area.
        mesh_height: Height of the mesh area.
        cell_size: Size of grid cells for mesh generation.

    Returns:
        A NavigationMesh covering the walkable area.
    """
    navmesh = NavigationMesh()
    polygon_id = 0
    grid_width = int(mesh_width / cell_size)
    grid_height = int(mesh_height / cell_size)

    visited: set[tuple[int, int]] = set()

    for y in range(grid_height):
        for x in range(grid_width):
            if (x, y) in visited:
                continue

            cell_x = x * cell_size
            cell_y = y * cell_size

            walkable = True
            for obs in obstacles:
                if not (
                    cell_x + cell_size < obs.x1 or cell_x > obs.x2 or cell_y + cell_size < obs.y1 or cell_y > obs.y2
                ):
                    walkable = False
                    break

            if walkable:
                width = 1
                while x + width < grid_width and (x + width, y) not in visited:
                    next_x = (x + width) * cell_size
                    next_y = y * cell_size
                    walkable_next = True
                    for obs in obstacles:
                        if not (
                            next_x + cell_size < obs.x1
                            or next_x > obs.x2
                            or next_y + cell_size < obs.y1
                            or next_y > obs.y2
                        ):
                            walkable_next = False
                            break
                    if walkable_next:
                        width += 1
                    else:
                        break

                vertices = (
                    (cell_x, cell_y),
                    (cell_x + width * cell_size, cell_y),
                    (cell_x + width * cell_size, cell_y + cell_size),
                    (cell_x, cell_y + cell_size),
                )
                center = (
                    (vertices[0][0] + vertices[2][0]) / 2,
                    (vertices[0][1] + vertices[2][1]) / 2,
                )

                polygon = NavMeshPolygon(
                    id=polygon_id,
                    vertices=vertices,
                    center=center,
                )
                navmesh.polygons[polygon_id] = polygon

                for i in range(x, x + width):
                    visited.add((i, y))

                polygon_id += 1

    _build_navmesh_connections(navmesh)
    return navmesh


def _build_navmesh_connections(navmesh: NavigationMesh) -> None:
    """Build connections between adjacent polygons."""
    portal_id = 0

    for poly1_id, poly1 in navmesh.polygons.items():
        for poly2_id, poly2 in navmesh.polygons.items():
            if poly1_id >= poly2_id:
                continue

            edge1 = _find_shared_edge(poly1, poly2)
            if edge1 is not None:
                p1, p2 = edge1
                portal = Portal(
                    id=portal_id,
                    from_poly=poly1_id,
                    to_poly=poly2_id,
                    p1=p1,
                    p2=p2,
                )
                navmesh.portals.append(portal)
                portal_id += 1

                poly1.neighbors.add(poly2_id)
                poly2.neighbors.add(poly1_id)

                reverse_portal = Portal(
                    id=portal_id,
                    from_poly=poly2_id,
                    to_poly=poly1_id,
                    p1=p2,
                    p2=p1,
                )
                navmesh.portals.append(reverse_portal)
                portal_id += 1


def _find_shared_edge(
    poly1: NavMeshPolygon, poly2: NavMeshPolygon
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Find shared edge between two polygons."""
    for i in range(len(poly1.vertices)):
        v1_start = poly1.vertices[i]
        v1_end = poly1.vertices[(i + 1) % len(poly1.vertices)]

        for j in range(len(poly2.vertices)):
            v2_start = poly2.vertices[j]
            v2_end = poly2.vertices[(j + 1) % len(poly2.vertices)]

            if (v1_start == v2_end and v1_end == v2_start) or (v1_start == v2_start and v1_end == v2_end):
                return (v1_start, v1_end)

    return None


def find_path_navmesh(
    navmesh: NavigationMesh,
    start_x: float,
    start_y: float,
    goal_x: float,
    goal_y: float,
) -> PathResult:
    """
    Find path on navigation mesh from start to goal.

    Uses polygon graph search followed by funnel algorithm.

    Args:
        navmesh: The navigation mesh.
        start_x: Start X coordinate.
        start_y: Start Y coordinate.
        goal_x: Goal X coordinate.
        goal_y: Goal Y coordinate.

    Returns:
        PathResult containing the smoothed path.
    """
    start_time = time.time()

    start_poly = navmesh.get_containing_polygon(start_x, start_y)
    goal_poly = navmesh.get_containing_polygon(goal_x, goal_y)

    if start_poly is None or goal_poly is None:
        return PathResult(found=False)

    poly_path = _find_polygon_path(navmesh, start_poly, goal_poly)

    if not poly_path:
        return PathResult(found=False)

    waypoints: list[tuple[float, float]] = [(start_x, start_y)]

    for i in range(len(poly_path) - 1):
        from_poly_id = poly_path[i]
        to_poly_id = poly_path[i + 1]

        for portal in navmesh.portals:
            if portal.from_poly == from_poly_id and portal.to_poly == to_poly_id:
                waypoints.append(portal.midpoint())
                break

    waypoints.append((goal_x, goal_y))

    smoothed = funnel_algorithm(waypoints)

    cost = sum(
        math.sqrt((smoothed[i][0] - smoothed[i - 1][0]) ** 2 + (smoothed[i][1] - smoothed[i - 1][1]) ** 2)
        for i in range(1, len(smoothed))
    )

    path_nodes = tuple(f"{x},{y}" for x, y in smoothed)
    path = Path(path_nodes, cost)

    return PathResult(
        found=True,
        path=path,
        cost=cost,
        nodes_expanded=len(poly_path),
        execution_time=time.time() - start_time,
    )


def _find_polygon_path(
    navmesh: NavigationMesh,
    start_poly: int,
    goal_poly: int,
) -> list[int]:
    """Find path through polygon graph."""
    if start_poly == goal_poly:
        return [start_poly]

    queue = deque([(start_poly, [start_poly])])
    visited = {start_poly}

    while queue:
        poly_id, path = queue.popleft()

        if poly_id == goal_poly:
            return path

        if poly_id not in navmesh.polygons:
            continue

        polygon = navmesh.polygons[poly_id]
        for neighbor_id in polygon.neighbors:
            if neighbor_id not in visited:
                visited.add(neighbor_id)
                queue.append((neighbor_id, path + [neighbor_id]))

    return []


def funnel_algorithm(
    waypoints: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    Apply funnel algorithm for string-pulling on waypoints.

    Removes unnecessary waypoints by straightening the path.

    Args:
        waypoints: List of waypoints forming a path.

    Returns:
        Smoothed path with unnecessary waypoints removed.
    """
    if len(waypoints) <= 2:
        return waypoints

    path: list[tuple[float, float]] = [waypoints[0]]
    left = waypoints[0]
    right = waypoints[0]
    left_idx = 0
    right_idx = 0

    for i in range(1, len(waypoints)):
        current = waypoints[i]

        if left_idx + 1 == right_idx:
            left = waypoints[left_idx]
            right = waypoints[right_idx]
            left_idx = i - 1
            right_idx = i
        else:
            left_cross = _cross_product(
                left,
                right,
                current,
            )
            right_cross = _cross_product(
                right,
                left,
                current,
            )

            if left_cross > 0:
                left = current
                left_idx = i
            elif right_cross > 0:
                right = current
                right_idx = i

        if i < len(waypoints) - 1:
            next_wp = waypoints[i + 1]
            if _can_reach(left, right, next_wp):
                path.append(current)

    path.append(waypoints[-1])
    return path


def _cross_product(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> float:
    """Calculate cross product to determine turn direction."""
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])


def _can_reach(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> bool:
    """Check if line segment from p1 to p2 can reach p3."""
    cross = _cross_product(p1, p2, p3)
    return cross < 0


def _point_in_polygon(
    x: float,
    y: float,
    polygon: NavMeshPolygon,
) -> bool:
    """Check if point is inside polygon using ray casting."""
    return polygon.contains_point(x, y)


def closest_point_on_navmesh(
    navmesh: NavigationMesh,
    x: float,
    y: float,
) -> tuple[float, float] | None:
    """
    Find closest point on navigation mesh to given point.

    Args:
        navmesh: The navigation mesh.
        x: X coordinate.
        y: Y coordinate.

    Returns:
        Closest point on mesh, or None if no mesh.
    """
    if not navmesh.polygons:
        return None

    min_dist = float("inf")
    closest_point = None

    for polygon in navmesh.polygons.values():
        dist = polygon.distance_to_point(x, y)
        if dist < min_dist:
            min_dist = dist
            closest_point = polygon.closest_point_on_edge(x, y)

    return closest_point


def expand_navmesh_for_agent(
    navmesh: NavigationMesh,
    agent_radius: float,
) -> NavigationMesh:
    """
    Expand navigation mesh to account for agent radius.

    Creates new boundaries that maintain minimum clearance.

    Args:
        navmesh: The original navigation mesh.
        agent_radius: Radius of the agent.

    Returns:
        Expanded NavigationMesh.
    """
    expanded = NavigationMesh(agent_radius=agent_radius)

    for poly_id, polygon in navmesh.polygons.items():
        expanded_vertices = _expand_polygon(polygon.vertices, agent_radius)
        if expanded_vertices:
            cx = sum(v[0] for v in expanded_vertices) / len(expanded_vertices)
            cy = sum(v[1] for v in expanded_vertices) / len(expanded_vertices)
            expanded_polygon = NavMeshPolygon(
                id=poly_id,
                vertices=tuple(expanded_vertices),
                center=(cx, cy),
            )
            expanded.polygons[poly_id] = expanded_polygon

    _build_navmesh_connections(expanded)
    return expanded


def _expand_polygon(
    vertices: tuple[tuple[float, float], ...],
    amount: float,
) -> list[tuple[float, float]]:
    """Expand polygon vertices outward."""
    if len(vertices) < 3:
        return list(vertices)

    expanded: list[tuple[float, float]] = []

    for i in range(len(vertices)):
        v_prev = vertices[(i - 1) % len(vertices)]
        v_curr = vertices[i]
        v_next = vertices[(i + 1) % len(vertices)]

        edge1 = (v_curr[0] - v_prev[0], v_curr[1] - v_prev[1])
        edge2 = (v_next[0] - v_curr[0], v_next[1] - v_curr[1])

        len1 = math.sqrt(edge1[0] ** 2 + edge1[1] ** 2)
        len2 = math.sqrt(edge2[0] ** 2 + edge2[1] ** 2)

        if len1 > 0:
            perp1 = (-edge1[1] / len1, edge1[0] / len1)
        else:
            perp1 = (0, 0)

        if len2 > 0:
            perp2 = (-edge2[1] / len2, edge2[0] / len2)
        else:
            perp2 = (0, 0)

        avg_perp = ((perp1[0] + perp2[0]) / 2, (perp1[1] + perp2[1]) / 2)
        avg_len = math.sqrt(avg_perp[0] ** 2 + avg_perp[1] ** 2)

        if avg_len > 0:
            expansion = (avg_perp[0] / avg_len * amount, avg_perp[1] / avg_len * amount)
        else:
            expansion = (0, 0)

        expanded.append((v_curr[0] + expansion[0], v_curr[1] + expansion[1]))

    return expanded
