"""Geometric transformations and image warping."""

import math

from thomas.marketplace.cv import core, features
from thomas.marketplace.cv._exceptions import InvalidImageError, InvalidParameterError, TransformationError
from thomas.marketplace.cv._types import Image, Transform2D


def affine_transform_matrix(
    translation: tuple[float, float] = (0, 0),
    rotation_degrees: float = 0,
    scaling: tuple[float, float] = (1, 1),
    shearing: tuple[float, float] = (0, 0),
    center: tuple[float, float] | None = None,
) -> Transform2D:
    """Create 2D affine transformation matrix.

    Args:
        translation: (tx, ty) translation
        rotation_degrees: Rotation angle in degrees
        scaling: (sx, sy) scaling factors
        shearing: (shx, shy) shearing factors
        center: Optional center point for rotation/scaling

    Returns:
        2x3 affine transformation matrix
    """
    if center is None:
        center = (0, 0)

    # Convert rotation to radians
    angle_rad = math.radians(rotation_degrees)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Build transformation matrix
    sx, sy = scaling
    shx, shy = shearing
    tx, ty = translation
    cx, cy = center

    # Combined transformation around center point
    matrix = [
        [sx * cos_a - shy * sin_a, -sx * sin_a + shx * cos_a, 0],
        [sy * sin_a + shy * cos_a, sy * cos_a - shx * sin_a, 0],
    ]

    # Adjust for center point
    dx = cx - (matrix[0][0] * cx + matrix[0][1] * cy)
    dy = cy - (matrix[1][0] * cx + matrix[1][1] * cy)

    matrix[0][2] = tx + dx
    matrix[1][2] = ty + dy

    return Transform2D(matrix, is_perspective=False)


def perspective_transform_matrix(
    src_points: list[tuple[float, float]], dst_points: list[tuple[float, float]]
) -> Transform2D | None:
    """Create perspective (3x3 homography) transformation.

    Args:
        src_points: List of 4 source points
        dst_points: List of 4 destination points

    Returns:
        3x3 perspective transformation matrix

    Raises:
        InvalidParameterError: If point lists are invalid
    """
    if len(src_points) != 4 or len(dst_points) != 4:
        raise InvalidParameterError("Must provide exactly 4 point pairs")

    return features.estimate_homography(src_points, dst_points)


def warp_affine(img: Image, transform: Transform2D, output_size: tuple[int, int] | None = None) -> Image:
    """Apply affine transformation with bilinear interpolation.

    Args:
        img: Input image
        transform: Affine transformation (2x3 matrix)
        output_size: Optional output image size

    Returns:
        Warped image

    Raises:
        InvalidImageError: If input is invalid
        TransformationError: If transformation is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if transform.is_perspective:
        raise TransformationError("Use warp_perspective for perspective transforms")

    if output_size is None:
        output_size = (img.width, img.height)

    out_w, out_h = output_size

    # Create inverse transform for sampling
    matrix = transform.matrix
    a00, a01, a02 = matrix[0][0], matrix[0][1], matrix[0][2]
    a10, a11, a12 = matrix[1][0], matrix[1][1], matrix[1][2]

    det = a00 * a11 - a01 * a10
    if abs(det) < 1e-10:
        raise TransformationError("Singular transformation matrix")

    # Inverse matrix elements
    inv_a00 = a11 / det
    inv_a01 = -a01 / det
    inv_a02 = (a01 * a12 - a11 * a02) / det
    inv_a10 = -a10 / det
    inv_a11 = a00 / det
    inv_a12 = (a10 * a02 - a00 * a12) / det

    output = core.create_image(out_w, out_h, img.channels, img.color_space)

    for y in range(out_h):
        for x in range(out_w):
            # Inverse mapping
            src_x = inv_a00 * x + inv_a01 * y + inv_a02
            src_y = inv_a10 * x + inv_a11 * y + inv_a12

            # Bilinear interpolation
            x0, y0 = int(src_x), int(src_y)
            x1, y1 = x0 + 1, y0 + 1

            if 0 <= x0 < img.width and 0 <= y0 < img.height:
                x1 = min(x1, img.width - 1)
                y1 = min(y1, img.height - 1)

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

                    output.data[y][x][c] = int(v) if isinstance(v00, int) else v

    return output


def warp_perspective(img: Image, transform: Transform2D, output_size: tuple[int, int] | None = None) -> Image:
    """Apply perspective transformation with bilinear interpolation.

    Args:
        img: Input image
        transform: Perspective transformation (3x3 matrix)
        output_size: Optional output image size

    Returns:
        Warped image

    Raises:
        InvalidImageError: If input is invalid
        TransformationError: If transformation is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if not transform.is_perspective:
        raise TransformationError("Use warp_affine for affine transforms")

    if output_size is None:
        output_size = (img.width, img.height)

    out_w, out_h = output_size
    output = core.create_image(out_w, out_h, img.channels, img.color_space)

    # Compute inverse transform
    matrix = transform.matrix
    det = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )

    if abs(det) < 1e-10:
        raise TransformationError("Singular transformation matrix")

    # Compute inverse (3x3)
    inv = [
        [
            (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1]) / det,
            (matrix[0][2] * matrix[2][1] - matrix[0][1] * matrix[2][2]) / det,
            (matrix[0][1] * matrix[1][2] - matrix[0][2] * matrix[1][1]) / det,
        ],
        [
            (matrix[1][2] * matrix[2][0] - matrix[1][0] * matrix[2][2]) / det,
            (matrix[0][0] * matrix[2][2] - matrix[0][2] * matrix[2][0]) / det,
            (matrix[0][2] * matrix[1][0] - matrix[0][0] * matrix[1][2]) / det,
        ],
        [
            (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0]) / det,
            (matrix[0][1] * matrix[2][0] - matrix[0][0] * matrix[2][1]) / det,
            (matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]) / det,
        ],
    ]

    for y in range(out_h):
        for x in range(out_w):
            # Perspective mapping
            w = inv[2][0] * x + inv[2][1] * y + inv[2][2]
            if abs(w) > 1e-10:
                src_x = (inv[0][0] * x + inv[0][1] * y + inv[0][2]) / w
                src_y = (inv[1][0] * x + inv[1][1] * y + inv[1][2]) / w
            else:
                continue

            # Bilinear interpolation
            x0, y0 = int(src_x), int(src_y)
            x1, y1 = x0 + 1, y0 + 1

            if 0 <= x0 < img.width and 0 <= y0 < img.height:
                x1 = min(x1, img.width - 1)
                y1 = min(y1, img.height - 1)

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

                    output.data[y][x][c] = int(v) if isinstance(v00, int) else v

    return output


def stitch_images(img1: Image, img2: Image, overlap: int = 50) -> Image | None:
    """Stitch two images together using feature matching.

    Args:
        img1: First image (left)
        img2: Second image (right)
        overlap: Expected overlap region in pixels

    Returns:
        Stitched panorama image or None if stitching fails
    """
    if not isinstance(img1, Image) or not isinstance(img2, Image):
        raise InvalidImageError("Both inputs must be Image objects")

    # Simple overlap stitching (feature-based approach would be more robust)
    if overlap <= 0 or overlap >= min(img1.width, img2.width):
        raise InvalidParameterError("Invalid overlap value")

    # Create output image
    out_width = img1.width + img2.width - overlap
    out_height = max(img1.height, img2.height)

    stitched = core.create_image(out_width, out_height, img1.channels, img1.color_space)

    # Copy first image
    for y in range(img1.height):
        for x in range(img1.width):
            stitched.data[y][x] = img1.data[y][x][:]

    # Blend second image
    x_offset = img1.width - overlap

    for y in range(img2.height):
        for x in range(img2.width):
            dst_x = x_offset + x

            if dst_x >= out_width:
                continue

            # Blending in overlap region
            if x < overlap:
                alpha = x / overlap
            else:
                alpha = 1.0

            if y < out_height:
                for c in range(img2.channels):
                    if dst_x < stitched.width:
                        v1 = stitched.data[y][dst_x][c] if dst_x < stitched.width else 0
                        v2 = img2.data[y][x][c]
                        stitched.data[y][dst_x][c] = int(v1 * (1 - alpha) + v2 * alpha)

    return stitched


def camera_calibration_matrix(focal_length: float, principal_point: tuple[float, float]) -> list[list[float]]:
    """Create camera intrinsic calibration matrix.

    Args:
        focal_length: Focal length in pixels
        principal_point: (cx, cy) principal point coordinates

    Returns:
        3x3 camera intrinsic matrix K
    """
    cx, cy = principal_point
    return [
        [focal_length, 0, cx],
        [0, focal_length, cy],
        [0, 0, 1],
    ]


def undistort_image(img: Image, k1: float = 0, k2: float = 0, p1: float = 0, p2: float = 0) -> Image:
    """Apply lens distortion correction.

    Args:
        img: Input image
        k1: First radial distortion coefficient
        k2: Second radial distortion coefficient
        p1: First tangential distortion coefficient
        p2: Second tangential distortion coefficient

    Returns:
        Undistorted image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    undistorted = core.create_image(img.width, img.height, img.channels, img.color_space)

    # Image center
    cx = img.width / 2
    cy = img.height / 2

    # Focal length assumption (normalized)
    f = max(img.width, img.height)

    for y in range(img.height):
        for x in range(img.width):
            # Normalized coordinates
            xn = (x - cx) / f
            yn = (y - cy) / f

            # Radius
            r2 = xn * xn + yn * yn
            r4 = r2 * r2

            # Radial distortion
            radial = 1 + k1 * r2 + k2 * r4

            # Tangential distortion
            dx = 2 * p1 * xn * yn + p2 * (r2 + 2 * xn * xn)
            dy = p1 * (r2 + 2 * yn * yn) + 2 * p2 * xn * yn

            # Distorted coordinates
            src_xn = xn * radial + dx
            src_yn = yn * radial + dy

            # Back to pixel coordinates
            src_x = src_xn * f + cx
            src_y = src_yn * f + cy

            # Sample with interpolation
            x0, y0 = int(src_x), int(src_y)
            x1, y1 = x0 + 1, y0 + 1

            if 0 <= x0 < img.width and 0 <= y0 < img.height:
                x1 = min(x1, img.width - 1)
                y1 = min(y1, img.height - 1)

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

                    undistorted.data[y][x][c] = int(v)

    return undistorted
