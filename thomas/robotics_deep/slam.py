"""
SLAM: Simultaneous Localization and Mapping.
Includes EKF-SLAM, occupancy grid mapping, and particle filter localization.
"""

import math

from thomas.robotics_deep._types import LaserScan, OccupancyGrid, Pose, Vec3


class EKFSLAMFilter:
    """Extended Kalman Filter SLAM."""

    def __init__(self, num_landmarks: int = 10, process_noise: float = 0.01) -> None:
        """
        Initialize EKF-SLAM filter.

        Args:
            num_landmarks: Maximum number of landmarks to track
            process_noise: Process noise covariance
        """
        self.num_landmarks = num_landmarks
        self.process_noise = process_noise

        # State: [x, y, theta, landmark1_x, landmark1_y, ...]
        state_dim = 3 + 2 * num_landmarks
        self.state = [0.0] * state_dim
        self.covariance = self._init_covariance(state_dim)
        self.seen_landmarks = set()

    def _init_covariance(self, dim: int) -> list[list[float]]:
        """Initialize covariance matrix."""
        cov = [[0.0] * dim for _ in range(dim)]
        # Initial pose uncertainty
        for i in range(3):
            cov[i][i] = 0.1
        # Landmark uncertainty
        for i in range(3, dim):
            cov[i][i] = 1e6  # Unknown landmarks
        return cov

    def predict(self, delta_x: float, delta_y: float, delta_theta: float, dt: float = 1.0) -> None:
        """
        Predict step: update pose based on motion.

        Args:
            delta_x: Change in x
            delta_y: Change in y
            delta_theta: Change in theta
            dt: Time step
        """
        # Simple motion model: add motion to pose
        self.state[0] += delta_x
        self.state[1] += delta_y
        self.state[2] += delta_theta

        # Add process noise to covariance
        for i in range(3):
            self.covariance[i][i] += self.process_noise

    def update(self, landmark_id: int, range_obs: float, bearing_obs: float) -> None:
        """
        Update step: incorporate landmark observation.

        Args:
            landmark_id: Observed landmark ID
            range_obs: Range to landmark
            bearing_obs: Bearing to landmark (relative to robot heading)
        """
        x = self.state[0]
        y = self.state[1]
        theta = self.state[2]

        # Landmark position index
        lm_idx = 3 + 2 * landmark_id

        if landmark_id not in self.seen_landmarks:
            # Initialize new landmark
            lm_x = x + range_obs * math.cos(theta + bearing_obs)
            lm_y = y + range_obs * math.sin(theta + bearing_obs)
            self.state[lm_idx] = lm_x
            self.state[lm_idx + 1] = lm_y
            self.seen_landmarks.add(landmark_id)
        else:
            # Update existing landmark
            lm_x = self.state[lm_idx]
            lm_y = self.state[lm_idx + 1]

            # Expected observation
            dx = lm_x - x
            dy = lm_y - y
            expected_range = math.sqrt(dx**2 + dy**2)
            expected_bearing = math.atan2(dy, dx) - theta

            # Observation residual
            range_residual = range_obs - expected_range
            bearing_residual = bearing_obs - expected_bearing

            # Normalize bearing residual
            while bearing_residual > math.pi:
                bearing_residual -= 2 * math.pi
            while bearing_residual < -math.pi:
                bearing_residual += 2 * math.pi

            # Simplified Kalman gain (diagonal approximation)
            measurement_noise = 0.1
            K_range = self.covariance[0][0] / (self.covariance[0][0] + measurement_noise)
            K_bearing = self.covariance[2][2] / (self.covariance[2][2] + measurement_noise)

            # State update
            self.state[0] += K_range * range_residual * math.cos(theta + bearing_obs)
            self.state[1] += K_range * range_residual * math.sin(theta + bearing_obs)
            self.state[2] += K_bearing * bearing_residual

            # Landmark update
            self.state[lm_idx] += K_range * range_residual * math.cos(theta + bearing_obs)
            self.state[lm_idx + 1] += K_range * range_residual * math.sin(theta + bearing_obs)

    def get_pose(self) -> Pose:
        """Get current robot pose estimate."""
        pos = Vec3(self.state[0], self.state[1], 0)
        from thomas.robotics_deep._types import Quaternion

        orient = Quaternion.from_euler(0, 0, self.state[2])
        return Pose(position=pos, orientation=orient)

    def get_landmarks(self) -> list[Vec3]:
        """Get estimated landmark positions."""
        landmarks = []
        for i in self.seen_landmarks:
            lm_idx = 3 + 2 * i
            if lm_idx + 1 < len(self.state):
                landmarks.append(Vec3(self.state[lm_idx], self.state[lm_idx + 1], 0))
        return landmarks


class OccupancyGridMapper:
    """Map building using laser scans with occupancy grid."""

    def __init__(self, grid: OccupancyGrid, max_range: float = 10.0) -> None:
        """
        Initialize occupancy grid mapper.

        Args:
            grid: Occupancy grid to update
            max_range: Maximum range for sensor
        """
        self.grid = grid
        self.max_range = max_range

    def update(self, scan: LaserScan, robot_pose: Pose) -> None:
        """
        Update occupancy grid with laser scan.

        Args:
            scan: Laser scan data
            robot_pose: Robot pose when scan was taken
        """
        x = robot_pose.position.x
        y = robot_pose.position.y
        roll, pitch, yaw = robot_pose.orientation.to_euler()

        for range_val, angle in zip(scan.ranges, scan.angles):
            if range_val > self.max_range:
                continue

            # Ray end point
            world_angle = yaw + angle
            hit_x = x + range_val * math.cos(world_angle)
            hit_y = y + range_val * math.sin(world_angle)

            # Ray cast: mark free cells
            self._ray_cast(x, y, hit_x, hit_y, occupied=False)

            # Mark hit cell as occupied
            self.grid.set_cell(hit_x, hit_y, 0.9)

    def _ray_cast(self, x1: float, y1: float, x2: float, y2: float, occupied: bool) -> None:
        """
        Ray cast using Bresenham-like algorithm.

        Args:
            x1: Ray start x
            y1: Ray start y
            x2: Ray end x
            y2: Ray end y
            occupied: Mark cells as occupied (True) or free (False)
        """
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        steps = max(int(dx / self.grid.resolution), int(dy / self.grid.resolution)) + 1

        for i in range(steps):
            t = i / steps if steps > 0 else 0
            cx = x1 + t * (x2 - x1)
            cy = y1 + t * (y2 - y1)

            value = 0.2 if occupied else 0.2
            self.grid.set_cell(cx, cy, 0.3)  # Mark as free


class ParticleFilterLocalizer:
    """Particle filter for Monte Carlo localization."""

    def __init__(self, num_particles: int = 100) -> None:
        """
        Initialize particle filter.

        Args:
            num_particles: Number of particles for localization
        """
        self.num_particles = num_particles
        self.particles: list[tuple[float, float, float, float]] = []  # x, y, theta, weight
        self._initialize_particles()

    def _initialize_particles(self) -> None:
        """Initialize particles uniformly."""
        import random

        self.particles = [
            (
                random.uniform(-5, 5),
                random.uniform(-5, 5),
                random.uniform(-math.pi, math.pi),
                1.0 / self.num_particles,
            )
            for _ in range(self.num_particles)
        ]

    def predict(self, delta_x: float, delta_y: float, delta_theta: float) -> None:
        """
        Motion update: propagate particles.

        Args:
            delta_x: Change in x
            delta_y: Change in y
            delta_theta: Change in theta
        """
        import random

        updated = []
        for x, y, theta, w in self.particles:
            # Add noise to motion
            noise_scale = 0.01
            new_x = x + delta_x + random.gauss(0, noise_scale)
            new_y = y + delta_y + random.gauss(0, noise_scale)
            new_theta = theta + delta_theta + random.gauss(0, noise_scale * 0.5)

            updated.append((new_x, new_y, new_theta, w))

        self.particles = updated

    def update(self, scan: LaserScan, grid: OccupancyGrid) -> None:
        """
        Measurement update: weight particles by likelihood.

        Args:
            scan: Laser scan observation
            grid: Occupancy grid for likelihood
        """
        import math as m

        for i, (x, y, theta, w) in enumerate(self.particles):
            likelihood = 1.0

            for range_val, angle in zip(scan.ranges, scan.angles):
                if range_val > 10.0:
                    continue

                # Ray end in world frame
                world_angle = theta + angle
                hit_x = x + range_val * m.cos(world_angle)
                hit_y = y + range_val * m.sin(world_angle)

                # Likelihood from grid
                occupancy = grid.get_cell(hit_x, hit_y)
                likelihood *= occupancy if occupancy > 0.5 else 1 - occupancy

            self.particles[i] = (x, y, theta, w * likelihood)

        # Normalize weights
        total_weight = sum(p[3] for p in self.particles)
        if total_weight > 0:
            self.particles = [(x, y, theta, w / total_weight) for x, y, theta, w in self.particles]

    def resample(self) -> None:
        """Resample particles based on weights."""
        import random

        weights = [p[3] for p in self.particles]
        indices = []

        cumsum = 0.0
        for _ in range(self.num_particles):
            rand = random.random()
            cumsum = 0.0
            for j, w in enumerate(weights):
                cumsum += w
                if rand <= cumsum:
                    indices.append(j)
                    break

        self.particles = [self.particles[i] for i in indices]
        # Reset weights uniformly
        for i in range(len(self.particles)):
            x, y, theta, _ = self.particles[i]
            self.particles[i] = (x, y, theta, 1.0 / self.num_particles)

    def get_pose(self) -> Pose:
        """Get mean pose estimate."""
        if not self.particles:
            return Pose.identity()

        # Mean position
        mean_x = sum(p[0] * p[3] for p in self.particles)
        mean_y = sum(p[1] * p[3] for p in self.particles)
        mean_theta = sum(p[2] * p[3] for p in self.particles)

        from thomas.robotics_deep._types import Quaternion

        pos = Vec3(mean_x, mean_y, 0)
        orient = Quaternion.from_euler(0, 0, mean_theta)
        return Pose(position=pos, orientation=orient)
