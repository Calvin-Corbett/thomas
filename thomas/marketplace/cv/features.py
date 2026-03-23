"""Feature detection and matching algorithms."""

import math
import random

from thomas.marketplace.cv import core, filters
from thomas.marketplace.cv._exceptions import InvalidImageError, InvalidParameterError
from thomas.marketplace.cv._types import Descriptor, Feature, Image, Match, Transform2D


def harris_corner_detector(img: Image, block_size: int = 5, k: float = 0.04, threshold: float = 0.01) -> list[Feature]:
    """Harris corner detector using structure tensor.

    Args:
        img: Input image
        block_size: Size of neighborhood for structure tensor
        k: Harris detector parameter
        threshold: Response threshold for corner detection

    Returns:
        List of detected corners as Features
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if block_size % 2 == 0 or block_size <= 0:
        raise InvalidParameterError("Block size must be positive and odd")

    # Compute gradients
    gx = filters.sobel_x(img)
    gy = filters.sobel_y(img)

    # Compute structure tensor components
    ixx = core.create_image(img.width, img.height, 1)
    iyy = core.create_image(img.width, img.height, 1)
    ixy = core.create_image(img.width, img.height, 1)

    for y in range(img.height):
        for x in range(img.width):
            gx_val = gx.data[y][x][0]
            gy_val = gy.data[y][x][0]

            ixx.data[y][x][0] = gx_val * gx_val
            iyy.data[y][x][0] = gy_val * gy_val
            ixy.data[y][x][0] = gx_val * gy_val

    # Blur structure tensor
    radius = block_size // 2
    ixx = filters.gaussian_blur(ixx, block_size, sigma=1.0)
    iyy = filters.gaussian_blur(iyy, block_size, sigma=1.0)
    ixy = filters.gaussian_blur(ixy, block_size, sigma=1.0)

    # Compute corner response
    response = core.create_image(img.width, img.height, 1)

    for y in range(img.height):
        for x in range(img.width):
            ixx_val = ixx.data[y][x][0]
            iyy_val = iyy.data[y][x][0]
            ixy_val = ixy.data[y][x][0]

            det = ixx_val * iyy_val - ixy_val * ixy_val
            trace = ixx_val + iyy_val

            if trace > 0:
                r = det - k * (trace**2)
            else:
                r = 0

            response.data[y][x][0] = r

    # Non-maximum suppression and threshold
    corners = []
    for y in range(1, img.height - 1):
        for x in range(1, img.width - 1):
            r = response.data[y][x][0]

            if r > threshold:
                is_max = True
                for dy in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        if dy == 0 and dx == 0:
                            continue
                        if response.data[y + dy][x + dx][0] > r:
                            is_max = False
                            break
                    if not is_max:
                        break

                if is_max:
                    corners.append(Feature(x=x, y=y, response=r))

    # Sort by response strength
    corners.sort(key=lambda f: f.response, reverse=True)
    return corners


def fast_corner_detector(img: Image, threshold: int = 30, max_features: int | None = None) -> list[Feature]:
    """FAST corner detector using segment test on Bresenham circle.

    Args:
        img: Input image
        threshold: Intensity threshold for corner detection
        max_features: Maximum number of features to return (None for all)

    Returns:
        List of detected corners as Features
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if threshold < 0 or threshold > 255:
        raise InvalidParameterError("Threshold must be in [0, 255]")

    # Bresenham circle of radius 3
    circle_offsets = [
        (0, -3),
        (1, -3),
        (2, -2),
        (3, -1),
        (3, 0),
        (3, 1),
        (2, 2),
        (1, 3),
        (0, 3),
        (-1, 3),
        (-2, 2),
        (-3, 1),
        (-3, 0),
        (-3, -1),
        (-2, -2),
        (-1, -3),
    ]

    corners = []

    for y in range(3, img.height - 3):
        for x in range(3, img.width - 3):
            center_val = img.data[y][x][0]

            # Count darker and lighter pixels
            darker = 0
            lighter = 0

            for dx, dy in circle_offsets:
                neighbor_val = img.data[y + dy][x + dx][0]
                if neighbor_val < center_val - threshold:
                    darker += 1
                elif neighbor_val > center_val + threshold:
                    lighter += 1

            # Corner if 9+ consecutive pixels are darker or lighter
            if darker >= 9 or lighter >= 9:
                corners.append(Feature(x=x, y=y, response=float(max(darker, lighter))))

    # Sort by response
    corners.sort(key=lambda f: f.response, reverse=True)

    if max_features:
        corners = corners[:max_features]

    return corners


def brief_descriptor(img: Image, features: list[Feature], descriptor_size: int = 256) -> list[Descriptor]:
    """BRIEF binary descriptor - descriptor from pairwise intensity comparisons.

    Args:
        img: Input image
        features: List of feature points
        descriptor_size: Number of bits in descriptor

    Returns:
        List of binary descriptors
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    # Generate random comparison pairs (deterministic seed for reproducibility)
    random.seed(42)
    patch_size = 31
    half_size = patch_size // 2

    pairs = []
    for _ in range(descriptor_size):
        x1 = random.randint(-half_size, half_size)
        y1 = random.randint(-half_size, half_size)
        x2 = random.randint(-half_size, half_size)
        y2 = random.randint(-half_size, half_size)
        pairs.append(((x1, y1), (x2, y2)))

    descriptors = []

    for feature_id, feature in enumerate(features):
        x, y = int(feature.x), int(feature.y)

        # Skip if too close to border
        if x < half_size or x >= img.width - half_size or y < half_size or y >= img.height - half_size:
            continue

        descriptor_bits = []

        for (x1, y1), (x2, y2) in pairs:
            px1 = x + x1
            py1 = y + y1
            px2 = x + x2
            py2 = y + y2

            if 0 <= px1 < img.width and 0 <= py1 < img.height:
                v1 = img.data[py1][px1][0]
            else:
                v1 = 0

            if 0 <= px2 < img.width and 0 <= py2 < img.height:
                v2 = img.data[py2][px2][0]
            else:
                v2 = 0

            bit = 1 if v1 < v2 else 0
            descriptor_bits.append(bit)

        descriptors.append(Descriptor(descriptor_bits, feature_id, "BRIEF"))

    return descriptors


def match_features(
    query_descriptors: list[Descriptor], train_descriptors: list[Descriptor], ratio_threshold: float = 0.7
) -> list[Match]:
    """Match binary descriptors using brute force and ratio test.

    Args:
        query_descriptors: Query descriptors
        train_descriptors: Training/reference descriptors
        ratio_threshold: Lowe's ratio test threshold

    Returns:
        List of good matches
    """
    if not query_descriptors or not train_descriptors:
        return []

    matches = []

    for q_idx, query in enumerate(query_descriptors):
        distances = []

        for t_idx, train in enumerate(train_descriptors):
            dist = query.hamming_distance(train)
            distances.append((dist, t_idx))

        distances.sort()

        if not distances:
            continue

        best_dist, best_idx = distances[0]

        # With a single candidate, keep the best available correspondence.
        if len(distances) == 1:
            matches.append(
                Match(
                    query_idx=q_idx,
                    train_idx=best_idx,
                    distance=best_dist,
                    good=True,
                )
            )
            continue

        second_best_dist = distances[1][0]
        if second_best_dist == 0:
            keep = best_dist == 0
        else:
            keep = best_dist <= ratio_threshold * second_best_dist

        if keep:
            matches.append(
                Match(
                    query_idx=q_idx,
                    train_idx=best_idx,
                    distance=best_dist,
                    good=True,
                )
            )

    return matches


def estimate_homography(
    src_points: list[tuple[float, float]], dst_points: list[tuple[float, float]]
) -> Transform2D | None:
    """Estimate homography using DLT (Direct Linear Transform) with RANSAC.

    Args:
        src_points: Source points (from image 1)
        dst_points: Destination points (from image 2)

    Returns:
        Estimated 3x3 homography matrix as Transform2D, or None if estimation fails

    Raises:
        InvalidParameterError: If point lists have different lengths or insufficient points
    """
    if len(src_points) != len(dst_points):
        raise InvalidParameterError("Source and destination point lists must have same length")

    if len(src_points) < 4:
        raise InvalidParameterError("Need at least 4 point pairs for homography estimation")

    best_homography = None
    # Start below zero so we always keep at least one valid hypothesis.
    best_inliers = -1
    threshold = 1.0

    # RANSAC iterations
    for _ in range(1000):
        # Randomly select 4 points
        indices = random.sample(range(len(src_points)), 4)
        selected_src = [src_points[i] for i in indices]
        selected_dst = [dst_points[i] for i in indices]

        # Estimate homography from 4 points
        H = _dlt_homography(selected_src, selected_dst)

        if H is None:
            continue

        # Count inliers
        inliers = 0
        for i in range(len(src_points)):
            proj = H.transform_point(core.Point(src_points[i][0], src_points[i][1]))
            error = math.sqrt((proj.x - dst_points[i][0]) ** 2 + (proj.y - dst_points[i][1]) ** 2)

            if error < threshold:
                inliers += 1

        if inliers > best_inliers:
            best_inliers = inliers
            best_homography = H

    return best_homography


def _dlt_homography(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> Transform2D | None:
    """Compute homography from 4 point correspondences using DLT."""
    if len(src) != 4 or len(dst) != 4:
        return None

    # Build system matrix
    A = []
    for i in range(4):
        x, y = src[i]
        xp, yp = dst[i]

        A.append([x, y, 1, 0, 0, 0, -xp * x, -xp * y, -xp])
        A.append([0, 0, 0, x, y, 1, -yp * x, -yp * y, -yp])

    # Simple least squares: use first 8 equations
    try:
        # Normalize A
        H = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        return Transform2D(H, is_perspective=True)
    except (ValueError, IndexError):
        return None
