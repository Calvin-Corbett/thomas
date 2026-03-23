"""Morphological image operations."""

from thomas.marketplace.cv import core
from thomas.marketplace.cv._exceptions import InvalidImageError, InvalidParameterError
from thomas.marketplace.cv._types import ColorSpace, Image


def _create_structuring_element(size: int = 3, shape: str = "rect") -> list[list[int]]:
    """Create a structuring element (kernel).

    Args:
        size: Size of the element (must be odd)
        shape: Shape type ('rect' for rectangle, 'ellipse' for ellipse)

    Returns:
        2D binary structuring element
    """
    if size % 2 == 0:
        size += 1

    element = [[0] * size for _ in range(size)]
    center = size // 2

    if shape == "rect":
        element = [[1] * size for _ in range(size)]
    elif shape == "ellipse":
        for y in range(size):
            for x in range(size):
                dy = y - center
                dx = x - center
                if dx * dx + dy * dy <= (center + 0.5) ** 2:
                    element[y][x] = 1

    return element


def erode(img: Image, kernel_size: int = 3, kernel_shape: str = "rect") -> Image:
    """Erode image with morphological erosion.

    Args:
        img: Binary input image
        kernel_size: Size of structuring element (must be odd)
        kernel_shape: Shape of structuring element ('rect' or 'ellipse')

    Returns:
        Eroded image

    Raises:
        InvalidParameterError: If kernel_size is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if kernel_size % 2 == 0 or kernel_size <= 0:
        raise InvalidParameterError("Kernel size must be positive and odd")

    element = _create_structuring_element(kernel_size, kernel_shape)
    radius = kernel_size // 2

    eroded = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                min_val = 255

                for ky in range(kernel_size):
                    for kx in range(kernel_size):
                        if element[ky][kx] == 0:
                            continue

                        ny = y + ky - radius
                        nx = x + kx - radius

                        if 0 <= ny < img.height and 0 <= nx < img.width:
                            min_val = min(min_val, img.data[ny][nx][c])

                eroded.data[y][x][c] = min_val

    return eroded


def dilate(img: Image, kernel_size: int = 3, kernel_shape: str = "rect") -> Image:
    """Dilate image with morphological dilation.

    Args:
        img: Binary input image
        kernel_size: Size of structuring element (must be odd)
        kernel_shape: Shape of structuring element ('rect' or 'ellipse')

    Returns:
        Dilated image

    Raises:
        InvalidParameterError: If kernel_size is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if kernel_size % 2 == 0 or kernel_size <= 0:
        raise InvalidParameterError("Kernel size must be positive and odd")

    element = _create_structuring_element(kernel_size, kernel_shape)
    radius = kernel_size // 2

    dilated = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                max_val = 0

                for ky in range(kernel_size):
                    for kx in range(kernel_size):
                        if element[ky][kx] == 0:
                            continue

                        ny = y + ky - radius
                        nx = x + kx - radius

                        if 0 <= ny < img.height and 0 <= nx < img.width:
                            max_val = max(max_val, img.data[ny][nx][c])

                dilated.data[y][x][c] = max_val

    return dilated


def opening(img: Image, kernel_size: int = 3, kernel_shape: str = "rect") -> Image:
    """Morphological opening (erosion followed by dilation).

    Args:
        img: Input image
        kernel_size: Size of structuring element
        kernel_shape: Shape of structuring element

    Returns:
        Opened image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    eroded = erode(img, kernel_size, kernel_shape)
    return dilate(eroded, kernel_size, kernel_shape)


def closing(img: Image, kernel_size: int = 3, kernel_shape: str = "rect") -> Image:
    """Morphological closing (dilation followed by erosion).

    Args:
        img: Input image
        kernel_size: Size of structuring element
        kernel_shape: Shape of structuring element

    Returns:
        Closed image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    dilated = dilate(img, kernel_size, kernel_shape)
    return erode(dilated, kernel_size, kernel_shape)


def morphological_gradient(img: Image, kernel_size: int = 3) -> Image:
    """Compute morphological gradient (dilation - erosion).

    Args:
        img: Input image
        kernel_size: Size of structuring element

    Returns:
        Morphological gradient
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    dilated = dilate(img, kernel_size)
    eroded = erode(img, kernel_size)

    gradient = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                gradient.data[y][x][c] = max(0, dilated.data[y][x][c] - eroded.data[y][x][c])

    return gradient


def top_hat_transform(img: Image, kernel_size: int = 3) -> Image:
    """Top-hat transform (original - opening).

    Args:
        img: Input image
        kernel_size: Size of structuring element

    Returns:
        Top-hat transformed image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    opened = opening(img, kernel_size)

    result = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                result.data[y][x][c] = max(0, img.data[y][x][c] - opened.data[y][x][c])

    return result


def black_hat_transform(img: Image, kernel_size: int = 3) -> Image:
    """Black-hat transform (closing - original).

    Args:
        img: Input image
        kernel_size: Size of structuring element

    Returns:
        Black-hat transformed image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    closed = closing(img, kernel_size)

    result = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                result.data[y][x][c] = max(0, closed.data[y][x][c] - img.data[y][x][c])

    return result


def connected_components(img: Image, connectivity: int = 4) -> tuple[Image, int]:
    """Label connected components in binary image using two-pass algorithm.

    Args:
        img: Binary input image
        connectivity: 4 or 8 connectivity

    Returns:
        Tuple of (labeled image, number of components)
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if connectivity not in (4, 8):
        raise InvalidParameterError("Connectivity must be 4 or 8")

    labels = core.create_image(img.width, img.height, 1, ColorSpace.GRAYSCALE)
    parent = {}  # Union-find structure

    def find(x):
        """Find root of union-find set."""
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        """Union two sets."""
        root_x = find(x)
        root_y = find(y)
        if root_x != root_y:
            parent[root_x] = root_y

    current_label = 0

    # First pass: assign tentative labels
    for y in range(img.height):
        for x in range(img.width):
            if img.data[y][x][0] > 127:
                neighbors = []

                if x > 0 and labels.data[y][x - 1][0] > 0:
                    neighbors.append(labels.data[y][x - 1][0])

                if y > 0 and labels.data[y - 1][x][0] > 0:
                    neighbors.append(labels.data[y - 1][x][0])

                if connectivity == 8:
                    if x > 0 and y > 0 and labels.data[y - 1][x - 1][0] > 0:
                        neighbors.append(labels.data[y - 1][x - 1][0])

                    if x < img.width - 1 and y > 0 and labels.data[y - 1][x + 1][0] > 0:
                        neighbors.append(labels.data[y - 1][x + 1][0])

                if neighbors:
                    label = min(neighbors)
                    for n in neighbors:
                        union(n, label)
                    labels.data[y][x][0] = label
                else:
                    current_label += 1
                    labels.data[y][x][0] = current_label
                    parent[current_label] = current_label

    # Second pass: relabel with roots
    label_map = {}
    final_label = 0

    for y in range(img.height):
        for x in range(img.width):
            if labels.data[y][x][0] > 0:
                old_label = labels.data[y][x][0]
                root = find(old_label)

                if root not in label_map:
                    final_label += 1
                    label_map[root] = final_label

                labels.data[y][x][0] = label_map[root]

    return labels, final_label


def flood_fill(img: Image, seed_x: int, seed_y: int, fill_value: int, tolerance: int = 0) -> Image:
    """Fill connected region using scanline algorithm.

    Args:
        img: Input image
        seed_x: X coordinate of seed point
        seed_y: Y coordinate of seed point
        fill_value: Value to fill with
        tolerance: Color tolerance for fill

    Returns:
        Filled image

    Raises:
        IndexError: If seed point is out of bounds
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if not (0 <= seed_x < img.width and 0 <= seed_y < img.height):
        raise IndexError(f"Seed point ({seed_x}, {seed_y}) out of bounds")

    result = core.clone_image(img)

    seed_color = img.data[seed_y][seed_x][0]

    # Scanline fill
    stack = [(seed_x, seed_y)]
    visited = set()

    while stack:
        x, y = stack.pop()

        if (x, y) in visited:
            continue

        if not (0 <= x < img.width and 0 <= y < img.height):
            continue

        color = result.data[y][x][0]

        if abs(color - seed_color) > tolerance:
            continue

        visited.add((x, y))
        result.data[y][x][0] = fill_value

        # Add neighbors
        stack.append((x + 1, y))
        stack.append((x - 1, y))
        stack.append((x, y + 1))
        stack.append((x, y - 1))

    return result
