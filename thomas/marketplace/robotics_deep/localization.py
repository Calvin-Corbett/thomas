"""
Robot localization: odometry, EKF, particle filter, ICP scan matching.
"""

import math

from thomas.marketplace.robotics_deep._types import LaserScan, Pose, Vec3


class OdometryFilter:
    """Dead reckoning with error accumulation."""

    def __init__(self, drift_rate: float = 0.01) -> None:
        """
        Initialize odometry filter.

        Args:
            drift_rate: Odometry drift rate (error per unit distance)
        """
        self.drift_rate = drift_rate
        self.pose = Pose.identity()
        self.accumulated_distance = 0.0

    def update(self, displacement: Vec3, rotation: float, dt: float = 0.01) -> Pose:
        """
        Update pose estimate from odometry.

        Args:
            displacement: Linear displacement
            rotation: Angular displacement (yaw)
            dt: Time step

        Returns:
            Updated pose estimate
        """
        # Accumulate distance for drift tracking
        distance = displacement.magnitude()
        self.accumulated_distance += distance

        # Update position
        roll, pitch, yaw = self.pose.orientation.to_euler()
        new_x = self.pose.position.x + displacement.x
        new_y = self.pose.position.y + displacement.y
        new_z = self.pose.position.z + displacement.z

        # Update orientation
        new_yaw = yaw + rotation

        self.pose.position = Vec3(new_x, new_y, new_z)
        self.pose.orientation = self.pose.orientation.__class__.from_euler(0, 0, new_yaw)

        return self.pose

    def get_covariance(self) -> list[list[float]]:
        """Get pose covariance (growing with distance traveled)."""
        cov = [[0.0] * 3 for _ in range(3)]
        error = self.drift_rate * self.accumulated_distance

        cov[0][0] = error**2  # x uncertainty
        cov[1][1] = error**2  # y uncertainty
        cov[2][2] = (error * 0.5) ** 2  # heading uncertainty

        return cov


class ExtendedKalmanFilterLocalizer:
    """EKF for localization using landmarks."""

    def __init__(self, process_noise: float = 0.01, measurement_noise: float = 0.1) -> None:
        """
        Initialize EKF localizer.

        Args:
            process_noise: Process noise covariance
            measurement_noise: Measurement noise covariance
        """
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise

        # State: [x, y, theta]
        self.state = [0.0, 0.0, 0.0]
        self.covariance = [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 0.1]]

    def predict(self, delta_x: float, delta_y: float, delta_theta: float) -> None:
        """
        Predict step using motion model.

        Args:
            delta_x: Change in x
            delta_y: Change in y
            delta_theta: Change in theta
        """
        # Update state
        self.state[0] += delta_x
        self.state[1] += delta_y
        self.state[2] += delta_theta

        # Update covariance (add process noise)
        for i in range(3):
            self.covariance[i][i] += self.process_noise

    def update(
        self,
        landmark_position: Vec3,
        observed_range: float,
        observed_bearing: float,
    ) -> None:
        """
        Update step using landmark observation.

        Args:
            landmark_position: True landmark position
            observed_range: Measured range to landmark
            observed_bearing: Measured bearing to landmark
        """
        x, y, theta = self.state

        # Expected measurement
        dx = landmark_position.x - x
        dy = landmark_position.y - y
        expected_range = math.sqrt(dx**2 + dy**2)
        expected_bearing = math.atan2(dy, dx) - theta

        # Residuals
        range_residual = observed_range - expected_range
        bearing_residual = observed_bearing - expected_bearing

        # Normalize bearing
        while bearing_residual > math.pi:
            bearing_residual -= 2 * math.pi
        while bearing_residual < -math.pi:
            bearing_residual += 2 * math.pi

        # Kalman gain (simplified diagonal)
        K = [self.covariance[i][i] / (self.covariance[i][i] + self.measurement_noise) for i in range(3)]

        # Update state
        self.state[0] += K[0] * range_residual * math.cos(theta + observed_bearing)
        self.state[1] += K[1] * range_residual * math.sin(theta + observed_bearing)
        self.state[2] += K[2] * bearing_residual

        # Update covariance
        for i in range(3):
            self.covariance[i][i] *= 1 - K[i]

    def get_pose(self) -> Pose:
        """Get pose estimate."""
        from thomas.marketplace.robotics_deep._types import Quaternion

        pos = Vec3(self.state[0], self.state[1], 0)
        orient = Quaternion.from_euler(0, 0, self.state[2])
        return Pose(position=pos, orientation=orient)


class ParticleFilterLocalizer:
    """Particle filter for Monte Carlo localization (imported from SLAM)."""

    def __init__(self, num_particles: int = 100) -> None:
        """Initialize particle filter."""
        self.num_particles = num_particles
        self.particles: list[tuple[float, float, float, float]] = []
        self._initialize_particles()

    def _initialize_particles(self) -> None:
        """Initialize particles uniformly."""
        import random

        self.particles = [
            (
                random.uniform(-10, 10),
                random.uniform(-10, 10),
                random.uniform(-math.pi, math.pi),
                1.0 / self.num_particles,
            )
            for _ in range(self.num_particles)
        ]

    def predict(self, delta_x: float, delta_y: float, delta_theta: float) -> None:
        """Motion update with odometry."""
        import random

        updated = []
        for x, y, theta, w in self.particles:
            noise_scale = 0.05
            new_x = x + delta_x + random.gauss(0, noise_scale)
            new_y = y + delta_y + random.gauss(0, noise_scale)
            new_theta = theta + delta_theta + random.gauss(0, noise_scale * 0.5)
            updated.append((new_x, new_y, new_theta, w))
        self.particles = updated

    def update(self, landmark_position: Vec3, observed_range: float, observed_bearing: float) -> None:
        """Measurement update."""
        for i, (x, y, theta, w) in enumerate(self.particles):
            dx = landmark_position.x - x
            dy = landmark_position.y - y
            expected_range = math.sqrt(dx**2 + dy**2)
            expected_bearing = math.atan2(dy, dx) - theta

            # Likelihood
            range_error = abs(observed_range - expected_range)
            bearing_error = abs(observed_bearing - expected_bearing)

            likelihood = math.exp(-(range_error**2 + bearing_error**2) / (2 * 0.1))
            self.particles[i] = (x, y, theta, w * likelihood)

        # Normalize weights
        total_weight = sum(p[3] for p in self.particles)
        if total_weight > 0:
            self.particles = [(x, y, theta, w / total_weight) for x, y, theta, w in self.particles]

    def resample(self) -> None:
        """Resample particles."""
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
        for i in range(len(self.particles)):
            x, y, theta, _ = self.particles[i]
            self.particles[i] = (x, y, theta, 1.0 / self.num_particles)

    def get_pose(self) -> Pose:
        """Get mean pose."""
        if not self.particles:
            return Pose.identity()

        mean_x = sum(p[0] * p[3] for p in self.particles)
        mean_y = sum(p[1] * p[3] for p in self.particles)
        mean_theta = sum(p[2] * p[3] for p in self.particles)

        from thomas.marketplace.robotics_deep._types import Quaternion

        pos = Vec3(mean_x, mean_y, 0)
        orient = Quaternion.from_euler(0, 0, mean_theta)
        return Pose(position=pos, orientation=orient)


class ICPScanMatcher:
    """Iterative Closest Point (ICP) for scan matching."""

    def __init__(self, max_iterations: int = 20) -> None:
        """
        Initialize ICP matcher.

        Args:
            max_iterations: Maximum ICP iterations
        """
        self.max_iterations = max_iterations

    def match(
        self,
        source_scan: LaserScan,
        target_scan: LaserScan,
        initial_pose: Pose,
    ) -> tuple[float, float, float]:
        """
        Match source scan to target scan.

        Args:
            source_scan: Source laser scan
            target_scan: Target laser scan
            initial_pose: Initial pose estimate

        Returns:
            Tuple of (dx, dy, dtheta) transformation
        """
        # Convert scans to point clouds
        source_points = self._scan_to_points(source_scan, initial_pose)
        target_points = self._scan_to_points(target_scan, Pose.identity())

        if not source_points or not target_points:
            return 0.0, 0.0, 0.0

        # ITC iteration
        pose = initial_pose
        for _ in range(self.max_iterations):
            # Find closest points
            matches = self._find_matches(source_points, target_points)

            if not matches:
                break

            # Compute transformation
            dx, dy, dtheta = self._compute_transform(matches)

            if abs(dx) < 1e-4 and abs(dy) < 1e-4 and abs(dtheta) < 1e-4:
                break

            pose.position.x += dx
            pose.position.y += dy
            roll, pitch, yaw = pose.orientation.to_euler()
            pose.orientation = pose.orientation.__class__.from_euler(0, 0, yaw + dtheta)

        roll, pitch, yaw = pose.orientation.to_euler()
        return pose.position.x - initial_pose.position.x, pose.position.y - initial_pose.position.y, yaw

    def _scan_to_points(self, scan: LaserScan, pose: Pose) -> list[tuple[float, float]]:
        """Convert laser scan to 2D points."""
        points = []
        x = pose.position.x
        y = pose.position.y
        _, _, yaw = pose.orientation.to_euler()

        for range_val, angle in zip(scan.ranges, scan.angles):
            if range_val > 20.0:
                continue
            world_angle = yaw + angle
            px = x + range_val * math.cos(world_angle)
            py = y + range_val * math.sin(world_angle)
            points.append((px, py))

        return points

    def _find_matches(
        self, source: list[tuple[float, float]], target: list[tuple[float, float]]
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """Find closest point matches."""
        matches = []

        for s_point in source:
            closest_t = min(target, key=lambda t: (s_point[0] - t[0]) ** 2 + (s_point[1] - t[1]) ** 2)
            matches.append((s_point, closest_t))

        return matches

    def _compute_transform(
        self, matches: list[tuple[tuple[float, float], tuple[float, float]]]
    ) -> tuple[float, float, float]:
        """Compute transformation from matches."""
        if not matches:
            return 0.0, 0.0, 0.0

        # Mean positions
        source_mean = [
            sum(m[0][0] for m in matches) / len(matches),
            sum(m[0][1] for m in matches) / len(matches),
        ]
        target_mean = [
            sum(m[1][0] for m in matches) / len(matches),
            sum(m[1][1] for m in matches) / len(matches),
        ]

        # Translation
        dx = target_mean[0] - source_mean[0]
        dy = target_mean[1] - source_mean[1]

        # Rotation (simplified)
        num_matches = len(matches)
        if num_matches < 3:
            return dx, dy, 0.0

        numerator = 0.0
        denominator = 0.0
        for m in matches:
            sx_centered = m[0][0] - source_mean[0]
            sy_centered = m[0][1] - source_mean[1]
            tx_centered = m[1][0] - target_mean[0]
            ty_centered = m[1][1] - target_mean[1]

            numerator += sx_centered * ty_centered - sy_centered * tx_centered
            denominator += sx_centered * tx_centered + sy_centered * ty_centered

        dtheta = math.atan2(numerator, denominator) if denominator != 0 else 0.0

        return dx, dy, dtheta
