"""Image segmentation algorithms."""

import math
import random

from thomas.cv import core
from thomas.cv._exceptions import InvalidImageError, InvalidParameterError
from thomas.cv._types import ColorSpace, Image


def otsu_threshold(img: Image) -> int:
    """Calculate optimal threshold using Otsu's method (maximum between-class variance).

    Args:
        img: Grayscale input image

    Returns:
        Optimal threshold value
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    # Calculate histogram
    histogram = [0] * 256
    for y in range(img.height):
        for x in range(img.width):
            value = img.data[y][x][0]
            histogram[value] += 1

    # Total pixels
    total = img.width * img.height

    # Calculate probabilities
    prob = [h / total for h in histogram]

    # Calculate cumulative probabilities and means
    omega = [0] * 256  # Class 0 probability
    mu = [0] * 256  # Class 0 mean

    omega[0] = prob[0]
    mu[0] = 0

    for i in range(1, 256):
        omega[i] = omega[i - 1] + prob[i]
        mu[i] = mu[i - 1] + i * prob[i]

    # Calculate global mean
    mu_t = mu[255]

    # Find optimal threshold
    max_variance = -1.0
    candidate_thresholds: list[int] = []

    for t in range(256):
        if omega[t] == 0 or omega[t] == 1:
            continue

        mu_0 = mu[t] / omega[t]
        mu_1 = (mu_t - mu[t]) / (1 - omega[t])

        variance = omega[t] * (1 - omega[t]) * ((mu_0 - mu_1) ** 2)

        if variance > max_variance + 1e-12:
            max_variance = variance
            candidate_thresholds = [t]
        elif abs(variance - max_variance) <= 1e-12:
            candidate_thresholds.append(t)

    if not candidate_thresholds:
        return 0

    # If multiple thresholds tie, pick their midpoint to avoid biasing to
    # the first histogram bin in broad plateaus.
    return int(round(sum(candidate_thresholds) / len(candidate_thresholds)))


def binary_threshold(img: Image, threshold: int) -> Image:
    """Apply binary thresholding.

    Args:
        img: Grayscale input image
        threshold: Threshold value

    Returns:
        Binary image (0 or 255)
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    binary = core.create_image(img.width, img.height, 1, ColorSpace.GRAYSCALE)

    for y in range(img.height):
        for x in range(img.width):
            value = img.data[y][x][0]
            binary.data[y][x][0] = 255 if value >= threshold else 0

    return binary


def adaptive_threshold(img: Image, block_size: int = 11, method: str = "mean") -> Image:
    """Apply adaptive thresholding with local mean/Gaussian.

    Args:
        img: Grayscale input image
        block_size: Size of local neighborhood (must be odd)
        method: 'mean' or 'gaussian'

    Returns:
        Binary image

    Raises:
        InvalidParameterError: If block_size is invalid or method is unknown
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if block_size % 2 == 0 or block_size <= 0:
        raise InvalidParameterError("Block size must be positive and odd")

    if method not in ("mean", "gaussian"):
        raise InvalidParameterError(f"Unknown method: {method}")

    binary = core.create_image(img.width, img.height, 1, ColorSpace.GRAYSCALE)
    radius = block_size // 2

    for y in range(img.height):
        for x in range(img.width):
            if method == "mean":
                # Calculate local mean
                local_sum = 0
                count = 0

                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        ny = y + dy
                        nx = x + dx

                        if 0 <= ny < img.height and 0 <= nx < img.width:
                            local_sum += img.data[ny][nx][0]
                            count += 1

                threshold = local_sum // count if count > 0 else 128

            else:  # gaussian
                # Calculate local Gaussian mean
                local_sum = 0
                weight_sum = 0

                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        ny = y + dy
                        nx = x + dx

                        if 0 <= ny < img.height and 0 <= nx < img.width:
                            weight = math.exp(-(dx * dx + dy * dy) / (2 * (radius / 3) ** 2))
                            local_sum += img.data[ny][nx][0] * weight
                            weight_sum += weight

                threshold = int(local_sum / weight_sum) if weight_sum > 0 else 128

            value = img.data[y][x][0]
            binary.data[y][x][0] = 255 if value >= threshold else 0

    return binary


def kmeans_color_clustering(img: Image, k: int = 3, max_iterations: int = 100) -> Image:
    """Segment image using k-means color clustering.

    Args:
        img: RGB input image
        k: Number of clusters
        max_iterations: Maximum iterations for k-means

    Returns:
        Segmented image with cluster colors
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    if k <= 0:
        raise InvalidParameterError("k must be positive")

    # Collect all colors
    colors = []
    for y in range(img.height):
        for x in range(img.width):
            colors.append((img.data[y][x][0], img.data[y][x][1], img.data[y][x][2]))

    # Random initialization
    random.seed(42)
    centers = random.sample(colors, min(k, len(colors)))

    for iteration in range(max_iterations):
        # Assign colors to nearest center
        assignments = []
        for color in colors:
            min_dist = float("inf")
            best_center = 0

            for i, center in enumerate(centers):
                dist = sum((color[j] - center[j]) ** 2 for j in range(3))
                if dist < min_dist:
                    min_dist = dist
                    best_center = i

            assignments.append(best_center)

        # Update centers
        new_centers = []
        for i in range(k):
            cluster_colors = [colors[j] for j in range(len(colors)) if assignments[j] == i]

            if cluster_colors:
                new_center = (
                    sum(c[0] for c in cluster_colors) // len(cluster_colors),
                    sum(c[1] for c in cluster_colors) // len(cluster_colors),
                    sum(c[2] for c in cluster_colors) // len(cluster_colors),
                )
            else:
                new_center = random.choice(centers)

            new_centers.append(new_center)

        centers = new_centers

    # Create segmented image
    segmented = core.create_image(img.width, img.height, 3, img.color_space)
    idx = 0

    for y in range(img.height):
        for x in range(img.width):
            center_idx = assignments[idx]
            center = centers[center_idx]
            segmented.data[y][x][0] = center[0]
            segmented.data[y][x][1] = center[1]
            segmented.data[y][x][2] = center[2]
            idx += 1

    return segmented


def region_growing(img: Image, seed_x: int, seed_y: int, threshold: int = 30) -> Image:
    """Segment image using region growing from seed point.

    Args:
        img: Input image
        seed_x: X coordinate of seed
        seed_y: Y coordinate of seed
        threshold: Color similarity threshold

    Returns:
        Segmented image with labeled regions

    Raises:
        IndexError: If seed point is out of bounds
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if not (0 <= seed_x < img.width and 0 <= seed_y < img.height):
        raise IndexError(f"Seed point ({seed_x}, {seed_y}) out of bounds")

    segmented = core.create_image(img.width, img.height, 1, ColorSpace.GRAYSCALE)
    visited = [[False] * img.width for _ in range(img.height)]

    seed_color = img.data[seed_y][seed_x][:]
    queue = [(seed_x, seed_y)]
    visited[seed_y][seed_x] = True

    while queue:
        x, y = queue.pop(0)
        segmented.data[y][x][0] = 255

        # Check neighbors
        for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
            nx, ny = x + dx, y + dy

            if 0 <= nx < img.width and 0 <= ny < img.height and not visited[ny][nx]:
                neighbor_color = img.data[ny][nx][:]
                channel_count = min(len(seed_color), len(neighbor_color))
                if channel_count == 0:
                    continue
                distance = sum((neighbor_color[i] - seed_color[i]) ** 2 for i in range(channel_count)) ** 0.5

                if distance < threshold:
                    visited[ny][nx] = True
                    queue.append((nx, ny))

    return segmented


def watershed_transform(img: Image) -> Image:
    """Marker-based watershed segmentation.

    Args:
        img: Grayscale image (higher values = watershed peaks)

    Returns:
        Segmented image with labeled regions
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    # Simple watershed: assign each pixel to nearest local minimum
    labels = core.create_image(img.width, img.height, 1, ColorSpace.GRAYSCALE)

    # Find local minima as markers
    markers = []
    for y in range(1, img.height - 1):
        for x in range(1, img.width - 1):
            is_minimum = True
            val = img.data[y][x][0]

            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    if dy == 0 and dx == 0:
                        continue
                    if img.data[y + dy][x + dx][0] < val:
                        is_minimum = False
                        break
                if not is_minimum:
                    break

            if is_minimum:
                markers.append((x, y, len(markers)))

    # Grow from markers using BFS
    visited = [[False] * img.width for _ in range(img.height)]
    queue = list(markers)

    for mx, my, label in markers:
        labels.data[my][mx][0] = label + 1
        visited[my][mx] = True

    while queue:
        x, y, label = queue.pop(0)

        for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
            nx, ny = x + dx, y + dy

            if 0 <= nx < img.width and 0 <= ny < img.height and not visited[ny][nx]:
                visited[ny][nx] = True
                labels.data[ny][nx][0] = label + 1
                queue.append((nx, ny, label))

    return labels


def grabcut_foreground_extraction(img: Image, bbox_x: int, bbox_y: int, bbox_w: int, bbox_h: int) -> Image:
    """Simplified GrabCut-style foreground extraction.

    Args:
        img: RGB input image
        bbox_x: Bounding box x coordinate
        bbox_y: Bounding box y coordinate
        bbox_w: Bounding box width
        bbox_h: Bounding box height

    Returns:
        Binary foreground/background mask

    Raises:
        InvalidParameterError: If bounding box is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    if bbox_x < 0 or bbox_y < 0 or bbox_w <= 0 or bbox_h <= 0:
        raise InvalidParameterError("Invalid bounding box")

    # Simple approach: model foreground/background with means
    foreground_colors = []
    background_colors = []

    # Collect background colors (border regions)
    border_size = 10
    for y in range(img.height):
        for x in range(img.width):
            if y < border_size or y >= img.height - border_size or x < border_size or x >= img.width - border_size:
                color = tuple(img.data[y][x][:3])
                background_colors.append(color)

    # Collect foreground colors (bbox region)
    for y in range(bbox_y, min(bbox_y + bbox_h, img.height)):
        for x in range(bbox_x, min(bbox_x + bbox_w, img.width)):
            color = tuple(img.data[y][x][:3])
            foreground_colors.append(color)

    # Calculate mean colors
    if foreground_colors and background_colors:
        fg_mean = tuple(sum(c[i] for c in foreground_colors) // len(foreground_colors) for i in range(3))
        bg_mean = tuple(sum(c[i] for c in background_colors) // len(background_colors) for i in range(3))
    else:
        fg_mean = (128, 128, 128)
        bg_mean = (64, 64, 64)

    # Create mask: classify each pixel
    mask = core.create_image(img.width, img.height, 1, ColorSpace.GRAYSCALE)

    for y in range(img.height):
        for x in range(img.width):
            color = tuple(img.data[y][x][:3])

            fg_dist = sum((color[i] - fg_mean[i]) ** 2 for i in range(3)) ** 0.5
            bg_dist = sum((color[i] - bg_mean[i]) ** 2 for i in range(3)) ** 0.5

            mask.data[y][x][0] = 255 if fg_dist < bg_dist else 0

    return mask
