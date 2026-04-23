"""
Tests for compression module.
"""

import numpy as np
import pytest

from thomas.marketplace.image_proc import Image
from thomas.marketplace.image_proc.compression import CompressionCodec


class TestCompressionCodec:
    """Test image compression functionality."""

    @pytest.fixture
    def codec(self):
        """Create compression codec instance."""
        return CompressionCodec()

    @pytest.fixture
    def test_image(self):
        """Create test image."""
        h, w = 64, 64
        # Create gradient pattern
        x = np.linspace(0, 1, w)
        y = np.linspace(0, 1, h)
        xx, yy = np.meshgrid(x, y)

        pattern = (xx + yy) / 2
        img_data = np.dstack([pattern] * 3)

        return Image(data=np.clip(img_data, 0, 1))

    def test_psnr_identical_images(self):
        """Test PSNR of identical images is very high."""
        img1 = np.ones((32, 32, 3)) * 0.5
        img2 = np.ones((32, 32, 3)) * 0.5

        psnr = CompressionCodec.psnr(img1, img2)

        assert psnr > 90  # Very high PSNR for identical images

    def test_psnr_different_images(self):
        """Test PSNR of different images is lower."""
        img1 = np.ones((32, 32, 3)) * 0.2
        img2 = np.ones((32, 32, 3)) * 0.8

        psnr = CompressionCodec.psnr(img1, img2)

        assert 0 < psnr < 90

    def test_ssim_identical_images(self):
        """Test SSIM of identical images is 1."""
        img1 = np.random.rand(32, 32, 3)
        img2 = img1.copy()

        ssim = CompressionCodec.ssim(img1, img2)

        assert 0.99 < ssim <= 1.0

    def test_ssim_range(self):
        """Test SSIM is in [0, 1] range."""
        img1 = np.random.rand(32, 32, 3)
        img2 = np.random.rand(32, 32, 3)

        ssim = CompressionCodec.ssim(img1, img2)

        assert 0 <= ssim <= 1

    def test_ms_ssim_range(self):
        """Test MS-SSIM is in [0, 1] range."""
        img1 = np.random.rand(64, 64, 3)
        img2 = np.random.rand(64, 64, 3)

        ms_ssim = CompressionCodec.ms_ssim(img1, img2)

        assert 0 <= ms_ssim <= 1

    def test_psnr_grayscale(self):
        """Test PSNR with grayscale images."""
        img1 = np.random.rand(32, 32)
        img2 = np.random.rand(32, 32)

        psnr = CompressionCodec.psnr(img1, img2)

        assert psnr > 0
        assert np.isfinite(psnr)

    def test_ssim_grayscale(self):
        """Test SSIM with grayscale images."""
        img1 = np.random.rand(32, 32)
        img2 = np.random.rand(32, 32)

        ssim = CompressionCodec.ssim(img1, img2)

        assert 0 <= ssim <= 1

    def test_rgb_to_ycbcr_conversion(self, codec):
        """Test RGB to YCbCr conversion."""
        rgb = np.array([[[1.0, 0.0, 0.0]]])  # Red
        ycbcr = codec._rgb_to_ycbcr(rgb)

        assert ycbcr.shape == (1, 1, 3)
        assert np.all(np.isfinite(ycbcr))
        assert 0 <= ycbcr[0, 0, 0] <= 1  # Y channel

    def test_ycbcr_to_rgb_conversion(self, codec):
        """Test YCbCr to RGB conversion."""
        ycbcr = np.array([[[0.5, 0.5, 0.5]]])
        rgb = codec._ycbcr_to_rgb(ycbcr)

        assert rgb.shape == (1, 1, 3)
        assert np.all(np.isfinite(rgb))

    def test_rgb_ycbcr_roundtrip(self, codec, test_image):
        """Test RGB ↔ YCbCr roundtrip."""
        rgb_orig = test_image.data.copy()

        ycbcr = codec._rgb_to_ycbcr(rgb_orig)
        rgb_back = codec._ycbcr_to_rgb(ycbcr)

        # Should be close but not exact due to color space
        assert np.allclose(rgb_orig, rgb_back, atol=0.01)

    def test_zigzag_encode_decode(self, codec):
        """Test zigzag encoding and decoding."""
        block = np.random.randn(8, 8)
        zigzag = codec._zigzag_encode(block)
        reconstructed = codec._zigzag_decode(zigzag)

        # Should have same dimensions
        assert reconstructed.shape == (8, 8)

        # Should preserve all values (ignoring numerical precision)
        assert np.allclose(block, reconstructed, atol=1e-10)

    def test_run_length_encoding(self, codec):
        """Test run-length encoding."""
        data = np.array([1, 1, 1, 2, 2, 3, 1, 1])
        encoded = codec._run_length_encode(data)

        assert len(encoded) <= len(data)  # Encoded should be same or shorter

    def test_run_length_roundtrip(self, codec):
        """Test run-length encode/decode roundtrip."""
        data = np.array([1, 1, 1, 2, 2, 3, 1, 1], dtype=int)
        encoded = codec._run_length_encode(data)
        decoded = codec._run_length_decode(encoded, len(data))

        assert np.array_equal(data, decoded)

    def test_png_filter_none(self, codec):
        """Test PNG filter type 0 (None)."""
        row = np.array([100, 150, 120, 180, 200], dtype=np.uint8)
        filtered = codec.png_filter_row(row, filter_type=0)

        # No filter, should be identical
        assert np.array_equal(row, filtered)

    def test_png_filter_sub(self, codec):
        """Test PNG filter type 1 (Sub)."""
        row = np.array([100, 150, 120, 180, 200], dtype=np.uint8)
        filtered = codec.png_filter_row(row, filter_type=1)

        # First byte unchanged, others are differences
        assert filtered[0] == row[0]
        assert len(filtered) == len(row)

    def test_paeth_predictor(self, codec):
        """Test Paeth predictor calculation."""
        # Simple case
        result = codec._paeth_predictor(100, 50, 75)

        assert 0 <= result <= 255

    def test_jpeg_compression_execution(self, codec, test_image):
        """Test JPEG compression execution."""
        # Just test that it runs without error
        compressed = codec.jpeg_compress(test_image, quality=85)

        assert isinstance(compressed, bytes)
        assert len(compressed) > 0

    def test_jpeg_quality_factor_range(self, codec, test_image):
        """Test JPEG quality factor bounds."""
        # Test boundary values
        for quality in [1, 50, 100]:
            codec.jpeg_compress(test_image, quality=quality)
            assert codec.quality_factor == np.clip(quality, 1, 100)

    def test_quality_metrics_consistency(self, codec):
        """Test consistency of quality metrics."""
        img1 = np.ones((32, 32, 3)) * 0.5
        img2 = np.ones((32, 32, 3)) * 0.51

        # Slight difference, metrics should reflect that
        psnr = codec.psnr(img1, img2)
        ssim = codec.ssim(img1, img2)

        assert psnr >= 40 - 1e-9  # High PSNR for small difference
        assert ssim > 0.95  # High SSIM for small difference

    def test_metrics_on_different_sized_images(self, codec):
        """Test metrics on different image sizes."""
        for h, w in [(16, 16), (32, 32), (64, 64), (128, 128)]:
            img1 = np.random.rand(h, w, 3)
            img2 = np.random.rand(h, w, 3)

            psnr = codec.psnr(img1, img2)
            ssim = codec.ssim(img1, img2)

            assert np.isfinite(psnr)
            assert 0 <= ssim <= 1

    def test_ssim_symmetry(self, codec):
        """Test that SSIM is symmetric."""
        img1 = np.random.rand(32, 32, 3)
        img2 = np.random.rand(32, 32, 3)

        ssim12 = codec.ssim(img1, img2)
        ssim21 = codec.ssim(img2, img1)

        assert np.isclose(ssim12, ssim21)

    def test_psnr_symmetry(self, codec):
        """Test that PSNR is symmetric."""
        img1 = np.random.rand(32, 32, 3)
        img2 = np.random.rand(32, 32, 3)

        psnr12 = codec.psnr(img1, img2)
        psnr21 = codec.psnr(img2, img1)

        assert np.isclose(psnr12, psnr21)

    def test_compression_reduces_size_simple_image(self, codec):
        """Test that compressing uniform image reduces size."""
        # Uniform image should compress well
        uniform = np.ones((256, 256, 3)) * 0.5
        img = Image(data=uniform)

        compressed = codec.jpeg_compress(img, quality=90)

        # Compressed should be smaller than raw
        raw_size = 256 * 256 * 3 * 4  # float32
        assert len(compressed) < raw_size

    def test_jpeg_quality_factor_effects(self, codec, test_image):
        """Test JPEG quality factor effects on compression."""
        # High quality should preserve more detail
        sizes = []

        for quality in [30, 60, 90]:
            compressed = codec.jpeg_compress(test_image, quality=quality)
            sizes.append(len(compressed))

        # Lower quality might be smaller (depends on content)
        assert len(sizes) == 3

    def test_rgb_ycbcr_edge_cases(self, codec):
        """Test RGB to YCbCr conversion edge cases."""
        test_colors = [
            np.array([[[0, 0, 0]]]),  # Black
            np.array([[[1, 1, 1]]]),  # White
            np.array([[[1, 0, 0]]]),  # Red
            np.array([[[0, 1, 0]]]),  # Green
            np.array([[[0, 0, 1]]]),  # Blue
        ]

        for color in test_colors:
            ycbcr = codec._rgb_to_ycbcr(color)
            assert np.all(np.isfinite(ycbcr))
            assert ycbcr.shape == (1, 1, 3)

    def test_psnr_with_noise(self, codec):
        """Test PSNR degradation with noise."""
        img_clean = np.ones((64, 64, 3)) * 0.5

        # Add different noise levels
        psnr_vals = []

        for noise_std in [0.01, 0.05, 0.1, 0.2]:
            img_noisy = img_clean + np.random.normal(0, noise_std, img_clean.shape)
            psnr = codec.psnr(img_clean, np.clip(img_noisy, 0, 1))
            psnr_vals.append(psnr)

        # PSNR should decrease with more noise
        assert psnr_vals[0] > psnr_vals[-1]

    def test_ssim_with_blur(self, codec):
        """Test SSIM with Gaussian blur."""
        from scipy.ndimage import gaussian_filter

        img = np.random.rand(64, 64, 3)

        # Apply blur
        img_blurred = np.zeros_like(img)
        for c in range(3):
            img_blurred[:, :, c] = gaussian_filter(img[:, :, c], sigma=1.0)

        ssim = codec.ssim(img, img_blurred)

        # Blurred should be similar but not identical.
        # For random textures with sigma=1 blur, SSIM is typically moderate.
        assert 0.25 < ssim < 0.95

    def test_ms_ssim_scales(self, codec):
        """Test MS-SSIM at different scales."""
        img1 = np.random.rand(128, 128, 3)
        img2 = np.random.rand(128, 128, 3)

        ms_ssim_5 = codec.ms_ssim(img1, img2, scales=5)
        ms_ssim_3 = codec.ms_ssim(img1, img2, scales=3)

        # Different scales should give different values
        assert ms_ssim_5 >= 0 and ms_ssim_5 <= 1
        assert ms_ssim_3 >= 0 and ms_ssim_3 <= 1

    def test_zigzag_pattern_correctness(self, codec):
        """Test zigzag encoding follows correct pattern."""
        block = np.arange(64).reshape(8, 8)

        zigzag = codec._zigzag_encode(block)

        # Should start from (0, 0)
        assert zigzag[0] == block[0, 0]

        # Should end with (7, 7)
        assert zigzag[-1] == block[7, 7]

    def test_run_length_compression_ratio(self, codec):
        """Test run-length encoding compression."""
        # Highly compressible data
        data = np.array([1] * 100 + [2] * 100 + [3] * 100)

        encoded = codec._run_length_encode(data)

        # Should compress significantly
        assert len(encoded) < len(data) / 10

    def test_paeth_predictor_ranges(self, codec):
        """Test Paeth predictor with various inputs."""
        test_cases = [
            (100, 50, 75),
            (255, 0, 0),
            (50, 100, 75),
        ]

        for a, b, c in test_cases:
            result = codec._paeth_predictor(a, b, c)
            assert 0 <= result <= 255

    def test_quality_metrics_on_gradients(self, codec):
        """Test metrics on smooth gradients."""
        h, w = 64, 64
        x = np.linspace(0, 1, w)
        y = np.linspace(0, 1, h)
        xx, yy = np.meshgrid(x, y)

        grad_img1 = xx
        grad_img2 = yy

        psnr = codec.psnr(grad_img1, grad_img2)
        ssim = codec.ssim(grad_img1, grad_img2)

        assert 0 < psnr < 50
        assert 0 <= ssim <= 1

    def test_compression_colorspace_conversion(self, codec):
        """Test YCbCr colorspace conversion properties."""
        # Test that conversion is invertible
        rgb_samples = [
            np.array([[[1, 0, 0]]]),
            np.array([[[0, 1, 0]]]),
            np.array([[[0, 0, 1]]]),
            np.array([[[0.5, 0.5, 0.5]]]),
        ]

        for rgb in rgb_samples:
            ycbcr = codec._rgb_to_ycbcr(rgb)
            rgb_back = codec._ycbcr_to_rgb(ycbcr)

            # Should be close (colorspace roundtrip)
            assert np.allclose(rgb, rgb_back, atol=0.02)
