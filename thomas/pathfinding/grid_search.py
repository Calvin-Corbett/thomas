"""
Grid-based pathfinding algorithms.

This module implements Jump Point Search (JPS), Theta*, and grid-based A* for efficient
pathfinding on uniform grids.
"""

import heapq
import math
import time

from thomas.pathfinding._types import Grid2D, Path, PathResult


def jump_point_search(
    grid: Grid2D,
    start_x: int,
    start_y: int,
    goal_x: int,
    goal_y: int,
) -> PathResult:
    """
    Find shortest path using Jump Point Search algorithm.

    Optimizes A* by eliminating symmetric paths through intelligent neighbor pruning.

    Args:
        grid: The 2D grid to search.
        start_x: Start X coordinate.
        start_y: Start Y coordinate.
        goal_x: Goal X coordinate.
        goal_y: Goal Y coordinate.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = 1

    if not grid.is_walkable(start_x, start_y) or not grid.is_walkable(goal_x, goal_y):
        return PathResult(found=False)

    open_set: list[tuple[float, int, int]] = []
    closed_set: set[tuple[int, int]] = set()
    g_score: dict[tuple[int, int], float] = {(start_x, start_y): 0.0}
    parent: dict[tuple[int, int], tuple[int, int] | None] = {(start_x, start_y): None}

    def heuristic(x: int, y: int) -> float:
        return abs(x - goal_x) + abs(y - goal_y)

    start_h = heuristic(start_x, start_y)
    heapq.heappush(open_set, (start_h, start_x, start_y))

    while open_set:
        _, x, y = heapq.heappop(open_set)

        if (x, y) in closed_set:
            continue

        if x == goal_x and y == goal_y:
            path_nodes: list[tuple[int, int]] = []
            pos = (x, y)
            while pos is not None:
                path_nodes.append(pos)
                pos = parent[pos]
            path_nodes.reverse()
            cost = g_score[(x, y)]
            path = Path(tuple(str(p) for p in path_nodes), cost)
            return PathResult(
                found=True,
                path=path,
                cost=cost,
                nodes_expanded=nodes_expanded,
                nodes_generated=nodes_generated,
                execution_time=time.time() - start_time,
            )

        closed_set.add((x, y))
        nodes_expanded += 1

        neighbors = _jps_prune_neighbors(grid, x, y, parent.get((x, y)))

        for nx, ny in neighbors:
            if (nx, ny) in closed_set:
                continue

            jump_x, jump_y = _jump(grid, nx, ny, x, y, goal_x, goal_y)

            if jump_x is None:
                continue

            new_g = g_score[(x, y)] + math.sqrt((jump_x - x) ** 2 + (jump_y - y) ** 2)

            if (jump_x, jump_y) not in g_score or new_g < g_score[(jump_x, jump_y)]:
                g_score[(jump_x, jump_y)] = new_g
                parent[(jump_x, jump_y)] = (x, y)
                h = heuristic(jump_x, jump_y)
                nodes_generated += 1
                heapq.heappush(open_set, (new_g + h, jump_x, jump_y))

    return PathResult(
        found=False,
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )


def _jps_prune_neighbors(
    grid: Grid2D,
    x: int,
    y: int,
    parent: tuple[int, int] | None,
) -> list[tuple[int, int]]:
    """Get pruned neighbors for JPS."""
    if parent is None:
        neighbors = []
        for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if grid.is_walkable(nx, ny):
                neighbors.append((nx, ny))
        if grid.diagonal_movement:
            for dx, dy in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
                nx, ny = x + dx, y + dy
                if grid.is_walkable(nx, ny):
                    neighbors.append((nx, ny))
        return neighbors

    px, py = parent
    dx = 0 if x == px else (1 if x > px else -1)
    dy = 0 if y == py else (1 if y > py else -1)

    neighbors = []

    if dx != 0 and dy != 0:
        if grid.is_walkable(x + dx, y):
            neighbors.append((x + dx, y))
        if grid.is_walkable(x, y + dy):
            neighbors.append((x, y + dy))
        if grid.is_walkable(x + dx, y + dy):
            neighbors.append((x + dx, y + dy))
        if not grid.is_walkable(x - dx, y):
            if grid.is_walkable(x - dx, y + dy):
                neighbors.append((x - dx, y + dy))
        if not grid.is_walkable(x, y - dy):
            if grid.is_walkable(x + dx, y - dy):
                neighbors.append((x + dx, y - dy))
    else:
        if dx != 0:
            if grid.is_walkable(x + dx, y):
                neighbors.append((x + dx, y))
            for dy_side in [-1, 1]:
                if not grid.is_walkable(x, y + dy_side):
                    if grid.is_walkable(x + dx, y + dy_side):
                        neighbors.append((x + dx, y + dy_side))
        else:
            if grid.is_walkable(x, y + dy):
                neighbors.append((x, y + dy))
            for dx_side in [-1, 1]:
                if not grid.is_walkable(x + dx_side, y):
                    if grid.is_walkable(x + dx_side, y + dy):
                        neighbors.append((x + dx_side, y + dy))

    return neighbors


def _jump(
    grid: Grid2D,
    x: int,
    y: int,
    px: int,
    py: int,
    goal_x: int,
    goal_y: int,
    depth: int = 0,
) -> tuple[int | None, int | None]:
    """Jump in direction from parent."""
    if depth > 100:
        return (None, None)

    if not grid.is_walkable(x, y):
        return (None, None)

    dx = 0 if x == px else (1 if x > px else -1)
    dy = 0 if y == py else (1 if y > py else -1)

    if x == goal_x and y == goal_y:
        return (x, y)

    if dx != 0 and dy != 0:
        if grid.is_walkable(x - dx, y + dy) and not grid.is_walkable(x - dx, y):
            return (x, y)
        if grid.is_walkable(x + dx, y - dy) and not grid.is_walkable(x, y - dy):
            return (x, y)
        result = _jump(grid, x + dx, y, x, y, goal_x, goal_y, depth + 1)
        if result[0] is not None:
            return (x, y)
        result = _jump(grid, x, y + dy, x, y, goal_x, goal_y, depth + 1)
        if result[0] is not None:
            return (x, y)
    else:
        if dx != 0:
            result = _jump(grid, x + dx, y, x, y, goal_x, goal_y, depth + 1)
            if result[0] is not None:
                return (x, y)
        else:
            result = _jump(grid, x, y + dy, x, y, goal_x, goal_y, depth + 1)
            if result[0] is not None:
                return (x, y)

    next_x = x + dx
    next_y = y + dy
    if grid.is_walkable(next_x, next_y):
        return _jump(grid, next_x, next_y, x, y, goal_x, goal_y, depth + 1)

    return (None, None)


def theta_star(
    grid: Grid2D,
    start_x: int,
    start_y: int,
    goal_x: int,
    goal_y: int,
) -> PathResult:
    """
    Find shortest path using Theta* algorithm for any-angle pathfinding.

    Allows movement at any angle, not just along grid directions.

    Args:
        grid: The 2D grid to search.
        start_x: Start X coordinate.
        start_y: Start Y coordinate.
        goal_x: Goal X coordinate.
        goal_y: Goal Y coordinate.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = 1

    if not grid.is_walkable(start_x, start_y) or not grid.is_walkable(goal_x, goal_y):
        return PathResult(found=False)

    open_set: list[tuple[float, int, int]] = []
    closed_set: set[tuple[int, int]] = set()
    g_score: dict[tuple[int, int], float] = {(start_x, start_y): 0.0}
    parent: dict[tuple[int, int], tuple[int, int] | None] = {(start_x, start_y): None}

    def heuristic(x: int, y: int) -> float:
        return math.sqrt((x - goal_x) ** 2 + (y - goal_y) ** 2)

    start_h = heuristic(start_x, start_y)
    heapq.heappush(open_set, (start_h, start_x, start_y))

    while open_set:
        _, x, y = heapq.heappop(open_set)

        if (x, y) in closed_set:
            continue

        closed_set.add((x, y))
        nodes_expanded += 1

        if x == goal_x and y == goal_y:
            path_nodes: list[tuple[int, int]] = []
            pos = (x, y)
            while pos is not None:
                path_nodes.append(pos)
                pos = parent[pos]
            path_nodes.reverse()
            cost = g_score[(x, y)]
            path = Path(tuple(str(p) for p in path_nodes), cost)
            return PathResult(
                found=True,
                path=path,
                cost=cost,
                nodes_expanded=nodes_expanded,
                nodes_generated=nodes_generated,
                execution_time=time.time() - start_time,
            )

        for nx, ny, cost in grid.get_neighbors(x, y):
            if (nx, ny) in closed_set:
                continue

            tentative_g = float("inf")

            if parent[(x, y)] is None:
                tentative_g = g_score[(x, y)] + cost
            else:
                px, py = parent[(x, y)]

                if _line_of_sight(grid, px, py, nx, ny):
                    tentative_g = g_score[(px, py)] + math.sqrt((nx - px) ** 2 + (ny - py) ** 2)
                else:
                    tentative_g = g_score[(x, y)] + cost

            if (nx, ny) not in g_score or tentative_g < g_score[(nx, ny)]:
                g_score[(nx, ny)] = tentative_g
                if parent[(x, y)] is not None and _line_of_sight(grid, parent[(x, y)][0], parent[(x, y)][1], nx, ny):
                    parent[(nx, ny)] = parent[(x, y)]
                else:
                    parent[(nx, ny)] = (x, y)
                h = heuristic(nx, ny)
                nodes_generated += 1
                heapq.heappush(open_set, (tentative_g + h, nx, ny))

    return PathResult(
        found=False,
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )


def _line_of_sight(grid: Grid2D, x1: int, y1: int, x2: int, y2: int) -> bool:
    """Check line-of-sight using Bresenham's algorithm."""
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1

    if dx > dy:
        err = dx / 2.0
        y = y1
        while x1 != x2:
            if not grid.is_walkable(x1, y):
                return False
            err -= dy
            if err < 0:
                y += sy
                err += dx
            x1 += sx
        if not grid.is_walkable(x1, y):
            return False
    else:
        err = dy / 2.0
        x = x1
        while y1 != y2:
            if not grid.is_walkable(x, y1):
                return False
            err -= dx
            if err < 0:
                x += sx
                err += dy
            y1 += sy
        if not grid.is_walkable(x, y1):
            return False

    return True


def grid_search_astar(
    grid: Grid2D,
    start_x: int,
    start_y: int,
    goal_x: int,
    goal_y: int,
) -> PathResult:
    """
    Find shortest path on grid using standard A* algorithm.

    Args:
        grid: The 2D grid to search.
        start_x: Start X coordinate.
        start_y: Start Y coordinate.
        goal_x: Goal X coordinate.
        goal_y: Goal Y coordinate.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()
    nodes_expanded = 0
    nodes_generated = 1

    if not grid.is_walkable(start_x, start_y) or not grid.is_walkable(goal_x, goal_y):
        return PathResult(found=False)

    open_set: list[tuple[float, int, int]] = []
    closed_set: set[tuple[int, int]] = set()
    g_score: dict[tuple[int, int], float] = {(start_x, start_y): 0.0}
    parent: dict[tuple[int, int], tuple[int, int] | None] = {(start_x, start_y): None}

    def heuristic(x: int, y: int) -> float:
        return abs(x - goal_x) + abs(y - goal_y)

    start_h = heuristic(start_x, start_y)
    heapq.heappush(open_set, (start_h, start_x, start_y))

    while open_set:
        _, x, y = heapq.heappop(open_set)

        if (x, y) in closed_set:
            continue

        closed_set.add((x, y))
        nodes_expanded += 1

        if x == goal_x and y == goal_y:
            path_nodes: list[tuple[int, int]] = []
            pos = (x, y)
            while pos is not None:
                path_nodes.append(pos)
                pos = parent[pos]
            path_nodes.reverse()
            cost = g_score[(x, y)]
            path = Path(tuple(str(p) for p in path_nodes), cost)
            return PathResult(
                found=True,
                path=path,
                cost=cost,
                nodes_expanded=nodes_expanded,
                nodes_generated=nodes_generated,
                execution_time=time.time() - start_time,
            )

        for nx, ny, cost in grid.get_neighbors(x, y):
            if (nx, ny) in closed_set:
                continue

            new_g = g_score[(x, y)] + cost
            if (nx, ny) not in g_score or new_g < g_score[(nx, ny)]:
                g_score[(nx, ny)] = new_g
                parent[(nx, ny)] = (x, y)
                h = heuristic(nx, ny)
                nodes_generated += 1
                heapq.heappush(open_set, (new_g + h, nx, ny))

    return PathResult(
        found=False,
        nodes_expanded=nodes_expanded,
        nodes_generated=nodes_generated,
        execution_time=time.time() - start_time,
    )
