"""Core type definitions for the computer vision module."""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ColorSpace(Enum):
    """Enumeration of supported color spaces."""

    RGB = "RGB"
    BGR = "BGR"
    GRAYSCALE = "GRAYSCALE"
    HSV = "HSV"
    HSL = "HSL"
    YCbCr = "YCbCr"
    Lab = "Lab"


class ImageFormat(Enum):
    """Enumeration of supported image file formats."""

    BMP = "BMP"
    PPM = "PPM"
    PGM = "PGM"
    TGA = "TGA"
    RAW = "RAW"


@dataclass
class Point:
    """Represents a 2D point in image space.

    Attributes:
        x: Horizontal coordinate
        y: Vertical coordinate
    """

    x: float
    y: float

    def __add__(self, other: "Point") -> "Point":
        """Add two points."""
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point") -> "Point":
        """Subtract two points."""
        return Point(self.x - other.x, self.y - other.y)

    def distance_to(self, other: "Point") -> float:
        """Calculate Euclidean distance to another point."""
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def dot(self, other: "Point") -> float:
        """Calculate dot product with another point."""
        return self.x * other.x + self.y * other.y


@dataclass
class Color:
    """Represents an RGB color value.

    Attributes:
        r: Red channel (0-255)
        g: Green channel (0-255)
        b: Blue channel (0-255)
        a: Alpha channel (0-255), optional
    """

    r: int
    g: int
    b: int
    a: int = 255

    def to_tuple(self) -> tuple[int, int, int, int]:
        """Convert to RGBA tuple."""
        return (self.r, self.g, self.b, self.a)

    def to_grayscale(self, weights: tuple[float, float, float] | None = None) -> int:
        """Convert color to grayscale using weighted average."""
        if weights is None:
            weights = (0.299, 0.587, 0.114)  # BT.601
        return int(self.r * weights[0] + self.g * weights[1] + self.b * weights[2])


@dataclass
class Pixel:
    """Represents a single pixel with coordinates and value.

    Attributes:
        x: Horizontal position
        y: Vertical position
        value: Pixel value (int or float)
    """

    x: int
    y: int
    value: int | float


@dataclass
class BoundingBox:
    """Represents an axis-aligned bounding box.

    Attributes:
        x: Left coordinate
        y: Top coordinate
        width: Box width
        height: Box height
    """

    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        """Calculate bounding box area."""
        return self.width * self.height

    def intersection(self, other: "BoundingBox") -> Optional["BoundingBox"]:
        """Calculate intersection with another bounding box."""
        x1 = max(self.x, other.x)
        y1 = max(self.y, other.y)
        x2 = min(self.x + self.width, other.x + other.width)
        y2 = min(self.y + self.height, other.y + other.height)

        if x2 <= x1 or y2 <= y1:
            return None
        return BoundingBox(x1, y1, x2 - x1, y2 - y1)

    def union(self, other: "BoundingBox") -> "BoundingBox":
        """Calculate union with another bounding box."""
        x1 = min(self.x, other.x)
        y1 = min(self.y, other.y)
        x2 = max(self.x + self.width, other.x + other.width)
        y2 = max(self.y + self.height, other.y + other.height)
        return BoundingBox(x1, y1, x2 - x1, y2 - y1)

    def iou(self, other: "BoundingBox") -> float:
        """Calculate intersection over union with another bounding box."""
        intersection = self.intersection(other)
        if intersection is None:
            return 0.0
        intersection_area = intersection.area
        union_area = self.area + other.area - intersection_area
        return intersection_area / union_area if union_area > 0 else 0.0


@dataclass
class ROI:
    """Region of Interest within an image.

    Attributes:
        bbox: Bounding box defining the region
        label: Optional label for the region
    """

    bbox: BoundingBox
    label: str | None = None


@dataclass
class Contour:
    """Represents a contour (ordered set of boundary points).

    Attributes:
        points: List of (x, y) tuples forming the contour
    """

    points: list[tuple[int, int]] = field(default_factory=list)

    @property
    def area(self) -> float:
        """Calculate contour area using shoelace formula."""
        if len(self.points) < 3:
            return 0.0
        area = 0.0
        for i in range(len(self.points)):
            j = (i + 1) % len(self.points)
            area += self.points[i][0] * self.points[j][1]
            area -= self.points[j][0] * self.points[i][1]
        return abs(area) / 2.0

    @property
    def perimeter(self) -> float:
        """Calculate contour perimeter."""
        if len(self.points) < 2:
            return 0.0
        perimeter = 0.0
        for i in range(len(self.points)):
            j = (i + 1) % len(self.points)
            dx = self.points[j][0] - self.points[i][0]
            dy = self.points[j][1] - self.points[i][1]
            perimeter += math.sqrt(dx * dx + dy * dy)
        return perimeter

    @property
    def centroid(self) -> Point:
        """Calculate contour centroid."""
        if not self.points:
            return Point(0, 0)
        cx = sum(p[0] for p in self.points) / len(self.points)
        cy = sum(p[1] for p in self.points) / len(self.points)
        return Point(cx, cy)

    @property
    def bounding_box(self) -> BoundingBox:
        """Calculate minimal bounding box."""
        if not self.points:
            return BoundingBox(0, 0, 0, 0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        return BoundingBox(x_min, y_min, x_max - x_min, y_max - y_min)


@dataclass
class Histogram:
    """Represents a histogram of values.

    Attributes:
        bins: Number of histogram bins
        data: Histogram bin counts
        range: (min, max) value range
    """

    bins: int
    data: list[int] = field(default_factory=list)
    range: tuple[float, float] = (0.0, 256.0)

    def normalize(self) -> list[float]:
        """Normalize histogram to 0-1 range."""
        total = sum(self.data) if self.data else 1
        return [x / total for x in self.data]


@dataclass
class Kernel:
    """Represents a convolution kernel.

    Attributes:
        data: 2D kernel data as list of lists
        size: (height, width) of kernel
        anchor: (y, x) anchor point for convolution
    """

    data: list[list[float]]
    anchor: tuple[int, int] = (0, 0)

    @property
    def size(self) -> tuple[int, int]:
        """Get kernel dimensions."""
        if not self.data:
            return (0, 0)
        return (len(self.data), len(self.data[0]))

    @property
    def sum(self) -> float:
        """Calculate sum of all kernel elements."""
        return sum(sum(row) for row in self.data)

    def normalize(self) -> "Kernel":
        """Return normalized kernel (sum = 1)."""
        total = self.sum
        if total == 0:
            return Kernel(self.data.copy(), self.anchor)
        normalized = [[x / total for x in row] for row in self.data]
        return Kernel(normalized, self.anchor)


@dataclass
class Feature:
    """Represents a detected feature (corner/keypoint) in an image.

    Attributes:
        x: Horizontal coordinate
        y: Vertical coordinate
        response: Feature strength/score
        scale: Characteristic scale
        angle: Dominant orientation (in radians)
    """

    x: float
    y: float
    response: float
    scale: float = 1.0
    angle: float = 0.0

    def to_point(self) -> Point:
        """Convert to Point."""
        return Point(self.x, self.y)


@dataclass
class Descriptor:
    """Represents a feature descriptor (e.g., BRIEF).

    Attributes:
        data: Binary descriptor as list of bits or float vector
        feature_id: ID of associated feature
        descriptor_type: Type of descriptor (e.g., 'BRIEF', 'SIFT')
    """

    data: list[int] | list[float]
    feature_id: int = 0
    descriptor_type: str = "UNKNOWN"

    def hamming_distance(self, other: "Descriptor") -> int:
        """Calculate Hamming distance to another binary descriptor."""
        if not isinstance(self.data[0], int) or not isinstance(other.data[0], int):
            raise ValueError("Hamming distance requires binary descriptors")
        return sum(a != b for a, b in zip(self.data, other.data))

    def euclidean_distance(self, other: "Descriptor") -> float:
        """Calculate Euclidean distance to another descriptor."""
        if not isinstance(self.data[0], (int, float)):
            raise ValueError("Invalid descriptor data type")
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(self.data, other.data)))


@dataclass
class Match:
    """Represents a feature match between two descriptors.

    Attributes:
        query_idx: Index in query descriptor set
        train_idx: Index in training descriptor set
        distance: Match distance/error
        good: Whether match passed filtering
    """

    query_idx: int
    train_idx: int
    distance: float
    good: bool = True


@dataclass
class Transform2D:
    """Represents a 2D affine or perspective transformation.

    Attributes:
        matrix: 2x3 (affine) or 3x3 (perspective) transformation matrix
        is_perspective: Whether this is a perspective transform
    """

    matrix: list[list[float]]
    is_perspective: bool = False

    def transform_point(self, point: Point) -> Point:
        """Apply transformation to a single point."""
        if self.is_perspective and len(self.matrix) == 3:
            x = self.matrix[0][0] * point.x + self.matrix[0][1] * point.y + self.matrix[0][2]
            y = self.matrix[1][0] * point.x + self.matrix[1][1] * point.y + self.matrix[1][2]
            w = self.matrix[2][0] * point.x + self.matrix[2][1] * point.y + self.matrix[2][2]
            if abs(w) > 1e-10:
                return Point(x / w, y / w)
            return Point(0, 0)
        else:
            x = self.matrix[0][0] * point.x + self.matrix[0][1] * point.y + self.matrix[0][2]
            y = self.matrix[1][0] * point.x + self.matrix[1][1] * point.y + self.matrix[1][2]
            return Point(x, y)

    @staticmethod
    def identity() -> "Transform2D":
        """Create identity transform."""
        return Transform2D([[1, 0, 0], [0, 1, 0]])

    @staticmethod
    def translation(tx: float, ty: float) -> "Transform2D":
        """Create translation transform."""
        return Transform2D([[1, 0, tx], [0, 1, ty]])

    @staticmethod
    def scaling(sx: float, sy: float) -> "Transform2D":
        """Create scaling transform."""
        return Transform2D([[sx, 0, 0], [0, sy, 0]])

    @staticmethod
    def rotation(angle_rad: float, cx: float = 0, cy: float = 0) -> "Transform2D":
        """Create rotation transform around point (cx, cy)."""
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        tx = cx - cx * cos_a + cy * sin_a
        ty = cy - cx * sin_a - cy * cos_a
        return Transform2D([[cos_a, -sin_a, tx], [sin_a, cos_a, ty]])


class Image:
    """2D image wrapper with automatic width/height/channels tracking.

    Stores image data as a 3D array with shape (height, width, channels).
    Supports multiple data types (uint8, float32, etc.).

    Attributes:
        width: Image width in pixels
        height: Image height in pixels
        channels: Number of color channels (1 for grayscale, 3 for RGB, 4 for RGBA)
        dtype: Data type of pixel values
        color_space: Color space representation
    """

    def __init__(
        self,
        data: list[list[list[int | float]]],
        color_space: ColorSpace = ColorSpace.RGB,
        dtype: str = "uint8",
    ) -> None:
        """Initialize Image from 3D data array.

        Args:
            data: 3D array [height][width][channels]
            color_space: Color space of the image
            dtype: Data type ('uint8' or 'float32')
        """
        self.data = data
        self.color_space = color_space
        self.dtype = dtype

    @property
    def height(self) -> int:
        """Get image height."""
        return len(self.data)

    @property
    def width(self) -> int:
        """Get image width."""
        return len(self.data[0]) if self.data else 0

    @property
    def channels(self) -> int:
        """Get number of channels."""
        if self.height > 0 and self.width > 0:
            return len(self.data[0][0])
        return 0

    @property
    def shape(self) -> tuple[int, int, int]:
        """Get shape tuple (height, width, channels)."""
        return (self.height, self.width, self.channels)

    @property
    def size(self) -> int:
        """Get total number of pixels."""
        return self.height * self.width

    def get_pixel(self, x: int, y: int) -> Pixel:
        """Get pixel value at coordinates.

        Args:
            x: Horizontal coordinate
            y: Vertical coordinate

        Returns:
            Pixel with value (tuple for multi-channel)
        """
        if 0 <= y < self.height and 0 <= x < self.width:
            value = self.data[y][x]
            return Pixel(x, y, value)
        raise IndexError(f"Pixel ({x}, {y}) out of bounds")

    def set_pixel(self, x: int, y: int, value: int | float | list | tuple) -> None:
        """Set pixel value at coordinates.

        Args:
            x: Horizontal coordinate
            y: Vertical coordinate
            value: New pixel value
        """
        if 0 <= y < self.height and 0 <= x < self.width:
            self.data[y][x] = value
        else:
            raise IndexError(f"Pixel ({x}, {y}) out of bounds")

    def copy(self) -> "Image":
        """Create deep copy of image."""
        new_data = [[[v for v in pixel] for pixel in row] for row in self.data]
        return Image(new_data, self.color_space, self.dtype)

    def __repr__(self) -> str:
        """String representation."""
        return f"Image({self.width}x{self.height}x{self.channels}, {self.color_space.value}, {self.dtype})"
