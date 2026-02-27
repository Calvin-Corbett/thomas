"""
Sampling-based motion planning algorithms.

This module implements RRT, RRT*, RRT-Connect, Informed RRT*, and PRM for path planning
in continuous spaces with obstacles.
"""

import math
import random
import time
from dataclasses import dataclass
from typing import Optional

from thomas.pathfinding._types import Obstacle, Path, PathResult


@dataclass
class TreeNode:
    """Node in RRT tree."""

    x: float
    y: float
    parent: Optional["TreeNode"] = None
    cost: float = 0.0


def rrt(
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list[Obstacle],
    bounds: tuple[float, float, float, float],
    max_iterations: int = 5000,
    step_size: float = 1.0,
    goal_bias: float = 0.1,
) -> PathResult:
    """
    Find path using Rapidly-exploring Random Tree (RRT).

    Args:
        start: Start position (x, y).
        goal: Goal position (x, y).
        obstacles: List of rectangular obstacles.
        bounds: Bounds (min_x, min_y, max_x, max_y).
        max_iterations: Maximum tree expansion iterations.
        step_size: Maximum step size when extending tree.
        goal_bias: Probability of sampling goal directly.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()

    def collision_free(x1: float, y1: float, x2: float, y2: float) -> bool:
        """Check if line segment collides with obstacles."""
        for obs in obstacles:
            if _segment_intersects_box(x1, y1, x2, y2, obs):
                return False
        return True

    def in_bounds(x: float, y: float) -> bool:
        """Check if point is in bounds."""
        return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]

    root = TreeNode(start[0], start[1])
    nodes = [root]

    for iteration in range(max_iterations):
        if random.random() < goal_bias:
            rand_x, rand_y = goal
        else:
            rand_x = random.uniform(bounds[0], bounds[2])
            rand_y = random.uniform(bounds[1], bounds[3])

        nearest_node = min(
            nodes,
            key=lambda n: math.sqrt((n.x - rand_x) ** 2 + (n.y - rand_y) ** 2),
        )

        dist = math.sqrt((rand_x - nearest_node.x) ** 2 + (rand_y - nearest_node.y) ** 2)
        if dist < 1e-6:
            continue

        new_x = nearest_node.x + (rand_x - nearest_node.x) / dist * step_size
        new_y = nearest_node.y + (rand_y - nearest_node.y) / dist * step_size

        if not in_bounds(new_x, new_y):
            continue

        if not collision_free(nearest_node.x, nearest_node.y, new_x, new_y):
            continue

        new_node = TreeNode(new_x, new_y, parent=nearest_node, cost=nearest_node.cost + step_size)
        nodes.append(new_node)

        if math.sqrt((new_x - goal[0]) ** 2 + (new_y - goal[1]) ** 2) < step_size:
            goal_node = TreeNode(goal[0], goal[1], parent=new_node)
            nodes.append(goal_node)

            path_nodes = []
            node = goal_node
            while node is not None:
                path_nodes.append((node.x, node.y))
                node = node.parent
            path_nodes.reverse()

            cost = goal_node.cost
            path = Path(tuple(str(p) for p in path_nodes), cost)

            return PathResult(
                found=True,
                path=path,
                cost=cost,
                nodes_expanded=len(nodes),
                nodes_generated=len(nodes),
                execution_time=time.time() - start_time,
            )

    return PathResult(
        found=False,
        nodes_expanded=len(nodes),
        nodes_generated=len(nodes),
        execution_time=time.time() - start_time,
    )


def rrt_star(
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list[Obstacle],
    bounds: tuple[float, float, float, float],
    max_iterations: int = 5000,
    step_size: float = 1.0,
    goal_bias: float = 0.1,
    rewire_radius: float = 5.0,
) -> PathResult:
    """
    Find path using RRT* (asymptotically optimal RRT).

    Args:
        start: Start position (x, y).
        goal: Goal position (x, y).
        obstacles: List of rectangular obstacles.
        bounds: Bounds (min_x, min_y, max_x, max_y).
        max_iterations: Maximum tree expansion iterations.
        step_size: Maximum step size when extending tree.
        goal_bias: Probability of sampling goal directly.
        rewire_radius: Radius for rewiring edges.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()

    def collision_free(x1: float, y1: float, x2: float, y2: float) -> bool:
        for obs in obstacles:
            if _segment_intersects_box(x1, y1, x2, y2, obs):
                return False
        return True

    def in_bounds(x: float, y: float) -> bool:
        return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]

    root = TreeNode(start[0], start[1])
    nodes = [root]
    best_goal_cost = float("inf")
    best_goal_node = None

    for iteration in range(max_iterations):
        if random.random() < goal_bias:
            rand_x, rand_y = goal
        else:
            rand_x = random.uniform(bounds[0], bounds[2])
            rand_y = random.uniform(bounds[1], bounds[3])

        nearest_node = min(
            nodes,
            key=lambda n: math.sqrt((n.x - rand_x) ** 2 + (n.y - rand_y) ** 2),
        )

        dist = math.sqrt((rand_x - nearest_node.x) ** 2 + (rand_y - nearest_node.y) ** 2)
        if dist < 1e-6:
            continue

        new_x = nearest_node.x + (rand_x - nearest_node.x) / dist * step_size
        new_y = nearest_node.y + (rand_y - nearest_node.y) / dist * step_size

        if not in_bounds(new_x, new_y):
            continue

        if not collision_free(nearest_node.x, nearest_node.y, new_x, new_y):
            continue

        new_node = TreeNode(new_x, new_y, parent=nearest_node, cost=nearest_node.cost + dist)

        neighbors = [n for n in nodes if math.sqrt((n.x - new_x) ** 2 + (n.y - new_y) ** 2) < rewire_radius]

        best_parent = nearest_node
        best_cost = new_node.cost

        for neighbor in neighbors:
            if collision_free(neighbor.x, neighbor.y, new_x, new_y):
                neighbor_dist = math.sqrt((neighbor.x - new_x) ** 2 + (neighbor.y - new_y) ** 2)
                neighbor_cost = neighbor.cost + neighbor_dist
                if neighbor_cost < best_cost:
                    best_cost = neighbor_cost
                    best_parent = neighbor

        new_node.parent = best_parent
        new_node.cost = best_cost
        nodes.append(new_node)

        for neighbor in neighbors:
            if neighbor == best_parent:
                continue
            neighbor_dist = math.sqrt((neighbor.x - new_x) ** 2 + (neighbor.y - new_y) ** 2)
            neighbor_new_cost = new_node.cost + neighbor_dist
            if neighbor_new_cost < neighbor.cost and collision_free(new_x, new_y, neighbor.x, neighbor.y):
                neighbor.parent = new_node
                neighbor.cost = neighbor_new_cost

        goal_dist = math.sqrt((new_x - goal[0]) ** 2 + (new_y - goal[1]) ** 2)
        if goal_dist < step_size and collision_free(new_x, new_y, goal[0], goal[1]):
            goal_cost = new_node.cost + goal_dist
            if goal_cost < best_goal_cost:
                best_goal_cost = goal_cost
                best_goal_node = new_node

    if best_goal_node:
        path_nodes = []
        node = best_goal_node
        while node is not None:
            path_nodes.append((node.x, node.y))
            node = node.parent
        path_nodes.reverse()

        path = Path(tuple(str(p) for p in path_nodes), best_goal_cost)
        return PathResult(
            found=True,
            path=path,
            cost=best_goal_cost,
            nodes_expanded=len(nodes),
            nodes_generated=len(nodes),
            execution_time=time.time() - start_time,
        )

    return PathResult(
        found=False,
        nodes_expanded=len(nodes),
        nodes_generated=len(nodes),
        execution_time=time.time() - start_time,
    )


def rrt_connect(
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list[Obstacle],
    bounds: tuple[float, float, float, float],
    max_iterations: int = 5000,
    step_size: float = 1.0,
) -> PathResult:
    """
    Find path using bidirectional RRT-Connect.

    Searches from both start and goal simultaneously.

    Args:
        start: Start position (x, y).
        goal: Goal position (x, y).
        obstacles: List of rectangular obstacles.
        bounds: Bounds (min_x, min_y, max_x, max_y).
        max_iterations: Maximum tree expansion iterations.
        step_size: Maximum step size when extending tree.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()

    def collision_free(x1: float, y1: float, x2: float, y2: float) -> bool:
        for obs in obstacles:
            if _segment_intersects_box(x1, y1, x2, y2, obs):
                return False
        return True

    def in_bounds(x: float, y: float) -> bool:
        return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]

    root_start = TreeNode(start[0], start[1])
    root_goal = TreeNode(goal[0], goal[1])
    start_nodes = [root_start]
    goal_nodes = [root_goal]

    for iteration in range(max_iterations):
        rand_x = random.uniform(bounds[0], bounds[2])
        rand_y = random.uniform(bounds[1], bounds[3])

        nearest_start = min(
            start_nodes,
            key=lambda n: math.sqrt((n.x - rand_x) ** 2 + (n.y - rand_y) ** 2),
        )

        dist = math.sqrt((rand_x - nearest_start.x) ** 2 + (rand_y - nearest_start.y) ** 2)
        if dist > 1e-6:
            new_x = nearest_start.x + (rand_x - nearest_start.x) / dist * step_size
            new_y = nearest_start.y + (rand_y - nearest_start.y) / dist * step_size

            if in_bounds(new_x, new_y) and collision_free(nearest_start.x, nearest_start.y, new_x, new_y):
                new_node_start = TreeNode(new_x, new_y, parent=nearest_start, cost=nearest_start.cost + dist)
                start_nodes.append(new_node_start)

                nearest_goal = min(
                    goal_nodes,
                    key=lambda n: math.sqrt((n.x - new_x) ** 2 + (n.y - new_y) ** 2),
                )

                goal_dist = math.sqrt((nearest_goal.x - new_x) ** 2 + (nearest_goal.y - new_y) ** 2)
                if goal_dist < step_size and collision_free(new_x, new_y, nearest_goal.x, nearest_goal.y):
                    path_nodes_start = []
                    node = new_node_start
                    while node is not None:
                        path_nodes_start.append((node.x, node.y))
                        node = node.parent
                    path_nodes_start.reverse()

                    path_nodes_goal = []
                    node = nearest_goal
                    while node is not None:
                        path_nodes_goal.append((node.x, node.y))
                        node = node.parent

                    path_nodes = path_nodes_start + path_nodes_goal
                    total_cost = new_node_start.cost + goal_dist + nearest_goal.cost

                    path = Path(tuple(str(p) for p in path_nodes), total_cost)
                    return PathResult(
                        found=True,
                        path=path,
                        cost=total_cost,
                        nodes_expanded=len(start_nodes) + len(goal_nodes),
                        nodes_generated=len(start_nodes) + len(goal_nodes),
                        execution_time=time.time() - start_time,
                    )

    return PathResult(
        found=False,
        nodes_expanded=len(start_nodes) + len(goal_nodes),
        nodes_generated=len(start_nodes) + len(goal_nodes),
        execution_time=time.time() - start_time,
    )


def informed_rrt_star(
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list[Obstacle],
    bounds: tuple[float, float, float, float],
    max_iterations: int = 5000,
    step_size: float = 1.0,
    initial_solution_cost: float | None = None,
) -> PathResult:
    """
    Find path using Informed RRT* with ellipsoidal sampling.

    Args:
        start: Start position (x, y).
        goal: Goal position (x, y).
        obstacles: List of rectangular obstacles.
        bounds: Bounds (min_x, min_y, max_x, max_y).
        max_iterations: Maximum tree expansion iterations.
        step_size: Maximum step size when extending tree.
        initial_solution_cost: Initial upper bound on solution cost.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()

    def collision_free(x1: float, y1: float, x2: float, y2: float) -> bool:
        for obs in obstacles:
            if _segment_intersects_box(x1, y1, x2, y2, obs):
                return False
        return True

    def in_bounds(x: float, y: float) -> bool:
        return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]

    def sample_from_ellipse(c_min: float, c_max: float) -> tuple[float, float]:
        """Sample from ellipse defined by start-goal distance."""
        if c_max <= c_min:
            return (random.uniform(bounds[0], bounds[2]), random.uniform(bounds[1], bounds[3]))

        center_x = (start[0] + goal[0]) / 2
        center_y = (start[1] + goal[1]) / 2
        c = math.sqrt((goal[0] - start[0]) ** 2 + (goal[1] - start[1]) ** 2)

        a = c_max / 2
        b = math.sqrt(a * a - (c / 2) ** 2) if c_max > c else 0

        angle = math.atan2(goal[1] - start[1], goal[0] - start[0])

        r = random.random()
        theta = 2 * math.pi * random.random()

        x_ellipse = a * math.cos(theta)
        y_ellipse = b * math.sin(theta)

        x = center_x + x_ellipse * math.cos(angle) - y_ellipse * math.sin(angle)
        y = center_y + x_ellipse * math.sin(angle) + y_ellipse * math.cos(angle)

        return (x, y)

    root = TreeNode(start[0], start[1])
    nodes = [root]
    best_goal_cost = initial_solution_cost or float("inf")
    best_goal_node = None

    for iteration in range(max_iterations):
        rand_x, rand_y = sample_from_ellipse(
            math.sqrt((goal[0] - start[0]) ** 2 + (goal[1] - start[1]) ** 2),
            best_goal_cost,
        )

        if not in_bounds(rand_x, rand_y):
            continue

        nearest_node = min(
            nodes,
            key=lambda n: math.sqrt((n.x - rand_x) ** 2 + (n.y - rand_y) ** 2),
        )

        dist = math.sqrt((rand_x - nearest_node.x) ** 2 + (rand_y - nearest_node.y) ** 2)
        if dist < 1e-6:
            continue

        new_x = nearest_node.x + (rand_x - nearest_node.x) / dist * step_size
        new_y = nearest_node.y + (rand_y - nearest_node.y) / dist * step_size

        if not collision_free(nearest_node.x, nearest_node.y, new_x, new_y):
            continue

        new_node = TreeNode(new_x, new_y, parent=nearest_node, cost=nearest_node.cost + dist)
        nodes.append(new_node)

        goal_dist = math.sqrt((new_x - goal[0]) ** 2 + (new_y - goal[1]) ** 2)
        if goal_dist < step_size and collision_free(new_x, new_y, goal[0], goal[1]):
            goal_cost = new_node.cost + goal_dist
            if goal_cost < best_goal_cost:
                best_goal_cost = goal_cost
                best_goal_node = new_node

    if best_goal_node:
        path_nodes = []
        node = best_goal_node
        while node is not None:
            path_nodes.append((node.x, node.y))
            node = node.parent
        path_nodes.reverse()

        path = Path(tuple(str(p) for p in path_nodes), best_goal_cost)
        return PathResult(
            found=True,
            path=path,
            cost=best_goal_cost,
            nodes_expanded=len(nodes),
            nodes_generated=len(nodes),
            execution_time=time.time() - start_time,
        )

    return PathResult(
        found=False,
        nodes_expanded=len(nodes),
        nodes_generated=len(nodes),
        execution_time=time.time() - start_time,
    )


def probabilistic_roadmap(
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list[Obstacle],
    bounds: tuple[float, float, float, float],
    num_samples: int = 100,
    max_neighbors: int = 10,
    max_edge_length: float = 20.0,
) -> PathResult:
    """
    Find path using Probabilistic Roadmap (PRM).

    Args:
        start: Start position (x, y).
        goal: Goal position (x, y).
        obstacles: List of rectangular obstacles.
        bounds: Bounds (min_x, min_y, max_x, max_y).
        num_samples: Number of random samples to generate.
        max_neighbors: Maximum neighbors to connect to.
        max_edge_length: Maximum edge length in roadmap.

    Returns:
        PathResult containing the path and statistics.
    """
    start_time = time.time()

    def collision_free(x1: float, y1: float, x2: float, y2: float) -> bool:
        for obs in obstacles:
            if _segment_intersects_box(x1, y1, x2, y2, obs):
                return False
        return True

    def in_bounds(x: float, y: float) -> bool:
        return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]

    samples = [start, goal]
    for _ in range(num_samples):
        while True:
            x = random.uniform(bounds[0], bounds[2])
            y = random.uniform(bounds[1], bounds[3])
            if in_bounds(x, y) and collision_free(x, y, x, y):
                collision_free_point = True
                for obs in obstacles:
                    if obs.contains_point(x, y):
                        collision_free_point = False
                        break
                if collision_free_point:
                    samples.append((x, y))
                    break

    roadmap: Dict[int, list[tuple[int, float]]] = {i: [] for i in range(len(samples))}

    for i in range(len(samples)):
        distances = [
            (j, math.sqrt((samples[j][0] - samples[i][0]) ** 2 + (samples[j][1] - samples[i][1]) ** 2))
            for j in range(len(samples))
            if i != j
        ]
        distances.sort(key=lambda x: x[1])

        for j, dist in distances[:max_neighbors]:
            if dist <= max_edge_length:
                if collision_free(samples[i][0], samples[i][1], samples[j][0], samples[j][1]):
                    roadmap[i].append((j, dist))

    from collections import deque

    queue = deque([(0, [0], 0.0)])
    visited = {0}

    while queue:
        node_idx, path, cost = queue.popleft()

        if node_idx == 1:
            path_coords = [samples[idx] for idx in path]
            path_obj = Path(tuple(str(p) for p in path_coords), cost)
            return PathResult(
                found=True,
                path=path_obj,
                cost=cost,
                nodes_expanded=len(visited),
                nodes_generated=len(samples),
                execution_time=time.time() - start_time,
            )

        for next_idx, edge_cost in roadmap[node_idx]:
            if next_idx not in visited:
                visited.add(next_idx)
                queue.append((next_idx, path + [next_idx], cost + edge_cost))

    return PathResult(
        found=False,
        nodes_expanded=len(visited),
        nodes_generated=len(samples),
        execution_time=time.time() - start_time,
    )


def _segment_intersects_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    box: Obstacle,
) -> bool:
    """Check if line segment intersects axis-aligned box."""
    min_x = min(x1, x2)
    max_x = max(x1, x2)
    min_y = min(y1, y2)
    max_y = max(y1, y2)

    if max_x < box.x1 or min_x > box.x2 or max_y < box.y1 or min_y > box.y2:
        return False

    return True
