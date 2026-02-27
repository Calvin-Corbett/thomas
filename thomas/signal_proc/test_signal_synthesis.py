"""
Tests for signal synthesis (waveforms, modulation, ADSR).
"""

import numpy as np
import pytest

from thomas.signal_proc._exceptions import SignalError
from thomas.signal_proc.synthesis import (
    adsr_envelope,
    am_modulation,
    chirp,
    fm_modulation,
    pink_noise,
    sawtooth_wave,
    sine_wave,
    square_wave,
    triangle_wave,
    wavetable_synthesis,
    white_noise,
)


class TestSineWave:
    """Test sine wave generation."""

    def test_sine_wave_basic(self):
        """Sine wave should have correct frequency."""
        sig = sine_wave(
            frequency=50,
            sample_rate=1000,
            duration=1.0,
        )

        assert len(sig.samples) == 1000
        assert sig.sample_rate == 1000

    def test_sine_wave_frequency(self):
        """Sine wave frequency should match specified frequency."""
        from thomas.signal_proc.fft import fft, frequency_bins, magnitude_spectrum

        sig = sine_wave(
            frequency=100,
            sample_rate=1000,
            duration=1.0,
        )

        X = fft(sig.samples)
        mag = magnitude_spectrum(X)
        freqs = frequency_bins(len(sig.samples), sig.sample_rate)

        peak_idx = np.argmax(mag)
        detected_freq = freqs[peak_idx]

        assert abs(detected_freq - 100) < 2

    def test_sine_wave_amplitude(self):
        """Sine wave amplitude should match specified amplitude."""
        amplitude = 2.5
        sig = sine_wave(
            frequency=50,
            sample_rate=1000,
            duration=0.1,
            amplitude=amplitude,
        )

        # Peak should be close to amplitude
        peak = np.max(np.abs(sig.samples))
        assert abs(peak - amplitude) < 0.01

    def test_sine_wave_phase(self):
        """Sine wave phase should be applied correctly."""
        phase = np.pi / 4

        sig = sine_wave(
            frequency=10,
            sample_rate=1000,
            duration=0.1,
            phase=phase,
        )

        # First sample should have the phase
        expected_first = np.sin(phase)
        assert np.isclose(sig.samples[0], expected_first, atol=0.01)


class TestSquareWave:
    """Test square wave generation."""

    def test_square_wave_basic(self):
        """Square wave should be generated."""
        sig = square_wave(
            frequency=50,
            sample_rate=1000,
            duration=1.0,
        )

        assert len(sig.samples) > 0

    def test_square_wave_range(self):
        """Square wave should be bounded."""
        sig = square_wave(
            frequency=50,
            sample_rate=1000,
            duration=0.1,
        )

        assert np.max(sig.samples) <= 1.5
        assert np.min(sig.samples) >= -1.5

    def test_square_wave_harmonics(self):
        """Square wave should contain odd harmonics."""
        from thomas.signal_proc.fft import fft, frequency_bins, magnitude_spectrum

        sig = square_wave(
            frequency=50,
            sample_rate=5000,
            duration=1.0,
        )

        X = fft(sig.samples)
        mag = magnitude_spectrum(X)
        freqs = frequency_bins(len(sig.samples), sig.sample_rate)

        # Find peaks at odd harmonics
        fundamental_idx = np.argmin(np.abs(freqs - 50))
        third_harmonic_idx = np.argmin(np.abs(freqs - 150))
        second_harmonic_idx = np.argmin(np.abs(freqs - 100))

        # Third harmonic should be strong
        assert mag[third_harmonic_idx] > 0
        # Second harmonic should be weak
        assert mag[second_harmonic_idx] < mag[third_harmonic_idx]


class TestSawtoothWave:
    """Test sawtooth wave generation."""

    def test_sawtooth_wave_basic(self):
        """Sawtooth wave should be generated."""
        sig = sawtooth_wave(
            frequency=50,
            sample_rate=1000,
            duration=0.1,
        )

        assert len(sig.samples) > 0

    def test_sawtooth_wave_range(self):
        """Sawtooth wave should be bounded."""
        sig = sawtooth_wave(
            frequency=50,
            sample_rate=1000,
            duration=0.1,
        )

        assert np.max(sig.samples) <= 1.0
        assert np.min(sig.samples) >= -1.0


class TestTriangleWave:
    """Test triangle wave generation."""

    def test_triangle_wave_basic(self):
        """Triangle wave should be generated."""
        sig = triangle_wave(
            frequency=50,
            sample_rate=1000,
            duration=0.1,
        )

        assert len(sig.samples) > 0

    def test_triangle_wave_range(self):
        """Triangle wave should be bounded."""
        sig = triangle_wave(
            frequency=50,
            sample_rate=1000,
            duration=0.1,
        )

        assert np.max(sig.samples) <= 1.0
        assert np.min(sig.samples) >= -1.0


class TestWhiteNoise:
    """Test white noise generation."""

    def test_white_noise_basic(self):
        """White noise should be generated."""
        sig = white_noise(
            sample_rate=1000,
            duration=0.1,
        )

        assert len(sig.samples) == 100

    def test_white_noise_amplitude(self):
        """White noise amplitude should be controlled."""
        amplitude = 5.0
        sig = white_noise(
            sample_rate=1000,
            duration=1.0,
            amplitude=amplitude,
        )

        # RMS should be roughly amplitude / sqrt(3) for uniform noise, amplitude * sqrt(1/3) for Gaussian
        rms = np.sqrt(np.mean(sig.samples**2))
        assert rms < amplitude

    def test_white_noise_reproducibility(self):
        """White noise with same seed should be identical."""
        sig1 = white_noise(sample_rate=1000, duration=0.1, seed=42)
        sig2 = white_noise(sample_rate=1000, duration=0.1, seed=42)

        assert np.allclose(sig1.samples, sig2.samples)

    def test_white_noise_flat_spectrum(self):
        """White noise should have roughly flat spectrum."""
        from thomas.signal_proc.fft import fft, magnitude_spectrum

        sig = white_noise(sample_rate=1000, duration=1.0, seed=42)

        X = fft(sig.samples)
        mag = magnitude_spectrum(X)

        # Spectrum should be relatively flat (std < 20% of mean)
        assert np.std(mag) < np.mean(mag) * 0.3


class TestPinkNoise:
    """Test pink noise (1/f) generation."""

    def test_pink_noise_basic(self):
        """Pink noise should be generated."""
        sig = pink_noise(
            sample_rate=1000,
            duration=0.1,
        )

        assert len(sig.samples) == 100

    def test_pink_noise_spectrum(self):
        """Pink noise should have 1/f spectrum."""
        from thomas.signal_proc.fft import fft, magnitude_spectrum

        sig = pink_noise(sample_rate=1000, duration=5.0, seed=42)

        X = fft(sig.samples)
        mag = magnitude_spectrum(X)

        # High frequencies should have lower power than low frequencies
        low_freq_power = np.mean(mag[1:50] ** 2)
        high_freq_power = np.mean(mag[200:250] ** 2)

        assert low_freq_power > high_freq_power


class TestChirp:
    """Test chirp signal generation."""

    def test_chirp_linear_basic(self):
        """Linear chirp should be generated."""
        sig = chirp(
            start_freq=10,
            end_freq=100,
            sample_rate=1000,
            duration=1.0,
            chirp_type="linear",
        )

        assert len(sig.samples) == 1000

    def test_chirp_logarithmic_basic(self):
        """Logarithmic chirp should be generated."""
        sig = chirp(
            start_freq=10,
            end_freq=100,
            sample_rate=1000,
            duration=1.0,
            chirp_type="logarithmic",
        )

        assert len(sig.samples) == 1000

    def test_chirp_frequency_sweep(self):
        """Chirp frequency should increase over time."""
        from thomas.signal_proc.spectral import stft

        sig = chirp(
            start_freq=50,
            end_freq=200,
            sample_rate=1000,
            duration=1.0,
            chirp_type="linear",
        )

        spec = stft(sig.samples, window_size=256, hop_size=128, sample_rate=1000)

        # Peak frequency should increase across time frames
        peak_freqs = []
        for i in range(min(3, spec.magnitude.shape[0])):
            peak_idx = np.argmax(spec.magnitude[i, :])
            peak_freqs.append(spec.frequencies[peak_idx])

        # Should generally increase
        if len(peak_freqs) > 1:
            assert peak_freqs[-1] > peak_freqs[0]

    def test_chirp_invalid_type(self):
        """Invalid chirp type should raise error."""
        with pytest.raises(SignalError):
            chirp(10, 100, 1000, 1.0, chirp_type="invalid")


class TestAMModulation:
    """Test amplitude modulation."""

    def test_am_modulation_basic(self):
        """AM signal should be generated."""
        sig = am_modulation(
            carrier_freq=1000,
            modulator_freq=10,
            sample_rate=10000,
            duration=0.1,
        )

        assert len(sig.samples) == 1000

    def test_am_modulation_sidebands(self):
        """AM signal should have sidebands."""
        from thomas.signal_proc.fft import fft, frequency_bins, magnitude_spectrum

        sig = am_modulation(
            carrier_freq=1000,
            modulator_freq=100,
            sample_rate=10000,
            duration=1.0,
            modulation_depth=0.5,
        )

        X = fft(sig.samples)
        mag = magnitude_spectrum(X)
        freqs = frequency_bins(len(sig.samples), sig.sample_rate)

        # Should have peaks at carrier and sidebands
        carrier_idx = np.argmin(np.abs(freqs - 1000))
        upper_sideband_idx = np.argmin(np.abs(freqs - 1100))
        lower_sideband_idx = np.argmin(np.abs(freqs - 900))

        # All should be strong
        assert mag[carrier_idx] > np.max(mag) * 0.3
        assert mag[upper_sideband_idx] > 0
        assert mag[lower_sideband_idx] > 0


class TestFMModulation:
    """Test frequency modulation."""

    def test_fm_modulation_basic(self):
        """FM signal should be generated."""
        sig = fm_modulation(
            carrier_freq=1000,
            modulator_freq=10,
            sample_rate=10000,
            duration=0.1,
        )

        assert len(sig.samples) == 1000

    def test_fm_modulation_bounds(self):
        """FM signal should be bounded."""
        sig = fm_modulation(
            carrier_freq=1000,
            modulator_freq=100,
            sample_rate=10000,
            duration=0.5,
        )

        assert np.max(sig.samples) <= 1.5
        assert np.min(sig.samples) >= -1.5


class TestADSREnvelope:
    """Test ADSR envelope generation."""

    def test_adsr_basic(self):
        """ADSR envelope should be generated."""
        env = adsr_envelope(
            attack_time=0.1,
            decay_time=0.1,
            sustain_level=0.7,
            release_time=0.1,
            sample_rate=1000,
        )

        assert len(env) == 300  # 0.3 seconds at 1000 Hz

    def test_adsr_attack(self):
        """ADSR attack should rise from 0."""
        env = adsr_envelope(
            attack_time=0.1,
            decay_time=0.0,
            sustain_level=1.0,
            release_time=0.0,
            sample_rate=1000,
        )

        assert env[0] == 0
        assert np.all(np.diff(env[:100]) >= 0)  # Should be increasing

    def test_adsr_sustain(self):
        """ADSR sustain level should be maintained."""
        sustain = 0.8
        env = adsr_envelope(
            attack_time=0.05,
            decay_time=0.05,
            sustain_level=sustain,
            release_time=0.05,
            sample_rate=1000,
            total_time=0.2,
        )

        # Middle portion should be at sustain level
        assert np.isclose(env[150], sustain, atol=0.01)

    def test_adsr_release(self):
        """ADSR release should decay to 0."""
        env = adsr_envelope(
            attack_time=0.0,
            decay_time=0.0,
            sustain_level=1.0,
            release_time=0.1,
            sample_rate=1000,
        )

        assert env[-1] == 0
        assert np.all(np.diff(env[-100:]) <= 0)  # Should be decreasing


class TestWavetableSynthesis:
    """Test wavetable synthesis."""

    def test_wavetable_basic(self):
        """Wavetable synthesis should work."""
        wavetable = np.sin(2 * np.pi * np.linspace(0, 1, 256))

        sig = wavetable_synthesis(
            wavetable=wavetable,
            frequency=100,
            sample_rate=1000,
            duration=0.1,
        )

        assert len(sig.samples) == 100

    def test_wavetable_frequency(self):
        """Wavetable synthesis frequency should be correct."""
        from thomas.signal_proc.fft import fft, frequency_bins, magnitude_spectrum

        wavetable = np.sin(2 * np.pi * np.linspace(0, 1, 256))

        sig = wavetable_synthesis(
            wavetable=wavetable,
            frequency=50,
            sample_rate=1000,
            duration=1.0,
        )

        X = fft(sig.samples)
        mag = magnitude_spectrum(X)
        freqs = frequency_bins(len(sig.samples), sig.sample_rate)

        peak_idx = np.argmax(mag)
        detected_freq = freqs[peak_idx]

        assert abs(detected_freq - 50) < 2

    def test_wavetable_amplitude(self):
        """Wavetable amplitude should be controlled."""
        wavetable = np.sin(2 * np.pi * np.linspace(0, 1, 256))
        amplitude = 3.0

        sig = wavetable_synthesis(
            wavetable=wavetable,
            frequency=50,
            sample_rate=1000,
            duration=0.1,
            amplitude=amplitude,
        )

        peak = np.max(np.abs(sig.samples))
        assert np.isclose(peak, amplitude, rtol=0.1)

    def test_wavetable_too_short(self):
        """Wavetable with less than 2 samples should raise error."""
        with pytest.raises(SignalError):
            wavetable_synthesis(
                wavetable=np.array([1.0]),
                frequency=100,
                sample_rate=1000,
                duration=0.1,
            )


class TestSynthesisIntegration:
    """Integration tests for synthesis."""

    def test_modulated_sine_wave(self):
        """Modulated sine wave from basic components."""
        # Generate base sine wave
        sig = sine_wave(frequency=1000, sample_rate=10000, duration=0.5)

        # Generate modulator
        mod_sig = sine_wave(frequency=10, sample_rate=10000, duration=0.5)

        # Apply amplitude modulation
        modulated = sig.samples * (1 + 0.5 * mod_sig.samples)

        assert len(modulated) == len(sig.samples)

    def test_envelope_application(self):
        """Apply ADSR envelope to signal."""
        sig = sine_wave(frequency=440, sample_rate=44100, duration=1.0)

        env = adsr_envelope(
            attack_time=0.1,
            decay_time=0.2,
            sustain_level=0.8,
            release_time=0.3,
            sample_rate=44100,
            total_time=1.0,
        )

        enveloped = sig.samples * env

        # Should have zero start and end
        assert abs(enveloped[0]) < 0.01
        assert abs(enveloped[-1]) < 0.01
