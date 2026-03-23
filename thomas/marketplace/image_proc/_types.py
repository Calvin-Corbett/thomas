"""
Core types and data structures for image processing.

Defines fundamental types for representing images, pixels, color spaces,
histograms, kernels, and algorithm-specific configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np

# ============================================================================
# Image and Pixel Representations
# ============================================================================


@dataclass
class Pixel:
    """
    Represents a single pixel with optional alpha channel.

    Attributes:
        values: Pixel color values (1D array, length 1-4).
        alpha: Optional alpha (transparency) value, 0.0-1.0.
    """

    values: np.ndarray
    alpha: float = 1.0

    def __post_init__(self) -> None:
        """Validate pixel values."""
        if not isinstance(self.values, np.ndarray):
            self.values = np.asarray(self.values, dtype=np.float32)
        if self.values.ndim != 1 or self.values.size == 0:
            raise ValueError("Pixel values must be 1D non-empty array")
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError("Alpha must be in [0.0, 1.0]")

    def to_bgr(self) -> np.ndarray:
        """Convert pixel to BGR representation."""
        return self.values.copy()

    def to_rgb(self) -> np.ndarray:
        """Convert pixel to RGB representation."""
        if self.values.size >= 3:
            rgb = self.values.copy()
            rgb[[0, 2]] = self.values[[2, 0]]
            return rgb
        return self.values.copy()


@dataclass
class Image:
    """
    Represents a digital image with multiple channels.

    Attributes:
        data: Image pixel data (H x W x C), values in appropriate range.
        color_space: Color space representation (RGB, YCbCr, Lab, etc).
        bit_depth: Bits per channel (8, 16, 32, etc).
        metadata: Optional image metadata dictionary.
    """

    data: np.ndarray
    color_space: str = "RGB"
    bit_depth: int = 8
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate image data."""
        if self.data.ndim != 3:
            raise ValueError(f"Image data must be 3D (H, W, C), got shape {self.data.shape}")
        if self.data.shape[2] == 0:
            raise ValueError("Image must have at least 1 channel")

    @property
    def height(self) -> int:
        """Image height in pixels."""
        return self.data.shape[0]

    @property
    def width(self) -> int:
        """Image width in pixels."""
        return self.data.shape[1]

    @property
    def channels(self) -> int:
        """Number of color channels."""
        return self.data.shape[2]

    @property
    def dtype(self) -> np.dtype:
        """Data type of pixel values."""
        return self.data.dtype

    def to_8bit(self) -> Image:
        """Convert image to 8-bit integer format."""
        if self.bit_depth == 8:
            return self.copy()
        scaled = np.clip(self.data * (255.0 / (2**self.bit_depth - 1)), 0, 255)
        return Image(
            data=scaled.astype(np.uint8),
            color_space=self.color_space,
            bit_depth=8,
            metadata=self.metadata.copy(),
        )

    def to_float32(self) -> Image:
        """Convert image to float32 in [0, 1] range."""
        if self.data.dtype == np.float32:
            return self.copy()
        if np.issubdtype(self.data.dtype, np.integer):
            info = np.iinfo(self.data.dtype)
            scaled = self.data.astype(np.float32) / info.max
        else:
            scaled = self.data.astype(np.float32)
        return Image(
            data=scaled,
            color_space=self.color_space,
            bit_depth=32,
            metadata=self.metadata.copy(),
        )

    def copy(self) -> Image:
        """Create a deep copy of the image."""
        return Image(
            data=self.data.copy(),
            color_space=self.color_space,
            bit_depth=self.bit_depth,
            metadata=self.metadata.copy(),
        )

    def get_channel(self, idx: int) -> np.ndarray:
        """Extract a single channel as 2D array."""
        if not 0 <= idx < self.channels:
            raise IndexError(f"Channel {idx} out of range [0, {self.channels})")
        return self.data[:, :, idx]

    def set_channel(self, idx: int, channel: np.ndarray) -> None:
        """Set a single channel from 2D array."""
        if channel.shape != (self.height, self.width):
            raise ValueError(f"Channel shape {channel.shape} doesn't match image {(self.height, self.width)}")
        if not 0 <= idx < self.channels:
            raise IndexError(f"Channel {idx} out of range [0, {self.channels})")
        self.data[:, :, idx] = channel


# ============================================================================
# Color Spaces and Conversions
# ============================================================================


class ColorSpace(Enum):
    """Enumeration of supported color spaces."""

    RGB = auto()
    BGR = auto()
    YCbCr = auto()
    Lab = auto()
    LCH = auto()
    HSV = auto()
    HSL = auto()
    XYZ = auto()
    Grayscale = auto()


# ============================================================================
# Histogram
# ============================================================================


@dataclass
class Histogram:
    """
    Represents color or intensity histogram.

    Attributes:
        bins: Histogram bin counts (1D or 3D array).
        range: (min, max) value range.
        num_bins: Number of histogram bins.
    """

    bins: np.ndarray
    range: tuple[float, float]
    num_bins: int

    @property
    def is_color(self) -> bool:
        """Check if histogram is for color image."""
        return self.bins.ndim == 2

    def normalize(self) -> np.ndarray:
        """Return normalized histogram (sum to 1)."""
        return self.bins / self.bins.sum()

    def cumulative(self) -> np.ndarray:
        """Compute cumulative histogram."""
        normalized = self.normalize()
        return np.cumsum(normalized)


# ============================================================================
# Kernels and Filters
# ============================================================================


@dataclass
class Kernel:
    """
    Convolution kernel for filtering operations.

    Attributes:
        data: Kernel coefficients (2D array, typically odd dimensions).
        anchor: (y, x) anchor point for kernel center.
        normalize: Whether to normalize kernel coefficients.
    """

    data: np.ndarray
    anchor: tuple[int, int] | None = None
    normalize: bool = True

    def __post_init__(self) -> None:
        """Validate and normalize kernel."""
        if self.data.ndim != 2:
            raise ValueError("Kernel data must be 2D")
        if self.normalize:
            kernel_sum = self.data.sum()
            if abs(kernel_sum) > 1e-10:
                self.data = self.data / kernel_sum
        if self.anchor is None:
            self.anchor = (self.data.shape[0] // 2, self.data.shape[1] // 2)

    @staticmethod
    def gaussian(size: int, sigma: float) -> Kernel:
        """Create Gaussian blur kernel."""
        ax = np.arange(-size // 2 + 1.0, size // 2 + 1.0)
        kernel = np.exp(-(ax**2) / (2 * sigma**2))
        kernel = np.outer(kernel, kernel)
        return Kernel(kernel / kernel.sum())

    @staticmethod
    def sobel_x() -> Kernel:
        """Create Sobel X edge detection kernel."""
        data = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
        return Kernel(data, normalize=False)

    @staticmethod
    def sobel_y() -> Kernel:
        """Create Sobel Y edge detection kernel."""
        data = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
        return Kernel(data, normalize=False)

    @staticmethod
    def laplacian() -> Kernel:
        """Create Laplacian edge detection kernel."""
        data = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
        return Kernel(data, normalize=False)


# ============================================================================
# Blending and Tone Mapping
# ============================================================================


class BlendMode(Enum):
    """Enumeration of blend modes for image composition."""

    NORMAL = auto()
    MULTIPLY = auto()
    SCREEN = auto()
    OVERLAY = auto()
    ADD = auto()
    SUBTRACT = auto()
    LIGHTEN = auto()
    DARKEN = auto()


class ToneMap(Enum):
    """Enumeration of tone mapping operators."""

    REINHARD_GLOBAL = auto()
    REINHARD_LOCAL = auto()
    DRAGO = auto()
    MANTIUK = auto()


# ============================================================================
# HDR and Exposure
# ============================================================================


@dataclass
class ExposureInfo:
    """
    Information about image exposure and EV (exposure value).

    Attributes:
        exposure_value: EV offset from reference (stops).
        f_number: f-stop number for aperture.
        iso: ISO sensitivity value.
        shutter_speed: Shutter speed in seconds.
    """

    exposure_value: float
    f_number: float = 2.8
    iso: float = 100.0
    shutter_speed: float = 0.01


# ============================================================================
# Panorama
# ============================================================================


@dataclass
class Panorama:
    """
    Represents a panoramic image result.

    Attributes:
        image: Final panorama image.
        transformations: List of transformation matrices for each input.
        warps: Warping boundaries for each input image.
        blending_masks: Alpha masks for blending.
    """

    image: Image
    transformations: list[np.ndarray] = field(default_factory=list)
    warps: list[tuple[int, int, int, int]] = field(default_factory=list)
    blending_masks: list[np.ndarray] = field(default_factory=list)


@dataclass
class Seam:
    """
    Represents a seam for blending in panorama or inpainting.

    Attributes:
        path: Sequence of pixel coordinates defining seam.
        cost: Total seam cost (energy).
    """

    path: np.ndarray
    cost: float


# ============================================================================
# Inpainting
# ============================================================================


@dataclass
class InpaintMask:
    """
    Mask for specifying inpainting regions.

    Attributes:
        data: Binary mask (0 = intact, >0 = inpaint region).
        priority_map: Optional priority weights for inpainting.
        dilation_iter: Iterations for mask dilation during inpainting.
    """

    data: np.ndarray
    priority_map: np.ndarray | None = None
    dilation_iter: int = 3

    def __post_init__(self) -> None:
        """Validate mask."""
        if self.data.ndim != 2:
            raise ValueError("Mask must be 2D")


# ============================================================================
# Super-Resolution
# ============================================================================


@dataclass
class SuperResConfig:
    """
    Configuration for super-resolution processing.

    Attributes:
        scale_factor: Upscaling factor (2, 4, 8).
        method: Algorithm ('bicubic', 'ibp', 'sparse', 'self-sim').
        iterations: Number of algorithm iterations.
        lambda_reg: Regularization parameter.
        dict_size: Dictionary size for sparse coding.
    """

    scale_factor: int = 2
    method: str = "bicubic"
    iterations: int = 10
    lambda_reg: float = 0.01
    dict_size: int = 256


# ============================================================================
# Style Transfer
# ============================================================================


@dataclass
class StyleTransferConfig:
    """
    Configuration for style transfer.

    Attributes:
        style_strength: Blend factor between content and style (0-1).
        preserve_color: Whether to preserve content colors.
        edge_threshold: Threshold for edge detection.
    """

    style_strength: float = 0.8
    preserve_color: bool = True
    edge_threshold: float = 10.0


# ============================================================================
# Noise Models
# ============================================================================


@dataclass
class NoiseModel:
    """
    Parametric noise model for images.

    Attributes:
        noise_type: Type ('gaussian', 'poisson', 'salt_pepper').
        sigma: Gaussian noise standard deviation.
        poisson_scale: Poisson noise intensity.
        salt_pepper_prob: Salt & pepper probability.
    """

    noise_type: str = "gaussian"
    sigma: float = 10.0
    poisson_scale: float = 1.0
    salt_pepper_prob: float = 0.01


# ============================================================================
# Denoising
# ============================================================================


@dataclass
class DenoisingConfig:
    """
    Configuration for denoising algorithms.

    Attributes:
        method: Algorithm ('nlm', 'bilateral', 'wavelet', 'bm3d').
        h: Filtering parameter (strength).
        patch_size: Size of patches for comparison.
        search_window: Search radius for similar patches.
    """

    method: str = "nlm"
    h: float = 10.0
    patch_size: int = 5
    search_window: int = 30
