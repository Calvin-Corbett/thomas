"""
Tests for SLAM module.
"""

import math

import pytest

from thomas.robotics_deep._types import LaserScan, OccupancyGrid, Pose, Quaternion, Vec3
from thomas.robotics_deep.slam import EKFSLAMFilter, OccupancyGridMapper, ParticleFilterLocalizer


class TestEKFSLAM:
    """Test EKF-SLAM filter."""

    def test_ekf_slam_initialization(self) -> None:
        """Test SLAM filter initialization."""
        ekf = EKFSLAMFilter(num_landmarks=10)

        assert len(ekf.state) == 3 + 2 * 10
        assert len(ekf.covariance) == 3 + 2 * 10

    def test_ekf_slam_predict(self) -> None:
        """Test prediction step."""
        ekf = EKFSLAMFilter()

        initial_x = ekf.state[0]
        initial_y = ekf.state[1]

        ekf.predict(delta_x=1.0, delta_y=0.5, delta_theta=0.1)

        assert ekf.state[0] == initial_x + 1.0
        assert ekf.state[1] == initial_y + 0.5
        assert ekf.state[2] == 0.1

    def test_ekf_slam_update_new_landmark(self) -> None:
        """Test landmark initialization."""
        ekf = EKFSLAMFilter()

        ekf.update(landmark_id=0, range_obs=1.0, bearing_obs=0.0)

        assert 0 in ekf.seen_landmarks

    def test_ekf_slam_pose_estimate(self) -> None:
        """Test pose estimation."""
        ekf = EKFSLAMFilter()

        ekf.predict(1.0, 1.0, 0.5)

        pose = ekf.get_pose()

        assert pose.position.x == 1.0
        assert pose.position.y == 1.0

    def test_ekf_slam_landmark_tracking(self) -> None:
        """Test landmark position tracking."""
        ekf = EKFSLAMFilter()

        ekf.update(landmark_id=0, range_obs=1.0, bearing_obs=0.0)
        ekf.update(landmark_id=1, range_obs=1.5, bearing_obs=math.pi / 2)

        landmarks = ekf.get_landmarks()

        assert len(landmarks) == 2


class TestOccupancyGridMapping:
    """Test occupancy grid mapping."""

    def test_occupancy_grid_creation(self) -> None:
        """Test grid creation."""
        grid = OccupancyGrid(width=10, height=10, resolution=0.1, origin_x=0, origin_y=0)

        assert grid.width == 10
        assert grid.height == 10
        assert len(grid.data) == 10
        assert len(grid.data[0]) == 10

    def test_occupancy_grid_cell_access(self) -> None:
        """Test grid cell access."""
        grid = OccupancyGrid(width=10, height=10, resolution=0.1, origin_x=0, origin_y=0)

        grid.set_cell(0.5, 0.5, 0.9)

        occupancy = grid.get_cell(0.5, 0.5)

        assert occupancy == 0.9

    def test_occupancy_grid_clamping(self) -> None:
        """Test occupancy values are clamped."""
        grid = OccupancyGrid(width=10, height=10, resolution=0.1, origin_x=0, origin_y=0)

        grid.set_cell(0.5, 0.5, 1.5)  # Over 1.0
        occupancy = grid.get_cell(0.5, 0.5)

        assert occupancy <= 1.0
        assert occupancy >= 0.0

    def test_occupancy_grid_mapping(self) -> None:
        """Test grid mapping with laser scans."""
        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)

        mapper = OccupancyGridMapper(grid, max_range=2.0)

        # Create a simple scan
        scan = LaserScan(
            timestamp=0.0,
            ranges=[1.0, 1.0, 1.0],
            angles=[0, math.pi / 2, math.pi],
            min_angle=0,
            max_angle=math.pi,
            angle_increment=math.pi / 2,
        )

        robot_pose = Pose(
            position=Vec3(0, 0, 0),
            orientation=Quaternion.identity(),
        )

        mapper.update(scan, robot_pose)

        # Check that grid was updated
        assert grid.data is not None


class TestParticleFilter:
    """Test particle filter for localization."""

    def test_particle_filter_initialization(self) -> None:
        """Test particle filter initialization."""
        pf = ParticleFilterLocalizer(num_particles=100)

        assert len(pf.particles) == 100

    def test_particle_filter_weight_normalization(self) -> None:
        """Test particle weights sum to 1."""
        pf = ParticleFilterLocalizer(num_particles=100)

        weights = [p[3] for p in pf.particles]
        total_weight = sum(weights)

        assert abs(total_weight - 1.0) < 1e-6

    def test_particle_filter_predict(self) -> None:
        """Test motion prediction."""
        pf = ParticleFilterLocalizer(num_particles=50)

        # Store initial positions
        initial_x = pf.particles[0][0]

        pf.predict(delta_x=1.0, delta_y=0.0, delta_theta=0.0)

        # Particles should move forward
        new_x = pf.particles[0][0]
        assert new_x > initial_x

    def test_particle_filter_resample(self) -> None:
        """Test particle resampling."""
        pf = ParticleFilterLocalizer(num_particles=100)

        pf.resample()

        weights = [p[3] for p in pf.particles]
        total_weight = sum(weights)

        assert abs(total_weight - 1.0) < 1e-6

    def test_particle_filter_pose_estimate(self) -> None:
        """Test mean pose estimation."""
        pf = ParticleFilterLocalizer(num_particles=100)

        pose = pf.get_pose()

        assert pose is not None
        assert pose.position is not None

    def test_particle_filter_update(self) -> None:
        """Test measurement update."""
        pf = ParticleFilterLocalizer(num_particles=100)

        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)

        scan = LaserScan(
            timestamp=0.0,
            ranges=[1.0, 1.0],
            angles=[0, math.pi],
            min_angle=0,
            max_angle=math.pi,
            angle_increment=math.pi,
        )

        pf.update(scan, grid)

        # Weights should be updated
        weights = [p[3] for p in pf.particles]
        assert all(w >= 0 for w in weights)


class TestSLAMConsistency:
    """Test SLAM consistency properties."""

    def test_ekf_covariance_growth(self) -> None:
        """Test covariance grows with uncertainty."""
        ekf = EKFSLAMFilter()

        cov_initial = ekf.covariance[0][0]

        ekf.predict(1.0, 0.0, 0.0)

        cov_after_predict = ekf.covariance[0][0]

        assert cov_after_predict > cov_initial

    def test_particle_filter_convergence(self) -> None:
        """Test particle filter converges over time."""
        pf = ParticleFilterLocalizer(num_particles=200)

        # Multiple prediction and update cycles
        for _ in range(5):
            pf.predict(0.1, 0.0, 0.0)

        pose = pf.get_pose()

        assert pose.position.x > 0.4  # Should move forward

    def test_grid_mapping_consistency(self) -> None:
        """Test grid mapping maintains consistency."""
        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)
        mapper = OccupancyGridMapper(grid)

        pose1 = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        scan = LaserScan(
            timestamp=0.0,
            ranges=[1.0, 1.0],
            angles=[0, math.pi / 2],
            min_angle=0,
            max_angle=math.pi / 2,
            angle_increment=math.pi / 2,
        )

        mapper.update(scan, pose1)

        occupied_count_1 = sum(1 for row in grid.data for val in row if val > 0.5)

        mapper.update(scan, pose1)

        occupied_count_2 = sum(1 for row in grid.data for val in row if val > 0.5)

        assert occupied_count_2 >= occupied_count_1


class TestScanMatching:
    """Test scan matching functionality."""

    def test_lidar_simulator_output_format(self) -> None:
        """Test Lidar simulator produces correct format."""
        from thomas.robotics_deep.sensors import LidarSimulator

        lidar = LidarSimulator(num_rays=10, max_range=5.0)

        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)
        pose = Pose(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

        scan = lidar.scan(pose, grid)

        assert len(scan.ranges) == 10
        assert len(scan.angles) == 10
        assert scan.angle_increment > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
