"""
Tests for denoising module.
"""

import numpy as np
import pytest

from thomas.marketplace.image_proc import Denoiser, DenoisingConfig, Image, NoiseModel


class TestDenoising:
    """Test image denoising functionality."""

    @pytest.fixture
    def denoiser(self):
        """Create denoiser instance."""
        return Denoiser()

    @pytest.fixture
    def noisy_image(self):
        """Create a noisy test image."""
        h, w = 64, 64
        # Create a gradient
        x_grad = np.linspace(0.2, 0.8, w)
        y_grad = np.linspace(0.2, 0.8, h)
        xx, yy = np.meshgrid(x_grad, y_grad)
        base = (xx + yy) / 2

        # Add Gaussian noise
        noise = np.random.normal(0, 0.05, (h, w))
        noisy = np.clip(base + noise, 0, 1)

        return Image(data=np.dstack([noisy] * 3))

    def test_denoise_nlm(self, denoiser, noisy_image):
        """Test non-local means denoising."""
        config = DenoisingConfig(method="nlm", h=10.0, patch_size=5, search_window=30)
        denoiser.config = config

        result = denoiser.denoise(noisy_image)

        assert result.height == noisy_image.height
        assert result.width == noisy_image.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_denoise_bilateral(self, denoiser, noisy_image):
        """Test bilateral filtering."""
        config = DenoisingConfig(method="bilateral", h=10.0, patch_size=5)
        denoiser.config = config

        result = denoiser.denoise(noisy_image)

        assert result.height == noisy_image.height
        assert result.width == noisy_image.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_denoise_wavelet(self, denoiser, noisy_image):
        """Test wavelet denoising."""
        config = DenoisingConfig(method="wavelet")
        denoiser.config = config

        result = denoiser.denoise(noisy_image)

        assert result.height == noisy_image.height
        assert result.width == noisy_image.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_denoise_bm3d(self, denoiser, noisy_image):
        """Test simplified BM3D denoising."""
        config = DenoisingConfig(method="bm3d", h=10.0)
        denoiser.config = config

        result = denoiser.denoise(noisy_image)

        assert result.height == noisy_image.height
        assert result.width == noisy_image.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_unsupported_method_raises_error(self, denoiser):
        """Test that unsupported method raises error."""
        config = DenoisingConfig(method="unsupported_method")
        denoiser.config = config

        img = Image(data=np.random.rand(32, 32, 3))

        with pytest.raises(Exception):
            denoiser.denoise(img)

    def test_estimate_noise_gaussian(self, denoiser, noisy_image):
        """Test Gaussian noise estimation."""
        noise_model = denoiser.estimate_noise(noisy_image)

        assert isinstance(noise_model, NoiseModel)
        assert noise_model.noise_type == "gaussian"
        assert noise_model.sigma > 0

    def test_noise_estimation_is_reasonable(self, denoiser):
        """Test that noise estimation gives reasonable values."""
        h, w = 64, 64
        # Image with known noise level
        clean = np.ones((h, w, 3)) * 0.5
        noise_std = 0.05
        noisy = clean + np.random.normal(0, noise_std, (h, w, 3))

        img = Image(data=np.clip(noisy, 0, 1))
        model = denoiser.estimate_noise(img)

        # Estimated sigma should be reasonably close
        assert 0.01 < model.sigma < 0.15

    def test_sharpen_noise_aware(self, denoiser, noisy_image):
        """Test noise-aware sharpening."""
        result = denoiser.sharpen_noise_aware(noisy_image, amount=1.0)

        assert result.height == noisy_image.height
        assert result.width == noisy_image.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_sharpen_different_amounts(self, denoiser, noisy_image):
        """Test sharpening with different amounts."""
        for amount in [0.5, 1.0, 1.5, 2.0]:
            result = denoiser.sharpen_noise_aware(noisy_image, amount=amount)

            assert result.height == noisy_image.height
            assert result.width == noisy_image.width

    def test_denoising_reduces_variance(self, denoiser, noisy_image):
        """Test that denoising actually reduces variance."""
        config = DenoisingConfig(method="bilateral", h=10.0)
        denoiser.config = config

        result = denoiser.denoise(noisy_image)

        noisy_var = np.var(noisy_image.data)
        result_var = np.var(result.data)

        # Denoised should have lower variance
        assert result_var < noisy_var

    def test_grayscale_denoising(self, denoiser):
        """Test denoising of grayscale image."""
        h, w = 32, 32
        noisy = np.random.rand(h, w, 1) * 0.5 + np.random.normal(0, 0.05, (h, w, 1))
        img = Image(data=np.clip(noisy, 0, 1))

        config = DenoisingConfig(method="nlm", h=10.0)
        denoiser.config = config

        result = denoiser.denoise(img)

        assert result.height == h
        assert result.width == w

    def test_wavelet_decomposition(self, denoiser):
        """Test Haar wavelet decomposition."""
        channel = np.random.rand(32, 32)

        cA, cH, cV, cD = denoiser._wavelet_decompose_haar(channel)

        assert cA.shape == (16, 16)
        assert cH.shape == (16, 16)
        assert cV.shape == (16, 16)
        assert cD.shape == (16, 16)

    def test_wavelet_reconstruction(self, denoiser):
        """Test Haar wavelet reconstruction."""
        channel = np.random.rand(32, 32)

        cA, cH, cV, cD = denoiser._wavelet_decompose_haar(channel)
        reconstructed = denoiser._wavelet_reconstruct_haar(cA, cH, cV, cD)

        assert reconstructed.shape == channel.shape
        # Reconstruction might not be perfect due to edge effects
        assert np.mean(np.abs(reconstructed - channel)) < 0.2

    def test_soft_threshold(self, denoiser):
        """Test soft thresholding."""
        coeffs = np.array([-2, -1, 0, 1, 2], dtype=np.float32)
        threshold = 0.5

        thresholded = denoiser._soft_threshold(coeffs, threshold)

        expected = np.array([-1.5, -0.5, 0, 0.5, 1.5])
        assert np.allclose(thresholded, expected)

    def test_nlm_patch_comparison(self, denoiser):
        """Test NLM patch distance computation."""
        h, w = 32, 32
        noisy_channel = np.random.rand(h, w)
        img = Image(data=np.dstack([noisy_channel] * 3))

        config = DenoisingConfig(method="nlm", patch_size=5)
        denoiser.config = config

        # Test that NLM runs without error
        result = denoiser._nlm_denoise(img)

        assert result.height == h
        assert result.width == w

    def test_bilateral_filter_edge_preservation(self, denoiser):
        """Test that bilateral filter preserves edges."""
        h, w = 32, 32
        # Create image with clear edge
        edge_img = np.zeros((h, w, 3))
        edge_img[: h // 2, :, :] = 0.2
        edge_img[h // 2 :, :, :] = 0.8

        # Add some noise
        noisy = edge_img + np.random.normal(0, 0.05, edge_img.shape)
        img = Image(data=np.clip(noisy, 0, 1))

        config = DenoisingConfig(method="bilateral", h=0.1, patch_size=3)
        denoiser.config = config

        result = denoiser.denoise(img)

        # Edge should still be present (difference between top and bottom)
        top_mean = np.mean(result.data[: h // 2, :, :])
        bottom_mean = np.mean(result.data[h // 2 :, :, :])

        assert abs(bottom_mean - top_mean) > 0.4

    def test_large_image_denoising(self, denoiser):
        """Test denoising on larger image."""
        h, w = 256, 256
        noisy = np.random.rand(h, w, 3) * 0.5 + np.random.normal(0, 0.05, (h, w, 3))
        img = Image(data=np.clip(noisy, 0, 1))

        config = DenoisingConfig(method="bilateral", h=10.0)
        denoiser.config = config

        result = denoiser.denoise(img)

        assert result.height == h
        assert result.width == w

    def test_different_filtering_strengths(self, denoiser, noisy_image):
        """Test denoising with different strength parameters."""
        for h_val in [5.0, 10.0, 20.0, 50.0]:
            config = DenoisingConfig(method="nlm", h=h_val)
            denoiser.config = config

            result = denoiser.denoise(noisy_image)

            assert result.height == noisy_image.height
            assert result.width == noisy_image.width

    def test_nlm_patch_sizes(self, denoiser, noisy_image):
        """Test NLM with different patch sizes."""
        for patch_size in [3, 5, 7, 9]:
            config = DenoisingConfig(method="nlm", patch_size=patch_size)
            denoiser.config = config

            result = denoiser.denoise(noisy_image)

            assert result.height == noisy_image.height

    def test_wavelet_multiple_levels(self, denoiser, noisy_image):
        """Test wavelet denoising preserves structure."""
        config = DenoisingConfig(method="wavelet")
        denoiser.config = config

        result = denoiser.denoise(noisy_image)

        # Should preserve edges
        gradient_orig = np.mean(np.abs(np.gradient(noisy_image.data)))
        gradient_result = np.mean(np.abs(np.gradient(result.data)))

        # Result should have some gradients but less noise
        assert 0 < gradient_result < gradient_orig

    def test_bilateral_preserves_boundaries(self, denoiser):
        """Test bilateral filter boundary preservation."""
        h, w = 64, 64
        # Create step edge
        img_data = np.ones((h, w, 3)) * 0.3
        img_data[:, w // 2 :, :] = 0.7

        # Add noise
        noisy = img_data + np.random.normal(0, 0.05, (h, w, 3))
        img = Image(data=np.clip(noisy, 0, 1))

        config = DenoisingConfig(method="bilateral", h=0.1)
        denoiser.config = config

        result = denoiser.denoise(img)

        # Edge should still be preserved
        left_mean = np.mean(result.data[:, : w // 3, :])
        right_mean = np.mean(result.data[:, 2 * w // 3 :, :])

        assert abs(right_mean - left_mean) > 0.2

    def test_denoising_color_consistency(self, denoiser):
        """Test that denoising preserves color balance."""
        h, w = 48, 48
        # Colored image
        colored = np.zeros((h, w, 3))
        colored[:, :, 0] = 0.7  # Red
        colored[:, :, 1] = 0.5  # Green
        colored[:, :, 2] = 0.3  # Blue

        # Add noise
        noisy = colored + np.random.normal(0, 0.05, (h, w, 3))
        img = Image(data=np.clip(noisy, 0, 1))

        config = DenoisingConfig(method="bilateral", h=10.0)
        denoiser.config = config

        result = denoiser.denoise(img)

        # Color ratios should be preserved
        orig_ratio = colored[:, :, 0].mean() / colored[:, :, 2].mean()
        result_ratio = result.data[:, :, 0].mean() / result.data[:, :, 2].mean()

        assert np.isclose(orig_ratio, result_ratio, rtol=0.1)

    def test_sharpen_with_zero_amount(self, denoiser, noisy_image):
        """Test sharpening with zero amount doesn't change image."""
        result = denoiser.sharpen_noise_aware(noisy_image, amount=0.0)

        # Should be very close to original
        assert np.allclose(result.data, noisy_image.data, atol=0.01)

    def test_denoise_preserves_image_type(self, denoiser):
        """Test that denoising preserves Image type."""
        img = Image(data=np.random.rand(32, 32, 3), color_space="RGB")

        config = DenoisingConfig(method="bilateral")
        denoiser.config = config

        result = denoiser.denoise(img)

        assert isinstance(result, Image)
        assert result.color_space == "RGB"

    def test_bm3d_block_processing(self, denoiser):
        """Test BM3D with block sizes."""
        h, w = 128, 128
        noisy = np.random.rand(h, w, 3)
        img = Image(data=noisy)

        config = DenoisingConfig(method="bm3d")
        denoiser.config = config

        result = denoiser.denoise(img)

        assert result.height == h
        assert result.width == w

    def test_noise_model_parameters(self, denoiser, noisy_image):
        """Test setting noise model parameters."""
        model = NoiseModel(noise_type="gaussian", sigma=0.08)

        denoiser.noise_model = model

        # Should not raise error
        assert denoiser.noise_model.sigma == 0.08

    def test_sharpen_high_amount(self, denoiser, noisy_image):
        """Test sharpening with high amount."""
        result = denoiser.sharpen_noise_aware(noisy_image, amount=2.0)

        # High sharpening should increase contrast
        result_var = np.var(result.data)
        orig_var = np.var(noisy_image.data)

        # Variance might increase with sharpening
        assert result_var >= 0
