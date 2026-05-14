"""Image I/O operations for various file formats."""

import struct

from thomas.marketplace.cv import core
from thomas.marketplace.cv._exceptions import (
    InvalidImageError,
    InvalidParameterError,
    UnsupportedFormatError,
)
from thomas.marketplace.cv._types import ColorSpace, Image, ImageFormat


def detect_format(file_path: str) -> ImageFormat | None:
    """Detect image format from magic bytes.

    Args:
        file_path: Path to image file

    Returns:
        Detected ImageFormat or None if unknown

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    with open(file_path, "rb") as f:
        magic = f.read(4)

    # BMP magic
    if magic[:2] == b"BM":
        return ImageFormat.BMP

    # PPM/PGM magic
    if magic[:2] in (b"P5", b"P6"):
        return ImageFormat.PPM if magic[1:2] == b"6" else ImageFormat.PGM

    # TGA magic (footer check)
    if len(magic) >= 4:
        return ImageFormat.TGA

    return None


def read_bmp(file_path: str) -> Image:
    """Read BMP image (24-bit uncompressed).

    Args:
        file_path: Path to BMP file

    Returns:
        Loaded Image

    Raises:
        UnsupportedFormatError: If file format is invalid
    """
    with open(file_path, "rb") as f:
        # BMP header
        header = f.read(14)
        if header[:2] != b"BM":
            raise UnsupportedFormatError("Invalid BMP file")

        offset = struct.unpack("<I", header[10:14])[0]

        # DIB header
        struct.unpack("<I", f.read(4))[0]
        f.seek(18)

        width = struct.unpack("<I", f.read(4))[0]
        height = struct.unpack("<I", f.read(4))[0]
        planes = struct.unpack("<H", f.read(2))[0]
        bits_per_pixel = struct.unpack("<H", f.read(2))[0]

        if planes != 1 or bits_per_pixel != 24:
            raise UnsupportedFormatError("Only 24-bit uncompressed BMP supported")

        f.seek(offset)

        # Read pixel data (BGR format in BMP)
        data = [[[0, 0, 0] for _ in range(width)] for _ in range(height)]

        for y in range(height - 1, -1, -1):
            for x in range(width):
                pixel = f.read(3)
                if len(pixel) < 3:
                    raise UnsupportedFormatError("Unexpected end of file")

                b, g, r = pixel
                data[y][x] = [r, g, b]

        return Image(data, ColorSpace.RGB, "uint8")


def write_bmp(img: Image, file_path: str) -> None:
    """Write image as BMP (24-bit uncompressed).

    Args:
        img: Image to write
        file_path: Output file path

    Raises:
        InvalidImageError: If image is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if img.channels < 3:
        raise UnsupportedFormatError("BMP requires at least 3 channels")

    with open(file_path, "wb") as f:
        # BMP file header
        file_size = 14 + 40 + (img.width * img.height * 3)
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", 54))

        # DIB header
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<I", img.width))
        f.write(struct.pack("<I", img.height))
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<H", 24))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 0))

        # Pixel data (bottom-up, BGR format)
        for y in range(img.height - 1, -1, -1):
            for x in range(img.width):
                r = int(img.data[y][x][0])
                g = int(img.data[y][x][1])
                b = int(img.data[y][x][2])
                f.write(struct.pack("BBB", b, g, r))


def read_ppm_pgm(file_path: str) -> Image:
    """Read PPM/PGM image (P5/P6 binary format).

    Args:
        file_path: Path to PPM/PGM file

    Returns:
        Loaded Image

    Raises:
        UnsupportedFormatError: If file format is invalid
    """
    with open(file_path, "rb") as f:
        magic = f.read(2)

        if magic == b"P6":
            is_color = True
        elif magic == b"P5":
            is_color = False
        else:
            raise UnsupportedFormatError("Invalid PPM/PGM file")

        # Skip whitespace and comments
        while True:
            line = f.readline()
            if not line.startswith(b"#"):
                break

        # Parse dimensions
        parts = line.split()
        width = int(parts[0])
        height = int(parts[1])

        # Parse max value
        int(f.readline().strip())

        # Read pixel data
        channels = 3 if is_color else 1
        data = [[[0] * channels for _ in range(width)] for _ in range(height)]

        for y in range(height):
            for x in range(width):
                if is_color:
                    r, g, b = f.read(3)
                    data[y][x] = [r, g, b]
                else:
                    val = f.read(1)[0]
                    data[y][x] = [val]

        color_space = ColorSpace.RGB if is_color else ColorSpace.GRAYSCALE
        return Image(data, color_space, "uint8")


def write_ppm_pgm(img: Image, file_path: str, is_pgm: bool = False) -> None:
    """Write image as PPM/PGM (P6/P5 binary format).

    Args:
        img: Image to write
        file_path: Output file path
        is_pgm: True for PGM (grayscale), False for PPM (color)

    Raises:
        InvalidImageError: If image is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    with open(file_path, "wb") as f:
        if is_pgm:
            f.write(b"P5\n")
        else:
            f.write(b"P6\n")

        f.write(f"{img.width} {img.height}\n".encode())
        f.write(b"255\n")

        # Write pixel data
        for y in range(img.height):
            for x in range(img.width):
                if is_pgm:
                    val = img.data[y][x][0]
                    f.write(struct.pack("B", int(val)))
                else:
                    r = int(img.data[y][x][0])
                    g = int(img.data[y][x][1] if img.channels > 1 else r)
                    b = int(img.data[y][x][2] if img.channels > 2 else r)
                    f.write(struct.pack("BBB", r, g, b))


def read_tga(file_path: str) -> Image:
    """Read TGA image (uncompressed).

    Args:
        file_path: Path to TGA file

    Returns:
        Loaded Image

    Raises:
        UnsupportedFormatError: If file format is invalid
    """
    with open(file_path, "rb") as f:
        # TGA header
        f.read(1)[0]
        f.read(1)[0]
        image_type = f.read(1)[0]

        # Skip color map
        f.seek(18)

        width = struct.unpack("<H", f.read(2))[0]
        height = struct.unpack("<H", f.read(2))[0]
        bits_per_pixel = f.read(1)[0]
        f.read(1)[0]

        if image_type not in (2, 3):
            raise UnsupportedFormatError("Only uncompressed TGA images supported")

        bytes_per_pixel = bits_per_pixel // 8

        if bytes_per_pixel not in (3, 4):
            raise UnsupportedFormatError("Only 24-bit and 32-bit TGA images supported")

        # Read pixel data
        data = [[[0] * 3 for _ in range(width)] for _ in range(height)]

        for y in range(height):
            for x in range(width):
                pixel = f.read(bytes_per_pixel)

                if bytes_per_pixel == 3:
                    b, g, r = pixel
                else:
                    b, g, r, a = pixel

                data[y][x] = [r, g, b]

        return Image(data, ColorSpace.RGB, "uint8")


def write_tga(img: Image, file_path: str) -> None:
    """Write image as TGA (uncompressed).

    Args:
        img: Image to write
        file_path: Output file path

    Raises:
        InvalidImageError: If image is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    with open(file_path, "wb") as f:
        # TGA header
        f.write(struct.pack("B", 0))  # ID length
        f.write(struct.pack("B", 0))  # Color map type
        f.write(struct.pack("B", 2))  # Image type (uncompressed RGB)

        # Color map
        for _ in range(5):
            f.write(struct.pack("B", 0))

        # Image spec
        f.write(struct.pack("<H", 0))  # X origin
        f.write(struct.pack("<H", 0))  # Y origin
        f.write(struct.pack("<H", img.width))
        f.write(struct.pack("<H", img.height))
        f.write(struct.pack("B", 24))  # Bits per pixel
        f.write(struct.pack("B", 0))  # Descriptor

        # Pixel data (BGR format)
        for y in range(img.height):
            for x in range(img.width):
                r = int(img.data[y][x][0])
                g = int(img.data[y][x][1] if img.channels > 1 else r)
                b = int(img.data[y][x][2] if img.channels > 2 else r)
                f.write(struct.pack("BBB", b, g, r))


def generate_thumbnail(img: Image, max_size: int = 128) -> Image:
    """Generate thumbnail from image.

    Args:
        img: Input image
        max_size: Maximum dimension of thumbnail

    Returns:
        Thumbnail image

    Raises:
        InvalidParameterError: If max_size is invalid
    """
    if not isinstance(img, Image):
        raise InvalidImageError("Input must be an Image object")

    if max_size <= 0:
        raise InvalidParameterError("Max size must be positive")

    scale = max_size / max(img.width, img.height)
    thumb_w = int(img.width * scale)
    thumb_h = int(img.height * scale)

    return core.resize_image(img, thumb_w, thumb_h, method="bilinear")


def psnr(img1: Image, img2: Image) -> float:
    """Calculate Peak Signal-to-Noise Ratio.

    Args:
        img1: First image
        img2: Second image

    Returns:
        PSNR in dB

    Raises:
        InvalidImageError: If images have different dimensions
    """
    if not isinstance(img1, Image) or not isinstance(img2, Image):
        raise InvalidImageError("Both inputs must be Image objects")

    if img1.shape != img2.shape:
        raise InvalidImageError("Images must have same dimensions")

    mse = 0.0
    total_pixels = img1.width * img1.height * img1.channels

    for y in range(img1.height):
        for x in range(img1.width):
            for c in range(img1.channels):
                v1 = img1.data[y][x][c]
                v2 = img2.data[y][x][c]
                mse += (v1 - v2) ** 2

    mse /= total_pixels

    if mse == 0:
        return 100.0

    max_val = 255.0
    psnr_val = 10 * (math.log10(max_val * max_val / mse))

    return psnr_val


def ssim_simplified(img1: Image, img2: Image, window_size: int = 11) -> float:
    """Calculate simplified Structural Similarity Index.

    Args:
        img1: First image
        img2: Second image
        window_size: Size of comparison window

    Returns:
        SSIM index (0-1, higher is better)

    Raises:
        InvalidImageError: If images have different dimensions
    """
    if not isinstance(img1, Image) or not isinstance(img2, Image):
        raise InvalidImageError("Both inputs must be Image objects")

    if img1.shape != img2.shape:
        raise InvalidImageError("Images must have same dimensions")

    c1, c2 = 6.5025, 58.5225

    ssim_values = []
    radius = window_size // 2

    for y in range(radius, img1.height - radius):
        for x in range(radius, img1.width - radius):
            mean1, mean2 = 0.0, 0.0
            var1, var2, cov = 0.0, 0.0, 0.0

            count = 0
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    v1 = img1.data[y + dy][x + dx][0]
                    v2 = img2.data[y + dy][x + dx][0]
                    mean1 += v1
                    mean2 += v2
                    count += 1

            mean1 /= count
            mean2 /= count

            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    v1 = img1.data[y + dy][x + dx][0] - mean1
                    v2 = img2.data[y + dy][x + dx][0] - mean2
                    var1 += v1 * v1
                    var2 += v2 * v2
                    cov += v1 * v2

            var1 /= count
            var2 /= count
            cov /= count

            ssim_window = ((2 * mean1 * mean2 + c1) * (2 * cov + c2)) / (
                (mean1 * mean1 + mean2 * mean2 + c1) * (var1 + var2 + c2)
            )
            ssim_values.append(ssim_window)

    return sum(ssim_values) / len(ssim_values) if ssim_values else 0.0


# Import math at module level
import math
