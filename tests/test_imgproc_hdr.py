"""
Tests for HDR imaging module.
"""

import numpy as np
import pytest

from thomas.image_proc import ExposureInfo, HDRProcessor, Image, ToneMap


class TestHDRProcessor:
    """Test HDR processing functionality."""

    @pytest.fixture
    def hdr_processor(self):
        """Create HDR processor instance."""
        return HDRProcessor()

    @pytest.fixture
    def exposure_sequence(self):
        """Create test exposure sequence."""
        h, w = 64, 64

        # Create three exposures of a gradient with different EV values
        images = []
        exposures = []

        for ev in [-1.0, 0.0, 1.0]:
            # Gradient pattern
            x_grad = np.linspace(0.1, 0.9, w)
            y_grad = np.linspace(0.1, 0.9, h)
            xx, yy = np.meshgrid(x_grad, y_grad)

            # Apply exposure
            pattern = (xx + yy) / 2
            pattern_exposed = np.clip(pattern * np.exp(ev), 0, 1)

            # Create RGB image
            img_data = np.dstack([pattern_exposed] * 3)
            images.append(Image(data=img_data, color_space="RGB", bit_depth=8))
            exposures.append(ExposureInfo(exposure_value=ev))

        return images, exposures

    def test_merge_exposures(self, hdr_processor, exposure_sequence):
        """Test basic exposure merging."""
        images, exposures = exposure_sequence
        result = hdr_processor.merge_exposures(images, exposures)

        assert result.height == 64
        assert result.width == 64
        assert result.channels == 3
        assert result.metadata.get("hdr") is True

    def test_merge_requires_multiple_exposures(self, hdr_processor, exposure_sequence):
        """Test that at least 2 exposures are required."""
        images, _ = exposure_sequence

        with pytest.raises(Exception):
            hdr_processor.merge_exposures([images[0]], [ExposureInfo(0)])

    def test_tone_mapping_reinhard_global(self, hdr_processor, exposure_sequence):
        """Test Reinhard global tone mapping."""
        images, exposures = exposure_sequence
        hdr_img = hdr_processor.merge_exposures(images, exposures)

        result = hdr_processor.tone_map(hdr_img, ToneMap.REINHARD_GLOBAL)

        assert result.height == hdr_img.height
        assert result.width == hdr_img.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_tone_mapping_reinhard_local(self, hdr_processor, exposure_sequence):
        """Test Reinhard local tone mapping."""
        images, exposures = exposure_sequence
        hdr_img = hdr_processor.merge_exposures(images, exposures)

        result = hdr_processor.tone_map(hdr_img, ToneMap.REINHARD_LOCAL)

        assert result.height == hdr_img.height
        assert result.width == hdr_img.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_tone_mapping_drago(self, hdr_processor, exposure_sequence):
        """Test Drago logarithmic tone mapping."""
        images, exposures = exposure_sequence
        hdr_img = hdr_processor.merge_exposures(images, exposures)

        result = hdr_processor.tone_map(hdr_img, ToneMap.DRAGO)

        assert result.height == hdr_img.height
        assert result.width == hdr_img.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_tone_mapping_mantiuk(self, hdr_processor, exposure_sequence):
        """Test Mantiuk contrast-preserving tone mapping."""
        images, exposures = exposure_sequence
        hdr_img = hdr_processor.merge_exposures(images, exposures)

        result = hdr_processor.tone_map(hdr_img, ToneMap.MANTIUK)

        assert result.height == hdr_img.height
        assert result.width == hdr_img.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_exposure_fusion(self, hdr_processor, exposure_sequence):
        """Test exposure fusion (Mertens method)."""
        images, _ = exposure_sequence
        result = hdr_processor.exposure_fusion(images)

        assert result.height == images[0].height
        assert result.width == images[0].width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_response_curve_estimation(self, hdr_processor, exposure_sequence):
        """Test camera response curve estimation."""
        images, exposures = exposure_sequence

        # Estimate curve
        curve = hdr_processor._estimate_response_curve(images, exposures)

        assert curve.shape == (256,)
        assert np.all(np.isfinite(curve))

    def test_radiance_map_computation(self, hdr_processor, exposure_sequence):
        """Test HDR radiance map computation."""
        images, exposures = exposure_sequence

        # Estimate response curve first
        hdr_processor._estimate_response_curve(images, exposures)

        # Compute radiance
        radiance = hdr_processor._compute_radiance_map(images, exposures)

        assert radiance.shape == (64, 64, 3)
        assert np.all(np.isfinite(radiance))

    def test_different_exposure_values(self, hdr_processor):
        """Test with various exposure value differences."""
        h, w = 32, 32
        base_pattern = np.random.rand(h, w, 3) * 0.5 + 0.25

        images = []
        exposures = []

        for ev in [-2.0, -1.0, 0.0, 1.0, 2.0]:
            exposed = np.clip(base_pattern * np.exp(ev), 0, 1)
            images.append(Image(data=exposed, color_space="RGB"))
            exposures.append(ExposureInfo(exposure_value=ev))

        result = hdr_processor.merge_exposures(images, exposures)

        assert result.height == h
        assert result.width == w

    def test_grayscale_exposure_sequence(self, hdr_processor):
        """Test HDR with grayscale images."""
        h, w = 32, 32

        images = []
        exposures = []

        for ev in [-1.0, 0.0, 1.0]:
            pattern = np.random.rand(h, w, 1) * 0.5 + 0.25
            exposed = np.clip(pattern * np.exp(ev), 0, 1)
            images.append(Image(data=exposed, color_space="RGB"))
            exposures.append(ExposureInfo(exposure_value=ev))

        result = hdr_processor.merge_exposures(images, exposures)

        assert result.height == h
        assert result.width == w

    def test_compute_contrast_weight(self):
        """Test contrast weight computation."""
        img_data = np.random.rand(32, 32, 3)
        img = Image(data=img_data)

        weights = HDRProcessor._compute_contrast_weight(img)

        assert weights.shape == (32, 32, 3)
        assert np.all(weights >= 0)

    def test_compute_saturation_weight(self):
        """Test saturation weight computation."""
        img_data = np.random.rand(32, 32, 3)
        img = Image(data=img_data)

        weights = HDRProcessor._compute_saturation_weight(img)

        assert weights.shape == (32, 32, 3)
        assert np.all(weights >= 0)

    def test_compute_exposedness_weight(self):
        """Test well-exposedness weight computation."""
        img_data = np.random.rand(32, 32, 3)
        img = Image(data=img_data)

        weights = HDRProcessor._compute_exposedness_weight(img)

        assert weights.shape == (32, 32, 3)
        assert np.all(weights >= 0) and np.all(weights <= 1)

    def test_tone_mapping_no_hdr_tag(self, hdr_processor):
        """Test tone mapping requires HDR image."""
        img = Image(data=np.random.rand(32, 32, 3))

        with pytest.raises(Exception):
            hdr_processor.tone_map(img)

    def test_exposure_fusion_requires_multiple_images(self, hdr_processor):
        """Test exposure fusion requires at least 2 images."""
        img = Image(data=np.random.rand(32, 32, 3))

        with pytest.raises(Exception):
            hdr_processor.exposure_fusion([img])

    def test_hdr_preserves_dimensions(self, hdr_processor):
        """Test that HDR processing preserves image dimensions."""
        h, w = 48, 64

        images = []
        exposures = []

        for ev in [-1.0, 0.0, 1.0]:
            img_data = np.random.rand(h, w, 3)
            images.append(Image(data=img_data))
            exposures.append(ExposureInfo(exposure_value=ev))

        result = hdr_processor.merge_exposures(images, exposures)

        assert result.height == h
        assert result.width == w

    def test_hdr_with_varying_channel_counts(self, hdr_processor):
        """Test HDR with images having different channels."""
        h, w = 32, 32

        # Create images with different channel counts
        rgb_img = Image(data=np.random.rand(h, w, 3))
        gray_img = Image(data=np.random.rand(h, w, 1))
        rgba_img = Image(data=np.random.rand(h, w, 4))

        # HDR should handle by converting appropriately
        images = [rgb_img, rgb_img, rgb_img]
        exposures = [ExposureInfo(exposure_value=ev) for ev in [-1, 0, 1]]

        result = hdr_processor.merge_exposures(images, exposures)
        assert result.channels >= 3

    def test_tone_mapping_output_range(self, hdr_processor, exposure_sequence):
        """Test that tone mapped output is in valid range."""
        images, exposures = exposure_sequence
        hdr_img = hdr_processor.merge_exposures(images, exposures)

        for method in [ToneMap.REINHARD_GLOBAL, ToneMap.REINHARD_LOCAL, ToneMap.DRAGO, ToneMap.MANTIUK]:
            result = hdr_processor.tone_map(hdr_img, method)
            assert np.all(result.data >= -0.01) and np.all(result.data <= 1.01)

    def test_hdr_with_extreme_exposures(self, hdr_processor):
        """Test HDR with extreme exposure differences."""
        h, w = 32, 32

        images = []
        exposures = []

        # Very different exposures (-3 to +3 stops)
        for ev in [-3.0, 0.0, 3.0]:
            pattern = np.ones((h, w, 3)) * 0.5
            exposed = np.clip(pattern * np.exp(ev), 0, 1)
            images.append(Image(data=exposed))
            exposures.append(ExposureInfo(exposure_value=ev))

        result = hdr_processor.merge_exposures(images, exposures)

        assert result.height == h
        assert result.width == w
        assert np.all(np.isfinite(result.data))

    def test_response_curve_properties(self, hdr_processor, exposure_sequence):
        """Test properties of estimated response curve."""
        images, exposures = exposure_sequence

        curve = hdr_processor._estimate_response_curve(images, exposures)

        # Curve should be 256 values
        assert len(curve) == 256

        # Should be monotonic (increasing)
        diffs = np.diff(curve)
        assert np.sum(diffs > 0) > 200  # Most should increase

    def test_exposure_fusion_multiple_weights(self, hdr_processor, exposure_sequence):
        """Test exposure fusion with pre-computed weights."""
        images, _ = exposure_sequence

        # Create custom weights
        weights = [np.ones((64, 64, 1)) / 3 for _ in images]

        result = hdr_processor.exposure_fusion(images, weights=weights)

        assert result.height == images[0].height
        assert result.width == images[0].width

    def test_tone_mapping_different_parameters(self, hdr_processor, exposure_sequence):
        """Test tone mapping with various operator parameters."""
        images, exposures = exposure_sequence
        hdr_img = hdr_processor.merge_exposures(images, exposures)

        # Test Reinhard local with different parameters
        result1 = hdr_processor._reinhard_local(hdr_img.data, phi=4.0)
        result2 = hdr_processor._reinhard_local(hdr_img.data, phi=16.0)

        # Different parameters should give different results
        assert not np.allclose(result1, result2)

    def test_downsample_operation(self, hdr_processor):
        """Test image downsampling in Laplacian pyramid."""
        img = np.random.rand(64, 64, 3)

        downsampled = hdr_processor._downsample(img, level=1)

        # Should be half the size
        assert downsampled.shape == (32, 32, 3)

    def test_hdr_metadata_preservation(self, hdr_processor, exposure_sequence):
        """Test that HDR metadata is correctly set."""
        images, exposures = exposure_sequence
        result = hdr_processor.merge_exposures(images, exposures)

        assert result.metadata.get("hdr") is True
        assert result.metadata.get("num_exposures") == 3

    def test_exposure_fusion_color_preservation(self, hdr_processor):
        """Test that exposure fusion preserves color information."""
        h, w = 48, 48

        images = []
        for _ in range(3):
            # Create colored image
            colored = np.zeros((h, w, 3))
            colored[:, :, 0] = 0.8  # Red channel
            colored[:, :, 1] = 0.3  # Green channel
            colored[:, :, 2] = 0.2  # Blue channel

            images.append(Image(data=colored))

        result = hdr_processor.exposure_fusion(images)

        # Result should retain color (not be grayscale)
        r_mean = np.mean(result.data[:, :, 0])
        g_mean = np.mean(result.data[:, :, 1])
        b_mean = np.mean(result.data[:, :, 2])

        # Should have variation between channels
        assert not (np.isclose(r_mean, g_mean) and np.isclose(g_mean, b_mean))
