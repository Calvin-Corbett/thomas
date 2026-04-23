"""Localization system for autonomous vehicles.

Includes Extended Kalman Filter, GPS/IMU fusion, wheel odometry integration,
map matching, and particle filter localization.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thomas.marketplace.autonomous_vehicles._exceptions import LocalizationDriftException
from thomas.marketplace.autonomous_vehicles._types import (
    Vector2D,
    VehicleState,
)


@dataclass
class EKFState:
    """Extended Kalman Filter state."""

    x: np.ndarray  # State vector [x, y, theta, vx, vy, dtheta]
    P: np.ndarray  # Covariance matrix (6x6)
    Q: np.ndarray  # Process noise covariance
    R: np.ndarray  # Measurement noise covariance
    timestamp: float = 0.0

    def get_position(self: EKFState) -> Vector2D:
        """Get position from state."""
        return Vector2D(float(self.x[0]), float(self.x[1]))

    def get_heading(self: EKFState) -> float:
        """Get heading from state."""
        return float(self.x[2])

    def get_velocity(self: EKFState) -> Vector2D:
        """Get velocity from state."""
        return Vector2D(float(self.x[3]), float(self.x[4]))


class ExtendedKalmanFilter:
    """Extended Kalman Filter for pose estimation."""

    def __init__(
        self: ExtendedKalmanFilter,
        wheelbase: float = 2.7,
        process_noise: float = 0.1,
        measurement_noise: float = 0.5,
    ) -> None:
        """Initialize Extended Kalman Filter.

        Args:
            wheelbase: Vehicle wheelbase
            process_noise: Process noise standard deviation
            measurement_noise: Measurement noise standard deviation
        """
        self.wheelbase = wheelbase
        self.process_noise_std = process_noise
        self.measurement_noise_std = measurement_noise

        # Initialize state
        self.state = EKFState(
            x=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            P=np.eye(6) * 0.1,
            Q=np.eye(6) * (process_noise**2),
            R=np.eye(2) * (measurement_noise**2),
        )

    def predict(
        self: ExtendedKalmanFilter,
        acceleration: float,
        steering_angle: float,
        dt: float,
    ) -> None:
        """Predict state using motion model.

        Args:
            acceleration: Longitudinal acceleration (m/s^2)
            steering_angle: Steering angle (radians)
            dt: Time step (seconds)
        """
        x = self.state.x

        # Kinematic bicycle model
        v = np.sqrt(x[3] ** 2 + x[4] ** 2)

        # Limit velocity based on acceleration
        v_new = max(0.0, v + acceleration * dt)

        # Update heading rate using bicycle model
        if v_new > 0.1:
            dtheta = v_new * np.tan(steering_angle) / self.wheelbase
        else:
            dtheta = 0.0

        # Update state
        x_new = x.copy()
        x_new[0] += v_new * np.cos(x[2]) * dt  # x position
        x_new[1] += v_new * np.sin(x[2]) * dt  # y position
        x_new[2] += dtheta * dt  # heading
        x_new[3] = v_new * np.cos(x[2])  # vx
        x_new[4] = v_new * np.sin(x[2])  # vy
        x_new[5] = dtheta  # heading rate

        # Normalize heading to [-pi, pi]
        x_new[2] = self._normalize_angle(x_new[2])

        # Compute Jacobian of motion model
        F = self._compute_motion_jacobian(x, acceleration, steering_angle, dt)

        # Predict covariance
        P_new = F @ self.state.P @ F.T + self.state.Q

        self.state.x = x_new
        self.state.P = P_new

    def update(
        self: ExtendedKalmanFilter,
        measurement: np.ndarray,
        measurement_type: str = "position",
    ) -> None:
        """Update state with measurement.

        Args:
            measurement: Measurement vector
            measurement_type: Type of measurement (position, velocity, heading)
        """
        if measurement_type == "position":
            # Position measurement [x, y]
            H = np.array([[1, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0]])
            z = measurement[:2]
        elif measurement_type == "velocity":
            # Velocity measurement [vx, vy]
            H = np.array([[0, 0, 0, 1, 0, 0], [0, 0, 0, 0, 1, 0]])
            z = measurement[:2]
        elif measurement_type == "heading":
            # Heading measurement
            H = np.array([[0, 0, 1, 0, 0, 0]])
            z = np.array([self._normalize_angle(measurement[0])])
        else:
            raise ValueError(f"Unknown measurement type: {measurement_type}")

        # Innovation
        z_pred = H @ self.state.x
        y = z - z_pred

        # Normalize heading innovation
        if measurement_type == "heading":
            y[0] = self._normalize_angle(y[0])

        # Innovation covariance
        S = H @ self.state.P @ H.T + self.state.R

        # Kalman gain
        K = self.state.P @ H.T @ np.linalg.inv(S)

        # Update state
        self.state.x = self.state.x + K @ y

        # Update covariance
        I_KH = np.eye(6) - K @ H
        self.state.P = I_KH @ self.state.P

        # Normalize heading
        self.state.x[2] = self._normalize_angle(self.state.x[2])

    def _compute_motion_jacobian(
        self: ExtendedKalmanFilter,
        x: np.ndarray,
        acceleration: float,
        steering_angle: float,
        dt: float,
    ) -> np.ndarray:
        """Compute Jacobian of motion model."""
        F = np.eye(6)

        # Position derivatives
        v = np.sqrt(x[3] ** 2 + x[4] ** 2)
        v_new = max(0.0, v + acceleration * dt)

        F[0, 2] = -v_new * np.sin(x[2]) * dt
        F[0, 3] = np.cos(x[2]) * dt
        F[0, 4] = np.sin(x[2]) * dt

        F[1, 2] = v_new * np.cos(x[2]) * dt
        F[1, 3] = np.sin(x[2]) * dt
        F[1, 4] = -np.cos(x[2]) * dt

        return F

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Normalize angle to [-pi, pi]."""
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle


class ParticleFilter:
    """Particle filter for localization."""

    def __init__(
        self: ParticleFilter,
        num_particles: int = 100,
        process_noise_std: float = 0.1,
        measurement_noise_std: float = 0.5,
    ) -> None:
        """Initialize particle filter.

        Args:
            num_particles: Number of particles
            process_noise_std: Process noise standard deviation
            measurement_noise_std: Measurement noise standard deviation
        """
        self.num_particles = num_particles
        self.process_noise_std = process_noise_std
        self.measurement_noise_std = measurement_noise_std

        # Initialize particles uniformly
        self.particles = np.random.randn(num_particles, 3) * [1.0, 1.0, np.pi]
        self.weights = np.ones(num_particles) / num_particles

    def predict(
        self: ParticleFilter,
        acceleration: float,
        steering_angle: float,
        dt: float,
        wheelbase: float = 2.7,
    ) -> None:
        """Predict particle states.

        Args:
            acceleration: Longitudinal acceleration
            steering_angle: Steering angle
            dt: Time step
            wheelbase: Vehicle wheelbase
        """
        for i in range(self.num_particles):
            x, y, theta = self.particles[i]

            # Add process noise
            noise = np.random.randn(3) * [
                self.process_noise_std,
                self.process_noise_std,
                self.process_noise_std * 0.1,
            ]

            # Motion model
            v = 1.0  # Assume constant velocity for prediction
            dtheta = v * np.tan(steering_angle) / wheelbase

            x_new = x + v * np.cos(theta) * dt + noise[0]
            y_new = y + v * np.sin(theta) * dt + noise[1]
            theta_new = theta + dtheta * dt + noise[2]

            # Normalize heading
            theta_new = self._normalize_angle(theta_new)

            self.particles[i] = [x_new, y_new, theta_new]

    def update(self: ParticleFilter, measurement: np.ndarray) -> None:
        """Update particle weights with measurement.

        Args:
            measurement: Position measurement [x, y]
        """
        # Compute likelihood for each particle
        likelihoods = np.zeros(self.num_particles)

        for i in range(self.num_particles):
            x, y, _ = self.particles[i]
            dx = x - measurement[0]
            dy = y - measurement[1]

            # Gaussian likelihood
            likelihood = np.exp(-(dx**2 + dy**2) / (2 * self.measurement_noise_std**2))
            likelihoods[i] = likelihood

        # Update weights
        self.weights = self.weights * likelihoods
        self.weights /= np.sum(self.weights) + 1e-10

    def resample(self: ParticleFilter) -> None:
        """Resample particles based on weights."""
        # Check effective sample size
        n_eff = 1.0 / np.sum(self.weights**2)

        if n_eff < self.num_particles / 2:
            # Resample
            indices = np.random.choice(
                self.num_particles,
                size=self.num_particles,
                p=self.weights,
            )
            self.particles = self.particles[indices]
            self.weights = np.ones(self.num_particles) / self.num_particles

    def get_estimate(self: ParticleFilter) -> tuple[np.ndarray, np.ndarray]:
        """Get position and heading estimate.

        Returns:
            Tuple of (position [x, y], covariance)
        """
        # Weighted mean
        mean_x = np.sum(self.weights * self.particles[:, 0])
        mean_y = np.sum(self.weights * self.particles[:, 1])

        # Weighted covariance
        cov_xx = np.sum(self.weights * (self.particles[:, 0] - mean_x) ** 2)
        cov_yy = np.sum(self.weights * (self.particles[:, 1] - mean_y) ** 2)
        cov_xy = np.sum(self.weights * (self.particles[:, 0] - mean_x) * (self.particles[:, 1] - mean_y))

        covariance = np.array([[cov_xx, cov_xy], [cov_xy, cov_yy]])

        return np.array([mean_x, mean_y]), covariance

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Normalize angle to [-pi, pi]."""
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle


class MapMatcher:
    """Map matching to snap vehicle to road network."""

    def __init__(self: MapMatcher, search_radius: float = 10.0) -> None:
        """Initialize map matcher.

        Args:
            search_radius: Search radius for nearest road
        """
        self.search_radius = search_radius
        self.map_waypoints: list[Vector2D] = []

    def set_map(self: MapMatcher, waypoints: list[Vector2D]) -> None:
        """Set map waypoints.

        Args:
            waypoints: List of waypoints on road network
        """
        self.map_waypoints = waypoints

    def match_to_map(self: MapMatcher, position: Vector2D) -> tuple[Vector2D, int] | None:
        """Match vehicle position to nearest point on map.

        Args:
            position: Vehicle position

        Returns:
            Tuple of (matched position, waypoint index) or None if no match
        """
        if len(self.map_waypoints) < 2:
            return None

        min_distance = float("inf")
        best_match = None
        best_index = 0

        for i in range(len(self.map_waypoints) - 1):
            p1 = self.map_waypoints[i]
            p2 = self.map_waypoints[i + 1]

            # Project position onto line segment
            matched_point, distance = self._project_point_to_segment(position, p1, p2)

            if distance < min_distance:
                min_distance = distance
                best_match = matched_point
                best_index = i

        if min_distance < self.search_radius and best_match is not None:
            return best_match, best_index

        return None

    @staticmethod
    def _project_point_to_segment(point: Vector2D, seg_start: Vector2D, seg_end: Vector2D) -> tuple[Vector2D, float]:
        """Project point onto line segment.

        Args:
            point: Point to project
            seg_start: Segment start
            seg_end: Segment end

        Returns:
            Tuple of (projected point, distance)
        """
        # Vector from start to end
        dx = seg_end.x - seg_start.x
        dy = seg_end.y - seg_start.y

        # Vector from start to point
        px = point.x - seg_start.x
        py = point.y - seg_start.y

        # Project onto segment
        t = max(0.0, min(1.0, (px * dx + py * dy) / (dx**2 + dy**2 + 1e-10)))

        projected_x = seg_start.x + t * dx
        projected_y = seg_start.y + t * dy

        projected = Vector2D(projected_x, projected_y)
        distance = point.distance_to(projected)

        return projected, distance


class LocalizationSystem:
    """Complete localization system."""

    def __init__(
        self: LocalizationSystem,
        wheelbase: float = 2.7,
        max_drift: float = 1.0,
    ) -> None:
        """Initialize localization system.

        Args:
            wheelbase: Vehicle wheelbase
            max_drift: Maximum acceptable localization drift
        """
        self.wheelbase = wheelbase
        self.max_drift = max_drift

        self.ekf = ExtendedKalmanFilter(wheelbase=wheelbase)
        self.particle_filter = ParticleFilter()
        self.map_matcher = MapMatcher()

        self.last_timestamp = 0.0
        self.covariance_history: list[np.ndarray] = []

    def set_map(self: LocalizationSystem, waypoints: list[Vector2D]) -> None:
        """Set map for matching.

        Args:
            waypoints: Road network waypoints
        """
        self.map_matcher.set_map(waypoints)

    def initialize_at_position(self: LocalizationSystem, position: Vector2D, heading: float = 0.0) -> None:
        """Initialize localization at known position.

        Args:
            position: Initial position
            heading: Initial heading
        """
        self.ekf.state.x = np.array([position.x, position.y, heading, 0.0, 0.0, 0.0])
        self.ekf.state.P = np.eye(6) * 0.01

    def update(
        self: LocalizationSystem,
        vehicle_state: VehicleState,
        gps_position: Vector2D | None = None,
        imu_heading_rate: float = 0.0,
        wheel_speeds: list[float] | None = None,
    ) -> VehicleState:
        """Update localization with sensor data.

        Args:
            vehicle_state: Current vehicle state
            gps_position: GPS position measurement
            imu_heading_rate: IMU heading rate
            wheel_speeds: Wheel speeds from odometry

        Returns:
            Updated vehicle state

        Raises:
            LocalizationDriftException: If drift exceeds threshold
        """
        dt = vehicle_state.timestamp - self.last_timestamp
        if dt <= 0.0:
            dt = 0.1

        # EKF predict step
        self.ekf.predict(
            acceleration=0.0,
            steering_angle=vehicle_state.steering_angle,
            dt=dt,
        )

        # GPS update
        if gps_position is not None:
            gps_measurement = np.array([gps_position.x, gps_position.y])
            self.ekf.update(gps_measurement, measurement_type="position")

        # IMU update
        if imu_heading_rate != 0.0:
            imu_measurement = np.array([imu_heading_rate])
            self.ekf.update(imu_measurement, measurement_type="heading")

        # Particle filter update
        self.particle_filter.predict(0.0, vehicle_state.steering_angle, dt, self.wheelbase)

        if gps_position is not None:
            gps_measurement = np.array([gps_position.x, gps_position.y])
            self.particle_filter.update(gps_measurement)
            self.particle_filter.resample()

        # Get state from EKF
        position = self.ekf.state.get_position()
        velocity = self.ekf.state.get_velocity()
        heading = self.ekf.state.get_heading()

        # Map matching
        matched = self.map_matcher.match_to_map(position)
        if matched is not None:
            position, _ = matched

        # Check drift
        drift = np.sqrt(np.trace(self.ekf.state.P[:2, :2]))
        if drift > self.max_drift:
            raise LocalizationDriftException(f"Localization drift {drift:.2f}m exceeds threshold")

        self.last_timestamp = vehicle_state.timestamp
        self.covariance_history.append(self.ekf.state.P.copy())

        return VehicleState(
            timestamp=vehicle_state.timestamp,
            position=position,
            velocity=velocity,
            acceleration=vehicle_state.acceleration,
            heading=heading,
            heading_rate=imu_heading_rate,
            steering_angle=vehicle_state.steering_angle,
            speed=velocity.norm(),
        )

    def get_uncertainty(self: LocalizationSystem) -> float:
        """Get current localization uncertainty.

        Returns:
            Uncertainty in meters
        """
        return float(np.sqrt(np.trace(self.ekf.state.P[:2, :2])))
