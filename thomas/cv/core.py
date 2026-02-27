"""Core image manipulation functions."""

import math

from thomas.cv._exceptions import InvalidImageError, InvalidParameterError
from thomas.cv._types import ColorSpace, Image


def create_image(width: int, height: int, channels: int = 3, color_space: ColorSpace = ColorSpace.RGB) -> Image:
    """Create a blank image filled with zeros.

    Args:
        width: Image width in pixels
        height: Image height in pixels
        channels: Number of color channels (default: 3 for RGB)
        color_space: Color space for the image

    Returns:
        New blank Image

    Raises:
        InvalidParameterError: If dimensions are invalid
    """
    if width <= 0 or height <= 0 or channels <= 0:
        raise InvalidParameterError("Image dimensions must be positive")

    data = [[[0 for _ in range(channels)] for _ in range(width)] for _ in range(height)]
    return Image(data, color_space, dtype="uint8")


def clone_image(img: Image) -> Image:
    """Create a deep copy of an image.

    Args:
        img: Image to clone

    Returns:
        Cloned Image with same data and properties
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    new_data = [[[v for v in pixel] for pixel in row] for row in img.data]
    return Image(new_data, img.color_space, img.dtype)


def get_pixel(img: Image, x: int, y: int) -> int | float | list:
    """Get pixel value at specified coordinates.

    Args:
        img: Input image
        x: X coordinate
        y: Y coordinate

    Returns:
        Pixel value (single value for grayscale, list for multi-channel)

    Raises:
        IndexError: If coordinates are out of bounds
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if y < 0 or y >= img.height or x < 0 or x >= img.width:
        raise IndexError(f"Coordinates ({x}, {y}) out of bounds for {img.width}x{img.height}")

    return img.data[y][x]


def set_pixel(img: Image, x: int, y: int, value: int | float | list) -> None:
    """Set pixel value at specified coordinates.

    Args:
        img: Input image
        x: X coordinate
        y: Y coordinate
        value: New pixel value

    Raises:
        IndexError: If coordinates are out of bounds
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if y < 0 or y >= img.height or x < 0 or x >= img.width:
        raise IndexError(f"Coordinates ({x}, {y}) out of bounds")

    img.data[y][x] = value


def crop_image(img: Image, x: int, y: int, width: int, height: int) -> Image:
    """Crop a rectangular region from an image.

    Args:
        img: Input image
        x: Left coordinate
        y: Top coordinate
        width: Crop width
        height: Crop height

    Returns:
        Cropped image

    Raises:
        InvalidParameterError: If crop region is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise InvalidParameterError("Invalid crop parameters")

    if x + width > img.width or y + height > img.height:
        raise InvalidParameterError("Crop region exceeds image bounds")

    cropped = [[img.data[y + j][x + i][:] for i in range(width)] for j in range(height)]
    return Image(cropped, img.color_space, img.dtype)


def resize_image(img: Image, new_width: int, new_height: int, method: str = "nearest") -> Image:
    """Resize image to new dimensions.

    Args:
        img: Input image
        new_width: Target width
        new_height: Target height
        method: Resizing method ('nearest' or 'bilinear')

    Returns:
        Resized image

    Raises:
        InvalidParameterError: If new dimensions are invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if new_width <= 0 or new_height <= 0:
        raise InvalidParameterError("New dimensions must be positive")

    if method == "nearest":
        return _resize_nearest_neighbor(img, new_width, new_height)
    elif method == "bilinear":
        return _resize_bilinear(img, new_width, new_height)
    else:
        raise InvalidParameterError(f"Unknown resize method: {method}")


def _resize_nearest_neighbor(img: Image, new_width: int, new_height: int) -> Image:
    """Resize using nearest neighbor interpolation."""
    resized = create_image(new_width, new_height, img.channels, img.color_space)

    x_scale = img.width / new_width
    y_scale = img.height / new_height

    for y in range(new_height):
        for x in range(new_width):
            src_x = int(x * x_scale)
            src_y = int(y * y_scale)
            src_x = min(src_x, img.width - 1)
            src_y = min(src_y, img.height - 1)
            resized.data[y][x] = img.data[src_y][src_x][:]

    return resized


def _resize_bilinear(img: Image, new_width: int, new_height: int) -> Image:
    """Resize using bilinear interpolation."""
    resized = create_image(new_width, new_height, img.channels, img.color_space)

    x_scale = (img.width - 1) / (new_width - 1) if new_width > 1 else 0
    y_scale = (img.height - 1) / (new_height - 1) if new_height > 1 else 0

    for y in range(new_height):
        for x in range(new_width):
            src_x = x * x_scale
            src_y = y * y_scale

            x0 = int(src_x)
            y0 = int(src_y)
            x1 = min(x0 + 1, img.width - 1)
            y1 = min(y0 + 1, img.height - 1)

            dx = src_x - x0
            dy = src_y - y0

            for c in range(img.channels):
                v00 = img.data[y0][x0][c]
                v10 = img.data[y0][x1][c]
                v01 = img.data[y1][x0][c]
                v11 = img.data[y1][x1][c]

                v0 = v00 * (1 - dx) + v10 * dx
                v1 = v01 * (1 - dx) + v11 * dx
                v = v0 * (1 - dy) + v1 * dy

                resized.data[y][x][c] = int(v) if isinstance(v00, int) else v

    return resized


def rotate_image(img: Image, angle_degrees: float, fill_value: int = 0) -> Image:
    """Rotate image by specified angle using affine transformation.

    Args:
        img: Input image
        angle_degrees: Rotation angle in degrees (counter-clockwise)
        fill_value: Value to fill empty areas after rotation

    Returns:
        Rotated image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    angle_rad = math.radians(angle_degrees)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Calculate new dimensions
    h, w = img.height, img.width
    corners = [
        (0, 0),
        (w - 1, 0),
        (w - 1, h - 1),
        (0, h - 1),
    ]

    new_corners = []
    for cx, cy in corners:
        nx = cx * cos_a - cy * sin_a
        ny = cx * sin_a + cy * cos_a
        new_corners.append((nx, ny))

    xs = [p[0] for p in new_corners]
    ys = [p[1] for p in new_corners]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    new_width = int(max_x - min_x) + 1
    new_height = int(max_y - min_y) + 1

    rotated = create_image(new_width, new_height, img.channels, img.color_space)

    # Fill with background
    for y in range(new_height):
        for x in range(new_width):
            rotated.data[y][x] = [fill_value] * img.channels

    # Inverse mapping
    cos_a_inv = cos_a
    sin_a_inv = -sin_a

    for y in range(new_height):
        for x in range(new_width):
            src_x = (x + min_x) * cos_a_inv - (y + min_y) * sin_a_inv
            src_y = (x + min_x) * sin_a_inv + (y + min_y) * cos_a_inv

            src_x0 = int(src_x)
            src_y0 = int(src_y)

            if 0 <= src_x0 < img.width and 0 <= src_y0 < img.height:
                src_x1 = min(src_x0 + 1, img.width - 1)
                src_y1 = min(src_y0 + 1, img.height - 1)

                dx = src_x - src_x0
                dy = src_y - src_y0

                for c in range(img.channels):
                    v00 = img.data[src_y0][src_x0][c]
                    v10 = img.data[src_y0][src_x1][c]
                    v01 = img.data[src_y1][src_x0][c]
                    v11 = img.data[src_y1][src_x1][c]

                    v0 = v00 * (1 - dx) + v10 * dx
                    v1 = v01 * (1 - dx) + v11 * dx
                    v = v0 * (1 - dy) + v1 * dy

                    rotated.data[y][x][c] = int(v) if isinstance(v00, int) else v

    return rotated


def flip_image(img: Image, horizontal: bool = False, vertical: bool = False) -> Image:
    """Flip image horizontally and/or vertically.

    Args:
        img: Input image
        horizontal: Whether to flip horizontally
        vertical: Whether to flip vertically

    Returns:
        Flipped image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    flipped = create_image(img.width, img.height, img.channels, img.color_space)
    flipped.dtype = img.dtype

    for y in range(img.height):
        src_y = img.height - 1 - y if vertical else y
        for x in range(img.width):
            src_x = img.width - 1 - x if horizontal else x
            flipped.data[y][x] = img.data[src_y][src_x][:]

    return flipped


def split_channels(img: Image) -> list[Image]:
    """Split multi-channel image into separate single-channel images.

    Args:
        img: Input image with multiple channels

    Returns:
        List of grayscale images, one per channel
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    channels = []
    for c in range(img.channels):
        channel_data = [[[img.data[y][x][c]] for x in range(img.width)] for y in range(img.height)]
        channel_img = Image(channel_data, ColorSpace.GRAYSCALE, img.dtype)
        channels.append(channel_img)

    return channels


def merge_channels(images: list[Image]) -> Image:
    """Merge single-channel images into a multi-channel image.

    Args:
        images: List of grayscale images to merge

    Returns:
        Multi-channel image

    Raises:
        InvalidImageError: If images have inconsistent dimensions
    """
    if not images:
        raise InvalidImageError("Must provide at least one image")

    h, w = images[0].height, images[0].width
    for img in images:
        if img.height != h or img.width != w:
            raise InvalidImageError("All images must have same dimensions")

    merged_data = [[[images[c].data[y][x][0] for c in range(len(images))] for x in range(w)] for y in range(h)]

    return Image(merged_data, ColorSpace.RGB, images[0].dtype)


def convert_dtype(img: Image, target_dtype: str) -> Image:
    """Convert image data type (uint8 to float32 or vice versa).

    Args:
        img: Input image
        target_dtype: Target data type ('uint8' or 'float32')

    Returns:
        Image with converted data type

    Raises:
        InvalidParameterError: If target_dtype is unsupported
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if target_dtype not in ("uint8", "float32"):
        raise InvalidParameterError(f"Unsupported dtype: {target_dtype}")

    converted = clone_image(img)

    if img.dtype == "uint8" and target_dtype == "float32":
        for y in range(img.height):
            for x in range(img.width):
                for c in range(img.channels):
                    converted.data[y][x][c] = img.data[y][x][c] / 255.0

    elif img.dtype == "float32" and target_dtype == "uint8":
        for y in range(img.height):
            for x in range(img.width):
                for c in range(img.channels):
                    v = img.data[y][x][c]
                    v = max(0, min(255, int(v * 255)))
                    converted.data[y][x][c] = v

    converted.dtype = target_dtype
    return converted


def pad_image(img: Image, top: int, bottom: int, left: int, right: int, mode: str = "zero") -> Image:
    """Pad image with specified border.

    Args:
        img: Input image
        top: Padding on top
        bottom: Padding on bottom
        left: Padding on left
        right: Padding on right
        mode: Padding mode ('zero', 'reflect', 'replicate')

    Returns:
        Padded image

    Raises:
        InvalidParameterError: If padding values are negative or mode is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if any(p < 0 for p in (top, bottom, left, right)):
        raise InvalidParameterError("Padding values must be non-negative")

    if mode not in ("zero", "reflect", "replicate"):
        raise InvalidParameterError(f"Unknown padding mode: {mode}")

    new_height = img.height + top + bottom
    new_width = img.width + left + right

    padded = create_image(new_width, new_height, img.channels, img.color_space)

    # Copy center
    for y in range(img.height):
        for x in range(img.width):
            padded.data[top + y][left + x] = img.data[y][x][:]

    # Fill padding
    for y in range(new_height):
        for x in range(new_width):
            if top <= y < top + img.height and left <= x < left + img.width:
                continue

            src_y = y - top
            src_x = x - left

            if mode == "zero":
                padded.data[y][x] = [0] * img.channels
            elif mode == "replicate":
                src_y = max(0, min(img.height - 1, src_y))
                src_x = max(0, min(img.width - 1, src_x))
                padded.data[y][x] = img.data[src_y][src_x][:]
            elif mode == "reflect":
                if src_y < 0:
                    src_y = -src_y - 1
                elif src_y >= img.height:
                    src_y = 2 * img.height - src_y - 1
                if src_x < 0:
                    src_x = -src_x - 1
                elif src_x >= img.width:
                    src_x = 2 * img.width - src_x - 1
                src_y = max(0, min(img.height - 1, src_y))
                src_x = max(0, min(img.width - 1, src_x))
                padded.data[y][x] = img.data[src_y][src_x][:]

    return padded


def blend_images(img1: Image, img2: Image, alpha: float) -> Image:
    """Blend two images using alpha compositing.

    Args:
        img1: First image (background)
        img2: Second image (foreground)
        alpha: Blend factor (0.0 = img1, 1.0 = img2)

    Returns:
        Blended image

    Raises:
        InvalidImageError: If images have different dimensions
        InvalidParameterError: If alpha is outside [0, 1]
    """
    if not isinstance(img1, Image) or not isinstance(img2, Image):
        raise InvalidImageError("Both inputs must be Image objects")

    if img1.shape != img2.shape:
        raise InvalidImageError("Images must have same dimensions and channels")

    if not (0.0 <= alpha <= 1.0):
        raise InvalidParameterError("Alpha must be between 0 and 1")

    blended = create_image(img1.width, img1.height, img1.channels, img1.color_space)

    for y in range(img1.height):
        for x in range(img1.width):
            for c in range(img1.channels):
                v1 = img1.data[y][x][c]
                v2 = img2.data[y][x][c]
                value = v1 * (1 - alpha) + v2 * alpha
                if img1.dtype == "uint8":
                    blended.data[y][x][c] = int(max(0, min(255, round(value))))
                else:
                    blended.data[y][x][c] = value

    return blended
