"""
Path tracking controllers: pure pursuit, Stanley, trajectory generation, waypoint following.
"""

import math

from thomas.marketplace.robotics_deep._types import Pose, Vec3


class PurePursuit:
    """Pure pursuit path tracking algorithm."""

    def __init__(self, lookahead_distance: float = 1.0) -> None:
        """
        Initialize pure pursuit controller.

        Args:
            lookahead_distance: Distance to lookahead point
        """
        self.lookahead_distance = lookahead_distance

    def compute_steering(self, current_pose: Pose, path: list[Vec3], vehicle_length: float = 0.3) -> float:
        """
        Compute steering angle to follow path.

        Args:
            current_pose: Current robot pose
            path: List of waypoints
            vehicle_length: Distance from front axle to rear axle

        Returns:
            Steering angle in radians
        """
        x = current_pose.position.x
        y = current_pose.position.y
        roll, pitch, yaw = current_pose.orientation.to_euler()

        # Find closest point on path
        closest_idx = 0
        closest_dist = float("inf")

        for i, waypoint in enumerate(path):
            dist = math.sqrt((x - waypoint.x) ** 2 + (y - waypoint.y) ** 2)
            if dist < closest_dist:
                closest_dist = dist
                closest_idx = i

        # Find lookahead point
        lookahead_point = None
        for i in range(closest_idx, len(path)):
            waypoint = path[i]
            dist = math.sqrt((x - waypoint.x) ** 2 + (y - waypoint.y) ** 2)
            if dist >= self.lookahead_distance:
                lookahead_point = waypoint
                break

        if lookahead_point is None:
            if path:
                lookahead_point = path[-1]
            else:
                return 0.0

        # Calculate steering angle using pure pursuit law
        dx = lookahead_point.x - x
        dy = lookahead_point.y - y
        distance = math.sqrt(dx**2 + dy**2)

        if distance < 1e-6:
            return 0.0

        # Cross track error
        target_angle = math.atan2(dy, dx)
        cross_track = math.sin(target_angle - yaw) * distance

        # Pure pursuit steering law
        steering = math.atan(2 * vehicle_length * cross_track / (distance**2))

        return steering


class StanleyController:
    """Stanley controller for path tracking."""

    def __init__(self, gain: float = 1.0, damping: float = 0.5) -> None:
        """
        Initialize Stanley controller.

        Args:
            gain: Cross-track error gain
            damping: Heading error damping
        """
        self.gain = gain
        self.damping = damping

    def compute_steering(self, current_pose: Pose, path: list[Vec3], speed: float = 1.0) -> float:
        """
        Compute steering angle using Stanley method.

        Args:
            current_pose: Current robot pose
            path: List of waypoints
            speed: Current vehicle speed

        Returns:
            Steering angle in radians
        """
        x = current_pose.position.x
        y = current_pose.position.y
        roll, pitch, yaw = current_pose.orientation.to_euler()

        # Find closest point on path
        closest_segment = 0
        min_dist = float("inf")

        for i in range(len(path) - 1):
            p1 = path[i]
            p2 = path[i + 1]

            # Distance from point to line segment
            dist = self._point_to_segment_distance(x, y, p1.x, p1.y, p2.x, p2.y)

            if dist < min_dist:
                min_dist = dist
                closest_segment = i

        # Path tangent angle
        if closest_segment < len(path) - 1:
            p1 = path[closest_segment]
            p2 = path[closest_segment + 1]
            path_angle = math.atan2(p2.y - p1.y, p2.x - p1.x)
        else:
            path_angle = yaw

        # Heading error
        heading_error = path_angle - yaw

        # Normalize
        while heading_error > math.pi:
            heading_error -= 2 * math.pi
        while heading_error < -math.pi:
            heading_error += 2 * math.pi

        # Cross-track error
        if closest_segment < len(path) - 1:
            p1 = path[closest_segment]
            p2 = path[closest_segment + 1]
            cte = self._signed_distance(x, y, p1.x, p1.y, p2.x, p2.y)
        else:
            cte = 0.0

        # Stanley law
        steering = heading_error + math.atan(self.gain * cte / (speed + 0.1))

        return steering

    def _point_to_segment_distance(self, x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> float:
        """Distance from point to line segment."""
        dx = x2 - x1
        dy = y2 - y1
        t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx**2 + dy**2 + 1e-6)))
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        return math.sqrt((x - closest_x) ** 2 + (y - closest_y) ** 2)

    def _signed_distance(self, x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> float:
        """Signed distance from point to line."""
        return ((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1) / (math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2) + 1e-6)


class TrajectoryGenerator:
    """Generate smooth trajectories with velocity profiles."""

    def __init__(self) -> None:
        """Initialize trajectory generator."""
        pass

    def trapezoidal_profile(
        self,
        start: float,
        goal: float,
        max_velocity: float = 1.0,
        max_acceleration: float = 0.5,
    ) -> list[tuple[float, float, float]]:
        """
        Generate trapezoidal velocity profile.

        Args:
            start: Start position
            goal: Goal position
            max_velocity: Maximum velocity
            max_acceleration: Maximum acceleration

        Returns:
            List of (position, velocity, time)
        """
        distance = abs(goal - start)
        sign = 1 if goal > start else -1

        # Acceleration time
        t_accel = max_velocity / max_acceleration
        accel_distance = 0.5 * max_acceleration * t_accel**2

        # Total distance at max velocity
        if 2 * accel_distance >= distance:
            # Triangular profile (no constant velocity phase)
            t_accel = math.sqrt(distance / max_acceleration)
            t_coast = 0.0
            t_decel = t_accel
        else:
            # Trapezoidal profile
            t_coast = (distance - 2 * accel_distance) / max_velocity
            t_decel = t_accel

        # Generate trajectory
        trajectory = []
        dt = 0.01
        t = 0.0

        while t <= t_accel + t_coast + t_decel:
            if t <= t_accel:
                # Acceleration phase
                pos = start + 0.5 * sign * max_acceleration * t**2
                vel = sign * max_acceleration * t
            elif t <= t_accel + t_coast:
                # Constant velocity phase
                t_rel = t - t_accel
                pos = start + sign * (accel_distance + max_velocity * t_rel)
                vel = sign * max_velocity
            else:
                # Deceleration phase
                t_rel = t - t_accel - t_coast
                pos = start + sign * (
                    accel_distance + max_velocity * t_coast + max_velocity * t_rel - 0.5 * max_acceleration * t_rel**2
                )
                vel = sign * (max_velocity - max_acceleration * t_rel)

            trajectory.append((pos, vel, t))
            t += dt

        return trajectory

    def quintic_polynomial(
        self,
        start: float,
        goal: float,
        duration: float,
        start_vel: float = 0.0,
        goal_vel: float = 0.0,
    ) -> list[tuple[float, float, float]]:
        """
        Generate quintic polynomial trajectory.

        Args:
            start: Start position
            goal: Goal position
            duration: Total duration
            start_vel: Starting velocity
            goal_vel: Goal velocity

        Returns:
            List of (position, velocity, time)
        """
        # Quintic: p(t) = a0 + a1*t + a2*t^2 + a3*t^3 + a4*t^4 + a5*t^5
        # Conditions: p(0)=start, v(0)=start_vel, p(T)=goal, v(T)=goal_vel, a(0)=0, a(T)=0

        T = duration
        a0 = start
        a1 = start_vel
        a2 = 0.0

        # Solve for a3, a4, a5
        A = [[T**3, T**4, T**5], [3 * T**2, 4 * T**3, 5 * T**4], [6 * T, 12 * T**2, 20 * T**3]]
        b = [goal - start - start_vel * T, goal_vel - start_vel, 0.0]

        # Simple 3x3 solver
        det = (
            A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
            - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
            + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0])
        )

        if abs(det) < 1e-10:
            return []

        a3 = (
            b[0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
            - A[0][1] * (b[1] * A[2][2] - A[1][2] * b[2])
            + A[0][2] * (b[1] * A[2][1] - A[1][1] * b[2])
        ) / det

        a4 = (
            A[0][0] * (b[1] * A[2][2] - A[1][2] * b[2])
            - b[0] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
            + A[0][2] * (A[1][0] * b[2] - b[1] * A[2][0])
        ) / det

        a5 = (
            A[0][0] * (A[1][1] * b[2] - b[1] * A[2][1])
            - A[0][1] * (A[1][0] * b[2] - b[1] * A[2][0])
            + b[0] * (A[1][0] * A[2][1] - A[1][1] * A[2][0])
        ) / det

        # Generate trajectory
        trajectory = []
        dt = T / 100
        for i in range(101):
            t = i * dt
            pos = a0 + a1 * t + a2 * t**2 + a3 * t**3 + a4 * t**4 + a5 * t**5
            vel = a1 + 2 * a2 * t + 3 * a3 * t**2 + 4 * a4 * t**3 + 5 * a5 * t**4
            trajectory.append((pos, vel, t))

        return trajectory


class WaypointFollower:
    """Follow sequence of waypoints."""

    def __init__(self, lookahead_distance: float = 1.0) -> None:
        """
        Initialize waypoint follower.

        Args:
            lookahead_distance: Distance to lookahead waypoint
        """
        self.pure_pursuit = PurePursuit(lookahead_distance)
        self.current_waypoint_idx = 0

    def compute_steering(
        self,
        current_pose: Pose,
        waypoints: list[Vec3],
        vehicle_length: float = 0.3,
    ) -> float:
        """
        Compute steering to follow waypoints.

        Args:
            current_pose: Current robot pose
            waypoints: List of waypoints
            vehicle_length: Vehicle length

        Returns:
            Steering angle
        """
        if not waypoints:
            return 0.0

        # Use pure pursuit with remaining waypoints
        remaining_waypoints = waypoints[self.current_waypoint_idx :]

        if not remaining_waypoints:
            return 0.0

        # Check if reached current waypoint
        x = current_pose.position.x
        y = current_pose.position.y
        if self.current_waypoint_idx < len(waypoints):
            wp = waypoints[self.current_waypoint_idx]
            dist_to_wp = math.sqrt((x - wp.x) ** 2 + (y - wp.y) ** 2)
            if dist_to_wp < 0.2:  # Reached waypoint
                self.current_waypoint_idx += 1
                if self.current_waypoint_idx >= len(waypoints):
                    return 0.0

        steering = self.pure_pursuit.compute_steering(current_pose, remaining_waypoints, vehicle_length)

        return steering

    def reset(self) -> None:
        """Reset to first waypoint."""
        self.current_waypoint_idx = 0
