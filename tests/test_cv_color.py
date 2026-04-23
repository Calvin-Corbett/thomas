"""Tests for color space conversions and color processing."""

import pytest

from thomas.marketplace.cv import color, core
from thomas.marketplace.cv._exceptions import InvalidParameterError
from thomas.marketplace.cv._types import ColorSpace


class TestGrayscaleConversion:
    """Test RGB to grayscale conversion."""

    def test_rgb_to_grayscale(self) -> None:
        """Test basic RGB to grayscale conversion."""
        img = core.create_image(100, 100, 3, ColorSpace.RGB)
        gray = color.rgb_to_grayscale(img)

        assert gray.channels == 1
        assert gray.color_space == ColorSpace.GRAYSCALE

    def test_grayscale_red_channel(self) -> None:
        """Test grayscale from pure red."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 0, 0])

        gray = color.rgb_to_grayscale(img)
        # BT.601 weight for red is 0.299
        expected = int(255 * 0.299)
        assert gray.data[50][50][0] == expected

    def test_grayscale_custom_weights(self) -> None:
        """Test grayscale with custom weights."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [100, 100, 100])

        gray = color.rgb_to_grayscale(img, weights=(0.5, 0.3, 0.2))
        assert gray.data[50][50][0] == 100

    def test_grayscale_invalid_weights(self) -> None:
        """Test grayscale with invalid weights."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            color.rgb_to_grayscale(img, weights=(0, 0, 0))


class TestRGBtoHSV:
    """Test RGB to HSV conversion."""

    def test_rgb_to_hsv(self) -> None:
        """Test RGB to HSV conversion."""
        img = core.create_image(100, 100, 3, ColorSpace.RGB)
        hsv = color.rgb_to_hsv(img)

        assert hsv.channels == 3
        assert hsv.color_space == ColorSpace.HSV

    def test_hsv_pure_red(self) -> None:
        """Test HSV of pure red."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 0, 0])

        hsv = color.rgb_to_hsv(img)
        h, s, v = hsv.data[50][50]
        assert h == 0  # Red hue
        assert s == 100  # Full saturation

    def test_hsv_gray(self) -> None:
        """Test HSV of gray."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [128, 128, 128])

        hsv = color.rgb_to_hsv(img)
        h, s, v = hsv.data[50][50]
        assert s == 0  # No saturation


class TestHSVtoRGB:
    """Test HSV to RGB conversion."""

    def test_hsv_to_rgb(self) -> None:
        """Test HSV to RGB conversion."""
        img = core.create_image(100, 100, 3, ColorSpace.HSV)
        rgb = color.hsv_to_rgb(img)

        assert rgb.channels == 3
        assert rgb.color_space == ColorSpace.RGB

    def test_hsv_to_rgb_red(self) -> None:
        """Test HSV to RGB for red."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [0, 100, 100])

        rgb = color.hsv_to_rgb(img)
        r, g, b = rgb.data[50][50]
        assert r == 255  # Red channel


class TestRGBtoHSL:
    """Test RGB to HSL conversion."""

    def test_rgb_to_hsl(self) -> None:
        """Test RGB to HSL conversion."""
        img = core.create_image(100, 100, 3, ColorSpace.RGB)
        hsl = color.rgb_to_hsl(img)

        assert hsl.channels == 3
        assert hsl.color_space == ColorSpace.HSL

    def test_hsl_gray(self) -> None:
        """Test HSL of gray."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [128, 128, 128])

        hsl = color.rgb_to_hsl(img)
        h, s, l = hsl.data[50][50]
        assert s == 0  # No saturation


class TestRGBtoYCbCr:
    """Test RGB to YCbCr conversion."""

    def test_rgb_to_ycbcr(self) -> None:
        """Test RGB to YCbCr conversion."""
        img = core.create_image(100, 100, 3, ColorSpace.RGB)
        ycbcr = color.rgb_to_ycbcr(img)

        assert ycbcr.channels == 3
        assert ycbcr.color_space == ColorSpace.YCbCr

    def test_ycbcr_gray(self) -> None:
        """Test YCbCr of gray."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [128, 128, 128])

        ycbcr = color.rgb_to_ycbcr(img)
        y, cb, cr = ycbcr.data[50][50]
        assert 120 <= y <= 136  # Approximately 128


class TestRGBtoLab:
    """Test RGB to Lab conversion."""

    def test_rgb_to_lab(self) -> None:
        """Test RGB to Lab conversion."""
        img = core.create_image(100, 100, 3, ColorSpace.RGB)
        lab = color.rgb_to_lab(img)

        assert lab.channels == 3
        assert lab.color_space == ColorSpace.Lab

    def test_lab_black(self) -> None:
        """Test Lab of black."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [0, 0, 0])

        lab = color.rgb_to_lab(img)
        l, a, b = lab.data[50][50]
        assert l == 0


class TestHistogram:
    """Test histogram calculation."""

    def test_calculate_histogram(self) -> None:
        """Test basic histogram calculation."""
        img = core.create_image(100, 100, 1)
        hist = color.calculate_histogram(img, channel=0, bins=256)

        assert len(hist.data) == 256
        assert sum(hist.data) == img.width * img.height

    def test_histogram_invalid_channel(self) -> None:
        """Test histogram with invalid channel."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            color.calculate_histogram(img, channel=5)


class TestHistogramEqualization:
    """Test histogram equalization."""

    def test_histogram_equalization(self) -> None:
        """Test basic histogram equalization."""
        img = core.create_image(100, 100, 1)
        # Create image with limited range
        for y in range(100):
            for x in range(100):
                core.set_pixel(img, x, y, [128])

        equalized = color.histogram_equalization(img)
        assert equalized.shape == img.shape


class TestColorQuantization:
    """Test color quantization."""

    def test_color_quantization(self) -> None:
        """Test basic color quantization."""
        img = core.create_image(100, 100, 3)
        quantized = color.color_quantization(img, k=8)

        assert quantized.shape == img.shape

    def test_color_quantization_invalid_k(self) -> None:
        """Test color quantization with invalid k."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            color.color_quantization(img, k=0)

        with pytest.raises(InvalidParameterError):
            color.color_quantization(img, k=500)


class TestWhiteBalance:
    """Test white balance."""

    def test_white_balance_gray_world(self) -> None:
        """Test gray world white balance."""
        img = core.create_image(100, 100, 3)
        balanced = color.white_balance(img, method="gray_world")

        assert balanced.shape == img.shape

    def test_white_balance_invalid_method(self) -> None:
        """Test white balance with invalid method."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            color.white_balance(img, method="unknown")


class TestGammaCorrection:
    """Test gamma correction."""

    def test_gamma_correction(self) -> None:
        """Test basic gamma correction."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [128, 128, 128])

        corrected = color.gamma_correction(img, gamma=2.0)
        assert corrected.shape == img.shape

    def test_gamma_correction_brighten(self) -> None:
        """Test gamma correction brightening."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [128, 128, 128])

        # Gamma < 1 brightens
        corrected = color.gamma_correction(img, gamma=0.5)
        assert corrected.data[50][50][0] > 128

    def test_gamma_correction_invalid(self) -> None:
        """Test gamma correction with invalid gamma."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            color.gamma_correction(img, gamma=-1.0)
