"""Tests for image segmentation algorithms."""

import pytest

from thomas.cv import core, segmentation
from thomas.cv._exceptions import InvalidParameterError


class TestOtsuThreshold:
    """Test Otsu's thresholding."""

    def test_otsu_basic(self) -> None:
        """Test basic Otsu threshold calculation."""
        img = core.create_image(100, 100, 1)

        # Create bimodal distribution
        for y in range(100):
            for x in range(50):
                core.set_pixel(img, x, y, [50])
            for x in range(50, 100):
                core.set_pixel(img, x, y, [200])

        threshold = segmentation.otsu_threshold(img)
        assert 0 < threshold < 256
        assert 50 < threshold < 200

    def test_otsu_uniform_image(self) -> None:
        """Test Otsu on uniform image."""
        img = core.create_image(100, 100, 1)
        threshold = segmentation.otsu_threshold(img)
        assert 0 <= threshold < 256


class TestBinaryThreshold:
    """Test binary thresholding."""

    def test_binary_threshold(self) -> None:
        """Test basic binary thresholding."""
        img = core.create_image(100, 100, 1)
        core.set_pixel(img, 25, 25, [100])
        core.set_pixel(img, 75, 75, [200])

        binary = segmentation.binary_threshold(img, threshold=150)
        assert binary.data[25][25][0] == 0
        assert binary.data[75][75][0] == 255

    def test_binary_threshold_output_range(self) -> None:
        """Test binary threshold output is 0 or 255."""
        img = core.create_image(100, 100, 1)
        binary = segmentation.binary_threshold(img, threshold=128)

        for y in range(100):
            for x in range(100):
                assert binary.data[y][x][0] in (0, 255)


class TestAdaptiveThreshold:
    """Test adaptive thresholding."""

    def test_adaptive_threshold_mean(self) -> None:
        """Test adaptive threshold with mean method."""
        img = core.create_image(100, 100, 1)
        result = segmentation.adaptive_threshold(img, block_size=11, method="mean")

        assert result.shape == img.shape

    def test_adaptive_threshold_gaussian(self) -> None:
        """Test adaptive threshold with Gaussian method."""
        img = core.create_image(100, 100, 1)
        result = segmentation.adaptive_threshold(img, block_size=11, method="gaussian")

        assert result.shape == img.shape

    def test_adaptive_threshold_even_block(self) -> None:
        """Test adaptive threshold with even block size."""
        img = core.create_image(100, 100, 1)

        with pytest.raises(InvalidParameterError):
            segmentation.adaptive_threshold(img, block_size=10)

    def test_adaptive_threshold_invalid_method(self) -> None:
        """Test adaptive threshold with invalid method."""
        img = core.create_image(100, 100, 1)

        with pytest.raises(InvalidParameterError):
            segmentation.adaptive_threshold(img, method="unknown")


class TestKMeansClustering:
    """Test k-means color clustering."""

    def test_kmeans_basic(self) -> None:
        """Test basic k-means clustering."""
        img = core.create_image(100, 100, 3)

        # Create two color regions
        for y in range(100):
            for x in range(50):
                core.set_pixel(img, x, y, [255, 0, 0])
            for x in range(50, 100):
                core.set_pixel(img, x, y, [0, 0, 255])

        segmented = segmentation.kmeans_color_clustering(img, k=2)
        assert segmented.shape == img.shape

    def test_kmeans_invalid_k(self) -> None:
        """Test k-means with invalid k."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            segmentation.kmeans_color_clustering(img, k=0)


class TestRegionGrowing:
    """Test region growing."""

    def test_region_growing_basic(self) -> None:
        """Test basic region growing."""
        img = core.create_image(100, 100, 1)

        # Create white region
        for y in range(30, 70):
            for x in range(30, 70):
                core.set_pixel(img, x, y, [255])

        mask = segmentation.region_growing(img, seed_x=50, seed_y=50, threshold=30)
        assert mask.shape[0] == img.height
        assert mask.shape[1] == img.width

    def test_region_growing_out_of_bounds(self) -> None:
        """Test region growing with out of bounds seed."""
        img = core.create_image(100, 100, 1)

        with pytest.raises(IndexError):
            segmentation.region_growing(img, seed_x=200, seed_y=200)


class TestWatershedTransform:
    """Test watershed transform."""

    def test_watershed_basic(self) -> None:
        """Test basic watershed transform."""
        img = core.create_image(100, 100, 1)
        result = segmentation.watershed_transform(img)

        assert result.shape[0] == img.height
        assert result.shape[1] == img.width

    def test_watershed_multiple_minima(self) -> None:
        """Test watershed with multiple minima."""
        img = core.create_image(200, 200, 1)

        # Create multiple local minima
        for y in range(50, 150):
            for x in range(50, 150):
                core.set_pixel(img, x, y, [200])

        core.set_pixel(img, 75, 75, [50])
        core.set_pixel(img, 125, 125, [50])

        result = segmentation.watershed_transform(img)
        assert result.shape == img.shape


class TestGrabCutExtraction:
    """Test GrabCut foreground extraction."""

    def test_grabcut_basic(self) -> None:
        """Test basic GrabCut extraction."""
        img = core.create_image(100, 100, 3)

        # Create foreground object
        for y in range(30, 70):
            for x in range(30, 70):
                core.set_pixel(img, x, y, [255, 0, 0])

        mask = segmentation.grabcut_foreground_extraction(img, 30, 30, 40, 40)
        assert mask.shape[0] == img.height
        assert mask.shape[1] == img.width

    def test_grabcut_invalid_bbox(self) -> None:
        """Test GrabCut with invalid bounding box."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            segmentation.grabcut_foreground_extraction(img, -1, 0, 50, 50)

    def test_grabcut_output_binary(self) -> None:
        """Test GrabCut output is binary."""
        img = core.create_image(100, 100, 3)
        mask = segmentation.grabcut_foreground_extraction(img, 10, 10, 80, 80)

        for y in range(mask.height):
            for x in range(mask.width):
                assert mask.data[y][x][0] in (0, 255)
