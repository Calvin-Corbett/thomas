"""Image filtering operations."""

import math

from thomas.cv import core
from thomas.cv._exceptions import InvalidImageError, InvalidParameterError
from thomas.cv._types import Image, Kernel


def convolve_2d(img: Image, kernel: Kernel, padding_mode: str = "zero", scale: float | None = None) -> Image:
    """Apply 2D convolution with specified kernel.

    Args:
        img: Input image
        kernel: Convolution kernel
        padding_mode: Padding mode ('zero', 'reflect', 'replicate')
        scale: Optional scaling factor for kernel (overrides kernel normalization)

    Returns:
        Convolved image

    Raises:
        InvalidImageError: If input is invalid
        InvalidParameterError: If kernel or parameters are invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if not kernel.data or len(kernel.data) == 0:
        raise InvalidParameterError("Invalid kernel")

    kh, kw = kernel.size
    if kh == 0 or kw == 0:
        raise InvalidParameterError("Kernel has zero dimension")

    # Pad image
    pad_h = kh // 2
    pad_w = kw // 2
    padded = core.pad_image(img, pad_h, pad_h, pad_w, pad_w, padding_mode)

    result = core.create_image(img.width, img.height, img.channels, img.color_space)

    # Apply kernel to each channel
    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                value = 0.0
                for ky in range(kh):
                    for kx in range(kw):
                        py = y + ky
                        px = x + kx
                        pixel_val = padded.data[py][px][c]
                        kernel_val = kernel.data[ky][kx]
                        value += pixel_val * kernel_val

                # Apply scale if provided
                if scale is not None:
                    value *= scale

                # Clamp to valid range
                if isinstance(img.data[0][0][0], int):
                    value = max(0, min(255, int(value)))
                result.data[y][x][c] = value

    return result


def gaussian_blur(img: Image, kernel_size: int, sigma: float) -> Image:
    """Apply Gaussian blur using separable kernel for efficiency.

    Args:
        img: Input image
        kernel_size: Kernel size (must be odd)
        sigma: Standard deviation of Gaussian

    Returns:
        Blurred image

    Raises:
        InvalidParameterError: If kernel_size is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if kernel_size % 2 == 0 or kernel_size <= 0:
        raise InvalidParameterError("Kernel size must be positive and odd")

    # Create 1D Gaussian kernel
    radius = kernel_size // 2
    kernel_1d = []
    total = 0.0

    for x in range(-radius, radius + 1):
        val = math.exp(-(x * x) / (2 * sigma * sigma))
        kernel_1d.append(val)
        total += val

    # Normalize
    kernel_1d = [x / total for x in kernel_1d]

    # Apply horizontal blur
    horizontal = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                value = 0.0
                for k in range(kernel_size):
                    kx = x + k - radius
                    if kx < 0:
                        kx = -kx - 1 if kx < 0 else kx
                    elif kx >= img.width:
                        kx = 2 * img.width - kx - 1
                    kx = max(0, min(img.width - 1, kx))
                    value += img.data[y][kx][c] * kernel_1d[k]

                horizontal.data[y][x][c] = int(value) if isinstance(value, float) else value

    # Apply vertical blur
    vertical = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                value = 0.0
                for k in range(kernel_size):
                    ky = y + k - radius
                    if ky < 0:
                        ky = -ky - 1 if ky < 0 else ky
                    elif ky >= img.height:
                        ky = 2 * img.height - ky - 1
                    ky = max(0, min(img.height - 1, ky))
                    value += horizontal.data[ky][x][c] * kernel_1d[k]

                vertical.data[y][x][c] = int(value) if isinstance(value, float) else value

    return vertical


def box_blur(img: Image, kernel_size: int) -> Image:
    """Apply box (averaging) blur.

    Args:
        img: Input image
        kernel_size: Kernel size (must be odd)

    Returns:
        Blurred image

    Raises:
        InvalidParameterError: If kernel_size is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if kernel_size % 2 == 0 or kernel_size <= 0:
        raise InvalidParameterError("Kernel size must be positive and odd")

    # Create uniform kernel
    kernel_val = 1.0 / (kernel_size * kernel_size)
    kernel_data = [[kernel_val] * kernel_size for _ in range(kernel_size)]
    kernel = Kernel(kernel_data)

    return convolve_2d(img, kernel, padding_mode="replicate")


def median_filter(img: Image, kernel_size: int) -> Image:
    """Apply median filter using histogram-based algorithm.

    Args:
        img: Input image
        kernel_size: Kernel size (must be odd)

    Returns:
        Filtered image

    Raises:
        InvalidParameterError: If kernel_size is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if kernel_size % 2 == 0 or kernel_size <= 0:
        raise InvalidParameterError("Kernel size must be positive and odd")

    result = core.create_image(img.width, img.height, img.channels, img.color_space)
    radius = kernel_size // 2
    mid_point = (kernel_size * kernel_size) // 2

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                # Collect neighborhood values
                values = []
                for ky in range(-radius, radius + 1):
                    for kx in range(-radius, radius + 1):
                        ny = y + ky
                        nx = x + kx
                        # Replicate padding
                        ny = max(0, min(img.height - 1, ny))
                        nx = max(0, min(img.width - 1, nx))
                        values.append(img.data[ny][nx][c])

                # Find median
                values.sort()
                result.data[y][x][c] = values[mid_point]

    return result


def bilateral_filter(img: Image, diameter: int, sigma_color: float, sigma_space: float) -> Image:
    """Apply bilateral filter for edge-preserving smoothing.

    Args:
        img: Input image
        diameter: Diameter of pixel neighborhood
        sigma_color: Range (color) standard deviation
        sigma_space: Spatial standard deviation

    Returns:
        Filtered image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if diameter <= 0:
        raise InvalidParameterError("Diameter must be positive")

    result = core.create_image(img.width, img.height, img.channels, img.color_space)
    radius = diameter // 2

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                center_val = img.data[y][x][c]
                weighted_sum = 0.0
                weight_sum = 0.0

                for ky in range(-radius, radius + 1):
                    for kx in range(-radius, radius + 1):
                        ny = y + ky
                        nx = x + kx

                        if 0 <= ny < img.height and 0 <= nx < img.width:
                            neighbor_val = img.data[ny][nx][c]

                            # Spatial distance
                            spatial_dist = math.sqrt(kx * kx + ky * ky)
                            spatial_weight = math.exp(-(spatial_dist * spatial_dist) / (2 * sigma_space * sigma_space))

                            # Range distance
                            range_dist = abs(neighbor_val - center_val)
                            range_weight = math.exp(-(range_dist * range_dist) / (2 * sigma_color * sigma_color))

                            weight = spatial_weight * range_weight
                            weighted_sum += neighbor_val * weight
                            weight_sum += weight

                if weight_sum > 0:
                    result.data[y][x][c] = int(weighted_sum / weight_sum)
                else:
                    result.data[y][x][c] = center_val

    return result


def sharpen(img: Image, amount: float = 1.0) -> Image:
    """Sharpen image using unsharp mask.

    Args:
        img: Input image
        amount: Sharpening strength (0-2 typical range)

    Returns:
        Sharpened image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if amount < 0:
        raise InvalidParameterError("Amount must be non-negative")

    # Create blurred version
    blurred = gaussian_blur(img, kernel_size=5, sigma=1.0)

    # Subtract blur from original and add back
    sharpened = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                diff = img.data[y][x][c] - blurred.data[y][x][c]
                value = img.data[y][x][c] + diff * amount
                value = max(0, min(255, int(value)))
                sharpened.data[y][x][c] = value

    return sharpened


def sobel_x(img: Image) -> Image:
    """Apply Sobel X edge detector (3x3).

    Args:
        img: Input image

    Returns:
        Gradient image in X direction
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    kernel_data = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
    kernel = Kernel(kernel_data)
    return convolve_2d(img, kernel, padding_mode="replicate", scale=1.0)


def sobel_y(img: Image) -> Image:
    """Apply Sobel Y edge detector (3x3).

    Args:
        img: Input image

    Returns:
        Gradient image in Y direction
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    kernel_data = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]
    kernel = Kernel(kernel_data)
    return convolve_2d(img, kernel, padding_mode="replicate", scale=1.0)


def sobel_xy(img: Image) -> tuple[Image, Image]:
    """Apply Sobel operators in both directions.

    Args:
        img: Input image

    Returns:
        Tuple of (gradient_x, gradient_y)
    """
    return sobel_x(img), sobel_y(img)


def laplacian(img: Image) -> Image:
    """Apply Laplacian edge detector.

    Args:
        img: Input image

    Returns:
        Edge detection result
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    kernel_data = [[0, -1, 0], [-1, 4, -1], [0, -1, 0]]
    kernel = Kernel(kernel_data)
    return convolve_2d(img, kernel, padding_mode="replicate", scale=1.0)


def custom_kernel_filter(img: Image, kernel: Kernel) -> Image:
    """Apply custom kernel to image.

    Args:
        img: Input image
        kernel: Custom convolution kernel

    Returns:
        Filtered image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if not kernel.data:
        raise InvalidParameterError("Invalid kernel")

    return convolve_2d(img, kernel, padding_mode="replicate")
