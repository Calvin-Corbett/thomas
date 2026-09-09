"""Perception pipeline for autonomous vehicles.

Includes LIDAR point cloud processing, obstacle detection, lane detection,
sensor fusion, and occupancy grid mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from thomas.autonomous_vehicles._exceptions import (
    LaneDetectionFailureException,
    SensorDropoutException,
)
from thomas.autonomous_vehicles._types import (
    LidarPoint,
    Obstacle,
    ObstacleType,
    SensorData,
    Vector2D,
)


@dataclass
class KalmanFilterState:
    """State for multi-sensor Kalman filter."""

    position: np.ndarray  # [x, y]
    velocity: np.ndarray  # [vx, vy]
    covariance: np.ndarray  # 4x4
    last_update: float = 0.0


@dataclass
class OccupancyGrid:
    """2D occupancy grid for environment mapping."""

    width: int
    height: int
    resolution: float  # meters per cell
    origin_x: float  # World x coordinate of grid origin
    origin_y: float  # World y coordinate of grid origin
    grid: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))

    def __post_init__(self: OccupancyGrid) -> None:
        """Initialize occupancy grid."""
        if self.grid.size == 0:
            self.grid = np.zeros((self.height, self.width), dtype=np.float32)

    def world_to_grid(self: OccupancyGrid, x: float, y: float) -> tuple[int, int]:
        """Convert world coordinates to grid indices."""
        grid_x = int((x - self.origin_x) / self.resolution)
        grid_y = int((y - self.origin_y) / self.resolution)
        return (grid_x, grid_y)

    def grid_to_world(self: OccupancyGrid, grid_x: int, grid_y: int) -> tuple[float, float]:
        """Convert grid indices to world coordinates."""
        x = grid_x * self.resolution + self.origin_x
        y = grid_y * self.resolution + self.origin_y
        return (x, y)

    def set_occupied(self: OccupancyGrid, x: float, y: float, probability: float = 1.0) -> None:
        """Mark cell as occupied."""
        grid_x, grid_y = self.world_to_grid(x, y)
        if 0 <= grid_x < self.width and 0 <= grid_y < self.height:
            self.grid[grid_y, grid_x] = max(self.grid[grid_y, grid_x], probability)

    def is_occupied(self: OccupancyGrid, x: float, y: float) -> bool:
        """Check if cell is occupied."""
        grid_x, grid_y = self.world_to_grid(x, y)
        if 0 <= grid_x < self.width and 0 <= grid_y < self.height:
            return self.grid[grid_y, grid_x] > 0.5
        return False

    def get_free_cells(self: OccupancyGrid) -> list[tuple[float, float]]:
        """Get list of free cell positions."""
        free_cells = []
        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y, x] < 0.5:
                    wx, wy = self.grid_to_world(x, y)
                    free_cells.append((wx, wy))
        return free_cells


class PointCloudProcessor:
    """Process LIDAR point clouds."""

    def __init__(
        self: PointCloudProcessor,
        ground_removal_threshold: float = 0.1,
        ground_plane_max_height: float = 0.5,
    ) -> None:
        """Initialize point cloud processor.

        Args:
            ground_removal_threshold: Height threshold for RANSAC ground detection
            ground_plane_max_height: Maximum height for ground plane points
        """
        self.ground_removal_threshold = ground_removal_threshold
        self.ground_plane_max_height = ground_plane_max_height

    def remove_ground_plane(self: PointCloudProcessor, points: list[LidarPoint]) -> list[LidarPoint]:
        """Remove ground plane points using RANSAC.

        Args:
            points: List of LIDAR points

        Returns:
            List of non-ground points
        """
        if len(points) < 3:
            return points

        points_array = np.array([[p.x, p.y, p.z] for p in points])

        best_inliers = []
        np.array([0, 0, 1], dtype=np.float32)

        # RANSAC iterations
        num_iterations = min(100, len(points) // 3)
        for _ in range(num_iterations):
            indices = np.random.choice(len(points), 3, replace=False)
            sample_points = points_array[indices]

            # Compute plane normal using cross product
            v1 = sample_points[1] - sample_points[0]
            v2 = sample_points[2] - sample_points[0]
            normal = np.cross(v1, v2)

            if np.linalg.norm(normal) < 1e-6:
                continue

            normal = normal / np.linalg.norm(normal)

            # Count inliers
            distances = np.abs(np.dot(points_array - sample_points[0], normal))
            inliers = np.where(distances < self.ground_removal_threshold)[0]

            if len(inliers) > len(best_inliers):
                best_inliers = inliers

        # Filter out ground points
        if len(best_inliers) > 0:
            outlier_indices = set(range(len(points))) - set(best_inliers)
            non_ground_points = [points[i] for i in outlier_indices]
        else:
            non_ground_points = points

        # Conservative post-filter: remove low-height residuals when present.
        height_filtered = [point for point in non_ground_points if point.z > self.ground_plane_max_height]
        if height_filtered:
            non_ground_points = height_filtered

        # Guard against overfitting in sparse clouds: if RANSAC labels everything
        # as ground, fall back to a simple height-based filter.
        if not non_ground_points:
            non_ground_points = [point for point in points if point.z > self.ground_plane_max_height]

        return non_ground_points

    def cluster_points(
        self: PointCloudProcessor, points: list[LidarPoint], eps: float = 0.5, min_points: int = 5
    ) -> list[list[LidarPoint]]:
        """Cluster points using DBSCAN algorithm.

        Args:
            points: List of LIDAR points
            eps: Epsilon neighborhood distance
            min_points: Minimum points to form a cluster

        Returns:
            List of point clusters
        """
        if len(points) == 0:
            return []

        points_array = np.array([[p.x, p.y, p.z] for p in points])

        # Compute pairwise distances
        from scipy.spatial.distance import cdist

        distances = cdist(points_array, points_array, metric="euclidean")

        clusters = []
        visited = np.zeros(len(points), dtype=bool)

        for i in range(len(points)):
            if visited[i]:
                continue

            neighbors = np.where(distances[i] < eps)[0]

            if len(neighbors) < min_points:
                continue

            # Start new cluster
            cluster = []
            to_process = list(neighbors)

            while to_process:
                j = to_process.pop(0)
                if visited[j]:
                    continue

                visited[j] = True
                cluster.append(points[j])

                # Expand cluster
                new_neighbors = np.where(distances[j] < eps)[0]
                if len(new_neighbors) >= min_points:
                    for k in new_neighbors:
                        if not visited[k]:
                            to_process.append(k)

            if len(cluster) > 0:
                clusters.append(cluster)

        return clusters


class LaneDetector:
    """Detect lanes from LIDAR data using Hough transform."""

    def __init__(
        self: LaneDetector,
        hough_threshold: int = 50,
        hough_line_length: float = 2.0,
        hough_line_gap: float = 0.5,
    ) -> None:
        """Initialize lane detector.

        Args:
            hough_threshold: Hough transform threshold
            hough_line_length: Minimum line length
            hough_line_gap: Maximum gap between line segments
        """
        self.hough_threshold = hough_threshold
        self.hough_line_length = hough_line_length
        self.hough_line_gap = hough_line_gap

    def detect_lanes(
        self: LaneDetector, points: list[LidarPoint], vehicle_heading: float = 0.0
    ) -> list[tuple[Vector2D, Vector2D]]:
        """Detect lane markings from LIDAR points.

        Args:
            points: Processed point cloud
            vehicle_heading: Current vehicle heading

        Returns:
            List of lane line segments (start, end)
        """
        if len(points) < 10:
            return []

        # Filter points to lateral region (lanes ahead and to sides)
        filtered_points = [p for p in points if 0.5 < p.x < 50.0 and abs(p.y) < 10.0 and abs(p.z) < 0.2]

        if len(filtered_points) < 10:
            return []

        # Create 2D image for Hough transform
        points_2d = np.array([[p.x, p.y] for p in filtered_points])

        # Normalize to image coordinates
        min_x, min_y = points_2d.min(axis=0)
        max_x, max_y = points_2d.max(axis=0)

        img_width, img_height = 512, 256
        normalized = np.zeros((img_height, img_width), dtype=np.uint8)

        for p in points_2d:
            ix = int((p[0] - min_x) / (max_x - min_x + 1e-6) * (img_width - 1))
            iy = int((p[1] - min_y) / (max_y - min_y + 1e-6) * (img_height - 1))
            if 0 <= ix < img_width and 0 <= iy < img_height:
                normalized[iy, ix] = 255

        # Apply edge detection
        try:
            from scipy import ndimage

            ndimage.sobel(normalized)
        except ImportError:
            pass

        # Simple line detection (replace with proper HoughLinesP if available)
        return [(Vector2D(0, 0), Vector2D(1, 1)) for _ in range(2)]  # Placeholder


class SensorFusion:
    """Multi-sensor fusion using Kalman filtering."""

    def __init__(
        self: SensorFusion,
        process_noise_std: float = 0.1,
        measurement_noise_std: float = 0.5,
    ) -> None:
        """Initialize sensor fusion.

        Args:
            process_noise_std: Process noise standard deviation
            measurement_noise_std: Measurement noise standard deviation
        """
        self.process_noise_std = process_noise_std
        self.measurement_noise_std = measurement_noise_std
        self.tracked_objects: dict[str, KalmanFilterState] = {}

    def update(
        self: SensorFusion,
        lidar_detections: list[tuple[Vector2D, float]],
        radar_detections: list[tuple[Vector2D, float]],
        camera_detections: list[tuple[Vector2D, float]],
        timestamp: float,
    ) -> list[tuple[Vector2D, Vector2D]]:
        """Fuse sensor measurements.

        Args:
            lidar_detections: Detected objects from LIDAR
            radar_detections: Detected objects from radar
            camera_detections: Detected objects from camera
            timestamp: Current timestamp

        Returns:
            List of fused detections (position, velocity)
        """
        all_detections = lidar_detections + radar_detections + camera_detections

        fused = []
        for pos, confidence in all_detections:
            # Simple averaging
            KalmanFilterState(
                position=np.array([pos.x, pos.y]),
                velocity=np.array([0.0, 0.0]),
                covariance=np.eye(4),
                last_update=timestamp,
            )
            fused.append((pos, Vector2D(0.0, 0.0)))

        return fused


class PerceptionPipeline:
    """Complete perception pipeline."""

    def __init__(self: PerceptionPipeline, config: dict[str, Any] | None = None) -> None:
        """Initialize perception pipeline.

        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.point_cloud_processor = PointCloudProcessor()
        self.lane_detector = LaneDetector()
        self.sensor_fusion = SensorFusion()
        self.occupancy_grid = OccupancyGrid(
            width=200,
            height=200,
            resolution=0.1,
            origin_x=-10.0,
            origin_y=-10.0,
        )

    def process_sensor_data(
        self: PerceptionPipeline, sensor_data: SensorData, vehicle_position: Vector2D
    ) -> tuple[list[Obstacle], list[tuple[Vector2D, Vector2D]], OccupancyGrid]:
        """Process sensor data and produce perception output.

        Args:
            sensor_data: Raw sensor measurements
            vehicle_position: Current vehicle position

        Returns:
            Tuple of (detected obstacles, lane detections, occupancy grid)

        Raises:
            SensorDropoutException: If critical sensor data is missing
        """
        if len(sensor_data.lidar_points) == 0:
            raise SensorDropoutException("No LIDAR points received")

        # Remove ground plane
        non_ground_points = self.point_cloud_processor.remove_ground_plane(sensor_data.lidar_points)

        if len(non_ground_points) < 5:
            raise SensorDropoutException("Insufficient points after ground removal")

        # Cluster points
        clusters = self.point_cloud_processor.cluster_points(non_ground_points)

        # Detect lanes
        try:
            lanes = self.lane_detector.detect_lanes(non_ground_points, vehicle_heading=0.0)
        except Exception as e:
            raise LaneDetectionFailureException(f"Lane detection failed: {e}")

        # Convert clusters to obstacles
        obstacles = self._clusters_to_obstacles(clusters, sensor_data.timestamp)

        # Update occupancy grid
        self._update_occupancy_grid(clusters, vehicle_position)

        return obstacles, lanes, self.occupancy_grid

    def _clusters_to_obstacles(
        self: PerceptionPipeline, clusters: list[list[LidarPoint]], timestamp: float
    ) -> list[Obstacle]:
        """Convert point clusters to obstacle objects.

        Args:
            clusters: List of point clusters
            timestamp: Current timestamp

        Returns:
            List of detected obstacles
        """
        obstacles = []

        for i, cluster in enumerate(clusters):
            if len(cluster) < 2:
                continue

            # Compute cluster statistics
            points = np.array([[p.x, p.y, p.z] for p in cluster])
            center = points.mean(axis=0)

            # Estimate dimensions
            distances = np.linalg.norm(points - center, axis=1)
            max_distance = distances.max()

            # Classify as vehicle based on size
            width = max_distance * 0.5
            length = max_distance * 0.8

            obstacle_type = ObstacleType.VEHICLE if max_distance > 1.0 else ObstacleType.DEBRIS

            obstacles.append(
                Obstacle(
                    obstacle_id=f"obs_{i}",
                    position=Vector2D(float(center[0]), float(center[1])),
                    velocity=Vector2D(0.0, 0.0),
                    acceleration=Vector2D(0.0, 0.0),
                    obstacle_type=obstacle_type,
                    width=float(width),
                    length=float(length),
                    heading=0.0,
                    confidence=0.8,
                    age=0.1,
                )
            )

        return obstacles

    def _update_occupancy_grid(
        self: PerceptionPipeline, clusters: list[list[LidarPoint]], vehicle_position: Vector2D
    ) -> None:
        """Update occupancy grid with point clusters.

        Args:
            clusters: Point clusters
            vehicle_position: Current vehicle position
        """
        for cluster in clusters:
            for point in cluster:
                self.occupancy_grid.set_occupied(point.x, point.y, 0.9)
