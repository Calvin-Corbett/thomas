"""Color space conversions and color processing."""

from thomas.cv import core
from thomas.cv._exceptions import InvalidImageError, InvalidParameterError
from thomas.cv._types import ColorSpace, Histogram, Image


def rgb_to_grayscale(img: Image, weights: tuple[float, float, float] | None = None) -> Image:
    """Convert RGB image to grayscale using weighted average.

    Args:
        img: RGB input image
        weights: Channel weights (R, G, B). Default: BT.601 weights

    Returns:
        Grayscale image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    if weights is None:
        weights = (0.299, 0.587, 0.114)  # BT.601

    if len(weights) != 3 or sum(weights) == 0:
        raise InvalidParameterError("Weights must be 3-tuple of non-zero sum")

    grayscale = core.create_image(img.width, img.height, 1, ColorSpace.GRAYSCALE)

    for y in range(img.height):
        for x in range(img.width):
            r = img.data[y][x][0]
            g = img.data[y][x][1]
            b = img.data[y][x][2]

            gray = int(r * weights[0] + g * weights[1] + b * weights[2])
            grayscale.data[y][x][0] = max(0, min(255, gray))

    return grayscale


def rgb_to_hsv(img: Image) -> Image:
    """Convert RGB image to HSV color space.

    Args:
        img: RGB input image

    Returns:
        HSV image (H: 0-360, S: 0-100, V: 0-100)
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    hsv = core.create_image(img.width, img.height, 3, ColorSpace.HSV)

    for y in range(img.height):
        for x in range(img.width):
            r = img.data[y][x][0] / 255.0
            g = img.data[y][x][1] / 255.0
            b = img.data[y][x][2] / 255.0

            c_max = max(r, g, b)
            c_min = min(r, g, b)
            delta = c_max - c_min

            # Hue
            if delta == 0:
                h = 0
            elif c_max == r:
                h = 60 * (((g - b) / delta) % 6)
            elif c_max == g:
                h = 60 * (((b - r) / delta) + 2)
            else:
                h = 60 * (((r - g) / delta) + 4)

            # Saturation
            s = 0 if c_max == 0 else (delta / c_max) * 100

            # Value
            v = c_max * 100

            hsv.data[y][x][0] = int(h % 360)
            hsv.data[y][x][1] = int(s)
            hsv.data[y][x][2] = int(v)

    return hsv


def hsv_to_rgb(img: Image) -> Image:
    """Convert HSV image to RGB color space.

    Args:
        img: HSV input image (H: 0-360, S: 0-100, V: 0-100)

    Returns:
        RGB image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    rgb = core.create_image(img.width, img.height, 3, ColorSpace.RGB)

    for y in range(img.height):
        for x in range(img.width):
            h = img.data[y][x][0]
            s = img.data[y][x][1] / 100.0
            v = img.data[y][x][2] / 100.0

            c = v * s
            hh = h / 60.0
            x_val = c * (1 - abs((hh % 2) - 1))
            m = v - c

            if 0 <= hh < 1:
                rr, gg, bb = c, x_val, 0
            elif 1 <= hh < 2:
                rr, gg, bb = x_val, c, 0
            elif 2 <= hh < 3:
                rr, gg, bb = 0, c, x_val
            elif 3 <= hh < 4:
                rr, gg, bb = 0, x_val, c
            elif 4 <= hh < 5:
                rr, gg, bb = x_val, 0, c
            else:
                rr, gg, bb = c, 0, x_val

            rgb.data[y][x][0] = int((rr + m) * 255)
            rgb.data[y][x][1] = int((gg + m) * 255)
            rgb.data[y][x][2] = int((bb + m) * 255)

    return rgb


def rgb_to_hsl(img: Image) -> Image:
    """Convert RGB image to HSL color space.

    Args:
        img: RGB input image

    Returns:
        HSL image (H: 0-360, S: 0-100, L: 0-100)
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    hsl = core.create_image(img.width, img.height, 3, ColorSpace.HSL)

    for y in range(img.height):
        for x in range(img.width):
            r = img.data[y][x][0] / 255.0
            g = img.data[y][x][1] / 255.0
            b = img.data[y][x][2] / 255.0

            c_max = max(r, g, b)
            c_min = min(r, g, b)
            delta = c_max - c_min

            # Lightness
            l = (c_max + c_min) / 2

            # Saturation
            if delta == 0:
                s = 0
            else:
                s = delta / (1 - abs(2 * l - 1))

            # Hue
            if delta == 0:
                h = 0
            elif c_max == r:
                h = 60 * (((g - b) / delta) % 6)
            elif c_max == g:
                h = 60 * (((b - r) / delta) + 2)
            else:
                h = 60 * (((r - g) / delta) + 4)

            hsl.data[y][x][0] = int(h % 360)
            hsl.data[y][x][1] = int(s * 100)
            hsl.data[y][x][2] = int(l * 100)

    return hsl


def rgb_to_ycbcr(img: Image) -> Image:
    """Convert RGB image to YCbCr color space.

    Args:
        img: RGB input image

    Returns:
        YCbCr image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    ycbcr = core.create_image(img.width, img.height, 3, ColorSpace.YCbCr)

    for y in range(img.height):
        for x in range(img.width):
            r = img.data[y][x][0]
            g = img.data[y][x][1]
            b = img.data[y][x][2]

            yval = 0.299 * r + 0.587 * g + 0.114 * b
            cb = 128 + (-0.168736 * r - 0.331264 * g + 0.5 * b)
            cr = 128 + (0.5 * r - 0.418688 * g - 0.081312 * b)

            ycbcr.data[y][x][0] = int(max(0, min(255, yval)))
            ycbcr.data[y][x][1] = int(max(0, min(255, cb)))
            ycbcr.data[y][x][2] = int(max(0, min(255, cr)))

    return ycbcr


def rgb_to_lab(img: Image) -> Image:
    """Convert RGB image to Lab color space (D65 illuminant).

    Args:
        img: RGB input image

    Returns:
        Lab image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    lab = core.create_image(img.width, img.height, 3, ColorSpace.Lab)

    # D65 illuminant reference
    ref_x, ref_y, ref_z = 0.95047, 1.0, 1.08883

    for y in range(img.height):
        for x in range(img.width):
            # Normalize to [0, 1]
            r = img.data[y][x][0] / 255.0
            g = img.data[y][x][1] / 255.0
            b = img.data[y][x][2] / 255.0

            # sRGB to linear RGB
            r = r / 12.92 if r <= 0.04045 else ((r + 0.055) / 1.055) ** 2.4
            g = g / 12.92 if g <= 0.04045 else ((g + 0.055) / 1.055) ** 2.4
            b = b / 12.92 if b <= 0.04045 else ((b + 0.055) / 1.055) ** 2.4

            # RGB to XYZ
            xyz_x = r * 0.4124 + g * 0.3576 + b * 0.1805
            xyz_y = r * 0.2126 + g * 0.7152 + b * 0.0722
            xyz_z = r * 0.0193 + g * 0.1192 + b * 0.9505

            # Normalize by reference
            xyz_x /= ref_x
            xyz_y /= ref_y
            xyz_z /= ref_z

            # XYZ to Lab
            epsilon = 0.008856
            kappa = 903.3

            fx = xyz_x ** (1 / 3) if xyz_x > epsilon else (kappa * xyz_x + 16) / 116
            fy = xyz_y ** (1 / 3) if xyz_y > epsilon else (kappa * xyz_y + 16) / 116
            fz = xyz_z ** (1 / 3) if xyz_z > epsilon else (kappa * xyz_z + 16) / 116

            lab_l = 116 * fy - 16
            lab_a = 500 * (fx - fy)
            lab_b = 200 * (fy - fz)

            lab.data[y][x][0] = int(max(0, min(100, lab_l)))
            lab.data[y][x][1] = int(max(-128, min(127, lab_a)))
            lab.data[y][x][2] = int(max(-128, min(127, lab_b)))

    return lab


def calculate_histogram(img: Image, channel: int = 0, bins: int = 256) -> Histogram:
    """Calculate histogram for a single channel.

    Args:
        img: Input image
        channel: Channel index (0 for single-channel)
        bins: Number of histogram bins

    Returns:
        Histogram object
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if channel < 0 or channel >= img.channels:
        raise InvalidParameterError(f"Invalid channel {channel}")

    histogram = Histogram(bins=bins)
    histogram.data = [0] * bins
    bin_width = 256 / bins

    for y in range(img.height):
        for x in range(img.width):
            value = img.data[y][x][channel]
            bin_idx = min(int(value / bin_width), bins - 1)
            histogram.data[bin_idx] += 1

    return histogram


def histogram_equalization(img: Image) -> Image:
    """Apply histogram equalization for contrast enhancement.

    Args:
        img: Input grayscale image

    Returns:
        Equalized image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    # Calculate histogram
    hist = calculate_histogram(img, channel=0, bins=256)

    # Calculate CDF
    cdf = [0] * 256
    cdf[0] = hist.data[0]
    for i in range(1, 256):
        cdf[i] = cdf[i - 1] + hist.data[i]

    # Normalize CDF
    min_cdf = min(cdf)
    levels = img.width * img.height
    cdf_normalized = [(c - min_cdf) * 255 // (levels - min_cdf) if levels > min_cdf else 0 for c in cdf]

    # Apply equalization
    equalized = core.clone_image(img)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                value = img.data[y][x][c]
                equalized.data[y][x][c] = cdf_normalized[value]

    return equalized


def color_quantization(img: Image, k: int = 8) -> Image:
    """Reduce colors using k-means clustering (median cut approximation).

    Args:
        img: RGB input image
        k: Number of colors in output palette

    Returns:
        Quantized image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if k <= 0 or k > 256:
        raise InvalidParameterError("k must be between 1 and 256")

    # Simple median cut implementation
    colors = []
    for y in range(img.height):
        for x in range(img.width):
            colors.append(tuple(img.data[y][x][:3]))

    # Get unique colors (up to k)
    unique_colors = list(set(colors))
    unique_colors.sort()

    if len(unique_colors) <= k:
        return core.clone_image(img)

    # Create palette by sampling
    palette = unique_colors[:: len(unique_colors) // k][:k]

    # Map colors to palette
    quantized = core.create_image(img.width, img.height, 3, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            r = img.data[y][x][0]
            g = img.data[y][x][1]
            b = img.data[y][x][2]

            # Find nearest palette color
            min_dist = float("inf")
            best_color = palette[0]

            for pr, pg, pb in palette:
                dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if dist < min_dist:
                    min_dist = dist
                    best_color = (pr, pg, pb)

            quantized.data[y][x][0] = best_color[0]
            quantized.data[y][x][1] = best_color[1]
            quantized.data[y][x][2] = best_color[2]

    return quantized


def white_balance(img: Image, method: str = "gray_world") -> Image:
    """Apply white balance correction.

    Args:
        img: RGB input image
        method: White balance method ('gray_world' or 'max_white')

    Returns:
        White-balanced image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise InvalidParameterError("Input must have at least 3 channels")

    if method not in ("gray_world", "max_white"):
        raise InvalidParameterError(f"Unknown method: {method}")

    balanced = core.clone_image(img)

    if method == "gray_world":
        # Average of each channel
        avg_r = sum(img.data[y][x][0] for y in range(img.height) for x in range(img.width)) / (img.width * img.height)
        avg_g = sum(img.data[y][x][1] for y in range(img.height) for x in range(img.width)) / (img.width * img.height)
        avg_b = sum(img.data[y][x][2] for y in range(img.height) for x in range(img.width)) / (img.width * img.height)

        avg_intensity = (avg_r + avg_g + avg_b) / 3

        r_scale = avg_intensity / avg_r if avg_r > 0 else 1
        g_scale = avg_intensity / avg_g if avg_g > 0 else 1
        b_scale = avg_intensity / avg_b if avg_b > 0 else 1

        for y in range(img.height):
            for x in range(img.width):
                balanced.data[y][x][0] = int(max(0, min(255, img.data[y][x][0] * r_scale)))
                balanced.data[y][x][1] = int(max(0, min(255, img.data[y][x][1] * g_scale)))
                balanced.data[y][x][2] = int(max(0, min(255, img.data[y][x][2] * b_scale)))

    return balanced


def gamma_correction(img: Image, gamma: float) -> Image:
    """Apply gamma correction.

    Args:
        img: Input image
        gamma: Gamma value (< 1 brightens, > 1 darkens)

    Returns:
        Gamma-corrected image
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if gamma <= 0:
        raise InvalidParameterError("Gamma must be positive")

    # Create lookup table
    # Use power gamma so gamma < 1 brightens and gamma > 1 darkens.
    lut = [int(255 * ((i / 255) ** gamma)) for i in range(256)]

    corrected = core.create_image(img.width, img.height, img.channels, img.color_space)

    for y in range(img.height):
        for x in range(img.width):
            for c in range(img.channels):
                value = img.data[y][x][c]
                corrected.data[y][x][c] = lut[value]

    return corrected
