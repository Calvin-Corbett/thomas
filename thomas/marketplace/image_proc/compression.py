"""
Image compression module.

Implements JPEG compression/decompression pipeline (DCT, quantization, Huffman),
PNG filtering, and compression quality metrics (PSNR, SSIM, MS-SSIM).
"""

from __future__ import annotations

import numpy as np
from scipy.fftpack import dctn, idctn
from scipy.ndimage import gaussian_filter

from ._exceptions import CompressionError
from ._types import Image


class CompressionCodec:
    """
    Image compression and decompression.

    Implements:
    - JPEG pipeline (DCT, quantization, Huffman)
    - PNG with filtering
    - Quality metrics (PSNR, SSIM, MS-SSIM)
    """

    # JPEG quantization tables for luminance (Q=50)
    JPEG_Q_TABLE_LUMA = np.array(
        [
            [16, 11, 10, 16, 24, 40, 51, 61],
            [12, 12, 14, 19, 26, 58, 60, 55],
            [14, 13, 16, 24, 40, 57, 69, 56],
            [14, 17, 22, 29, 51, 87, 80, 62],
            [18, 22, 37, 56, 68, 109, 103, 77],
            [24, 35, 55, 64, 81, 104, 113, 92],
            [49, 64, 78, 87, 103, 121, 120, 101],
            [72, 92, 95, 98, 112, 100, 103, 99],
        ]
    )

    # JPEG quantization table for chrominance (Q=50)
    JPEG_Q_TABLE_CHROMA = np.array(
        [
            [17, 18, 24, 47, 99, 99, 99, 99],
            [18, 21, 26, 66, 99, 99, 99, 99],
            [24, 26, 56, 99, 99, 99, 99, 99],
            [47, 66, 99, 99, 99, 99, 99, 99],
            [99, 99, 99, 99, 99, 99, 99, 99],
            [99, 99, 99, 99, 99, 99, 99, 99],
            [99, 99, 99, 99, 99, 99, 99, 99],
            [99, 99, 99, 99, 99, 99, 99, 99],
        ]
    )

    def __init__(self) -> None:
        """Initialize codec."""
        self.quality_factor = 85

    def jpeg_compress(self, image: Image, quality: int = 85) -> bytes:
        """
        JPEG compression.

        Args:
            image: Input image (RGB or grayscale).
            quality: Quality factor (1-100).

        Returns:
            Compressed image data (simplified format, not standard JPEG).

        Raises:
            CompressionError: If compression fails.
        """
        self.quality_factor = np.clip(quality, 1, 100)

        img_float = image.to_float32()

        # Convert to YCbCr
        if img_float.channels == 3:
            ycbcr = self._rgb_to_ycbcr(img_float.data)
        else:
            ycbcr = np.dstack([img_float.data, np.zeros_like(img_float.data), np.zeros_like(img_float.data)])

        h, w = img_float.height, img_float.width

        # Process in 8x8 blocks
        compressed_blocks = []
        block_size = 8

        for c in range(3):
            channel = ycbcr[:, :, c]

            for y in range(0, h, block_size):
                for x in range(0, w, block_size):
                    y_end = min(y + block_size, h)
                    x_end = min(x + block_size, w)

                    # Pad block if necessary
                    block = np.zeros((block_size, block_size))
                    block[: y_end - y, : x_end - x] = channel[y:y_end, x:x_end]

                    # DCT
                    dct_block = dctn(block - 128, type=2, norm="ortho")

                    # Quantization
                    q_table = self.JPEG_Q_TABLE_LUMA if c == 0 else self.JPEG_Q_TABLE_CHROMA
                    q_factor = (
                        (100 - self.quality_factor) / 50
                        if self.quality_factor < 50
                        else (200 - 2 * self.quality_factor) / 100
                    )
                    adjusted_q = np.maximum(1, (q_table * q_factor).astype(int))

                    quantized = np.round(dct_block / adjusted_q).astype(int)

                    # Zigzag scan
                    zigzag = self._zigzag_encode(quantized)

                    # RLE encoding
                    rle = self._run_length_encode(zigzag)

                    compressed_blocks.append((rle, adjusted_q))

        # Simple serialization (not real JPEG)
        return np.array(compressed_blocks, dtype=object).tobytes()

    def jpeg_decompress(self, data: bytes, shape: tuple[int, int, int]) -> Image:
        """
        JPEG decompression.

        Args:
            data: Compressed JPEG data.
            shape: (height, width, channels).

        Returns:
            Decompressed image.

        Raises:
            CompressionError: If decompression fails.
        """
        try:
            compressed_blocks = np.frombuffer(data, dtype=object)

            h, w, c = shape
            block_size = 8

            ycbcr = np.zeros(shape)

            idx = 0
            for ch in range(c):
                for y in range(0, h, block_size):
                    for x in range(0, w, block_size):
                        if idx >= len(compressed_blocks):
                            break

                        rle, q_table = compressed_blocks[idx]
                        idx += 1

                        # RLE decoding
                        zigzag = self._run_length_decode(rle, block_size**2)

                        # Inverse zigzag
                        quantized = self._zigzag_decode(zigzag)

                        # Dequantization
                        dequantized = quantized * q_table

                        # IDCT
                        block = idctn(dequantized, type=2, norm="ortho") + 128

                        # Copy to output
                        y_end = min(y + block_size, h)
                        x_end = min(x + block_size, w)
                        ycbcr[y:y_end, x:x_end, ch] = block[: y_end - y, : x_end - x]

            # YCbCr to RGB
            rgb = self._ycbcr_to_rgb(ycbcr)

            return Image(
                data=np.clip(rgb, 0, 1).astype(np.float32),
                color_space="RGB",
                bit_depth=32,
            )
        except Exception as e:
            raise CompressionError(f"JPEG decompression failed: {e}")

    @staticmethod
    def _rgb_to_ycbcr(rgb: np.ndarray) -> np.ndarray:
        """Convert RGB to YCbCr."""
        rgb = rgb.astype(np.float64, copy=False)
        ycbcr = np.zeros(rgb.shape, dtype=np.float64)

        # Y = 0.299*R + 0.587*G + 0.114*B
        ycbcr[:, :, 0] = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]

        # Cb = 0.5 * B / (1 - 0.114) - 0.5
        ycbcr[:, :, 1] = 0.5 * (rgb[:, :, 2] - ycbcr[:, :, 0]) / (1 - 0.114) + 0.5

        # Cr = 0.5 * R / (1 - 0.299) - 0.5
        ycbcr[:, :, 2] = 0.5 * (rgb[:, :, 0] - ycbcr[:, :, 0]) / (1 - 0.299) + 0.5

        return ycbcr

    @staticmethod
    def _ycbcr_to_rgb(ycbcr: np.ndarray) -> np.ndarray:
        """Convert YCbCr to RGB."""
        ycbcr = ycbcr.astype(np.float64, copy=False)
        rgb = np.zeros(ycbcr.shape, dtype=np.float64)

        Y = ycbcr[:, :, 0]
        Cb = ycbcr[:, :, 1]
        Cr = ycbcr[:, :, 2]

        rgb[:, :, 0] = Y + 1.402 * (Cr - 0.5)
        rgb[:, :, 1] = Y - 0.344136 * (Cb - 0.5) - 0.714136 * (Cr - 0.5)
        rgb[:, :, 2] = Y + 1.772 * (Cb - 0.5)

        return rgb

    @staticmethod
    def _zigzag_encode(block: np.ndarray) -> np.ndarray:
        """Zigzag scan of 8x8 block."""
        zigzag_order = [
            (0, 0),
            (0, 1),
            (1, 0),
            (2, 0),
            (1, 1),
            (0, 2),
            (0, 3),
            (1, 2),
            (2, 1),
            (3, 0),
            (4, 0),
            (3, 1),
            (2, 2),
            (1, 3),
            (0, 4),
            (0, 5),
            (1, 4),
            (2, 3),
            (3, 2),
            (4, 1),
            (5, 0),
            (6, 0),
            (5, 1),
            (4, 2),
            (3, 3),
            (2, 4),
            (1, 5),
            (0, 6),
            (0, 7),
            (1, 6),
            (2, 5),
            (3, 4),
            (4, 3),
            (5, 2),
            (6, 1),
            (7, 0),
            (7, 1),
            (6, 2),
            (5, 3),
            (4, 4),
            (3, 5),
            (2, 6),
            (1, 7),
            (2, 7),
            (3, 6),
            (4, 5),
            (5, 4),
            (6, 3),
            (7, 2),
            (7, 3),
            (6, 4),
            (5, 5),
            (4, 6),
            (3, 7),
            (4, 7),
            (5, 6),
            (6, 5),
            (7, 4),
            (7, 5),
            (6, 6),
            (5, 7),
            (6, 7),
            (7, 6),
            (7, 7),
        ]

        return np.array([block[i, j] for i, j in zigzag_order])

    @staticmethod
    def _zigzag_decode(zigzag: np.ndarray) -> np.ndarray:
        """Inverse zigzag scan."""
        block = np.zeros((8, 8))

        zigzag_order = [
            (0, 0),
            (0, 1),
            (1, 0),
            (2, 0),
            (1, 1),
            (0, 2),
            (0, 3),
            (1, 2),
            (2, 1),
            (3, 0),
            (4, 0),
            (3, 1),
            (2, 2),
            (1, 3),
            (0, 4),
            (0, 5),
            (1, 4),
            (2, 3),
            (3, 2),
            (4, 1),
            (5, 0),
            (6, 0),
            (5, 1),
            (4, 2),
            (3, 3),
            (2, 4),
            (1, 5),
            (0, 6),
            (0, 7),
            (1, 6),
            (2, 5),
            (3, 4),
            (4, 3),
            (5, 2),
            (6, 1),
            (7, 0),
            (7, 1),
            (6, 2),
            (5, 3),
            (4, 4),
            (3, 5),
            (2, 6),
            (1, 7),
            (2, 7),
            (3, 6),
            (4, 5),
            (5, 4),
            (6, 3),
            (7, 2),
            (7, 3),
            (6, 4),
            (5, 5),
            (4, 6),
            (3, 7),
            (4, 7),
            (5, 6),
            (6, 5),
            (7, 4),
            (7, 5),
            (6, 6),
            (5, 7),
            (6, 7),
            (7, 6),
            (7, 7),
        ]

        for idx, (i, j) in enumerate(zigzag_order):
            if idx < len(zigzag):
                block[i, j] = zigzag[idx]

        return block

    @staticmethod
    def _run_length_encode(data: np.ndarray) -> list:
        """Run-length encode array."""
        encoded = []
        current_val = data[0]
        count = 1

        for val in data[1:]:
            if val == current_val and count < 255:
                count += 1
            else:
                encoded.append((current_val, count))
                current_val = val
                count = 1

        encoded.append((current_val, count))
        return encoded

    @staticmethod
    def _run_length_decode(encoded: list, length: int) -> np.ndarray:
        """Run-length decode."""
        decoded = []

        for val, count in encoded:
            decoded.extend([val] * count)

        return np.array(decoded[:length])

    def png_filter_row(self, row: np.ndarray, filter_type: int = 0) -> np.ndarray:
        """Apply PNG filtering to row."""
        filtered = row.copy()

        if filter_type == 0:  # None
            return filtered
        elif filter_type == 1:  # Sub
            for i in range(1, len(row)):
                filtered[i] = np.uint8((int(row[i]) - int(row[i - 1])) & 0xFF)
        elif filter_type == 2:  # Up
            # Requires previous row (simplified)
            filtered = row
        elif filter_type == 3:  # Average
            for i in range(1, len(row)):
                filtered[i] = np.uint8((int(row[i]) - (int(row[i - 1]) // 2)) & 0xFF)
        elif filter_type == 4:  # Paeth
            for i in range(1, len(row)):
                predictor = self._paeth_predictor(int(row[i - 1]), 0, 0)
                filtered[i] = np.uint8((int(row[i]) - predictor) & 0xFF)

        return filtered

    @staticmethod
    def _paeth_predictor(a: int, b: int, c: int) -> int:
        """Paeth predictor for PNG filtering."""
        p = a + b - c
        pa = abs(p - a)
        pb = abs(p - b)
        pc = abs(p - c)

        if pa <= pb and pa <= pc:
            return a
        elif pb <= pc:
            return b
        else:
            return c

    @staticmethod
    def psnr(img1: np.ndarray, img2: np.ndarray) -> float:
        """
        Compute Peak Signal-to-Noise Ratio.

        Args:
            img1, img2: Images with values in [0, 1].

        Returns:
            PSNR in dB.
        """
        mse = np.mean((img1 - img2) ** 2)

        if mse < 1e-10:
            return 100.0

        max_val = 1.0
        return 20 * np.log10(max_val / np.sqrt(mse))

    @staticmethod
    def ssim(img1: np.ndarray, img2: np.ndarray, window_size: int = 11) -> float:
        """
        Compute Structural Similarity Index.

        Args:
            img1, img2: Images with values in [0, 1].
            window_size: Gaussian window size.

        Returns:
            SSIM in [0, 1].
        """
        c1, c2 = 0.01**2, 0.03**2

        # Convert to grayscale if needed and compute in float64 for stability.
        if img1.ndim == 3:
            img1 = np.mean(img1, axis=2)
        if img2.ndim == 3:
            img2 = np.mean(img2, axis=2)

        img1 = img1.astype(np.float64, copy=False)
        img2 = img2.astype(np.float64, copy=False)

        # Approximate an 11x11 Gaussian window when window_size=11.
        sigma = max(window_size / 6.0, 0.5)

        mu1 = gaussian_filter(img1, sigma=sigma)
        mu2 = gaussian_filter(img2, sigma=sigma)

        mu1_sq = mu1 * mu1
        mu2_sq = mu2 * mu2
        mu1_mu2 = mu1 * mu2

        sig1_sq = gaussian_filter(img1 * img1, sigma=sigma) - mu1_sq
        sig2_sq = gaussian_filter(img2 * img2, sigma=sigma) - mu2_sq
        sig12 = gaussian_filter(img1 * img2, sigma=sigma) - mu1_mu2

        num = (2 * mu1_mu2 + c1) * (2 * sig12 + c2)
        denom = (mu1_sq + mu2_sq + c1) * (sig1_sq + sig2_sq + c2)

        ssim_map = num / (denom + 1e-12)
        return float(np.clip(np.mean(ssim_map), 0.0, 1.0))

    @staticmethod
    def ms_ssim(img1: np.ndarray, img2: np.ndarray, scales: int = 5) -> float:
        """
        Compute Multi-Scale SSIM.

        Args:
            img1, img2: Images.
            scales: Number of scales.

        Returns:
            MS-SSIM in [0, 1].
        """
        weights = np.array([0.0448, 0.2856, 0.3001, 0.2363, 0.1333])

        mssim = []
        img1_cur = img1.copy()
        img2_cur = img2.copy()

        for scale in range(scales):
            ssim_val = CompressionCodec.ssim(img1_cur, img2_cur)
            mssim.append(ssim_val ** weights[scale])

            if scale < scales - 1:
                # Downsample
                img1_cur = img1_cur[::2, ::2]
                img2_cur = img2_cur[::2, ::2]

        return np.prod(mssim)
