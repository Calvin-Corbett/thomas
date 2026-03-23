"""
Tests for voice pitch detection module.
"""

import numpy as np
import pytest

from thomas.marketplace.voice._exceptions import PitchDetectionError
from thomas.marketplace.voice._types import AudioSample, PitchContour
from thomas.marketplace.voice.pitch import PitchDetector


class TestPitchDetector:
    """Tests for PitchDetector class."""

    @pytest.fixture
    def detector(self) -> PitchDetector:
        """Create pitch detector."""
        return PitchDetector(min_pitch=50, max_pitch=500)

    @pytest.fixture
    def sinusoid_audio(self) -> AudioSample:
        """Create sinusoidal audio at 200 Hz."""
        sample_rate = 16000
        duration = 1.0
        t = np.arange(0, duration, 1 / sample_rate)
        freq = 200.0
        data = np.sin(2 * np.pi * freq * t).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    @pytest.fixture
    def voiced_audio(self) -> AudioSample:
        """Create voiced audio with pitch contour."""
        sample_rate = 16000
        duration = 1.0
        t = np.arange(0, duration, 1 / sample_rate)
        # Frequency sweep from 100 Hz to 300 Hz
        freq = 100 + 200 * t / duration
        data = np.sin(2 * np.pi * freq * t).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    def test_autocorrelation_pitch_detection(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test autocorrelation pitch detection."""
        pitch = detector.detect_pitch(sinusoid_audio, method="autocorrelation")

        assert isinstance(pitch, PitchContour)
        assert len(pitch.frequency) > 0
        assert len(pitch.voicing) == len(pitch.frequency)

    def test_hps_pitch_detection(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test HPS pitch detection."""
        pitch = detector.detect_pitch(sinusoid_audio, method="hps")

        assert isinstance(pitch, PitchContour)
        assert len(pitch.frequency) > 0

    def test_cepstral_pitch_detection(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test cepstral pitch detection."""
        pitch = detector.detect_pitch(sinusoid_audio, method="cepstral")

        assert isinstance(pitch, PitchContour)
        assert len(pitch.frequency) > 0

    def test_pitch_contour_properties(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test pitch contour properties."""
        pitch = detector.detect_pitch(sinusoid_audio)

        assert pitch.num_frames > 0
        assert len(pitch.timestamp) == pitch.num_frames
        assert np.all(pitch.voicing >= 0)
        assert np.all(pitch.voicing <= 1)

    def test_pitch_in_valid_range(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test pitch values are in valid range."""
        pitch = detector.detect_pitch(sinusoid_audio)

        voiced = pitch.get_voiced_frames()
        if len(voiced) > 0:
            voiced_pitch = pitch.frequency[voiced]
            assert np.all(voiced_pitch >= detector.min_pitch)
            assert np.all(voiced_pitch <= detector.max_pitch)

    def test_get_voiced_frames(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test getting voiced frames."""
        pitch = detector.detect_pitch(sinusoid_audio)
        voiced = pitch.get_voiced_frames(threshold=0.5)

        assert isinstance(voiced, np.ndarray)
        assert len(voiced) <= pitch.num_frames

    def test_pitch_statistics(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test pitch statistics calculation."""
        pitch = detector.detect_pitch(sinusoid_audio)
        stats = detector.get_pitch_statistics(pitch)

        assert "mean" in stats
        assert "min" in stats
        assert "max" in stats
        assert "range" in stats
        assert "std" in stats
        assert "jitter" in stats
        assert stats["mean"] >= 0
        assert stats["std"] >= 0

    def test_mean_pitch(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test mean pitch calculation."""
        pitch = detector.detect_pitch(sinusoid_audio)
        mean = pitch.get_mean_pitch()

        assert isinstance(mean, float)
        assert mean >= 0

    def test_pitch_range(self, detector: PitchDetector, voiced_audio: AudioSample) -> None:
        """Test pitch range calculation."""
        pitch = detector.detect_pitch(voiced_audio)
        min_pitch, max_pitch = pitch.get_pitch_range()

        assert min_pitch >= 0
        assert max_pitch >= min_pitch

    def test_autocorrelation_calculation(self, detector: PitchDetector) -> None:
        """Test autocorrelation calculation."""
        signal = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 512))
        autocorr = detector._autocorrelation(signal, max_lag=100)

        assert len(autocorr) == 100
        assert autocorr[0] == np.max(autocorr)

    def test_frame_audio(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test audio framing."""
        frames = detector._frame_audio(sinusoid_audio.data, sinusoid_audio.sample_rate)

        assert len(frames) > 0
        assert all(len(f) == detector.frame_size for f in frames)

    def test_pitch_contour_smoothing(self, detector: PitchDetector, voiced_audio: AudioSample) -> None:
        """Test pitch contour smoothing."""
        pitch = detector.detect_pitch(voiced_audio)

        # Should have smooth transitions
        voiced = pitch.get_voiced_frames()
        if len(voiced) > 1:
            diffs = np.abs(np.diff(pitch.frequency[voiced]))
            # Most differences should be relatively small
            assert np.percentile(diffs, 75) < 100

    def test_invalid_method(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test invalid detection method."""
        with pytest.raises(PitchDetectionError):
            detector.detect_pitch(sinusoid_audio, method="invalid")

    def test_short_audio(self, detector: PitchDetector) -> None:
        """Test with very short audio."""
        sample_rate = 16000
        data = np.sin(2 * np.pi * 200 * np.linspace(0, 0.01, 160)).astype(np.float32)
        audio = AudioSample(data=data, sample_rate=sample_rate)

        pitch = detector.detect_pitch(audio)
        assert pitch.num_frames > 0

    def test_pitch_statistics_empty_audio(self, detector: PitchDetector) -> None:
        """Test pitch statistics with no voiced frames."""
        sample_rate = 16000
        data = np.zeros(16000, dtype=np.float32)
        audio = AudioSample(data=data, sample_rate=sample_rate)

        pitch = detector.detect_pitch(audio)
        stats = detector.get_pitch_statistics(pitch)

        assert stats["mean"] == 0.0
        assert stats["std"] == 0.0

    def test_detector_initialization(self) -> None:
        """Test detector initialization with different parameters."""
        detector = PitchDetector(min_pitch=80, max_pitch=400, frame_size=1024, hop_size=256)

        assert detector.min_pitch == 80
        assert detector.max_pitch == 400
        assert detector.frame_size == 1024
        assert detector.hop_size == 256

    def test_pitch_contour_get_frame(self, detector: PitchDetector, sinusoid_audio: AudioSample) -> None:
        """Test getting individual frames from pitch contour."""
        pitch = detector.detect_pitch(sinusoid_audio)

        if pitch.num_frames > 0:
            freq = pitch.frequency[0]
            assert isinstance(freq, (float, np.floating))
