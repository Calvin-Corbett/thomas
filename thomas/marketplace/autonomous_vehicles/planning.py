"""Path and motion planning for autonomous vehicles.

Includes global planning (A*), local planning (lattice planner),
trajectory optimization, lane change planning, and intersection navigation.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from thomas.marketplace.autonomous_vehicles._exceptions import NoPathFoundException
from thomas.marketplace.autonomous_vehicles._types import (
    Obstacle,
    PlannerConfig,
    Route,
    Vector2D,
    VehicleState,
    Waypoint,
)


@dataclass
class TrajectoryPoint:
    """Point along a trajectory."""

    x: float
    y: float
    theta: float
    v: float
    a: float
    t: float

    def to_waypoint(self: TrajectoryPoint) -> Waypoint:
        """Convert to waypoint."""
        return Waypoint(
            position=Vector2D(self.x, self.y),
            heading=self.theta,
            speed_limit=self.v,
            timestamp=self.t,
        )


@dataclass
class Trajectory:
    """Trajectory consisting of trajectory points."""

    points: list[TrajectoryPoint]
    cost: float = 0.0

    def length(self: Trajectory) -> float:
        """Compute trajectory length."""
        if len(self.points) < 2:
            return 0.0
        total = 0.0
        for i in range(len(self.points) - 1):
            dx = self.points[i + 1].x - self.points[i].x
            dy = self.points[i + 1].y - self.points[i].y
            total += np.sqrt(dx**2 + dy**2)
        return total

    def duration(self: Trajectory) -> float:
        """Get trajectory duration."""
        if len(self.points) < 2:
            return 0.0
        return self.points[-1].t - self.points[0].t

    def compute_jerk(self: Trajectory) -> float:
        """Compute total jerk along trajectory."""
        if len(self.points) < 3:
            return 0.0

        jerk_total = 0.0
        for i in range(1, len(self.points) - 1):
            da = self.points[i + 1].a - self.points[i - 1].a
            dt = self.points[i + 1].t - self.points[i - 1].t
            if dt > 1e-6:
                jerk = da / dt
                jerk_total += abs(jerk)

        return jerk_total


class GlobalPlanner:
    """Global path planner using A* on road network."""

    def __init__(self: GlobalPlanner) -> None:
        """Initialize global planner."""
        self.road_graph: dict[str, list[str]] = {}
        self.waypoints_map: dict[str, Vector2D] = {}

    def add_road_segment(
        self: GlobalPlanner, start_id: str, end_id: str, start_pos: Vector2D, end_pos: Vector2D
    ) -> None:
        """Add road segment to graph.

        Args:
            start_id: Start waypoint ID
            end_id: End waypoint ID
            start_pos: Start position
            end_pos: End position
        """
        if start_id not in self.road_graph:
            self.road_graph[start_id] = []
        if end_id not in self.road_graph:
            self.road_graph[end_id] = []

        self.road_graph[start_id].append(end_id)
        self.waypoints_map[start_id] = start_pos
        self.waypoints_map[end_id] = end_pos

    def plan(self: GlobalPlanner, start_id: str, goal_id: str) -> Route | None:
        """Plan global path using A*.

        Args:
            start_id: Start waypoint ID
            goal_id: Goal waypoint ID

        Returns:
            Route from start to goal, or None if no path exists
        """
        if start_id not in self.road_graph or goal_id not in self.road_graph:
            return None

        # A* search
        open_set = [(0.0, start_id)]
        came_from: dict[str, str] = {}
        g_score: dict[str, float] = {node: float("inf") for node in self.road_graph}
        g_score[start_id] = 0.0

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == goal_id:
                # Reconstruct path
                path = []
                node = current
                while node in came_from:
                    path.append(node)
                    node = came_from[node]
                path.append(start_id)
                path.reverse()

                # Convert path to waypoints
                waypoints: list[Waypoint] = []
                for idx, node in enumerate(path):
                    position = self.waypoints_map[node]
                    if idx + 1 < len(path):
                        next_position = self.waypoints_map[path[idx + 1]]
                        heading = np.arctan2(
                            next_position.y - position.y,
                            next_position.x - position.x,
                        )
                    elif idx > 0:
                        prev_position = self.waypoints_map[path[idx - 1]]
                        heading = np.arctan2(
                            position.y - prev_position.y,
                            position.x - prev_position.x,
                        )
                    else:
                        heading = 0.0

                    waypoints.append(Waypoint(position=position, heading=float(heading)))
                return Route(waypoints=waypoints)

            for neighbor in self.road_graph.get(current, []):
                current_pos = self.waypoints_map[current]
                neighbor_pos = self.waypoints_map[neighbor]
                cost = current_pos.distance_to(neighbor_pos)

                tentative_g = g_score[current] + cost
                if tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g

                    # Heuristic: distance to goal
                    h = neighbor_pos.distance_to(self.waypoints_map[goal_id])
                    f = tentative_g + h

                    heapq.heappush(open_set, (f, neighbor))

        return None


class LatticeTrajectoryGenerator:
    """Generate trajectory samples using lattice planner."""

    def __init__(self: LatticeTrajectoryGenerator, config: PlannerConfig) -> None:
        """Initialize lattice planner.

        Args:
            config: Planner configuration
        """
        self.config = config

    def generate_trajectories(
        self: LatticeTrajectoryGenerator,
        vehicle_state: VehicleState,
        target_speed: float,
        planning_horizon: float = 5.0,
    ) -> list[Trajectory]:
        """Generate candidate trajectories.

        Args:
            vehicle_state: Current vehicle state
            target_speed: Target longitudinal speed
            planning_horizon: Planning horizon in seconds

        Returns:
            List of candidate trajectories
        """
        trajectories = []
        num_steps = int(planning_horizon * self.config.planning_frequency)

        # Lateral offset targets
        lateral_targets = np.linspace(-2.0, 2.0, 5)

        for lat_target in lateral_targets:
            points = []

            # Initial point
            points.append(
                TrajectoryPoint(
                    x=vehicle_state.position.x,
                    y=vehicle_state.position.y,
                    theta=vehicle_state.heading,
                    v=vehicle_state.speed,
                    a=0.0,
                    t=vehicle_state.timestamp,
                )
            )

            # Simulate trajectory
            x, y = vehicle_state.position.x, vehicle_state.position.y
            theta = vehicle_state.heading
            v = vehicle_state.speed

            for step in range(num_steps):
                dt = 1.0 / self.config.planning_frequency
                t = vehicle_state.timestamp + (step + 1) * dt

                # Longitudinal acceleration
                a = (target_speed - v) * 0.5  # Simple proportional control

                # Lateral control to reach target
                current_lat = y - np.sin(theta) * x
                error = lat_target - current_lat
                steering = np.clip(error * 0.1, -self.config.max_steering_angle, self.config.max_steering_angle)

                # Update state using bicycle model
                v = np.clip(v + a * dt, 0.0, self.config.max_speed)

                if v > 0.1:
                    dtheta = v * np.tan(steering) / self.config.wheelbase
                else:
                    dtheta = 0.0

                x += v * np.cos(theta) * dt
                y += v * np.sin(theta) * dt
                theta += dtheta * dt

                # Normalize heading
                theta = self._normalize_angle(theta)

                points.append(
                    TrajectoryPoint(
                        x=x,
                        y=y,
                        theta=theta,
                        v=v,
                        a=a,
                        t=t,
                    )
                )

            trajectory = Trajectory(points=points)
            trajectories.append(trajectory)

        return trajectories

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Normalize angle to [-pi, pi]."""
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle


class TrajectoryOptimizer:
    """Optimize trajectories to minimize jerk and cost."""

    def __init__(self: TrajectoryOptimizer) -> None:
        """Initialize trajectory optimizer."""
        pass

    def optimize(
        self: TrajectoryOptimizer,
        trajectory: Trajectory,
        obstacles: list[Obstacle],
        vehicle_width: float = 1.8,
    ) -> Trajectory:
        """Optimize trajectory.

        Args:
            trajectory: Input trajectory
            obstacles: Detected obstacles
            vehicle_width: Vehicle width

        Returns:
            Optimized trajectory
        """
        # Do not mutate input trajectories in place; callers may reuse them.
        optimized = Trajectory(points=list(trajectory.points), cost=0.0)

        # Check collision
        for point in optimized.points:
            for obstacle in obstacles:
                dx = point.x - obstacle.position.x
                dy = point.y - obstacle.position.y
                dist = np.sqrt(dx**2 + dy**2)

                min_dist = (vehicle_width + obstacle.width) / 2 + 0.5

                if dist < min_dist:
                    # Collision detected, penalize
                    optimized.cost += 100.0

        # Penalize jerk
        jerk = optimized.compute_jerk()
        optimized.cost += jerk * 0.1

        return optimized


class LaneChangePlanner:
    """Plan lane change maneuvers."""

    def __init__(self: LaneChangePlanner) -> None:
        """Initialize lane change planner."""
        self.gap_acceptance_threshold = 10.0  # meters

    def plan_lane_change(
        self: LaneChangePlanner,
        vehicle_state: VehicleState,
        target_lane_offset: float,
        obstacles: list[Obstacle],
        config: PlannerConfig,
    ) -> Trajectory | None:
        """Plan lane change trajectory.

        Args:
            vehicle_state: Current vehicle state
            target_lane_offset: Target lateral offset
            obstacles: Detected obstacles
            config: Planner configuration

        Returns:
            Lane change trajectory or None if not safe
        """
        # Check for sufficient gap
        for obstacle in obstacles:
            if abs(obstacle.position.y - vehicle_state.position.y) < 1.5:
                dist_to_front = obstacle.position.x - vehicle_state.position.x

                if 0 < dist_to_front < self.gap_acceptance_threshold:
                    return None  # Not safe to change lanes

        # Generate lane change trajectory
        num_steps = int(4.0 * config.planning_frequency)  # 4 second maneuver
        points = []

        for step in range(num_steps):
            dt = 1.0 / config.planning_frequency
            t = vehicle_state.timestamp + step * dt

            # Linear interpolation for lateral position
            progress = step / max(1, num_steps - 1)
            lateral_pos = vehicle_state.position.y + (target_lane_offset - vehicle_state.position.y) * progress

            x = vehicle_state.position.x + vehicle_state.speed * t * progress
            y = lateral_pos
            theta = vehicle_state.heading

            points.append(
                TrajectoryPoint(
                    x=x,
                    y=y,
                    theta=theta,
                    v=vehicle_state.speed,
                    a=0.0,
                    t=t,
                )
            )

        return Trajectory(points=points)


class MotionPlanner:
    """Complete motion planning system."""

    def __init__(self: MotionPlanner, config: PlannerConfig) -> None:
        """Initialize motion planner.

        Args:
            config: Planner configuration
        """
        self.config = config
        self.global_planner = GlobalPlanner()
        self.lattice_generator = LatticeTrajectoryGenerator(config)
        self.trajectory_optimizer = TrajectoryOptimizer()
        self.lane_change_planner = LaneChangePlanner()

    def plan(
        self: MotionPlanner,
        vehicle_state: VehicleState,
        goal_position: Vector2D,
        obstacles: list[Obstacle],
        current_route: Route | None = None,
    ) -> Trajectory:
        """Plan motion for vehicle.

        Args:
            vehicle_state: Current vehicle state
            goal_position: Goal position
            obstacles: Detected obstacles
            current_route: Current planned route

        Returns:
            Planned trajectory

        Raises:
            NoPathFoundException: If no valid trajectory found
        """
        # Generate candidate trajectories
        target_speed = min(self.config.max_speed, 25.0)
        candidates = self.lattice_generator.generate_trajectories(
            vehicle_state,
            target_speed,
            planning_horizon=self.config.prediction_horizon,
        )

        if not candidates:
            raise NoPathFoundException("No candidate trajectories generated")

        # Evaluate and select best trajectory
        best_trajectory = None
        best_cost = float("inf")

        for trajectory in candidates:
            # Optimize trajectory
            optimized = self.trajectory_optimizer.optimize(trajectory, obstacles, self.config.vehicle_width)

            if optimized.cost < best_cost:
                best_cost = optimized.cost
                best_trajectory = optimized

        if best_trajectory is None:
            raise NoPathFoundException("No valid trajectory found")

        return best_trajectory
