"""Tests for perception module."""

import numpy as np
import pytest

from thomas.autonomous_vehicles._exceptions import (
    SensorDropoutException,
)
from thomas.autonomous_vehicles._types import (
    CameraFrame,
    LidarPoint,
    RadarReturn,
    SensorData,
    Vector2D,
)
from thomas.autonomous_vehicles.perception import (
    LaneDetector,
    OccupancyGrid,
    PerceptionPipeline,
    PointCloudProcessor,
    SensorFusion,
)


class TestPointCloudProcessor:
    """Test point cloud processor."""

    def test_remove_ground_plane(self) -> None:
        """Test ground plane removal."""
        processor = PointCloudProcessor()

        # Create point cloud with ground and non-ground points
        points = [
            LidarPoint(x=0.0, y=0.0, z=0.0, intensity=100, ring=0),
            LidarPoint(x=1.0, y=0.0, z=0.0, intensity=100, ring=0),
            LidarPoint(x=2.0, y=0.0, z=0.0, intensity=100, ring=0),
            LidarPoint(x=0.5, y=0.5, z=2.0, intensity=100, ring=1),  # Non-ground
            LidarPoint(x=1.5, y=0.5, z=2.0, intensity=100, ring=1),  # Non-ground
        ]

        non_ground = processor.remove_ground_plane(points)

        assert len(non_ground) > 0
        assert all(p.z > 0.5 for p in non_ground)

    def test_cluster_points(self) -> None:
        """Test point clustering."""
        processor = PointCloudProcessor()

        # Create two clusters
        cluster1 = [
            LidarPoint(x=0.0, y=0.0, z=1.0, intensity=100, ring=0),
            LidarPoint(x=0.1, y=0.1, z=1.0, intensity=100, ring=0),
            LidarPoint(x=0.2, y=0.0, z=1.0, intensity=100, ring=0),
        ]

        cluster2 = [
            LidarPoint(x=10.0, y=10.0, z=1.0, intensity=100, ring=0),
            LidarPoint(x=10.1, y=10.1, z=1.0, intensity=100, ring=0),
            LidarPoint(x=10.2, y=10.0, z=1.0, intensity=100, ring=0),
        ]

        points = cluster1 + cluster2

        clusters = processor.cluster_points(points, eps=0.5, min_points=2)

        assert len(clusters) >= 1
        assert all(len(cluster) >= 2 for cluster in clusters)

    def test_empty_point_cloud(self) -> None:
        """Test handling of empty point cloud."""
        processor = PointCloudProcessor()

        points: list = []
        non_ground = processor.remove_ground_plane(points)
        clusters = processor.cluster_points(points)

        assert len(non_ground) == 0
        assert len(clusters) == 0


class TestLaneDetector:
    """Test lane detector."""

    def test_detect_lanes_simple(self) -> None:
        """Test basic lane detection."""
        detector = LaneDetector()

        # Create point cloud in lane area
        points = [LidarPoint(x=5.0 + i * 0.5, y=-1.8, z=0.0, intensity=100, ring=0) for i in range(10)]
        points.extend([LidarPoint(x=5.0 + i * 0.5, y=1.8, z=0.0, intensity=100, ring=0) for i in range(10)])

        lanes = detector.detect_lanes(points, vehicle_heading=0.0)

        # Should detect some lane-like features
        assert isinstance(lanes, list)

    def test_empty_point_cloud_detection(self) -> None:
        """Test lane detection on empty point cloud."""
        detector = LaneDetector()

        points: list = []
        lanes = detector.detect_lanes(points)

        assert lanes is not None


class TestSensorFusion:
    """Test sensor fusion."""

    def test_fuse_sensors(self) -> None:
        """Test multi-sensor fusion."""
        fusion = SensorFusion()

        lidar_detections = [(Vector2D(10.0, 0.0), 0.9)]
        radar_detections = [(Vector2D(10.1, 0.0), 0.8)]
        camera_detections = [(Vector2D(10.05, 0.0), 0.85)]

        fused = fusion.update(
            lidar_detections,
            radar_detections,
            camera_detections,
            timestamp=1.0,
        )

        assert len(fused) > 0

    def test_no_detections(self) -> None:
        """Test fusion with no detections."""
        fusion = SensorFusion()

        fused = fusion.update([], [], [], timestamp=1.0)

        assert len(fused) == 0


class TestOccupancyGrid:
    """Test occupancy grid."""

    def test_occupancy_grid_basics(self) -> None:
        """Test basic occupancy grid operations."""
        grid = OccupancyGrid(
            width=100,
            height=100,
            resolution=0.1,
            origin_x=0.0,
            origin_y=0.0,
        )

        # Set occupied
        grid.set_occupied(1.5, 2.5, 0.9)

        assert grid.is_occupied(1.5, 2.5)

    def test_world_to_grid_conversion(self) -> None:
        """Test coordinate conversion."""
        grid = OccupancyGrid(
            width=100,
            height=100,
            resolution=0.1,
            origin_x=-5.0,
            origin_y=-5.0,
        )

        grid_x, grid_y = grid.world_to_grid(-4.95, -4.95)

        assert grid_x >= 0
        assert grid_y >= 0

    def test_get_free_cells(self) -> None:
        """Test retrieval of free cells."""
        grid = OccupancyGrid(
            width=10,
            height=10,
            resolution=1.0,
            origin_x=0.0,
            origin_y=0.0,
        )

        free_cells = grid.get_free_cells()

        assert len(free_cells) == 100


class TestPerceptionPipeline:
    """Test complete perception pipeline."""

    def test_pipeline_with_valid_data(self) -> None:
        """Test perception pipeline with valid sensor data."""
        pipeline = PerceptionPipeline()

        # Create synthetic sensor data
        lidar_points = [LidarPoint(x=5.0 + i * 0.1, y=0.0, z=1.0, intensity=100, ring=0) for i in range(20)]

        sensor_data = SensorData(
            timestamp=1.0,
            lidar_points=lidar_points,
            camera_frames=[],
            radar_returns=[],
            imu_acceleration=Vector2D(0.0, 0.0),
            imu_angular_velocity=0.0,
            gnss_position=Vector2D(0.0, 0.0),
            gnss_covariance=np.eye(2) * 0.1,
            wheel_speeds=[5.0, 5.0, 5.0, 5.0],
        )

        obstacles, lanes, grid = pipeline.process_sensor_data(sensor_data, Vector2D(0.0, 0.0))

        assert isinstance(obstacles, list)
        assert isinstance(lanes, list)
        assert grid is not None

    def test_pipeline_no_lidar(self) -> None:
        """Test pipeline with no LIDAR data."""
        pipeline = PerceptionPipeline()

        sensor_data = SensorData(
            timestamp=1.0,
            lidar_points=[],
            camera_frames=[],
            radar_returns=[],
            imu_acceleration=Vector2D(0.0, 0.0),
            imu_angular_velocity=0.0,
            gnss_position=Vector2D(0.0, 0.0),
            gnss_covariance=np.eye(2),
            wheel_speeds=[0.0, 0.0, 0.0, 0.0],
        )

        with pytest.raises(SensorDropoutException):
            pipeline.process_sensor_data(sensor_data, Vector2D(0.0, 0.0))

    def test_clusters_to_obstacles(self) -> None:
        """Test cluster to obstacle conversion."""
        pipeline = PerceptionPipeline()

        # Create point clusters
        cluster1 = [
            LidarPoint(x=5.0, y=0.0, z=1.0, intensity=100, ring=0),
            LidarPoint(x=5.1, y=0.1, z=1.0, intensity=100, ring=0),
            LidarPoint(x=5.2, y=0.0, z=1.0, intensity=100, ring=0),
        ]

        cluster2 = [
            LidarPoint(x=10.0, y=0.0, z=1.0, intensity=100, ring=0),
            LidarPoint(x=10.1, y=0.1, z=1.0, intensity=100, ring=0),
        ]

        clusters = [cluster1, cluster2]

        obstacles = pipeline._clusters_to_obstacles(clusters, timestamp=1.0)

        assert len(obstacles) == 2
        assert all(obs.width > 0 for obs in obstacles)
        assert all(obs.length > 0 for obs in obstacles)


class TestSensorDataAttributes:
    """Test SensorData helper methods."""

    def test_num_lidar_points(self) -> None:
        """Test LIDAR point count."""
        sensor_data = SensorData(
            timestamp=1.0,
            lidar_points=[LidarPoint(x=i, y=0.0, z=0.0, intensity=100, ring=0) for i in range(100)],
            camera_frames=[],
            radar_returns=[],
            imu_acceleration=Vector2D(0.0, 0.0),
            imu_angular_velocity=0.0,
            gnss_position=Vector2D(0.0, 0.0),
            gnss_covariance=np.eye(2),
            wheel_speeds=[0.0, 0.0, 0.0, 0.0],
        )

        assert sensor_data.num_lidar_points() == 100

    def test_num_sensors(self) -> None:
        """Test sensor counts."""
        sensor_data = SensorData(
            timestamp=1.0,
            lidar_points=[LidarPoint(x=0, y=0, z=0, intensity=100, ring=0)],
            camera_frames=[
                CameraFrame(
                    timestamp=1.0,
                    frame_id=0,
                    width=1280,
                    height=720,
                    image_data=np.zeros((720, 1280, 3), dtype=np.uint8),
                    intrinsics=np.eye(3),
                    distortion_coeffs=np.zeros(5),
                )
            ],
            radar_returns=[
                RadarReturn(
                    range_m=10.0,
                    azimuth_rad=0.0,
                    elevation_rad=0.0,
                    doppler_velocity=0.0,
                    rcs=-10.0,
                    signal_strength=50.0,
                )
            ],
            imu_acceleration=Vector2D(0.0, 0.0),
            imu_angular_velocity=0.0,
            gnss_position=Vector2D(0.0, 0.0),
            gnss_covariance=np.eye(2),
            wheel_speeds=[0.0, 0.0, 0.0, 0.0],
        )

        assert sensor_data.num_lidar_points() == 1
        assert sensor_data.num_cameras() == 1
        assert sensor_data.num_radar_returns() == 1
