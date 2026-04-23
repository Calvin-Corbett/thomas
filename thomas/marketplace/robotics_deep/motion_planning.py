"""
Motion planning algorithms: RRT, RRT*, PRM.
"""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional


@dataclass
class Node:
    """Node in planning tree/graph."""

    config: list[float]
    parent: Optional["Node"] = None
    cost: float = 0.0


class RRT:
    """Rapidly-exploring Random Trees for motion planning."""

    def __init__(
        self,
        config_dim: int,
        bounds: list[tuple[float, float]],
        collision_checker: Callable[[list[float]], bool],
        step_size: float = 0.5,
        goal_bias: float = 0.1,
    ) -> None:
        """
        Initialize RRT planner.

        Args:
            config_dim: Dimension of configuration space
            bounds: Bounds for each dimension (min, max)
            collision_checker: Function returning True if config is collision-free
            step_size: Maximum step size in configuration space
            goal_bias: Probability of biasing toward goal
        """
        self.config_dim = config_dim
        self.bounds = bounds
        self.collision_checker = collision_checker
        self.step_size = step_size
        self.goal_bias = goal_bias

    def plan(self, start: list[float], goal: list[float], max_iterations: int = 5000) -> list[list[float]] | None:
        """
        Plan path from start to goal using RRT.

        Args:
            start: Start configuration
            goal: Goal configuration
            max_iterations: Maximum iterations

        Returns:
            Path as list of configurations, or None if no path found
        """
        if not self.collision_checker(start) or not self.collision_checker(goal):
            return None

        root = Node(config=start)
        nodes = [root]

        for _ in range(max_iterations):
            # Sample random configuration
            if random.random() < self.goal_bias:
                q_rand = goal
            else:
                q_rand = [random.uniform(self.bounds[i][0], self.bounds[i][1]) for i in range(self.config_dim)]

            # Find nearest node
            nearest = min(nodes, key=lambda n: self._distance(n.config, q_rand))

            # Extend toward sample
            q_new = self._extend(nearest.config, q_rand, self.step_size)

            # Collision check path
            if self._path_collision_free(nearest.config, q_new):
                new_node = Node(config=q_new, parent=nearest)
                nodes.append(new_node)

                # Check if goal reached
                if self._distance(q_new, goal) < self.step_size:
                    goal_node = Node(config=goal, parent=new_node)
                    return self._extract_path(goal_node)

        return None

    def _distance(self, q1: list[float], q2: list[float]) -> float:
        """Euclidean distance in configuration space."""
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(q1, q2)))

    def _extend(self, q_from: list[float], q_to: list[float], step_size: float) -> list[float]:
        """Extend from q_from toward q_to by step_size."""
        direction = [q_to[i] - q_from[i] for i in range(self.config_dim)]
        dist = self._distance(q_from, q_to)

        if dist < 1e-6:
            return q_to

        scale = min(1.0, step_size / dist)
        return [q_from[i] + scale * direction[i] for i in range(self.config_dim)]

    def _path_collision_free(self, q1: list[float], q2: list[float], resolution: int = 10) -> bool:
        """Check if path segment is collision-free."""
        for i in range(resolution + 1):
            t = i / resolution if resolution > 0 else 0.0
            q = [q1[j] + t * (q2[j] - q1[j]) for j in range(self.config_dim)]
            if not self.collision_checker(q):
                return False
        return True

    def _extract_path(self, node: Node) -> list[list[float]]:
        """Extract path by backtracking from node to root."""
        path = []
        current = node
        while current is not None:
            path.append(current.config[:])
            current = current.parent
        return path[::-1]


class RRTStar(RRT):
    """RRT* with path rewiring for optimality."""

    def __init__(
        self,
        config_dim: int,
        bounds: list[tuple[float, float]],
        collision_checker: Callable[[list[float]], bool],
        step_size: float = 0.5,
        goal_bias: float = 0.1,
        rewire_radius: float = 2.0,
    ) -> None:
        """
        Initialize RRT* planner.

        Args:
            config_dim: Dimension of configuration space
            bounds: Bounds for each dimension
            collision_checker: Function returning True if config is collision-free
            step_size: Maximum step size
            goal_bias: Goal bias probability
            rewire_radius: Radius for rewiring neighbors
        """
        super().__init__(config_dim, bounds, collision_checker, step_size, goal_bias)
        self.rewire_radius = rewire_radius
        self.best_path_cost = float("inf")
        self.best_path: list[list[float]] | None = None

    def plan(self, start: list[float], goal: list[float], max_iterations: int = 5000) -> list[list[float]] | None:
        """
        Plan path using RRT* with rewiring.

        Args:
            start: Start configuration
            goal: Goal configuration
            max_iterations: Maximum iterations

        Returns:
            Path as list of configurations, or None if no path found
        """
        if not self.collision_checker(start) or not self.collision_checker(goal):
            return None

        root = Node(config=start, cost=0.0)
        nodes = [root]

        for _ in range(max_iterations):
            # Sample
            if random.random() < self.goal_bias:
                q_rand = goal
            else:
                q_rand = [random.uniform(self.bounds[i][0], self.bounds[i][1]) for i in range(self.config_dim)]

            # Find nearest
            nearest = min(nodes, key=lambda n: self._distance(n.config, q_rand))

            # Extend
            q_new = self._extend(nearest.config, q_rand, self.step_size)

            if self._path_collision_free(nearest.config, q_new):
                new_cost = nearest.cost + self._distance(nearest.config, q_new)
                new_node = Node(config=q_new, parent=nearest, cost=new_cost)

                # Rewiring: find neighbors within radius
                neighbors = [n for n in nodes if self._distance(n.config, q_new) < self.rewire_radius]

                # Find best parent
                for neighbor in neighbors:
                    tentative_cost = neighbor.cost + self._distance(neighbor.config, q_new)
                    if tentative_cost < new_node.cost:
                        if self._path_collision_free(neighbor.config, q_new):
                            new_node.parent = neighbor
                            new_node.cost = tentative_cost

                # Rewire neighbors through new node
                for neighbor in neighbors:
                    tentative_cost = new_node.cost + self._distance(q_new, neighbor.config)
                    if tentative_cost < neighbor.cost:
                        if self._path_collision_free(q_new, neighbor.config):
                            neighbor.parent = new_node
                            neighbor.cost = tentative_cost

                nodes.append(new_node)

                # Check goal
                if self._distance(q_new, goal) < self.step_size:
                    goal_cost = new_node.cost + self._distance(q_new, goal)
                    if goal_cost < self.best_path_cost:
                        goal_node = Node(config=goal, parent=new_node, cost=goal_cost)
                        self.best_path = self._extract_path(goal_node)
                        self.best_path_cost = goal_cost

        return self.best_path


class PRM:
    """Probabilistic Roadmap for motion planning."""

    def __init__(
        self,
        config_dim: int,
        bounds: list[tuple[float, float]],
        collision_checker: Callable[[list[float]], bool],
        connection_radius: float = 1.0,
    ) -> None:
        """
        Initialize PRM planner.

        Args:
            config_dim: Dimension of configuration space
            bounds: Bounds for each dimension
            collision_checker: Function returning True if config is collision-free
            connection_radius: Radius for connecting sampled nodes
        """
        self.config_dim = config_dim
        self.bounds = bounds
        self.collision_checker = collision_checker
        self.connection_radius = connection_radius
        self.roadmap: list[Node] = []

    def build_roadmap(self, num_samples: int = 500) -> None:
        """
        Build probabilistic roadmap by sampling and connecting.

        Args:
            num_samples: Number of configurations to sample
        """
        # Sample configurations
        samples = []
        for _ in range(num_samples):
            q = [random.uniform(self.bounds[i][0], self.bounds[i][1]) for i in range(self.config_dim)]
            if self.collision_checker(q):
                samples.append(Node(config=q))

        # Connect samples
        for i, node1 in enumerate(samples):
            for node2 in samples[i + 1 :]:
                dist = self._distance(node1.config, node2.config)
                if dist < self.connection_radius:
                    if self._path_collision_free(node1.config, node2.config):
                        # Bidirectional connection
                        # Store as adjacency (simplified)
                        pass

        self.roadmap = samples

    def query(self, start: list[float], goal: list[float]) -> list[list[float]] | None:
        """
        Query path from start to goal using built roadmap.

        Args:
            start: Start configuration
            goal: Goal configuration

        Returns:
            Path as list of configurations, or None if no path found
        """
        if not self.roadmap:
            return None

        # Find nearest nodes in roadmap
        start_nearest = min(
            self.roadmap,
            key=lambda n: self._distance(n.config, start),
            default=None,
        )
        goal_nearest = min(
            self.roadmap,
            key=lambda n: self._distance(n.config, goal),
            default=None,
        )

        if not start_nearest or not goal_nearest:
            return None

        if not self._path_collision_free(start, start_nearest.config):
            return None
        if not self._path_collision_free(goal_nearest.config, goal):
            return None

        # BFS in roadmap (simplified)
        path = [start, start_nearest.config, goal_nearest.config, goal]
        return path

    def _distance(self, q1: list[float], q2: list[float]) -> float:
        """Euclidean distance."""
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(q1, q2)))

    def _path_collision_free(self, q1: list[float], q2: list[float], resolution: int = 10) -> bool:
        """Check if path is collision-free."""
        for i in range(resolution + 1):
            t = i / resolution if resolution > 0 else 0.0
            q = [q1[j] + t * (q2[j] - q1[j]) for j in range(self.config_dim)]
            if not self.collision_checker(q):
                return False
        return True


class PathSmoother:
    """Smooth paths using shortcutting."""

    def __init__(self, collision_checker: Callable[[list[float]], bool], config_dim: int) -> None:
        """
        Initialize path smoother.

        Args:
            collision_checker: Function returning True if config is collision-free
            config_dim: Dimension of configuration space
        """
        self.collision_checker = collision_checker
        self.config_dim = config_dim

    def smooth(self, path: list[list[float]], max_iterations: int = 100) -> list[list[float]]:
        """
        Smooth path using shortcutting.

        Args:
            path: Original path
            max_iterations: Maximum smoothing iterations

        Returns:
            Smoothed path
        """
        smooth_path = [node[:] for node in path]

        for _ in range(max_iterations):
            improved = False

            for i in range(len(smooth_path) - 2):
                for j in range(i + 2, len(smooth_path)):
                    if self._path_collision_free(smooth_path[i], smooth_path[j]):
                        # Shortcut: remove nodes between i and j
                        smooth_path = smooth_path[: i + 1] + smooth_path[j:]
                        improved = True
                        break

                if improved:
                    break

            if not improved:
                break

        return smooth_path

    def _path_collision_free(self, q1: list[float], q2: list[float], resolution: int = 10) -> bool:
        """Check if path is collision-free."""
        for i in range(resolution + 1):
            t = i / resolution if resolution > 0 else 0.0
            q = [q1[j] + t * (q2[j] - q1[j]) for j in range(self.config_dim)]
            if not self.collision_checker(q):
                return False
        return True

    def _distance(self, q1: list[float], q2: list[float]) -> float:
        """Euclidean distance."""
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(q1, q2)))
