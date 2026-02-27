"""
Sensor models: Lidar, camera, IMU, encoder, and sensor fusion.
"""

import math
import random

from thomas.robotics_deep._types import LaserScan, OccupancyGrid, Pose, Vec3


class LidarSimulator:
    """Simulate Lidar/laser range finder."""

    def __init__(
        self,
        num_rays: int = 360,
        max_range: float = 10.0,
        min_angle: float = 0.0,
        max_angle: float = 2 * math.pi,
    ) -> None:
        """
        Initialize Lidar simulator.

        Args:
            num_rays: Number of rays
            max_range: Maximum range
            min_angle: Minimum angle
            max_angle: Maximum angle
        """
        self.num_rays = num_rays
        self.max_range = max_range
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.angle_increment = (max_angle - min_angle) / num_rays

    def scan(self, robot_pose: Pose, grid: OccupancyGrid, timestamp: float = 0.0) -> LaserScan:
        """
        Simulate laser scan on occupancy grid.

        Args:
            robot_pose: Robot pose
            grid: Occupancy grid
            timestamp: Timestamp of scan

        Returns:
            Laser scan data
        """
        x = robot_pose.position.x
        y = robot_pose.position.y
        roll, pitch, yaw = robot_pose.orientation.to_euler()

        ranges = []
        angles = []

        for i in range(self.num_rays):
            angle = self.min_angle + i * self.angle_increment
            world_angle = yaw + angle

            # Ray cast
            hit_range = self._ray_cast(x, y, world_angle, grid)

            ranges.append(hit_range)
            angles.append(angle)

        return LaserScan(
            timestamp=timestamp,
            ranges=ranges,
            angles=angles,
            min_angle=self.min_angle,
            max_angle=self.max_angle,
            angle_increment=self.angle_increment,
        )

    def _ray_cast(self, x: float, y: float, angle: float, grid: OccupancyGrid) -> float:
        """
        Ray cast to find range.

        Args:
            x: Start x
            y: Start y
            angle: Ray angle
            grid: Occupancy grid

        Returns:
            Range to obstacle (or max_range if no hit)
        """
        step = 0.05
        current_range = 0.0

        while current_range < self.max_range:
            current_range += step
            hit_x = x + current_range * math.cos(angle)
            hit_y = y + current_range * math.sin(angle)

            occupancy = grid.get_cell(hit_x, hit_y)
            if occupancy > 0.5:  # Occupied
                return current_range

        return self.max_range


class CameraModel:
    """Pinhole camera model with intrinsics and extrinsics."""

    def __init__(
        self,
        focal_length: float = 1.0,
        principal_point: tuple[float, float] = (0.0, 0.0),
        image_width: int = 640,
        image_height: int = 480,
    ) -> None:
        """
        Initialize camera model.

        Args:
            focal_length: Focal length in pixels
            principal_point: Principal point (cx, cy)
            image_width: Image width in pixels
            image_height: Image height in pixels
        """
        self.focal_length = focal_length
        self.principal_point = principal_point
        self.image_width = image_width
        self.image_height = image_height

    def intrinsic_matrix(self) -> list[list[float]]:
        """Get intrinsic matrix K."""
        cx, cy = self.principal_point
        K = [
            [self.focal_length, 0, cx],
            [0, self.focal_length, cy],
            [0, 0, 1],
        ]
        return K

    def project(self, point_3d: Vec3, extrinsic_pose: Pose) -> tuple[float, float] | None:
        """
        Project 3D point to image plane.

        Args:
            point_3d: 3D point in world frame
            extrinsic_pose: Camera pose

        Returns:
            (u, v) image coordinates or None if out of view
        """
        # Transform point to camera frame
        cam_pos = extrinsic_pose.position
        cam_orient = extrinsic_pose.orientation
        roll, pitch, yaw = cam_orient.to_euler()

        # Simple 2D projection (assuming camera looking forward)
        relative_point = point_3d - cam_pos
        rel_x = relative_point.x
        rel_z = relative_point.z

        if rel_z <= 0:
            return None

        # Project
        u = self.focal_length * rel_x / rel_z + self.principal_point[0]
        v = self.focal_length * relative_point.y / rel_z + self.principal_point[1]

        # Check bounds
        if 0 <= u < self.image_width and 0 <= v < self.image_height:
            return (u, v)

        return None


class IMUSimulator:
    """Simulate IMU: accelerometer + gyroscope."""

    def __init__(self, noise_level: float = 0.01) -> None:
        """
        Initialize IMU simulator.

        Args:
            noise_level: Standard deviation of Gaussian noise
        """
        self.noise_level = noise_level
        self.last_velocity = Vec3(0, 0, 0)

    def measure(self, velocity: Vec3, angular_velocity: Vec3, gravity: float = 9.81) -> tuple[Vec3, Vec3]:
        """
        Simulate IMU measurement.

        Args:
            velocity: Robot velocity
            angular_velocity: Robot angular velocity
            gravity: Gravitational acceleration

        Returns:
            Tuple of (acceleration, angular_velocity) with noise
        """
        # Acceleration (numerical derivative + gravity)
        dt = 0.01
        accel = (velocity - self.last_velocity) * (1.0 / dt)
        accel = accel + Vec3(0, 0, -gravity)
        self.last_velocity = velocity

        # Add Gaussian noise
        accel_noisy = Vec3(
            accel.x + random.gauss(0, self.noise_level),
            accel.y + random.gauss(0, self.noise_level),
            accel.z + random.gauss(0, self.noise_level),
        )

        gyro_noisy = Vec3(
            angular_velocity.x + random.gauss(0, self.noise_level),
            angular_velocity.y + random.gauss(0, self.noise_level),
            angular_velocity.z + random.gauss(0, self.noise_level),
        )

        return accel_noisy, gyro_noisy


class EncoderSimulator:
    """Simulate wheel encoder (tick counting)."""

    def __init__(self, wheel_radius: float = 0.1, ticks_per_rev: int = 100) -> None:
        """
        Initialize encoder simulator.

        Args:
            wheel_radius: Wheel radius in meters
            ticks_per_rev: Encoder ticks per revolution
        """
        self.wheel_radius = wheel_radius
        self.ticks_per_rev = ticks_per_rev
        self.total_ticks = 0
        self.last_position = Vec3(0, 0, 0)

    def update(self, position: Vec3) -> int:
        """
        Update encoder count based on position change.

        Args:
            position: Current position

        Returns:
            New tick count
        """
        displacement = (position - self.last_position).magnitude()
        circumference = 2 * math.pi * self.wheel_radius
        new_ticks = int(displacement / circumference * self.ticks_per_rev)
        self.total_ticks += new_ticks
        self.last_position = position
        return self.total_ticks

    def get_distance(self) -> float:
        """Get total distance traveled."""
        circumference = 2 * math.pi * self.wheel_radius
        return self.total_ticks / self.ticks_per_rev * circumference


class SensorFusion:
    """Fuse multiple sensor measurements."""

    def __init__(self) -> None:
        """Initialize sensor fusion filter."""
        self.imu_accel = Vec3(0, 0, 0)
        self.complementary_filter_alpha = 0.95

    def complementary_filter(self, accel: Vec3, gyro: Vec3, dt: float = 0.01) -> tuple[float, float, float]:
        """
        Complementary filter for IMU (accelerometer + gyroscope).

        Args:
            accel: Acceleration from accelerometer
            gyro: Angular velocity from gyroscope
            dt: Time step

        Returns:
            Tuple of (roll, pitch, yaw) in radians
        """
        alpha = self.complementary_filter_alpha

        # Accelerometer-based orientation (low-pass)
        accel_norm = accel.magnitude()
        if accel_norm > 1e-6:
            accel_roll = math.atan2(accel.y, accel.z)
            accel_pitch = math.atan2(-accel.x, math.sqrt(accel.y**2 + accel.z**2))
        else:
            accel_roll = 0.0
            accel_pitch = 0.0

        # Integrate gyroscope (high-pass)
        gyro_roll = gyro.x * dt
        gyro_pitch = gyro.y * dt

        # Fuse
        roll = alpha * (self.imu_roll + gyro_roll) + (1 - alpha) * accel_roll
        pitch = alpha * (self.imu_pitch + gyro_pitch) + (1 - alpha) * accel_pitch
        yaw = gyro.z * dt  # Yaw from gyro only (no accel info)

        self.imu_roll = roll
        self.imu_pitch = pitch
        self.imu_yaw = yaw

        return roll, pitch, yaw

    def __post_init__(self) -> None:
        """Initialize complementary filter state."""
        self.imu_roll = 0.0
        self.imu_pitch = 0.0
        self.imu_yaw = 0.0

    def kalman_position_filter(
        self,
        encoder_position: Vec3,
        imu_velocity: Vec3,
        process_noise: float = 0.01,
        measurement_noise: float = 0.1,
    ) -> Vec3:
        """
        Simple Kalman filter for position estimation.

        Args:
            encoder_position: Position from encoder
            imu_velocity: Velocity from IMU
            process_noise: Process noise covariance
            measurement_noise: Measurement noise covariance

        Returns:
            Filtered position estimate
        """
        if not hasattr(self, "kf_state"):
            self.kf_state = encoder_position
            self.kf_covariance = Vec3(measurement_noise, measurement_noise, measurement_noise)

        # Predict
        predicted_state = self.kf_state + imu_velocity * 0.01
        predicted_cov = Vec3(
            self.kf_covariance.x + process_noise,
            self.kf_covariance.y + process_noise,
            self.kf_covariance.z + process_noise,
        )

        # Update
        innovation = encoder_position - predicted_state
        kalman_gain = Vec3(
            predicted_cov.x / (predicted_cov.x + measurement_noise),
            predicted_cov.y / (predicted_cov.y + measurement_noise),
            predicted_cov.z / (predicted_cov.z + measurement_noise),
        )

        self.kf_state = predicted_state + Vec3(
            kalman_gain.x * innovation.x,
            kalman_gain.y * innovation.y,
            kalman_gain.z * innovation.z,
        )

        self.kf_covariance = Vec3(
            (1 - kalman_gain.x) * predicted_cov.x,
            (1 - kalman_gain.y) * predicted_cov.y,
            (1 - kalman_gain.z) * predicted_cov.z,
        )

        return self.kf_state
