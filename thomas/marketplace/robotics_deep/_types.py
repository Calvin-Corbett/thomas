"""
Core data types for robotics: vectors, matrices, quaternions, and robot state representations.
"""

import math
from dataclasses import dataclass, field
from enum import Enum


class JointType(Enum):
    """Robot joint types."""

    REVOLUTE = "revolute"
    PRISMATIC = "prismatic"
    FIXED = "fixed"


@dataclass
class Vec3:
    """3D vector with common operations."""

    x: float
    y: float
    z: float

    def __add__(self, other: "Vec3") -> "Vec3":
        """Vector addition."""
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        """Vector subtraction."""
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        """Scalar multiplication."""
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def dot(self, other: "Vec3") -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vec3") -> "Vec3":
        """Cross product."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def magnitude(self) -> float:
        """Vector magnitude."""
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def normalize(self) -> "Vec3":
        """Return normalized vector."""
        mag = self.magnitude()
        if mag == 0:
            return Vec3(0, 0, 0)
        return Vec3(self.x / mag, self.y / mag, self.z / mag)

    def to_list(self) -> list[float]:
        """Convert to list."""
        return [self.x, self.y, self.z]


@dataclass
class Matrix3x3:
    """3x3 rotation matrix."""

    data: list[list[float]] = field(default_factory=lambda: [[0] * 3 for _ in range(3)])

    @classmethod
    def identity(cls) -> "Matrix3x3":
        """Create identity matrix."""
        m = cls()
        for i in range(3):
            m.data[i][i] = 1.0
        return m

    @classmethod
    def from_list(cls, data: list[list[float]]) -> "Matrix3x3":
        """Create from 3x3 list."""
        m = cls()
        m.data = [row[:] for row in data]
        return m

    def multiply(self, other: "Matrix3x3") -> "Matrix3x3":
        """Matrix multiplication."""
        result = Matrix3x3()
        for i in range(3):
            for j in range(3):
                result.data[i][j] = sum(self.data[i][k] * other.data[k][j] for k in range(3))
        return result

    def transpose(self) -> "Matrix3x3":
        """Return transposed matrix."""
        result = Matrix3x3()
        for i in range(3):
            for j in range(3):
                result.data[i][j] = self.data[j][i]
        return result

    def determinant(self) -> float:
        """Compute determinant."""
        return (
            self.data[0][0] * (self.data[1][1] * self.data[2][2] - self.data[1][2] * self.data[2][1])
            - self.data[0][1] * (self.data[1][0] * self.data[2][2] - self.data[1][2] * self.data[2][0])
            + self.data[0][2] * (self.data[1][0] * self.data[2][1] - self.data[1][1] * self.data[2][0])
        )

    def inverse(self) -> "Matrix3x3":
        """Return inverse matrix."""
        det = self.determinant()
        if abs(det) < 1e-10:
            raise ValueError("Matrix is singular")

        result = Matrix3x3()
        result.data[0][0] = (self.data[1][1] * self.data[2][2] - self.data[1][2] * self.data[2][1]) / det
        result.data[0][1] = (self.data[0][2] * self.data[2][1] - self.data[0][1] * self.data[2][2]) / det
        result.data[0][2] = (self.data[0][1] * self.data[1][2] - self.data[0][2] * self.data[1][1]) / det
        result.data[1][0] = (self.data[1][2] * self.data[2][0] - self.data[1][0] * self.data[2][2]) / det
        result.data[1][1] = (self.data[0][0] * self.data[2][2] - self.data[0][2] * self.data[2][0]) / det
        result.data[1][2] = (self.data[1][0] * self.data[0][2] - self.data[0][0] * self.data[1][2]) / det
        result.data[2][0] = (self.data[1][0] * self.data[2][1] - self.data[2][0] * self.data[1][1]) / det
        result.data[2][1] = (self.data[2][0] * self.data[0][1] - self.data[0][0] * self.data[2][1]) / det
        result.data[2][2] = (self.data[0][0] * self.data[1][1] - self.data[1][0] * self.data[0][1]) / det
        return result

    def to_list(self) -> list[list[float]]:
        """Convert to list."""
        return [row[:] for row in self.data]


@dataclass
class Matrix4x4:
    """4x4 homogeneous transformation matrix."""

    data: list[list[float]] = field(default_factory=lambda: [[0] * 4 for _ in range(4)])

    @classmethod
    def identity(cls) -> "Matrix4x4":
        """Create identity matrix."""
        m = cls()
        for i in range(4):
            m.data[i][i] = 1.0
        return m

    @classmethod
    def from_pose(cls, position: Vec3, rotation: Matrix3x3) -> "Matrix4x4":
        """Create from position and rotation."""
        m = cls()
        for i in range(3):
            for j in range(3):
                m.data[i][j] = rotation.data[i][j]
            m.data[i][3] = position.to_list()[i]
        m.data[3][3] = 1.0
        return m

    def multiply(self, other: "Matrix4x4") -> "Matrix4x4":
        """Matrix multiplication."""
        result = Matrix4x4()
        for i in range(4):
            for j in range(4):
                result.data[i][j] = sum(self.data[i][k] * other.data[k][j] for k in range(4))
        return result

    def transpose(self) -> "Matrix4x4":
        """Return transposed matrix."""
        result = Matrix4x4()
        for i in range(4):
            for j in range(4):
                result.data[i][j] = self.data[j][i]
        return result

    def inverse(self) -> "Matrix4x4":
        """Return inverse of homogeneous transformation."""
        result = Matrix4x4()

        # Extract rotation
        rot = Matrix3x3()
        for i in range(3):
            for j in range(3):
                rot.data[i][j] = self.data[i][j]

        # Extract position
        pos = Vec3(self.data[0][3], self.data[1][3], self.data[2][3])

        # Inverse: R^T and -R^T * p
        rot_inv = rot.transpose()
        pos_inv = rot_inv.multiply(Matrix3x3.from_list([[p] for p in pos.to_list()]))

        for i in range(3):
            for j in range(3):
                result.data[i][j] = rot_inv.data[i][j]
            result.data[i][3] = -sum(rot_inv.data[i][k] * pos.to_list()[k] for k in range(3))

        result.data[3][3] = 1.0
        return result

    def get_position(self) -> Vec3:
        """Extract position vector."""
        return Vec3(self.data[0][3], self.data[1][3], self.data[2][3])

    def get_rotation(self) -> Matrix3x3:
        """Extract rotation matrix."""
        rot = Matrix3x3()
        for i in range(3):
            for j in range(3):
                rot.data[i][j] = self.data[i][j]
        return rot

    def to_list(self) -> list[list[float]]:
        """Convert to list."""
        return [row[:] for row in self.data]


@dataclass
class Quaternion:
    """Quaternion for rotation representation: q = w + xi + yj + zk."""

    w: float
    x: float
    y: float
    z: float

    @classmethod
    def identity(cls) -> "Quaternion":
        """Create identity quaternion."""
        return cls(w=1.0, x=0.0, y=0.0, z=0.0)

    @classmethod
    def from_euler(cls, roll: float, pitch: float, yaw: float) -> "Quaternion":
        """Create from Euler angles (XYZ order)."""
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)

        w = cr * cp * cy + sr * sp * sy
        x = sr * cp * cy - cr * sp * sy
        y = cr * sp * cy + sr * cp * sy
        z = cr * cp * sy - sr * sp * cy

        return cls(w=w, x=x, y=y, z=z)

    def to_euler(self) -> tuple[float, float, float]:
        """Convert to Euler angles (XYZ order)."""
        sinr_cosp = 2 * (self.w * self.x + self.y * self.z)
        cosr_cosp = 1 - 2 * (self.x**2 + self.y**2)
        roll = math.atan2(sinr_cosp, cosr_cosp)

        sinp = 2 * (self.w * self.y - self.z * self.x)
        sinp = min(1.0, max(-1.0, sinp))
        pitch = math.asin(sinp)

        siny_cosp = 2 * (self.w * self.z + self.x * self.y)
        cosy_cosp = 1 - 2 * (self.y**2 + self.z**2)
        yaw = math.atan2(siny_cosp, cosy_cosp)

        return roll, pitch, yaw

    def normalize(self) -> "Quaternion":
        """Return normalized quaternion."""
        mag = math.sqrt(self.w**2 + self.x**2 + self.y**2 + self.z**2)
        if mag == 0:
            return Quaternion.identity()
        return Quaternion(w=self.w / mag, x=self.x / mag, y=self.y / mag, z=self.z / mag)

    def multiply(self, other: "Quaternion") -> "Quaternion":
        """Quaternion multiplication."""
        w = self.w * other.w - self.x * other.x - self.y * other.y - self.z * other.z
        x = self.w * other.x + self.x * other.w + self.y * other.z - self.z * other.y
        y = self.w * other.y - self.x * other.z + self.y * other.w + self.z * other.x
        z = self.w * other.z + self.x * other.y - self.y * other.x + self.z * other.w
        return Quaternion(w=w, x=x, y=y, z=z)

    def slerp(self, other: "Quaternion", t: float) -> "Quaternion":
        """Spherical linear interpolation."""
        dot = self.w * other.w + self.x * other.x + self.y * other.y + self.z * other.z

        if dot < 0:
            other = Quaternion(-other.w, -other.x, -other.y, -other.z)
            dot = -dot

        dot = min(1.0, max(-1.0, dot))
        theta = math.acos(dot)
        sin_theta = math.sin(theta)

        if sin_theta < 1e-6:
            return Quaternion(
                w=self.w + t * (other.w - self.w),
                x=self.x + t * (other.x - self.x),
                y=self.y + t * (other.y - self.y),
                z=self.z + t * (other.z - self.z),
            )

        w1 = math.sin((1 - t) * theta) / sin_theta
        w2 = math.sin(t * theta) / sin_theta

        return Quaternion(
            w=w1 * self.w + w2 * other.w,
            x=w1 * self.x + w2 * other.x,
            y=w1 * self.y + w2 * other.y,
            z=w1 * self.z + w2 * other.z,
        ).normalize()

    def to_matrix(self) -> Matrix3x3:
        """Convert to 3x3 rotation matrix."""
        m = Matrix3x3()
        m.data[0][0] = 1 - 2 * (self.y**2 + self.z**2)
        m.data[0][1] = 2 * (self.x * self.y - self.w * self.z)
        m.data[0][2] = 2 * (self.x * self.z + self.w * self.y)
        m.data[1][0] = 2 * (self.x * self.y + self.w * self.z)
        m.data[1][1] = 1 - 2 * (self.x**2 + self.z**2)
        m.data[1][2] = 2 * (self.y * self.z - self.w * self.x)
        m.data[2][0] = 2 * (self.x * self.z - self.w * self.y)
        m.data[2][1] = 2 * (self.y * self.z + self.w * self.x)
        m.data[2][2] = 1 - 2 * (self.x**2 + self.y**2)
        return m


@dataclass
class DHParams:
    """Denavit-Hartenberg parameters for a joint."""

    a: float  # Link length
    alpha: float  # Link twist
    d: float  # Link offset
    theta: float  # Joint angle (for revolute)


@dataclass
class JointState:
    """State of a single robot joint."""

    position: float
    velocity: float
    acceleration: float
    effort: float


@dataclass
class Pose:
    """3D position and orientation."""

    position: Vec3
    orientation: Quaternion

    @classmethod
    def identity(cls) -> "Pose":
        """Create identity pose."""
        return cls(position=Vec3(0, 0, 0), orientation=Quaternion.identity())

    def to_matrix(self) -> Matrix4x4:
        """Convert to 4x4 transformation matrix."""
        return Matrix4x4.from_pose(self.position, self.orientation.to_matrix())

    @classmethod
    def from_matrix(cls, matrix: Matrix4x4) -> "Pose":
        """Create from 4x4 transformation matrix."""
        pos = matrix.get_position()
        rot = matrix.get_rotation()
        # Simplified quaternion from matrix
        quat = Quaternion.identity()
        trace = rot.data[0][0] + rot.data[1][1] + rot.data[2][2]
        if trace > 0:
            s = 0.5 / math.sqrt(trace + 1.0)
            quat.w = 0.25 / s
            quat.x = (rot.data[2][1] - rot.data[1][2]) * s
            quat.y = (rot.data[0][2] - rot.data[2][0]) * s
            quat.z = (rot.data[1][0] - rot.data[0][1]) * s
        return cls(position=pos, orientation=quat)


@dataclass
class Trajectory:
    """Robot trajectory: sequence of poses over time."""

    waypoints: list[Pose]
    times: list[float]

    def __post_init__(self) -> None:
        """Validate trajectory."""
        if len(self.waypoints) != len(self.times):
            raise ValueError("Waypoints and times must have same length")

    def duration(self) -> float:
        """Total trajectory duration."""
        return self.times[-1] if self.times else 0.0


@dataclass
class SensorReading:
    """Generic sensor reading with timestamp."""

    timestamp: float
    data: list[float]
    sensor_id: str


@dataclass
class LaserScan:
    """Lidar laser scan data."""

    timestamp: float
    ranges: list[float]  # Distance measurements
    angles: list[float]  # Angle of each ray
    min_angle: float
    max_angle: float
    angle_increment: float


@dataclass
class OccupancyGrid:
    """2D occupancy grid map."""

    width: int
    height: int
    resolution: float  # meters per cell
    origin_x: float
    origin_y: float
    data: list[list[float]]  # Occupancy probabilities [0, 1]

    def __post_init__(self) -> None:
        """Initialize grid if empty."""
        if not self.data:
            self.data = [[0.5 for _ in range(self.width)] for _ in range(self.height)]

    def get_cell(self, x: float, y: float) -> float:
        """Get occupancy at world coordinates."""
        grid_x = int((x - self.origin_x) / self.resolution)
        grid_y = int((y - self.origin_y) / self.resolution)
        if 0 <= grid_x < self.width and 0 <= grid_y < self.height:
            return self.data[grid_y][grid_x]
        return 0.5

    def set_cell(self, x: float, y: float, value: float) -> None:
        """Set occupancy at world coordinates."""
        grid_x = int((x - self.origin_x) / self.resolution)
        grid_y = int((y - self.origin_y) / self.resolution)
        if 0 <= grid_x < self.width and 0 <= grid_y < self.height:
            self.data[grid_y][grid_x] = max(0.0, min(1.0, value))
