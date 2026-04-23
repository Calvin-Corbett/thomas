"""
Flow field algorithms for crowd simulation and multi-agent pathfinding.

This module implements Dijkstra-based integration fields and gradient flow field
generation for efficient multi-agent movement.
"""

import heapq
import math

from thomas.marketplace.pathfinding._types import Grid2D


def compute_integration_field(
    grid: Grid2D,
    goal_x: int,
    goal_y: int,
) -> dict[tuple[int, int], float]:
    """
    Compute integration field using Dijkstra from goal.

    Distance field where each cell contains distance to goal.

    Args:
        grid: The 2D grid.
        goal_x: Goal X coordinate.
        goal_y: Goal Y coordinate.

    Returns:
        Dictionary mapping (x, y) to distance values.
    """
    if not grid.is_walkable(goal_x, goal_y):
        return {}

    integration_field: dict[tuple[int, int], float] = {}
    heap: list[tuple[float, int, int]] = [(0.0, goal_x, goal_y)]
    visited: set = set()

    while heap:
        dist, x, y = heapq.heappop(heap)

        if (x, y) in visited:
            continue

        visited.add((x, y))
        integration_field[(x, y)] = dist

        for nx, ny, cost in grid.get_neighbors(x, y):
            if (nx, ny) not in visited:
                new_dist = dist + cost
                heapq.heappush(heap, (new_dist, nx, ny))

    return integration_field


def compute_flow_field(
    grid: Grid2D,
    integration_field: dict[tuple[int, int], float],
) -> dict[tuple[int, int], tuple[float, float]]:
    """
    Compute flow field from integration field.

    Each cell contains a vector pointing toward lower cost.

    Args:
        grid: The 2D grid.
        integration_field: Integration field from compute_integration_field.

    Returns:
        Dictionary mapping (x, y) to (dx, dy) flow vectors.
    """
    flow_field: dict[tuple[int, int], tuple[float, float]] = {}

    for y in range(grid.height):
        for x in range(grid.width):
            if not grid.is_walkable(x, y):
                continue

            if (x, y) not in integration_field:
                continue

            current_cost = integration_field[(x, y)]
            best_neighbor = None
            best_cost = current_cost

            for nx, ny, _ in grid.get_neighbors(x, y):
                if (nx, ny) in integration_field:
                    neighbor_cost = integration_field[(nx, ny)]
                    if neighbor_cost < best_cost:
                        best_cost = neighbor_cost
                        best_neighbor = (nx, ny)

            if best_neighbor:
                dx = float(best_neighbor[0] - x)
                dy = float(best_neighbor[1] - y)
                length = math.sqrt(dx * dx + dy * dy)
                if length > 0:
                    flow_field[(x, y)] = (dx / length, dy / length)
                else:
                    flow_field[(x, y)] = (0.0, 0.0)
            else:
                flow_field[(x, y)] = (0.0, 0.0)

    return flow_field


def sample_flow_field(
    flow_field: dict[tuple[int, int], tuple[float, float]],
    x: float,
    y: float,
) -> tuple[float, float]:
    """
    Sample flow field at continuous coordinates using bilinear interpolation.

    Args:
        flow_field: The flow field.
        x: X coordinate (can be fractional).
        y: Y coordinate (can be fractional).

    Returns:
        Interpolated flow vector (dx, dy).
    """
    x1 = int(math.floor(x))
    y1 = int(math.floor(y))
    x2 = x1 + 1
    y2 = y1 + 1

    fx = x - x1
    fy = y - y1

    f11 = flow_field.get((x1, y1), (0.0, 0.0))
    f12 = flow_field.get((x1, y2), (0.0, 0.0))
    f21 = flow_field.get((x2, y1), (0.0, 0.0))
    f22 = flow_field.get((x2, y2), (0.0, 0.0))

    dx = (1 - fx) * (1 - fy) * f11[0] + (1 - fx) * fy * f12[0] + fx * (1 - fy) * f21[0] + fx * fy * f22[0]

    dy = (1 - fx) * (1 - fy) * f11[1] + (1 - fx) * fy * f12[1] + fx * (1 - fy) * f21[1] + fx * fy * f22[1]

    return (dx, dy)


class FlowFieldCache:
    """Cache for pre-computed flow fields."""

    def __init__(self, grid: Grid2D, max_fields: int = 10) -> None:
        """
        Initialize flow field cache.

        Args:
            grid: The grid for which to cache fields.
            max_fields: Maximum number of cached fields.
        """
        self.grid = grid
        self.max_fields = max_fields
        self.cache: dict[tuple[int, int], dict[tuple[int, int], tuple[float, float]]] = {}
        self.access_order: list[tuple[int, int]] = []

    def get_or_compute(
        self,
        goal_x: int,
        goal_y: int,
    ) -> dict[tuple[int, int], tuple[float, float]]:
        """
        Get flow field for goal, computing if necessary.

        Args:
            goal_x: Goal X coordinate.
            goal_y: Goal Y coordinate.

        Returns:
            Flow field for the goal.
        """
        goal_key = (goal_x, goal_y)

        if goal_key in self.cache:
            self.access_order.remove(goal_key)
            self.access_order.append(goal_key)
            return self.cache[goal_key]

        integration = compute_integration_field(self.grid, goal_x, goal_y)
        flow = compute_flow_field(self.grid, integration)

        if len(self.cache) >= self.max_fields:
            oldest = self.access_order.pop(0)
            del self.cache[oldest]

        self.cache[goal_key] = flow
        self.access_order.append(goal_key)
        return flow

    def clear(self) -> None:
        """Clear the cache."""
        self.cache.clear()
        self.access_order.clear()


def portal_flow_field(
    grid: Grid2D,
    portal_x: int,
    portal_y: int,
    goal_x: int,
    goal_y: int,
) -> dict[tuple[int, int], tuple[float, float]]:
    """
    Compute flow field that directs through a portal to goal.

    Args:
        grid: The grid.
        portal_x: Portal X coordinate.
        portal_y: Portal Y coordinate.
        goal_x: Goal X coordinate.
        goal_y: Goal Y coordinate.

    Returns:
        Flow field directing toward portal then goal.
    """
    integration = compute_integration_field(grid, goal_x, goal_y)

    flow_field: dict[tuple[int, int], tuple[float, float]] = {}

    for y in range(grid.height):
        for x in range(grid.width):
            if not grid.is_walkable(x, y):
                continue

            if (x, y) not in integration:
                continue

            portal_dist = abs(x - portal_x) + abs(y - portal_y)
            goal_dist = integration.get((x, y), float("inf"))

            current_cost = portal_dist + goal_dist

            best_dx = 0.0
            best_dy = 0.0
            best_cost = current_cost

            for nx, ny, _ in grid.get_neighbors(x, y):
                neighbor_portal_dist = abs(nx - portal_x) + abs(ny - portal_y)
                neighbor_goal_dist = integration.get((nx, ny), float("inf"))
                neighbor_cost = neighbor_portal_dist + neighbor_goal_dist

                if neighbor_cost < best_cost:
                    best_cost = neighbor_cost
                    best_dx = float(nx - x)
                    best_dy = float(ny - y)

            length = math.sqrt(best_dx * best_dx + best_dy * best_dy)
            if length > 0:
                flow_field[(x, y)] = (best_dx / length, best_dy / length)
            else:
                flow_field[(x, y)] = (0.0, 0.0)

    return flow_field


def sector_based_flow(
    grid: Grid2D,
    goal_x: int,
    goal_y: int,
    sector_size: int = 10,
) -> dict[tuple[int, int], tuple[float, float]]:
    """
    Compute flow field using sector-based approach for efficiency.

    Divides grid into sectors and computes flow for each sector.

    Args:
        grid: The grid.
        goal_x: Goal X coordinate.
        goal_y: Goal Y coordinate.
        sector_size: Size of each sector.

    Returns:
        Sector-based flow field.
    """
    flow_field: dict[tuple[int, int], tuple[float, float]] = {}

    goal_sector_x = goal_x // sector_size
    goal_sector_y = goal_y // sector_size

    num_sectors_x = (grid.width + sector_size - 1) // sector_size
    num_sectors_y = (grid.height + sector_size - 1) // sector_size

    sector_distances: dict[tuple[int, int], float] = {}
    heap: list[tuple[float, int, int]] = [(0.0, goal_sector_x, goal_sector_y)]
    visited: set = set()

    while heap:
        dist, sx, sy = heapq.heappop(heap)

        if (sx, sy) in visited:
            continue

        visited.add((sx, sy))
        sector_distances[(sx, sy)] = dist

        for dsx, dsy in [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
            nsx, nsy = sx + dsx, sy + dsy
            if 0 <= nsx < num_sectors_x and 0 <= nsy < num_sectors_y:
                if (nsx, nsy) not in visited:
                    new_dist = dist + math.sqrt(dsx * dsx + dsy * dsy)
                    heapq.heappush(heap, (new_dist, nsx, nsy))

    for y in range(grid.height):
        for x in range(grid.width):
            if not grid.is_walkable(x, y):
                continue

            sector_x = x // sector_size
            sector_y = y // sector_size

            current_sector_dist = sector_distances.get((sector_x, sector_y), float("inf"))

            best_dx = 0.0
            best_dy = 0.0
            best_dist = current_sector_dist

            for nx, ny, _ in grid.get_neighbors(x, y):
                neighbor_sector_x = nx // sector_size
                neighbor_sector_y = ny // sector_size
                neighbor_sector_dist = sector_distances.get((neighbor_sector_x, neighbor_sector_y), float("inf"))

                if neighbor_sector_dist < best_dist:
                    best_dist = neighbor_sector_dist
                    best_dx = float(nx - x)
                    best_dy = float(ny - y)

            length = math.sqrt(best_dx * best_dx + best_dy * best_dy)
            if length > 0:
                flow_field[(x, y)] = (best_dx / length, best_dy / length)
            else:
                flow_field[(x, y)] = (0.0, 0.0)

    return flow_field
