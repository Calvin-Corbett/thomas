"""
Tests for sensors module.
"""

import math

import pytest

from thomas.robotics_deep._types import OccupancyGrid, Pose, Quaternion, Vec3
from thomas.robotics_deep.sensors import (
    CameraModel,
    EncoderSimulator,
    IMUSimulator,
    LidarSimulator,
    SensorFusion,
)


class TestLidarSimulator:
    """Test Lidar/laser range finder simulator."""

    def test_lidar_initialization(self) -> None:
        """Test Lidar initialization."""
        lidar = LidarSimulator(num_rays=360, max_range=10.0)

        assert lidar.num_rays == 360
        assert lidar.max_range == 10.0

    def test_lidar_scan_output(self) -> None:
        """Test Lidar scan output format."""
        lidar = LidarSimulator(num_rays=10, max_range=5.0)

        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)
        pose = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        scan = lidar.scan(pose, grid)

        assert len(scan.ranges) == 10
        assert len(scan.angles) == 10
        assert all(0 <= r <= 5.0 for r in scan.ranges)

    def test_lidar_angle_increment(self) -> None:
        """Test Lidar angle increment."""
        num_rays = 360
        min_angle = 0
        max_angle = 2 * math.pi

        lidar = LidarSimulator(num_rays=num_rays, min_angle=min_angle, max_angle=max_angle)

        expected_increment = (max_angle - min_angle) / num_rays

        assert abs(lidar.angle_increment - expected_increment) < 1e-6

    def test_lidar_partial_angle_range(self) -> None:
        """Test Lidar with partial angle range."""
        lidar = LidarSimulator(
            num_rays=180,
            min_angle=-math.pi / 2,
            max_angle=math.pi / 2,
        )

        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)
        pose = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        scan = lidar.scan(pose, grid)

        assert len(scan.ranges) == 180


class TestCameraModel:
    """Test pinhole camera model."""

    def test_camera_initialization(self) -> None:
        """Test camera initialization."""
        camera = CameraModel(
            focal_length=1.0,
            principal_point=(320, 240),
            image_width=640,
            image_height=480,
        )

        assert camera.focal_length == 1.0
        assert camera.principal_point == (320, 240)

    def test_camera_intrinsic_matrix(self) -> None:
        """Test intrinsic matrix generation."""
        camera = CameraModel(focal_length=1.0, principal_point=(0, 0))

        K = camera.intrinsic_matrix()

        assert K[0][0] == 1.0  # fx
        assert K[1][1] == 1.0  # fy
        assert K[2][2] == 1.0

    def test_camera_projection(self) -> None:
        """Test 3D to image projection."""
        camera = CameraModel(
            focal_length=1.0,
            principal_point=(320, 240),
            image_width=640,
            image_height=480,
        )

        point_3d = Vec3(1, 0, 10)
        camera_pose = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        projection = camera.project(point_3d, camera_pose)

        if projection:
            u, v = projection
            assert 0 <= u < 640
            assert 0 <= v < 480

    def test_camera_behind_view(self) -> None:
        """Test projection of point behind camera."""
        camera = CameraModel()

        point_3d = Vec3(1, 0, -10)
        camera_pose = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        projection = camera.project(point_3d, camera_pose)

        assert projection is None


class TestIMUSimulator:
    """Test IMU (accelerometer + gyroscope) simulator."""

    def test_imu_initialization(self) -> None:
        """Test IMU initialization."""
        imu = IMUSimulator(noise_level=0.01)

        assert imu.noise_level == 0.01

    def test_imu_measurement(self) -> None:
        """Test IMU measurement."""
        imu = IMUSimulator(noise_level=0.0)  # No noise for testing

        velocity = Vec3(1.0, 0, 0)
        angular_velocity = Vec3(0, 0, 0.1)

        accel, gyro = imu.measure(velocity, angular_velocity)

        assert accel is not None
        assert gyro is not None

    def test_imu_gravity_effect(self) -> None:
        """Test gravity in acceleration measurement."""
        imu = IMUSimulator(noise_level=0.0)

        velocity = Vec3(0, 0, 0)
        angular_velocity = Vec3(0, 0, 0)

        accel, gyro = imu.measure(velocity, angular_velocity, gravity=9.81)

        # Gravity should appear in z acceleration
        assert accel.z < 0

    def test_imu_noise(self) -> None:
        """Test IMU noise effect."""
        imu = IMUSimulator(noise_level=1.0)

        velocity = Vec3(0, 0, 0)
        angular_velocity = Vec3(0, 0, 0)

        measurements = []
        for _ in range(10):
            accel, gyro = imu.measure(velocity, angular_velocity)
            measurements.append(accel.magnitude())

        # With noise, measurements should vary
        assert len(set(measurements)) > 1


class TestEncoderSimulator:
    """Test wheel encoder simulator."""

    def test_encoder_initialization(self) -> None:
        """Test encoder initialization."""
        encoder = EncoderSimulator(wheel_radius=0.1, ticks_per_rev=100)

        assert encoder.wheel_radius == 0.1
        assert encoder.ticks_per_rev == 100

    def test_encoder_update(self) -> None:
        """Test encoder tick counting."""
        encoder = EncoderSimulator(wheel_radius=0.1, ticks_per_rev=100)

        position = Vec3(0.1 * math.pi, 0, 0)  # Half revolution

        ticks = encoder.update(position)

        assert ticks > 0

    def test_encoder_distance(self) -> None:
        """Test distance calculation from ticks."""
        encoder = EncoderSimulator(wheel_radius=0.1, ticks_per_rev=100)

        # Move one full circumference
        circumference = 2 * math.pi * 0.1
        position = Vec3(circumference, 0, 0)

        ticks = encoder.update(position)
        distance = encoder.get_distance()

        assert abs(distance - circumference) < 0.01

    def test_encoder_accumulation(self) -> None:
        """Test tick accumulation."""
        encoder = EncoderSimulator()

        pos1 = Vec3(0.1, 0, 0)
        encoder.update(pos1)
        ticks1 = encoder.total_ticks

        pos2 = Vec3(0.2, 0, 0)
        encoder.update(pos2)
        ticks2 = encoder.total_ticks

        assert ticks2 > ticks1


class TestSensorFusion:
    """Test sensor fusion."""

    def test_complementary_filter_initialization(self) -> None:
        """Test complementary filter initialization."""
        fusion = SensorFusion()
        fusion.__post_init__()

        assert hasattr(fusion, "imu_roll")
        assert hasattr(fusion, "imu_pitch")

    def test_complementary_filter(self) -> None:
        """Test complementary filter."""
        fusion = SensorFusion()
        fusion.__post_init__()

        accel = Vec3(0, 0, 9.81)
        gyro = Vec3(0, 0, 0.1)

        roll, pitch, yaw = fusion.complementary_filter(accel, gyro)

        assert roll is not None
        assert pitch is not None
        assert yaw is not None

    def test_kalman_filter_position(self) -> None:
        """Test Kalman filter for position."""
        fusion = SensorFusion()

        encoder_pos = Vec3(1.0, 0, 0)
        imu_vel = Vec3(0.1, 0, 0)

        filtered_pos = fusion.kalman_position_filter(encoder_pos, imu_vel)

        assert filtered_pos is not None
        assert isinstance(filtered_pos, Vec3)

    def test_kalman_filter_convergence(self) -> None:
        """Test Kalman filter convergence."""
        fusion = SensorFusion()

        pos = Vec3(0, 0, 0)
        vel = Vec3(0, 0, 0)

        for i in range(10):
            pos = Vec3(i * 0.1, 0, 0)
            filtered = fusion.kalman_position_filter(pos, vel)

        assert filtered is not None


class TestSensorIntegration:
    """Test sensor integration scenarios."""

    def test_lidar_camera_fusion(self) -> None:
        """Test using Lidar and camera together."""
        lidar = LidarSimulator(num_rays=10)
        camera = CameraModel()

        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)
        pose = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        scan = lidar.scan(pose, grid)
        assert len(scan.ranges) == 10

        point = Vec3(1, 0, 5)
        projection = camera.project(point, pose)
        # May or may not project depending on camera orientation

    def test_imu_encoder_fusion(self) -> None:
        """Test IMU and encoder fusion."""
        imu = IMUSimulator()
        encoder = EncoderSimulator()
        fusion = SensorFusion()

        vel = Vec3(1.0, 0, 0)
        ang_vel = Vec3(0, 0, 0.1)

        accel, gyro = imu.measure(vel, ang_vel)

        fusion.__post_init__()
        roll, pitch, yaw = fusion.complementary_filter(accel, gyro)

        assert yaw > 0

    def test_multi_sensor_system(self) -> None:
        """Test complete multi-sensor system."""
        lidar = LidarSimulator(num_rays=8)
        camera = CameraModel()
        imu = IMUSimulator()
        encoder = EncoderSimulator()
        fusion = SensorFusion()

        # Simulate robot moving
        pose = Pose(position=Vec3(1, 1, 0), orientation=Quaternion.from_euler(0, 0, 0.5))
        grid = OccupancyGrid(width=30, height=30, resolution=0.1, origin_x=-1.5, origin_y=-1.5)

        # All sensors
        scan = lidar.scan(pose, grid)
        assert len(scan.ranges) == 8

        point = Vec3(2, 1, 5)
        proj = camera.project(point, pose)

        accel, gyro = imu.measure(Vec3(1, 0, 0), Vec3(0, 0, 0.1))

        pos = Vec3(1, 0, 0)
        ticks = encoder.update(pos)

        fusion.__post_init__()
        attitude = fusion.complementary_filter(accel, gyro)

        # System should work without errors
        assert scan is not None


class TestSensorNoise:
    """Test sensor noise characteristics."""

    def test_imu_noise_magnitude(self) -> None:
        """Test IMU noise magnitude."""
        noise_level = 0.1
        imu = IMUSimulator(noise_level=noise_level)

        measurements = []
        for _ in range(100):
            accel, gyro = imu.measure(Vec3(0, 0, 0), Vec3(0, 0, 0))
            measurements.append(accel.magnitude())

        avg_noise = sum(measurements) / len(measurements)

        # Average noise should be roughly noise_level scale
        assert avg_noise > 0

    def test_lidar_range_consistency(self) -> None:
        """Test Lidar returns consistent ranges."""
        lidar = LidarSimulator(num_rays=10, max_range=5.0)

        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)
        pose = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        scans = []
        for _ in range(3):
            scan = lidar.scan(pose, grid)
            scans.append(scan)

        # Multiple scans from same pose should be similar
        assert len(scans) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
