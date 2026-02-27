"""Tests for core image manipulation functions."""

import pytest

from thomas.cv import core
from thomas.cv._exceptions import InvalidImageError, InvalidParameterError
from thomas.cv._types import ColorSpace


class TestImageCreation:
    """Test image creation and basic operations."""

    def test_create_image(self) -> None:
        """Test basic image creation."""
        img = core.create_image(100, 100, 3, ColorSpace.RGB)
        assert img.width == 100
        assert img.height == 100
        assert img.channels == 3
        assert img.size == 10000

    def test_create_image_invalid_dimensions(self) -> None:
        """Test creation with invalid dimensions."""
        with pytest.raises(InvalidParameterError):
            core.create_image(-1, 100, 3)

        with pytest.raises(InvalidParameterError):
            core.create_image(100, 0, 3)

    def test_clone_image(self) -> None:
        """Test image cloning."""
        img1 = core.create_image(50, 50, 3)
        core.set_pixel(img1, 10, 10, [255, 0, 0])

        img2 = core.clone_image(img1)
        assert img2.shape == img1.shape
        assert img2.data[10][10] == [255, 0, 0]

        # Verify deep copy
        core.set_pixel(img2, 10, 10, [0, 255, 0])
        assert img1.data[10][10] == [255, 0, 0]


class TestPixelOperations:
    """Test pixel access and manipulation."""

    def test_get_pixel(self) -> None:
        """Test getting pixel values."""
        img = core.create_image(100, 100, 3)
        pixel = core.get_pixel(img, 50, 50)
        assert pixel == [0, 0, 0]

    def test_set_pixel(self) -> None:
        """Test setting pixel values."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 128, 64])
        pixel = core.get_pixel(img, 50, 50)
        assert pixel == [255, 128, 64]

    def test_pixel_out_of_bounds(self) -> None:
        """Test out of bounds access."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(IndexError):
            core.get_pixel(img, 200, 200)

        with pytest.raises(IndexError):
            core.set_pixel(img, -1, 0, [0, 0, 0])


class TestImageCropping:
    """Test image cropping."""

    def test_crop_image(self) -> None:
        """Test basic cropping."""
        img = core.create_image(100, 100, 3)
        cropped = core.crop_image(img, 10, 10, 50, 50)

        assert cropped.width == 50
        assert cropped.height == 50

    def test_crop_invalid_region(self) -> None:
        """Test cropping with invalid region."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            core.crop_image(img, 10, 10, 200, 50)


class TestResizing:
    """Test image resizing."""

    def test_resize_nearest_neighbor(self) -> None:
        """Test nearest neighbor resizing."""
        img = core.create_image(100, 100, 3)
        resized = core.resize_image(img, 50, 50, method="nearest")

        assert resized.width == 50
        assert resized.height == 50

    def test_resize_bilinear(self) -> None:
        """Test bilinear resizing."""
        img = core.create_image(100, 100, 3)
        resized = core.resize_image(img, 200, 200, method="bilinear")

        assert resized.width == 200
        assert resized.height == 200

    def test_resize_invalid_dimensions(self) -> None:
        """Test resize with invalid dimensions."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            core.resize_image(img, 0, 100)

    def test_resize_invalid_method(self) -> None:
        """Test resize with invalid method."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            core.resize_image(img, 50, 50, method="unknown")


class TestRotation:
    """Test image rotation."""

    def test_rotate_image(self) -> None:
        """Test image rotation."""
        img = core.create_image(100, 100, 3)
        rotated = core.rotate_image(img, 45)

        assert rotated.channels == img.channels
        assert rotated.width > 0
        assert rotated.height > 0

    def test_rotate_zero_degrees(self) -> None:
        """Test rotation by zero degrees."""
        img = core.create_image(100, 100, 3)
        rotated = core.rotate_image(img, 0)

        assert rotated.width == img.width
        assert rotated.height == img.height


class TestFlipping:
    """Test image flipping."""

    def test_flip_horizontal(self) -> None:
        """Test horizontal flip."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 0, 0, [255, 0, 0])

        flipped = core.flip_image(img, horizontal=True)
        pixel = core.get_pixel(flipped, 99, 0)
        assert pixel == [255, 0, 0]

    def test_flip_vertical(self) -> None:
        """Test vertical flip."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 0, 0, [255, 0, 0])

        flipped = core.flip_image(img, vertical=True)
        pixel = core.get_pixel(flipped, 0, 99)
        assert pixel == [255, 0, 0]

    def test_flip_both(self) -> None:
        """Test flipping both directions."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 0, 0, [255, 0, 0])

        flipped = core.flip_image(img, horizontal=True, vertical=True)
        pixel = core.get_pixel(flipped, 99, 99)
        assert pixel == [255, 0, 0]


class TestChannelOperations:
    """Test channel manipulation."""

    def test_split_channels(self) -> None:
        """Test splitting channels."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 128, 64])

        channels = core.split_channels(img)
        assert len(channels) == 3
        assert channels[0].channels == 1
        assert channels[0].data[50][50][0] == 255

    def test_merge_channels(self) -> None:
        """Test merging channels."""
        ch1 = core.create_image(100, 100, 1)
        ch2 = core.create_image(100, 100, 1)
        ch3 = core.create_image(100, 100, 1)

        core.set_pixel(ch1, 50, 50, [255])
        core.set_pixel(ch2, 50, 50, [128])
        core.set_pixel(ch3, 50, 50, [64])

        merged = core.merge_channels([ch1, ch2, ch3])
        assert merged.channels == 3
        assert merged.data[50][50] == [255, 128, 64]

    def test_merge_mismatched_dimensions(self) -> None:
        """Test merge with mismatched dimensions."""
        ch1 = core.create_image(100, 100, 1)
        ch2 = core.create_image(50, 50, 1)

        with pytest.raises(InvalidImageError):
            core.merge_channels([ch1, ch2])


class TestDataTypeConversion:
    """Test data type conversion."""

    def test_uint8_to_float32(self) -> None:
        """Test uint8 to float32 conversion."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 50, 50, [255, 128, 64])

        converted = core.convert_dtype(img, "float32")
        assert converted.dtype == "float32"
        assert abs(converted.data[50][50][0] - 1.0) < 0.01
        assert abs(converted.data[50][50][1] - 0.502) < 0.01

    def test_float32_to_uint8(self) -> None:
        """Test float32 to uint8 conversion."""
        img = core.create_image(100, 100, 3)
        img.dtype = "float32"
        core.set_pixel(img, 50, 50, [1.0, 0.5, 0.25])

        converted = core.convert_dtype(img, "uint8")
        assert converted.dtype == "uint8"
        assert converted.data[50][50][0] == 255
        assert converted.data[50][50][1] == 127


class TestPadding:
    """Test image padding."""

    def test_pad_zero_mode(self) -> None:
        """Test zero padding."""
        img = core.create_image(100, 100, 3)
        padded = core.pad_image(img, 10, 10, 10, 10, mode="zero")

        assert padded.width == 120
        assert padded.height == 120
        assert padded.data[0][0][0] == 0

    def test_pad_replicate_mode(self) -> None:
        """Test replicate padding."""
        img = core.create_image(100, 100, 3)
        core.set_pixel(img, 0, 0, [255, 0, 0])

        padded = core.pad_image(img, 5, 5, 5, 5, mode="replicate")
        assert padded.data[0][0][0] == 255

    def test_pad_invalid_values(self) -> None:
        """Test padding with invalid values."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            core.pad_image(img, -1, 10, 10, 10)


class TestBlending:
    """Test image blending."""

    def test_blend_images_50_50(self) -> None:
        """Test 50-50 blend."""
        img1 = core.create_image(100, 100, 3)
        img2 = core.create_image(100, 100, 3)

        core.set_pixel(img1, 50, 50, [255, 0, 0])
        core.set_pixel(img2, 50, 50, [0, 0, 255])

        blended = core.blend_images(img1, img2, 0.5)
        pixel = core.get_pixel(blended, 50, 50)
        assert pixel[0] == 127 or pixel[0] == 128
        assert pixel[2] == 127 or pixel[2] == 128

    def test_blend_invalid_alpha(self) -> None:
        """Test blend with invalid alpha."""
        img1 = core.create_image(100, 100, 3)
        img2 = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            core.blend_images(img1, img2, 1.5)

    def test_blend_mismatched_dimensions(self) -> None:
        """Test blend with mismatched dimensions."""
        img1 = core.create_image(100, 100, 3)
        img2 = core.create_image(50, 50, 3)

        with pytest.raises(InvalidImageError):
            core.blend_images(img1, img2, 0.5)
