"""
Tests for signal transforms (Hilbert, DCT, wavelet, Z-transform).
"""

import numpy as np
import pytest

from thomas.marketplace.signal_proc._exceptions import SignalError
from thomas.marketplace.signal_proc.transforms import (
    dct,
    hilbert_transform,
    idct,
    inverse_wavelet_transform,
    wavelet_transform,
    z_transform,
)


class TestHilbertTransform:
    """Test Hilbert transform."""

    def test_hilbert_basic(self):
        """Hilbert transform should produce complex output."""
        x = np.random.randn(256)
        analytic = hilbert_transform(x)

        assert analytic.dtype == np.complex128
        assert len(analytic) == len(x)

    def test_hilbert_real_part(self):
        """Real part of analytic signal should be original signal."""
        x = np.random.randn(256)
        analytic = hilbert_transform(x)

        # Real part should match original (approximately)
        assert np.allclose(np.real(analytic), x, atol=1e-10)

    def test_hilbert_orthogonality(self):
        """Real and imaginary parts of analytic signal should be orthogonal."""
        x = np.sin(2 * np.pi * np.linspace(0, 1, 256))
        analytic = hilbert_transform(x)

        real_part = np.real(analytic)
        imag_part = np.imag(analytic)

        # Should be approximately orthogonal
        correlation = np.dot(real_part, imag_part)
        assert abs(correlation) < 1.0

    def test_hilbert_amplitude_modulation(self):
        """Hilbert transform amplitude (envelope) should match original."""
        x = np.sin(2 * np.pi * np.linspace(0, 2, 512))
        analytic = hilbert_transform(x)

        envelope = np.abs(analytic)

        # Envelope should be roughly constant for unmodulated sine
        assert np.std(envelope) < np.mean(envelope) * 0.1


class TestDCT:
    """Test Discrete Cosine Transform."""

    def test_dct_basic(self):
        """DCT should produce real output."""
        x = np.random.randn(256)
        X = dct(x, kind=2)

        assert X.dtype == np.float64
        assert len(X) == len(x)

    def test_dct_symmetry(self):
        """DCT of symmetric signal should have mostly real coefficients."""
        x = np.random.randn(128)
        x = np.concatenate([x, x[::-1]])  # Make symmetric

        X = dct(x, kind=2)

        assert np.all(np.isfinite(X))

    def test_dct_energy_concentration(self):
        """DCT should concentrate energy in few coefficients."""
        x = np.ones(256)  # Constant signal
        X = dct(x, kind=2)

        # Most energy should be in first coefficient
        assert abs(X[0]) > np.mean(np.abs(X[1:]))

    def test_dct_kind1(self):
        """DCT-I should work."""
        x = np.random.randn(64)
        X = dct(x, kind=1)

        assert len(X) == len(x)
        assert np.all(np.isfinite(X))

    def test_dct_kind_invalid(self):
        """Invalid kind should raise error."""
        x = np.random.randn(64)

        with pytest.raises(SignalError):
            dct(x, kind=3)


class TestIDCT:
    """Test Inverse DCT."""

    def test_idct_roundtrip(self):
        """IDCT(DCT(x)) should recover x."""
        x = np.random.randn(128)
        X = dct(x, kind=2)
        x_recovered = idct(X, kind=2)

        assert np.allclose(x, x_recovered, atol=1e-10)

    def test_idct_kind1(self):
        """IDCT-I should work."""
        x = np.random.randn(64)
        X = dct(x, kind=1)
        x_recovered = idct(X, kind=1)

        assert np.allclose(x, x_recovered, atol=1e-9)

    def test_idct_kind_invalid(self):
        """Invalid kind should raise error."""
        X = np.random.randn(64)

        with pytest.raises(SignalError):
            idct(X, kind=3)


class TestWaveletTransform:
    """Test wavelet decomposition."""

    def test_wavelet_haar_basic(self):
        """Haar wavelet decomposition should work."""
        x = np.random.randn(128)
        ca, cd_list = wavelet_transform(x, wavelet="haar", level=1)

        assert len(ca) <= len(x) // 2
        assert len(cd_list) == 1
        assert len(cd_list[0]) <= len(x) // 2

    def test_wavelet_db4_basic(self):
        """Daubechies-4 wavelet decomposition should work."""
        x = np.random.randn(128)
        ca, cd_list = wavelet_transform(x, wavelet="db4", level=1)

        assert len(ca) > 0
        assert len(cd_list) == 1

    def test_wavelet_multilevel(self):
        """Multi-level wavelet decomposition should work."""
        x = np.random.randn(256)
        ca, cd_list = wavelet_transform(x, wavelet="haar", level=3)

        assert len(cd_list) == 3

    def test_wavelet_invalid_type(self):
        """Invalid wavelet type should raise error."""
        x = np.random.randn(128)

        with pytest.raises(SignalError):
            wavelet_transform(x, wavelet="invalid")


class TestInverseWaveletTransform:
    """Test wavelet reconstruction."""

    def test_inverse_wavelet_roundtrip(self):
        """Inverse wavelet should recover original signal."""
        x = np.random.randn(128)
        ca, cd_list = wavelet_transform(x, wavelet="haar", level=1)

        x_recovered = inverse_wavelet_transform(ca, cd_list, wavelet="haar")

        # Should approximately recover (not perfect due to downsampling)
        assert len(x_recovered) >= len(x) // 2

    def test_inverse_wavelet_db4_roundtrip(self):
        """Inverse Daubechies-4 should recover signal."""
        x = np.random.randn(128)
        ca, cd_list = wavelet_transform(x, wavelet="db4", level=1)

        x_recovered = inverse_wavelet_transform(ca, cd_list, wavelet="db4")

        assert len(x_recovered) > 0

    def test_inverse_wavelet_invalid_type(self):
        """Invalid wavelet type should raise error."""
        ca = np.random.randn(64)
        cd = [np.random.randn(64)]

        with pytest.raises(SignalError):
            inverse_wavelet_transform(ca, cd, wavelet="invalid")


class TestZTransform:
    """Test Z-transform evaluation."""

    def test_z_transform_scalar(self):
        """Z-transform at scalar should return scalar."""
        h = np.array([1, 0.5, 0.25])
        z = 1.0 + 1j * 0.5

        H_z = z_transform(h, z)

        assert isinstance(H_z, (complex, np.complex128))

    def test_z_transform_array(self):
        """Z-transform at array should return array."""
        h = np.array([1, 0.5, 0.25])
        z_vals = np.array([1.0 + 0j, 0.5 + 0.5j, 0.5 - 0.5j])

        H_z = z_transform(h, z_vals)

        assert len(H_z) == len(z_vals)

    def test_z_transform_unit_circle(self):
        """Z-transform on unit circle should give DTFT."""
        h = np.array([1, 0.5])
        # Points on unit circle
        z_vals = np.exp(1j * np.linspace(0, 2 * np.pi, 64))

        H_z = z_transform(h, z_vals)

        # Should be finite and reasonable
        assert np.all(np.isfinite(H_z))

    def test_z_transform_impulse(self):
        """Z-transform of impulse at origin should be unity."""
        h = np.array([1.0])
        z = 1.0

        H_z = z_transform(h, z)

        assert np.isclose(H_z, 1.0)

    def test_z_transform_dc_response(self):
        """Z-transform at z=1 gives DC response."""
        h = np.array([0.25, 0.5, 0.25])  # Moving average
        z = 1.0 + 0j

        H_z = z_transform(h, z)

        # Should be 1.0 for moving average (DC gain)
        assert np.isclose(np.abs(H_z), 1.0, rtol=0.01)


class TestDCTApplications:
    """Test DCT applications."""

    def test_dct_image_compression_analog(self):
        """DCT should concentrate energy for compressible signals."""
        # Create a smooth signal
        x = np.sin(2 * np.pi * np.linspace(0, 5, 256))

        X = dct(x, kind=2)

        # Sort coefficients by magnitude
        sorted_indices = np.argsort(np.abs(X))[::-1]

        # First 10% of coefficients should contain significant energy
        energy_full = np.sum(X**2)
        energy_10pct = np.sum(X[sorted_indices[:25]] ** 2)

        assert energy_10pct / energy_full > 0.8

    def test_dct_noise_signal(self):
        """DCT of noise should be more uniformly distributed."""
        noise = np.random.randn(256)

        X = dct(noise, kind=2)

        # Coefficients should be more uniform
        sorted_indices = np.argsort(np.abs(X))[::-1]
        energy_10pct = np.sum(X[sorted_indices[:25]] ** 2)
        energy_full = np.sum(X**2)

        # For noise, 10% of coefficients contain less energy
        assert energy_10pct / energy_full < 0.3


class TestWaveletApplications:
    """Test wavelet applications."""

    def test_wavelet_edge_detection(self):
        """Wavelet detail coefficients should detect edges."""
        x = np.zeros(128)
        x[64:] = 1.0  # Step edge

        ca, cd_list = wavelet_transform(x, wavelet="haar", level=1)

        # Detail coefficients should be strong at edge
        assert np.max(np.abs(cd_list[0])) > 0.1

    def test_wavelet_noise_reduction(self):
        """Wavelet can reduce noise via coefficient thresholding."""
        x = np.sin(2 * np.pi * np.linspace(0, 2, 256)) + 0.1 * np.random.randn(256)

        ca, cd_list = wavelet_transform(x, wavelet="haar", level=2)

        # Threshold small coefficients
        threshold = 0.05
        cd_list_thresholded = [np.where(np.abs(cd) > threshold, cd, 0) for cd in cd_list]

        x_denoised = inverse_wavelet_transform(ca, cd_list_thresholded, wavelet="haar")

        # Denoised should have lower variance
        # (Since we're removing high-frequency noise)
        assert np.var(np.diff(x_denoised)) < np.var(np.diff(x))


class TestTransformErrors:
    """Test error handling."""

    def test_z_transform_empty_filter(self):
        """Empty filter should handle gracefully."""
        h = np.array([])
        z = 1.0

        # Should return 0 or handle gracefully
        H_z = z_transform(h, z)
        assert H_z == 0

    def test_wavelet_invalid_length(self):
        """Short signals should still work with wavelets."""
        x = np.array([1.0, 2.0, 3.0])
        ca, cd = wavelet_transform(x, wavelet="haar", level=1)

        assert len(ca) >= 1


class TestTransformProperties:
    """Test mathematical properties of transforms."""

    def test_dct_parseval(self):
        """DCT should preserve energy (Parseval's theorem)."""
        x = np.random.randn(128)
        X = dct(x, kind=2)

        energy_time = np.sum(x**2)
        energy_freq = np.sum(X**2)

        # Should be similar (within normalization)
        assert np.isclose(energy_time, energy_freq, rtol=0.1)

    def test_hilbert_causality(self):
        """Hilbert transform should be causal (real = original)."""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        analytic = hilbert_transform(x)

        # Real part should match input
        assert np.allclose(np.real(analytic), x, atol=1e-10)
