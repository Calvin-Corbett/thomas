"""
Tests for spectral analysis (STFT, Welch PSD, spectral features).
"""

import numpy as np
import pytest

from thomas.marketplace.signal_proc._exceptions import SignalError
from thomas.marketplace.signal_proc._types import Signal
from thomas.marketplace.signal_proc.spectral import (
    cepstrum,
    hz_to_mel,
    mel_spectrogram,
    mel_to_hz,
    spectral_bandwidth,
    spectral_centroid,
    spectral_flatness,
    spectral_rolloff,
    spectrogram,
    stft,
    welch_psd,
)


class TestSTFT:
    """Test Short-Time Fourier Transform."""

    def test_stft_basic(self):
        """STFT should produce spectrogram."""
        fs = 1000
        duration = 1.0
        t = np.arange(int(fs * duration)) / fs
        x = np.sin(2 * np.pi * 50 * t)

        spec = stft(x, window_size=512, hop_size=256, sample_rate=fs)

        assert spec.magnitude.shape[0] > 0  # Time frames
        assert spec.magnitude.shape[1] == 512 // 2 + 1  # Frequency bins
        assert len(spec.time_frames) == spec.magnitude.shape[0]
        assert len(spec.frequencies) == spec.magnitude.shape[1]

    def test_stft_from_signal_object(self):
        """STFT should work with Signal objects."""
        signal = Signal(
            samples=np.random.randn(2000),
            sample_rate=1000,
        )

        spec = stft(signal, window_size=512)

        assert spec.magnitude.shape[0] > 0

    def test_stft_time_resolution(self):
        """STFT time resolution should match hop size."""
        fs = 1000
        duration = 2.0
        x = np.random.randn(int(fs * duration))

        hop_size = 256
        spec = stft(x, window_size=512, hop_size=hop_size, sample_rate=fs)

        # Time between frames should be hop_size / fs
        if len(spec.time_frames) > 1:
            time_diff = np.diff(spec.time_frames)
            expected_diff = hop_size / fs
            assert np.allclose(time_diff, expected_diff, rtol=0.01)

    def test_stft_frequency_resolution(self):
        """STFT frequency resolution should match window size."""
        fs = 1000
        x = np.random.randn(1000)

        window_size = 512
        spec = stft(x, window_size=window_size, sample_rate=fs)

        # Frequency spacing should be fs / window_size
        expected_spacing = fs / window_size
        actual_spacing = spec.frequencies[1] - spec.frequencies[0]
        assert np.isclose(actual_spacing, expected_spacing, rtol=0.01)


class TestSpectrogram:
    """Test spectrogram (magnitude STFT)."""

    def test_spectrogram_alias(self):
        """Spectrogram should be same as magnitude STFT."""
        x = np.random.randn(1000)

        spec1 = stft(x, window_size=512)
        spec2 = spectrogram(x, window_size=512)

        assert np.allclose(spec1.magnitude, spec2.magnitude)
        assert np.allclose(spec1.frequencies, spec2.frequencies)


class TestWelchPSD:
    """Test Welch's method for PSD estimation."""

    def test_welch_basic(self):
        """Welch PSD should produce valid output."""
        fs = 1000
        duration = 5.0
        t = np.arange(int(fs * duration)) / fs
        x = np.sin(2 * np.pi * 50 * t) + 0.5 * np.random.randn(len(t))

        freqs, psd = welch_psd(x, nperseg=512, sample_rate=fs)

        assert len(freqs) == len(psd)
        assert np.all(psd >= 0)
        assert np.all(freqs >= 0)

    def test_welch_from_signal_object(self):
        """Welch PSD should work with Signal objects."""
        signal = Signal(
            samples=np.random.randn(5000),
            sample_rate=1000,
        )

        freqs, psd = welch_psd(signal, nperseg=512)

        assert len(freqs) > 0
        assert len(psd) > 0

    def test_welch_peak_detection(self):
        """Welch PSD should show peak at signal frequency."""
        fs = 1000
        duration = 5.0
        f_signal = 50
        t = np.arange(int(fs * duration)) / fs
        x = np.sin(2 * np.pi * f_signal * t)

        freqs, psd = welch_psd(x, nperseg=512, sample_rate=fs)

        # Find peak
        peak_idx = np.argmax(psd)
        detected_freq = freqs[peak_idx]

        assert abs(detected_freq - f_signal) < 2

    def test_welch_overlap(self):
        """Welch PSD should handle overlap parameter."""
        x = np.random.randn(10000)

        freqs1, psd1 = welch_psd(x, nperseg=512, noverlap=0)
        freqs2, psd2 = welch_psd(x, nperseg=512, noverlap=256)

        # Different overlaps should give different estimates (but same frequency grid)
        assert len(freqs1) == len(freqs2)
        assert np.allclose(freqs1, freqs2)


class TestCepstrum:
    """Test cepstral analysis."""

    def test_cepstrum_real_output(self):
        """Cepstrum should be real."""
        from thomas.marketplace.signal_proc.fft import fft

        x = np.random.randn(256)
        X = fft(x)
        c = cepstrum(X)

        assert np.all(np.isreal(c))

    def test_cepstrum_symmetry(self):
        """Cepstrum should have symmetry properties."""
        from thomas.marketplace.signal_proc.fft import fft

        x = np.random.randn(512)
        X = fft(x)
        c = cepstrum(X)

        # Cepstrum should be symmetric (for real input FFT)
        if len(c) > 2:
            assert np.isclose(c[1], c[-1], rtol=0.1)


class TestSpectralFeatures:
    """Test spectral feature extraction."""

    def test_spectral_centroid_basic(self):
        """Spectral centroid should be in frequency range."""
        freqs = np.linspace(0, 500, 256)
        mag = np.ones(256)

        centroid = spectral_centroid(freqs, mag)

        assert 0 <= centroid <= 500

    def test_spectral_centroid_single_peak(self):
        """Spectral centroid of single peak should be near peak."""
        freqs = np.linspace(0, 1000, 1000)
        mag = np.zeros(1000)
        peak_freq = 300
        peak_idx = np.argmin(np.abs(freqs - peak_freq))
        mag[peak_idx] = 1.0

        centroid = spectral_centroid(freqs, mag)

        assert abs(centroid - peak_freq) < 5

    def test_spectral_bandwidth_basic(self):
        """Spectral bandwidth should be non-negative."""
        freqs = np.linspace(0, 1000, 256)
        mag = np.ones(256)

        bandwidth = spectral_bandwidth(freqs, mag)

        assert bandwidth >= 0

    def test_spectral_bandwidth_narrow(self):
        """Narrow spectrum should have small bandwidth."""
        freqs = np.linspace(0, 1000, 1000)
        mag = np.zeros(1000)
        # Narrow Gaussian around 500 Hz
        center_idx = 500
        mag[center_idx - 5 : center_idx + 6] = 1.0

        bandwidth = spectral_bandwidth(freqs, mag)

        narrow_threshold = 20  # Hz
        assert bandwidth < narrow_threshold

    def test_spectral_rolloff_basic(self):
        """Spectral rolloff should be in frequency range."""
        freqs = np.linspace(0, 1000, 256)
        mag = np.ones(256)

        rolloff = spectral_rolloff(freqs, mag)

        assert 0 <= rolloff <= 1000

    def test_spectral_rolloff_increasing(self):
        """Rolloff should increase with higher energy percentile."""
        freqs = np.linspace(0, 1000, 256)
        mag = np.ones(256)

        rolloff_90 = spectral_rolloff(freqs, mag, percentile=0.90)
        rolloff_99 = spectral_rolloff(freqs, mag, percentile=0.99)

        assert rolloff_99 >= rolloff_90

    def test_spectral_flatness_basic(self):
        """Spectral flatness should be between 0 and 1."""
        freqs = np.linspace(0, 1000, 256)
        mag = np.ones(256)

        flatness = spectral_flatness(mag)

        assert 0 <= flatness <= 1

    def test_spectral_flatness_white_noise(self):
        """White noise should have high flatness."""
        mag = np.ones(256) + 0.01 * np.random.randn(256)

        flatness = spectral_flatness(mag)

        # Should be close to 1 for flat spectrum
        assert flatness > 0.9

    def test_spectral_flatness_sine(self):
        """Sine wave should have low flatness."""
        mag = np.zeros(256)
        mag[128] = 1.0

        flatness = spectral_flatness(mag)

        # Should be low for concentrated spectrum
        assert flatness < 0.3


class TestMelConversion:
    """Test Mel scale conversion."""

    def test_hz_to_mel_zero(self):
        """0 Hz should map to 0 Mel."""
        mel = hz_to_mel(np.array([0]))
        assert np.isclose(mel[0], 0)

    def test_hz_to_mel_monotonic(self):
        """Hz to Mel conversion should be monotonically increasing."""
        freqs = np.linspace(0, 8000, 100)
        mels = hz_to_mel(freqs)

        assert np.all(np.diff(mels) > 0)

    def test_mel_to_hz_inverse(self):
        """mel_to_hz should invert hz_to_mel."""
        freqs_orig = np.linspace(0, 8000, 100)
        mels = hz_to_mel(freqs_orig)
        freqs_recovered = mel_to_hz(mels)

        assert np.allclose(freqs_orig, freqs_recovered, rtol=1e-5)

    def test_mel_scale_logarithmic(self):
        """Mel scale should compress high frequencies."""
        # Low frequency spacing in Hz
        low_mel = hz_to_mel(np.array([0, 100]))
        low_hz_spacing = 100

        # High frequency spacing in Hz (same Mel spacing)
        high_mel_target = hz_to_mel(np.array([0])) + (low_mel[1] - low_mel[0])
        high_hz_spacing = mel_to_hz(np.array([high_mel_target]))[0]

        # High frequencies should be spaced further apart
        assert high_hz_spacing > low_hz_spacing


class TestMelSpectrogram:
    """Test Mel-scale spectrogram."""

    def test_mel_spectrogram_basic(self):
        """Mel spectrogram should have correct dimensions."""
        x = np.random.randn(2000)

        spec = mel_spectrogram(x, n_mels=128, window_size=512)

        assert spec.magnitude.shape[1] == 128
        assert spec.magnitude.shape[0] > 0

    def test_mel_spectrogram_frequencies(self):
        """Mel spectrogram frequencies should be in Mel scale."""
        x = np.random.randn(2000)

        spec = mel_spectrogram(x, n_mels=64, window_size=512, sample_rate=1000)

        # Frequencies should be increasing (Mel scale)
        assert np.all(np.diff(spec.frequencies) > 0)

    def test_mel_spectrogram_from_signal_object(self):
        """Mel spectrogram should work with Signal objects."""
        signal = Signal(
            samples=np.random.randn(2000),
            sample_rate=1000,
        )

        spec = mel_spectrogram(signal, n_mels=128)

        assert spec.magnitude.shape[0] > 0


class TestSpectralErrors:
    """Test error handling."""

    def test_stft_empty_signal(self):
        """Empty signal should raise error."""
        with pytest.raises(SignalError):
            stft(np.array([]))

    def test_stft_too_short(self):
        """Signal shorter than window should raise error."""
        with pytest.raises(SignalError):
            stft(np.random.randn(10), window_size=512)

    def test_welch_invalid_scaling(self):
        """Invalid scaling parameter should raise error."""
        x = np.random.randn(1000)

        with pytest.raises(SignalError):
            welch_psd(x, scaling="invalid")

    def test_spectral_centroid_zero_magnitude(self):
        """Centroid of zero magnitude should be 0."""
        freqs = np.linspace(0, 1000, 256)
        mag = np.zeros(256)

        centroid = spectral_centroid(freqs, mag)

        assert centroid == 0


class TestSpectralLeakage:
    """Test spectral leakage and windowing effects."""

    def test_spectral_leakage_with_window(self):
        """Windowing should reduce spectral leakage."""
        fs = 1000
        duration = 1.0
        t = np.arange(int(fs * duration)) / fs

        # Non-integer number of cycles
        x = np.sin(2 * np.pi * 10.5 * t)

        spec_rect = stft(x, window_size=512, window_type="rectangular")
        spec_hamm = stft(x, window_size=512, window_type="hamming")

        # Hamming window should have less leakage (power more concentrated)
        # Compare spectral spread at first frame
        mag_rect = spec_rect.magnitude[0, :]
        mag_hamm = spec_hamm.magnitude[0, :]

        # Hamming should have lower side lobes (less spread)
        main_lobe_idx = np.argmax(mag_hamm)
        side_lobe_energy_rect = np.sum(mag_rect) - mag_rect[main_lobe_idx]
        side_lobe_energy_hamm = np.sum(mag_hamm) - mag_hamm[main_lobe_idx]

        assert side_lobe_energy_hamm < side_lobe_energy_rect
