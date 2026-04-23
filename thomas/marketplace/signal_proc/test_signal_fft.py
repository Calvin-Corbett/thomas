"""
Tests for FFT implementation and frequency-domain operations.
"""

import numpy as np
import pytest

from thomas.marketplace.signal_proc._exceptions import FFTError
from thomas.marketplace.signal_proc.fft import (
    dft,
    fft,
    fft_shift,
    frequency_bins,
    idft,
    ifft,
    magnitude_spectrum,
    phase_spectrum,
    power_spectrum,
    real_fft,
    verify_parseval,
    zero_pad_to_power2,
)


class TestFFTBasics:
    """Test basic FFT functionality."""

    def test_fft_simple_sine(self):
        """FFT of sine wave should have peak at the frequency."""
        fs = 1000  # Sample rate
        f = 10  # Signal frequency
        duration = 1.0
        t = np.arange(int(fs * duration)) / fs
        x = np.sin(2 * np.pi * f * t)

        X = fft(x)
        mag = magnitude_spectrum(X)
        freqs = frequency_bins(len(x), fs)

        # Find peak
        peak_idx = np.argmax(mag)
        detected_freq = freqs[peak_idx]

        # Should be close to actual frequency
        assert abs(detected_freq - f) < 2  # Within 2 Hz

    def test_fft_zero_input(self):
        """FFT of zeros should be zero."""
        x = np.zeros(128)
        X = fft(x)
        assert np.allclose(X, 0, atol=1e-10)

    def test_fft_impulse(self):
        """FFT of impulse should be flat (all frequencies equal)."""
        x = np.zeros(128)
        x[0] = 1.0

        X = fft(x)
        mag = magnitude_spectrum(X)

        # All frequencies should have roughly equal magnitude
        assert np.std(mag) < np.mean(mag) * 0.1

    def test_fft_linearity(self):
        """FFT should be linear: FFT(a*x + b*y) = a*FFT(x) + b*FFT(y)."""
        x = np.random.randn(256)
        y = np.random.randn(256)
        a, b = 2.5, 3.7

        X = fft(x)
        Y = fft(y)
        combined = fft(a * x + b * y)

        expected = a * X + b * Y

        assert np.allclose(combined, expected, rtol=1e-10)

    def test_fft_symmetry(self):
        """FFT of real signal should have conjugate symmetry."""
        x = np.random.randn(128)
        X = fft(x)

        # Check conjugate symmetry (ignoring DC and Nyquist for simplicity)
        for k in range(1, len(X) // 2):
            assert np.allclose(X[k], np.conj(X[-k]), atol=1e-10)

    def test_fft_power_of_2(self):
        """FFT should work correctly with power-of-2 lengths."""
        for n in [32, 64, 128, 256, 512, 1024]:
            x = np.random.randn(n)
            X = fft(x)
            assert len(X) >= n

    def test_fft_non_power_of_2(self):
        """FFT should auto-pad non-power-of-2 inputs."""
        x = np.random.randn(100)
        X = fft(x)
        # Should be padded to next power of 2 (128)
        assert len(X) >= 128


class TestIFFT:
    """Test inverse FFT."""

    def test_ifft_roundtrip_sine(self):
        """IFFT(FFT(x)) should recover original signal (up to padding)."""
        fs = 1000
        f = 25
        duration = 1.0
        t = np.arange(int(fs * duration)) / fs
        x = np.sin(2 * np.pi * f * t)

        X = fft(x)
        x_recovered = ifft(X)

        # Recover original length
        x_recovered = x_recovered[: len(x)]

        assert np.allclose(x, np.real(x_recovered), atol=1e-10)

    def test_ifft_orthogonality(self):
        """Test IFFT orthogonality property."""
        x = np.random.randn(128)
        X = fft(x)
        x_recovered = ifft(X)

        assert np.allclose(x, np.real(x_recovered), atol=1e-10)

    def test_ifft_energy(self):
        """Energy should be preserved through FFT/IFFT."""
        x = np.random.randn(256)
        X = fft(x)
        x_recovered = ifft(X)

        energy_original = np.sum(x**2)
        energy_recovered = np.sum(np.real(x_recovered) ** 2)

        assert np.isclose(energy_original, energy_recovered, rtol=1e-10)


class TestDFT:
    """Test naive DFT implementation."""

    def test_dft_matches_fft(self):
        """DFT should match FFT (for small signals)."""
        x = np.random.randn(16)
        X_dft = dft(x)
        X_fft = fft(x)[: len(x)]  # Trim to original length

        assert np.allclose(X_dft, X_fft, atol=1e-10)

    def test_idft_roundtrip(self):
        """IDFT(DFT(x)) should recover x."""
        x = np.random.randn(32)
        X = dft(x)
        x_recovered = idft(X)

        assert np.allclose(x, x_recovered, atol=1e-10)

    def test_dft_complexity(self):
        """DFT should be O(N^2) (slow for large N)."""
        import time

        x = np.random.randn(64)
        start = time.time()
        dft(x)
        dft_time = time.time() - start

        x = np.random.randn(128)
        start = time.time()
        dft(x)
        dft_time_2x = time.time() - start

        # 2x size should be roughly 4x slower
        assert dft_time_2x > dft_time


class TestRealFFT:
    """Test real-valued FFT optimization."""

    def test_real_fft_output_size(self):
        """Real FFT should return N/2+1 values."""
        n = 256
        x = np.random.randn(n)
        X_real, orig_len = real_fft(x)

        assert len(X_real) == n // 2 + 1
        assert orig_len == n

    def test_real_fft_vs_complex_fft(self):
        """Real FFT should match complex FFT (positive frequencies)."""
        x = np.random.randn(128)
        X_complex = fft(x)
        X_real, _ = real_fft(x)

        n_pos = len(x) // 2 + 1
        assert np.allclose(X_real, X_complex[:n_pos], atol=1e-10)


class TestSpectra:
    """Test magnitude, phase, and power spectrum computation."""

    def test_magnitude_spectrum(self):
        """Magnitude spectrum should be non-negative."""
        x = np.random.randn(256)
        X = fft(x)
        mag = magnitude_spectrum(X)

        assert np.all(mag >= 0)

    def test_phase_spectrum(self):
        """Phase spectrum should be in [-pi, pi]."""
        x = np.random.randn(256)
        X = fft(x)
        phase = phase_spectrum(X)

        assert np.all(phase >= -np.pi - 1e-10)
        assert np.all(phase <= np.pi + 1e-10)

    def test_power_spectrum(self):
        """Power spectrum should be magnitude squared."""
        x = np.random.randn(256)
        X = fft(x)
        power = power_spectrum(X)
        mag = magnitude_spectrum(X)

        assert np.allclose(power, mag**2, atol=1e-10)

    def test_magnitude_phase_reconstruction(self):
        """Magnitude and phase should reconstruct complex spectrum."""
        x = np.random.randn(128)
        X = fft(x)

        mag = magnitude_spectrum(X)
        phase = phase_spectrum(X)

        X_reconstructed = mag * np.exp(1j * phase)

        assert np.allclose(X, X_reconstructed, atol=1e-10)


class TestFrequencyBins:
    """Test frequency bin calculation."""

    def test_frequency_bins_nyquist(self):
        """Frequency bins should not exceed Nyquist."""
        fs = 1000
        n = 512

        freqs = frequency_bins(n, fs)

        nyquist = fs / 2
        assert np.all(freqs <= nyquist + 1e-10)

    def test_frequency_bins_spacing(self):
        """Frequency bin spacing should be fs/n."""
        fs = 1000
        n = 1024

        freqs = frequency_bins(n, fs)
        spacing = np.diff(freqs)

        expected_spacing = fs / n
        assert np.allclose(spacing[1:], expected_spacing, atol=1e-10)

    def test_frequency_bins_positive(self):
        """Positive-only frequency bins should not include negative frequencies."""
        fs = 1000
        n = 256

        freqs_pos = frequency_bins(n, fs, positive_only=True)
        freqs_full = frequency_bins(n, fs, positive_only=False)

        assert np.all(freqs_pos >= 0)
        assert len(freqs_pos) == n // 2 + 1

    def test_frequency_bins_dc(self):
        """First bin should be DC (0 Hz)."""
        fs = 1000
        n = 512

        freqs = frequency_bins(n, fs)

        assert freqs[0] == 0.0


class TestFFTShift:
    """Test FFT shift operation."""

    def test_fft_shift_centers_dc(self):
        """FFT shift should move DC component to center."""
        x = np.random.randn(256)
        X = fft(x)
        X_shifted = fft_shift(X)

        # DC component was at index 0, should now be near center
        center = len(X_shifted) // 2
        assert X_shifted[center] == X[0]

    def test_fft_shift_invertible(self):
        """FFT shift should be invertible."""
        from thomas.marketplace.signal_proc.fft import ifft_shift

        x = np.random.randn(256)
        X = fft(x)

        X_shifted = fft_shift(X)
        X_unshifted = ifft_shift(X_shifted)

        assert np.allclose(X, X_unshifted, atol=1e-10)


class TestZeroPadding:
    """Test zero-padding utilities."""

    def test_zero_pad_to_power2(self):
        """Should pad to next power of 2."""
        test_cases = [
            (100, 128),
            (256, 256),
            (257, 512),
            (1, 1),
            (1000, 1024),
        ]

        for n, expected_len in test_cases:
            x = np.random.randn(n)
            x_pad, orig_len = zero_pad_to_power2(x)

            assert len(x_pad) == expected_len
            assert orig_len == n
            assert np.allclose(x_pad[:n], x)
            assert np.allclose(x_pad[n:], 0)


class TestParseval:
    """Test Parseval's theorem verification."""

    def test_parseval_energy_conservation(self):
        """Energy should be conserved between time and frequency domains."""
        x = np.random.randn(256)
        X = fft(x)

        energy_time, energy_freq = verify_parseval(x, X)

        assert np.isclose(energy_time, energy_freq, rtol=1e-10)

    def test_parseval_sine_wave(self):
        """Sine wave energy should match FFT energy."""
        fs = 1000
        f = 50
        duration = 1.0
        t = np.arange(int(fs * duration)) / fs
        amplitude = 2.0
        x = amplitude * np.sin(2 * np.pi * f * t)

        X = fft(x)
        energy_time, energy_freq = verify_parseval(x, X)

        # For sine: energy = (A^2 / 2) * N
        expected = (amplitude**2 / 2) * len(x)

        assert np.isclose(energy_time, expected, rtol=0.01)
        assert np.isclose(energy_freq, expected, rtol=0.01)


class TestFFTErrors:
    """Test error handling."""

    def test_empty_input_error(self):
        """Empty input should raise error."""
        with pytest.raises(FFTError):
            fft(np.array([]))

    def test_complex_input_handling(self):
        """FFT should handle complex input."""
        x = np.random.randn(128) + 1j * np.random.randn(128)
        X = fft(x)

        assert len(X) >= len(x)
        assert X.dtype == np.complex128


class TestNumericalStability:
    """Test numerical stability of FFT."""

    def test_very_small_values(self):
        """FFT should handle very small values."""
        x = 1e-100 * np.random.randn(256)
        X = fft(x)

        X_expected = fft(x / 1e-100) * 1e-100
        assert np.allclose(X, X_expected, rtol=1e-5)

    def test_very_large_values(self):
        """FFT should handle very large values."""
        x = 1e100 * np.random.randn(256)
        X = fft(x)

        X_expected = fft(x / 1e100) * 1e100
        assert np.allclose(X, X_expected, rtol=1e-5)
