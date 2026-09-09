"""Type definitions for autonomous vehicle module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class VehicleType(Enum):
    """Vehicle type enumeration."""

    SEDAN = "sedan"
    SUV = "suv"
    TRUCK = "truck"
    BUS = "bus"


class TrafficLightState(Enum):
    """Traffic light state enumeration."""

    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


class TrafficSignType(Enum):
    """Traffic sign type enumeration."""

    STOP = "stop"
    YIELD = "yield"
    SPEED_LIMIT = "speed_limit"
    DO_NOT_ENTER = "do_not_enter"
    ONE_WAY = "one_way"
    NO_PARKING = "no_parking"


class ObstacleType(Enum):
    """Obstacle type enumeration."""

    VEHICLE = "vehicle"
    PEDESTRIAN = "pedestrian"
    BICYCLE = "bicycle"
    STATIC = "static"
    DEBRIS = "debris"


class ManeuverType(Enum):
    """Maneuver type enumeration."""

    LANE_FOLLOW = "lane_follow"
    LANE_CHANGE_LEFT = "lane_change_left"
    LANE_CHANGE_RIGHT = "lane_change_right"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    INTERSECTION_CROSSING = "intersection_crossing"
    MERGE = "merge"
    UNMERGE = "unmerge"


@dataclass
class Vector2D:
    """2D vector representation."""

    x: float
    y: float

    def __add__(self: Vector2D, other: Vector2D) -> Vector2D:
        """Add vectors."""
        return Vector2D(self.x + other.x, self.y + other.y)

    def __sub__(self: Vector2D, other: Vector2D) -> Vector2D:
        """Subtract vectors."""
        return Vector2D(self.x - other.x, self.y - other.y)

    def __mul__(self: Vector2D, scalar: float) -> Vector2D:
        """Scalar multiplication."""
        return Vector2D(self.x * scalar, self.y * scalar)

    def norm(self: Vector2D) -> float:
        """Compute vector norm."""
        return float(np.sqrt(self.x**2 + self.y**2))

    def distance_to(self: Vector2D, other: Vector2D) -> float:
        """Compute distance to another vector."""
        return (self - other).norm()

    def dot(self: Vector2D, other: Vector2D) -> float:
        """Compute dot product."""
        return self.x * other.x + self.y * other.y

    def to_array(self: Vector2D) -> np.ndarray:
        """Convert to numpy array."""
        return np.array([self.x, self.y])


@dataclass
class LidarPoint:
    """LIDAR point in 3D space with intensity."""

    x: float
    y: float
    z: float
    intensity: float
    ring: int = 0

    def to_array(self: LidarPoint) -> np.ndarray:
        """Convert to numpy array."""
        return np.array([self.x, self.y, self.z])

    def distance(self: LidarPoint) -> float:
        """Compute distance from origin."""
        return float(np.sqrt(self.x**2 + self.y**2 + self.z**2))


@dataclass
class CameraFrame:
    """Camera frame data."""

    timestamp: float
    frame_id: int
    width: int
    height: int
    image_data: np.ndarray  # HxWx3 uint8 array
    intrinsics: np.ndarray  # 3x3 camera matrix
    distortion_coeffs: np.ndarray  # Distortion coefficients

    def get_shape(self: CameraFrame) -> tuple[int, int, int]:
        """Get image shape."""
        return tuple(self.image_data.shape)


@dataclass
class RadarReturn:
    """Radar return measurement."""

    range_m: float  # Range in meters
    azimuth_rad: float  # Azimuth angle in radians
    elevation_rad: float  # Elevation angle in radians
    doppler_velocity: float  # Doppler velocity in m/s
    rcs: float  # Radar cross section in dBsm
    signal_strength: float  # Signal strength


@dataclass
class SensorData:
    """Aggregated sensor data from all onboard sensors."""

    timestamp: float
    lidar_points: list[LidarPoint]
    camera_frames: list[CameraFrame]
    radar_returns: list[RadarReturn]
    imu_acceleration: Vector2D
    imu_angular_velocity: float
    gnss_position: Vector2D
    gnss_covariance: np.ndarray
    wheel_speeds: list[float]  # [FL, FR, BL, BR]

    def num_lidar_points(self: SensorData) -> int:
        """Get number of LIDAR points."""
        return len(self.lidar_points)

    def num_cameras(self: SensorData) -> int:
        """Get number of camera frames."""
        return len(self.camera_frames)

    def num_radar_returns(self: SensorData) -> int:
        """Get number of radar returns."""
        return len(self.radar_returns)


@dataclass
class VehicleState:
    """Vehicle state: position, velocity, acceleration, heading, steering angle."""

    timestamp: float
    position: Vector2D
    velocity: Vector2D
    acceleration: Vector2D
    heading: float  # Yaw angle in radians
    heading_rate: float  # Yaw rate in rad/s
    steering_angle: float  # Steering angle in radians
    speed: float  # Speed magnitude in m/s

    def to_array(self: VehicleState) -> np.ndarray:
        """Convert state to numpy array [x, y, vx, vy, theta, delta]."""
        return np.array(
            [
                self.position.x,
                self.position.y,
                self.velocity.x,
                self.velocity.y,
                self.heading,
                self.steering_angle,
            ]
        )

    @classmethod
    def from_array(cls, state_array: np.ndarray, timestamp: float = 0.0) -> VehicleState:
        """Create VehicleState from numpy array."""
        x, y, vx, vy, theta, delta = state_array
        position = Vector2D(float(x), float(y))
        velocity = Vector2D(float(vx), float(vy))
        speed = float(np.sqrt(vx**2 + vy**2))
        acceleration = Vector2D(0.0, 0.0)
        return cls(
            timestamp=timestamp,
            position=position,
            velocity=velocity,
            acceleration=acceleration,
            heading=float(theta),
            heading_rate=0.0,
            steering_angle=float(delta),
            speed=speed,
        )


@dataclass
class ControlCommand:
    """Control command for vehicle."""

    timestamp: float
    acceleration: float  # m/s^2, positive = forward
    steering_angle: float  # radians, positive = left
    gear: str = "D"  # D, R, N, P
    brake_pedal: float = 0.0  # 0.0 to 1.0
    throttle_pedal: float = 0.0  # 0.0 to 1.0

    def is_valid(self: ControlCommand) -> bool:
        """Check if command is valid."""
        return (
            abs(self.acceleration) <= 10.0
            and abs(self.steering_angle) <= 1.0
            and 0.0 <= self.brake_pedal <= 1.0
            and 0.0 <= self.throttle_pedal <= 1.0
        )


@dataclass
class Waypoint:
    """Waypoint along a path."""

    position: Vector2D
    heading: float  # Yaw angle in radians
    curvature: float = 0.0  # Path curvature in 1/m
    speed_limit: float = 30.0  # Speed limit in m/s
    timestamp: float = 0.0

    def distance_to(self: Waypoint, other: Waypoint) -> float:
        """Compute distance to another waypoint."""
        return self.position.distance_to(other.position)


@dataclass
class Route:
    """Route consisting of waypoints."""

    waypoints: list[Waypoint]
    route_id: str = ""

    def length(self: Route) -> float:
        """Compute total route length."""
        if len(self.waypoints) < 2:
            return 0.0
        total_length = 0.0
        for i in range(len(self.waypoints) - 1):
            total_length += self.waypoints[i].distance_to(self.waypoints[i + 1])
        return total_length

    def get_waypoint_at_index(self: Route, index: int) -> Waypoint | None:
        """Get waypoint at index."""
        if 0 <= index < len(self.waypoints):
            return self.waypoints[index]
        return None


@dataclass
class Lane:
    """Lane geometry with centerline and boundaries."""

    lane_id: str
    centerline: list[Vector2D]  # Polyline points
    left_boundary: list[Vector2D]
    right_boundary: list[Vector2D]
    lane_width: float
    lane_type: str = "driving"  # driving, parking, shoulder
    direction: str = "forward"  # forward, backward, bidirectional

    def length(self: Lane) -> float:
        """Compute lane length."""
        if len(self.centerline) < 2:
            return 0.0
        total = 0.0
        for i in range(len(self.centerline) - 1):
            total += self.centerline[i].distance_to(self.centerline[i + 1])
        return total


@dataclass
class TrafficSign:
    """Traffic sign with position and type."""

    sign_id: str
    position: Vector2D
    sign_type: TrafficSignType
    value: float = 0.0  # Speed limit value for SPEED_LIMIT signs
    heading: float = 0.0


@dataclass
class TrafficLight:
    """Traffic light state and timing."""

    light_id: str
    position: Vector2D
    state: TrafficLightState
    time_until_change: float  # Seconds until next state change
    lane_id: str = ""


@dataclass
class Obstacle:
    """Detected obstacle with state and classification."""

    obstacle_id: str
    position: Vector2D
    velocity: Vector2D
    acceleration: Vector2D
    obstacle_type: ObstacleType
    width: float = 1.5
    length: float = 4.0
    height: float = 1.5
    heading: float = 0.0
    confidence: float = 1.0
    age: float = 0.0

    def distance_to(self: Obstacle, position: Vector2D) -> float:
        """Compute distance to position."""
        return self.position.distance_to(position)

    def time_to_collision(self: Obstacle, vehicle_position: Vector2D, vehicle_velocity: Vector2D) -> float | None:
        """Estimate time to collision with vehicle."""
        relative_position = self.position - vehicle_position
        relative_velocity = self.velocity - vehicle_velocity

        if relative_velocity.norm() < 1e-6:
            return None

        a = relative_velocity.x**2 + relative_velocity.y**2
        b = 2 * (relative_position.x * relative_velocity.x + relative_position.y * relative_velocity.y)
        c = relative_position.x**2 + relative_position.y**2 - ((self.width + self.length) / 2) ** 2

        discriminant = b**2 - 4 * a * c
        if discriminant < 0:
            return None

        t1 = (-b - np.sqrt(discriminant)) / (2 * a)
        if t1 >= 0:
            return float(t1)

        t2 = (-b + np.sqrt(discriminant)) / (2 * a)
        if t2 >= 0:
            return float(t2)

        return None


@dataclass
class PlannerConfig:
    """Configuration for motion planner."""

    max_speed: float = 25.0  # m/s
    max_acceleration: float = 3.0  # m/s^2
    max_deceleration: float = 8.0  # m/s^2
    max_steering_rate: float = 0.5  # rad/s
    max_steering_angle: float = 0.5  # radians (about 30 degrees)
    wheelbase: float = 2.7  # meters
    track_width: float = 1.6  # meters
    vehicle_length: float = 4.5  # meters
    vehicle_width: float = 1.8  # meters
    prediction_horizon: float = 5.0  # seconds
    planning_frequency: float = 10.0  # Hz
    lateral_tolerance: float = 0.3  # meters
    longitudinal_tolerance: float = 1.0  # meters
    dt: float = 0.1  # Time step in seconds
    num_trajectory_samples: int = 50  # Number of trajectory samples for planner

    def get_planning_dt(self: PlannerConfig) -> float:
        """Get planning time step."""
        return 1.0 / self.planning_frequency

    def get_num_steps(self: PlannerConfig, horizon: float | None = None) -> int:
        """Get number of planning steps for horizon."""
        h = horizon if horizon is not None else self.prediction_horizon
        return int(h * self.planning_frequency)
