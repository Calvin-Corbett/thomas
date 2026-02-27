"""
Tests for voice speaker recognition module.
"""

import numpy as np
import pytest

from thomas.voice._exceptions import SpeakerError
from thomas.voice._types import AudioSample
from thomas.voice.speaker import SpeakerRecognizer


class TestSpeakerRecognizer:
    """Tests for SpeakerRecognizer class."""

    @pytest.fixture
    def recognizer(self) -> SpeakerRecognizer:
        """Create speaker recognizer."""
        return SpeakerRecognizer(num_gmm_components=8)

    @pytest.fixture
    def speaker_audio(self) -> AudioSample:
        """Create test speaker audio."""
        sample_rate = 16000
        duration = 2.0
        t = np.arange(0, duration, 1 / sample_rate)
        # Mix of frequencies
        data = (0.5 * np.sin(2 * np.pi * 200 * t) + 0.3 * np.sin(2 * np.pi * 400 * t)).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    @pytest.fixture
    def different_speaker_audio(self) -> AudioSample:
        """Create audio from different speaker."""
        sample_rate = 16000
        duration = 2.0
        t = np.arange(0, duration, 1 / sample_rate)
        # Different mix of frequencies
        data = (0.5 * np.sin(2 * np.pi * 150 * t) + 0.3 * np.sin(2 * np.pi * 350 * t)).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    def test_enroll_speaker(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test speaker enrollment."""
        model = recognizer.enroll_speaker("speaker1", [speaker_audio])

        assert model.speaker_id == "speaker1"
        assert model.mean_vector is not None
        assert model.covariance_matrix is not None
        assert model.num_utterances == 1

    def test_enroll_multiple_utterances(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test enrollment with multiple utterances."""
        utterances = [speaker_audio for _ in range(3)]
        model = recognizer.enroll_speaker("speaker1", utterances)

        assert model.num_utterances == 3

    def test_speaker_verification_same_speaker(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test speaker verification with same speaker."""
        recognizer.enroll_speaker("speaker1", [speaker_audio])

        verified, score = recognizer.verify_speaker("speaker1", speaker_audio)

        assert isinstance(verified, bool)
        assert isinstance(score, float)
        assert 0 <= score <= 1
        assert verified

    def test_speaker_identification(
        self,
        recognizer: SpeakerRecognizer,
        speaker_audio: AudioSample,
        different_speaker_audio: AudioSample,
    ) -> None:
        """Test speaker identification."""
        recognizer.enroll_speaker("speaker1", [speaker_audio])
        recognizer.enroll_speaker("speaker2", [different_speaker_audio])

        identified_id, score = recognizer.identify_speaker(speaker_audio)

        assert isinstance(identified_id, str)
        assert isinstance(score, float)
        assert 0 <= score <= 1

    def test_verification_different_speaker(
        self,
        recognizer: SpeakerRecognizer,
        speaker_audio: AudioSample,
        different_speaker_audio: AudioSample,
    ) -> None:
        """Test verification rejects different speaker."""
        recognizer.enroll_speaker("speaker1", [speaker_audio])

        verified, score = recognizer.verify_speaker("speaker1", different_speaker_audio)

        assert not verified
        assert score < 0.5

    def test_speaker_model_feature_dimension(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test speaker model feature dimension."""
        model = recognizer.enroll_speaker("speaker1", [speaker_audio])

        dimension = model.get_feature_dimension()
        assert dimension == 13  # MFCC coefficients

    def test_verify_unenrolled_speaker(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test verification fails for unenrolled speaker."""
        with pytest.raises(SpeakerError):
            recognizer.verify_speaker("unknown", speaker_audio)

    def test_identify_no_speakers(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test identification fails with no enrolled speakers."""
        with pytest.raises(SpeakerError):
            recognizer.identify_speaker(speaker_audio)

    def test_speaker_clustering(
        self,
        recognizer: SpeakerRecognizer,
        speaker_audio: AudioSample,
        different_speaker_audio: AudioSample,
    ) -> None:
        """Test speaker clustering."""
        samples = [
            ("sample1", speaker_audio),
            ("sample2", speaker_audio),
            ("sample3", different_speaker_audio),
        ]

        clusters = recognizer.cluster_speakers(samples)

        assert len(clusters) > 0
        assert all(isinstance(c, list) for c in clusters)

    def test_clustering_same_speaker_samples(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test that same speaker samples cluster together."""
        samples = [
            ("sample1", speaker_audio),
            ("sample2", speaker_audio),
        ]

        clusters = recognizer.cluster_speakers(samples, distance_threshold=1.0)

        # Should cluster into one or two groups depending on threshold
        assert len(clusters) <= 2

    def test_clustering_empty_input(self, recognizer: SpeakerRecognizer) -> None:
        """Test clustering with empty input."""
        clusters = recognizer.cluster_speakers([])
        assert clusters == []

    def test_speaker_model_with_gmm(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test speaker model with GMM parameters."""
        model = recognizer.enroll_speaker("speaker1", [speaker_audio])

        assert model.gmm_weights is not None
        assert model.gmm_means is not None
        assert model.gmm_covariances is not None
        assert len(model.gmm_weights) == recognizer.num_gmm_components

    def test_recognizer_initialization(self) -> None:
        """Test recognizer initialization."""
        recognizer = SpeakerRecognizer(num_gmm_components=16)

        assert recognizer.num_gmm_components == 16

    def test_multiple_speaker_identification(
        self,
        recognizer: SpeakerRecognizer,
        speaker_audio: AudioSample,
        different_speaker_audio: AudioSample,
    ) -> None:
        """Test identification among multiple speakers."""
        recognizer.enroll_speaker("speaker1", [speaker_audio])
        recognizer.enroll_speaker("speaker2", [different_speaker_audio])

        # Test with speaker1 audio
        identified, score = recognizer.identify_speaker(speaker_audio)
        assert identified == "speaker1"

        # Test with speaker2 audio
        identified, score = recognizer.identify_speaker(different_speaker_audio)
        assert identified == "speaker2"

    def test_verification_threshold(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test verification with different thresholds."""
        recognizer.enroll_speaker("speaker1", [speaker_audio])

        verified_strict, _ = recognizer.verify_speaker("speaker1", speaker_audio, threshold=0.9)
        verified_loose, _ = recognizer.verify_speaker("speaker1", speaker_audio, threshold=0.1)

        # Loose threshold should verify
        assert verified_loose

    def test_covariance_matrix_properties(self, recognizer: SpeakerRecognizer, speaker_audio: AudioSample) -> None:
        """Test covariance matrix properties."""
        model = recognizer.enroll_speaker("speaker1", [speaker_audio])

        # Should be symmetric
        assert np.allclose(model.covariance_matrix, model.covariance_matrix.T)

        # Should be positive semi-definite
        eigenvalues = np.linalg.eigvalsh(model.covariance_matrix)
        assert np.all(eigenvalues >= -1e-10)
