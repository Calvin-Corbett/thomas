"""
Tests for audio analysis.
"""

import numpy as np

from thomas.marketplace.audio_engine.analysis import (
    BeatDetector,
    LoudnessAnalyzer,
    OnsetDetector,
    PitchDetector,
    SpectrogramAnalyzer,
    SpectrumAnalyzer,
    ZeroCrossingRate,
)


class TestSpectrumAnalyzer:
    """Test spectrum analyzer."""

    def test_spectrum_basic(self) -> None:
        """Test basic spectrum analysis."""
        analyzer = SpectrumAnalyzer(fft_size=2048, sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 2048)).astype(np.float32)
        frequencies, magnitude_db = analyzer.analyze(samples)

        assert len(frequencies) == 1025  # FFT size / 2 + 1
        assert len(magnitude_db) == 1025
        assert np.all(np.isfinite(magnitude_db))

    def test_spectrum_peak_detection(self) -> None:
        """Test peak detection in spectrum."""
        analyzer = SpectrumAnalyzer(fft_size=2048, sample_rate=44100)
        # Generate 440 Hz sine wave
        t = np.linspace(0, 1, 2048)
        samples = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        frequencies, magnitude_db = analyzer.analyze(samples)

        peaks = analyzer.find_peaks(magnitude_db, threshold=-20.0)
        assert len(peaks) > 0

    def test_spectrum_window_types(self) -> None:
        """Test different window types."""
        samples = np.ones(2048, dtype=np.float32)

        for window_type in ["hann", "hamming", "blackman"]:
            analyzer = SpectrumAnalyzer(fft_size=2048, window_type=window_type, sample_rate=44100)
            frequencies, magnitude_db = analyzer.analyze(samples)
            assert len(magnitude_db) == 1025


class TestSpectrogramAnalyzer:
    """Test spectrogram analyzer."""

    def test_spectrogram_basic(self) -> None:
        """Test basic spectrogram analysis."""
        analyzer = SpectrogramAnalyzer(fft_size=2048, hop_size=512, sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 10, 44100)).astype(np.float32)
        times, frequencies, spectrogram = analyzer.analyze(samples)

        assert len(times) > 0
        assert len(frequencies) == 1025
        assert spectrogram.shape[0] == 1025

    def test_spectrogram_dimensions(self) -> None:
        """Test spectrogram dimensions."""
        analyzer = SpectrogramAnalyzer(fft_size=512, hop_size=256, sample_rate=44100)
        samples = np.random.randn(22050).astype(np.float32) * 0.1
        times, frequencies, spectrogram = analyzer.analyze(samples)

        assert spectrogram.shape[0] == 257  # FFT size / 2 + 1
        assert spectrogram.shape[1] == len(times)


class TestPitchDetector:
    """Test pitch detector."""

    def test_pitch_detection_sine(self) -> None:
        """Test pitch detection on sine wave."""
        detector = PitchDetector(sample_rate=44100, min_freq=50.0, max_freq=500.0)
        # Generate 440 Hz sine wave
        t = np.linspace(0, 1, 44100)
        samples = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        frequency, confidence = detector.detect(samples)

        assert frequency > 0
        assert 0 <= confidence <= 1

    def test_pitch_detection_range(self) -> None:
        """Test pitch detection in frequency range."""
        detector = PitchDetector(sample_rate=44100, min_freq=200.0, max_freq=600.0)
        # Generate 440 Hz sine wave
        t = np.linspace(0, 1, 44100)
        samples = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        frequency, confidence = detector.detect(samples)

        # Detected frequency should be in range
        if confidence > 0.1:
            assert 200 <= frequency <= 600 or frequency == 0


class TestOnsetDetector:
    """Test onset detector."""

    def test_onset_detection_basic(self) -> None:
        """Test basic onset detection."""
        detector = OnsetDetector(sample_rate=44100, hop_size=512)
        # Generate signal with clear onsets
        samples = np.zeros(44100, dtype=np.float32)
        for i in range(4):
            start = i * 11025
            samples[start : start + 4410] = np.sin(2 * np.pi * np.linspace(0, 1, 4410))

        onsets = detector.detect_onsets(samples, threshold=0.3)
        assert isinstance(onsets, list)

    def test_onset_detection_count(self) -> None:
        """Test onset detection count."""
        detector = OnsetDetector(sample_rate=44100)
        # Generate silent signal
        samples = np.zeros(44100, dtype=np.float32)
        onsets = detector.detect_onsets(samples)

        # Silent signal should have few or no onsets
        assert len(onsets) < 10


class TestBeatDetector:
    """Test beat detector."""

    def test_beat_detection_basic(self) -> None:
        """Test basic beat detection."""
        detector = BeatDetector(sample_rate=44100, min_bpm=60.0, max_bpm=180.0)
        samples = np.zeros(44100, dtype=np.float32)
        # Generate beat-like pattern
        beat_interval = int(44100 / 2)  # Half second (120 BPM)
        for i in range(2):
            samples[i * beat_interval : i * beat_interval + 1000] = 0.5

        tempo, confidence = detector.detect_tempo(samples)

        # Returned values should be valid
        assert isinstance(tempo, float)
        assert 0 <= confidence <= 1

    def test_beat_detection_silent(self) -> None:
        """Test beat detection on silent signal."""
        detector = BeatDetector(sample_rate=44100)
        samples = np.zeros(44100, dtype=np.float32)
        tempo, confidence = detector.detect_tempo(samples)

        # Silent signal should have low confidence
        assert confidence < 0.5 or tempo == 0


class TestLoudnessAnalyzer:
    """Test loudness analyzer."""

    def test_loudness_measurement(self) -> None:
        """Test loudness measurement."""
        analyzer = LoudnessAnalyzer(sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 44100)).astype(np.float32)
        loudness = analyzer.measure(samples)

        assert isinstance(loudness, float)
        assert loudness < 0  # LUFS should be negative

    def test_loudness_stereo(self) -> None:
        """Test loudness measurement on stereo."""
        analyzer = LoudnessAnalyzer(sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 44100)).astype(np.float32)
        stereo = np.column_stack([samples, samples])
        loudness = analyzer.measure(stereo)

        assert isinstance(loudness, float)

    def test_true_peak_measurement(self) -> None:
        """Test true peak measurement."""
        analyzer = LoudnessAnalyzer(sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32) * 0.5
        peak = analyzer.measure_true_peak(samples)

        assert isinstance(peak, float)
        assert peak < 0  # Should be in dB

    def test_loudness_scaling(self) -> None:
        """Test loudness scales with amplitude."""
        analyzer = LoudnessAnalyzer(sample_rate=44100)
        samples1 = np.ones(44100, dtype=np.float32) * 0.1
        samples2 = np.ones(44100, dtype=np.float32) * 0.5

        loudness1 = analyzer.measure(samples1)
        loudness2 = analyzer.measure(samples2)

        # Higher amplitude should have higher loudness
        assert loudness2 > loudness1


class TestZeroCrossingRate:
    """Test zero-crossing rate."""

    def test_zcr_basic(self) -> None:
        """Test basic zero-crossing rate."""
        analyzer = ZeroCrossingRate(sample_rate=44100, hop_size=512)
        samples = np.sin(2 * np.pi * np.linspace(0, 10, 44100)).astype(np.float32)
        zcr = analyzer.analyze(samples)

        assert len(zcr) > 0
        assert np.all(zcr >= 0)
        assert np.all(zcr <= 1)

    def test_zcr_frequency_dependence(self) -> None:
        """Test ZCR frequency dependence."""
        analyzer = ZeroCrossingRate(sample_rate=44100, hop_size=512)

        # Low frequency
        samples_low = np.sin(2 * np.pi * 100 * np.linspace(0, 1, 44100)).astype(np.float32)
        zcr_low = analyzer.analyze(samples_low)

        # High frequency
        samples_high = np.sin(2 * np.pi * 1000 * np.linspace(0, 1, 44100)).astype(np.float32)
        zcr_high = analyzer.analyze(samples_high)

        # High frequency should have higher ZCR
        assert np.mean(zcr_high) > np.mean(zcr_low)
