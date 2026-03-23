"""Tests for image filtering functions."""

import pytest

from thomas.marketplace.cv import core, filters
from thomas.marketplace.cv._exceptions import InvalidParameterError
from thomas.marketplace.cv._types import Kernel


class TestConvolution:
    """Test 2D convolution."""

    def test_convolve_2d_identity(self) -> None:
        """Test convolution with identity kernel."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [100, 100, 100])

        kernel = Kernel([[0, 0, 0], [0, 1, 0], [0, 0, 0]])
        result = filters.convolve_2d(img, kernel)

        assert result.data[50][50][0] == 100

    def test_convolve_2d_box_blur(self) -> None:
        """Test convolution with box blur kernel."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 255, 255])

        kernel_val = 1.0 / 9.0
        kernel = Kernel([[kernel_val] * 3 for _ in range(3)])
        result = filters.convolve_2d(img, kernel)

        assert result.data[50][50][0] > 0

    def test_convolve_2d_invalid_kernel(self) -> None:
        """Test convolution with invalid kernel."""
        img = core.create_image(100, 100, 3)
        kernel = Kernel([])

        with pytest.raises(InvalidParameterError):
            filters.convolve_2d(img, kernel)


class TestGaussianBlur:
    """Test Gaussian blur."""

    def test_gaussian_blur_basic(self) -> None:
        """Test basic Gaussian blur."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 0, 0])

        blurred = filters.gaussian_blur(img, kernel_size=5, sigma=1.0)
        assert blurred.shape == img.shape

    def test_gaussian_blur_even_kernel(self) -> None:
        """Test Gaussian blur with even kernel size."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            filters.gaussian_blur(img, kernel_size=4, sigma=1.0)

    def test_gaussian_blur_zero_sigma(self) -> None:
        """Test Gaussian blur with zero sigma."""
        img = core.create_image(100, 100, 3)

        # Should not raise, but produce different result
        blurred = filters.gaussian_blur(img, kernel_size=5, sigma=0.1)
        assert blurred.shape == img.shape


class TestBoxBlur:
    """Test box blur."""

    def test_box_blur_basic(self) -> None:
        """Test basic box blur."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 0, 0])

        blurred = filters.box_blur(img, kernel_size=5)
        assert blurred.shape == img.shape

    def test_box_blur_even_kernel(self) -> None:
        """Test box blur with even kernel."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            filters.box_blur(img, kernel_size=4)


class TestMedianFilter:
    """Test median filter."""

    def test_median_filter_basic(self) -> None:
        """Test basic median filter."""
        img = core.create_image(100, 100, 1)
        core.set_pixel(img, 50, 50, [255])

        filtered = filters.median_filter(img, kernel_size=5)
        assert filtered.shape == img.shape

    def test_median_filter_noise_removal(self) -> None:
        """Test median filter for noise removal."""
        img = core.create_image(100, 100, 1)
        # Set most pixels to same value
        for y in range(img.height):
            for x in range(img.width):
                core.set_pixel(img, x, y, [128])

        # Add outlier
        core.set_pixel(img, 50, 50, [255])

        filtered = filters.median_filter(img, kernel_size=5)
        # Median should smooth the outlier
        assert filtered.data[50][50][0] < 255


class TestBilateralFilter:
    """Test bilateral filter."""

    def test_bilateral_filter_basic(self) -> None:
        """Test basic bilateral filter."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 0, 0])

        filtered = filters.bilateral_filter(img, diameter=5, sigma_color=50, sigma_space=1.0)
        assert filtered.shape == img.shape

    def test_bilateral_filter_invalid_diameter(self) -> None:
        """Test bilateral filter with invalid diameter."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            filters.bilateral_filter(img, diameter=-1, sigma_color=50, sigma_space=1.0)


class TestSharpening:
    """Test image sharpening."""

    def test_sharpen_basic(self) -> None:
        """Test basic sharpening."""
        img = core.create_image(100, 100, 3)
        sharpened = filters.sharpen(img, amount=1.0)
        assert sharpened.shape == img.shape

    def test_sharpen_invalid_amount(self) -> None:
        """Test sharpening with invalid amount."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            filters.sharpen(img, amount=-1)


class TestSobelEdgeDetection:
    """Test Sobel edge detection."""

    def test_sobel_x(self) -> None:
        """Test Sobel X filter."""
        img = core.create_image(100, 100, 3)
        result = filters.sobel_x(img)
        assert result.shape == img.shape

    def test_sobel_y(self) -> None:
        """Test Sobel Y filter."""
        img = core.create_image(100, 100, 3)
        result = filters.sobel_y(img)
        assert result.shape == img.shape

    def test_sobel_xy(self) -> None:
        """Test Sobel XY combined."""
        img = core.create_image(100, 100, 3)
        gx, gy = filters.sobel_xy(img)
        assert gx.shape == img.shape
        assert gy.shape == img.shape


class TestLaplacian:
    """Test Laplacian edge detection."""

    def test_laplacian(self) -> None:
        """Test Laplacian filter."""
        img = core.create_image(100, 100, 3)
        result = filters.laplacian(img)
        assert result.shape == img.shape

    def test_laplacian_edge_detection(self) -> None:
        """Test Laplacian detects edges."""
        img = core.create_image(100, 100, 1)

        # Create edge: left side black, right side white
        for y in range(100):
            for x in range(50):
                core.set_pixel(img, x, y, [0])
            for x in range(50, 100):
                core.set_pixel(img, x, y, [255])

        result = filters.laplacian(img)
        # Edge should have high response
        assert result.data[50][50][0] != result.data[30][30][0]


class TestCustomKernel:
    """Test custom kernel filtering."""

    def test_custom_kernel_filter(self) -> None:
        """Test custom kernel application."""
        img = core.create_image(100, 100, 3)

        kernel = Kernel([[0, 0, 0], [0, 1, 0], [0, 0, 0]])
        result = filters.custom_kernel_filter(img, kernel)

        assert result.shape == img.shape

    def test_custom_kernel_invalid(self) -> None:
        """Test custom kernel with invalid kernel."""
        img = core.create_image(100, 100, 3)
        kernel = Kernel([])

        with pytest.raises(InvalidParameterError):
            filters.custom_kernel_filter(img, kernel)
