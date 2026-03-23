"""
Tests for voice speech recognition module.
"""

import numpy as np
import pytest

from thomas.marketplace.voice._exceptions import RecognitionError
from thomas.marketplace.voice._types import AudioSample, TranscriptionResult
from thomas.marketplace.voice.recognition import (
    BeamSearchDecoder,
    BigramLanguageModel,
    DynamicTimeWarping,
    SpeechRecognizer,
    TemplateMatchingRecognizer,
)


class TestDynamicTimeWarping:
    """Tests for DynamicTimeWarping class."""

    def test_dtw_distance_identical_sequences(self) -> None:
        """Test DTW distance for identical sequences."""
        x = np.array([[1, 2], [3, 4], [5, 6]])
        y = np.array([[1, 2], [3, 4], [5, 6]])

        distance, _ = DynamicTimeWarping.compute_dtw(x, y)

        assert distance == 0.0

    def test_dtw_distance_different_lengths(self) -> None:
        """Test DTW distance for sequences of different lengths."""
        x = np.array([[1, 2], [3, 4]])
        y = np.array([[1, 2], [3, 4], [5, 6]])

        distance, _ = DynamicTimeWarping.compute_dtw(x, y)

        assert distance >= 0

    def test_dtw_cost_matrix_shape(self) -> None:
        """Test DTW cost matrix shape."""
        x = np.array([[1, 2], [3, 4], [5, 6]])
        y = np.array([[1, 2], [3, 4]])

        _, cost_matrix = DynamicTimeWarping.compute_dtw(x, y)

        assert cost_matrix.shape == (len(x), len(y))

    def test_get_alignment_path(self) -> None:
        """Test alignment path extraction."""
        x = np.array([[1, 2], [3, 4], [5, 6]])
        y = np.array([[1, 2], [3, 4]])

        _, cost_matrix = DynamicTimeWarping.compute_dtw(x, y)
        path = DynamicTimeWarping.get_alignment_path(cost_matrix)

        assert len(path) > 0
        assert path[0] == (1, 1)


class TestTemplateMatchingRecognizer:
    """Tests for TemplateMatchingRecognizer class."""

    @pytest.fixture
    def recognizer(self) -> TemplateMatchingRecognizer:
        """Create template matching recognizer."""
        return TemplateMatchingRecognizer()

    @pytest.fixture
    def audio_sample(self) -> AudioSample:
        """Create test audio sample."""
        sample_rate = 16000
        duration = 0.5
        t = np.arange(0, duration, 1 / sample_rate)
        data = np.sin(2 * np.pi * 200 * t).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    def test_enroll_template(self, recognizer: TemplateMatchingRecognizer, audio_sample: AudioSample) -> None:
        """Test template enrollment."""
        recognizer.enroll_template("hello", audio_sample)

        assert "hello" in recognizer.templates

    def test_recognize_enrolled_word(self, recognizer: TemplateMatchingRecognizer, audio_sample: AudioSample) -> None:
        """Test recognition of enrolled word."""
        recognizer.enroll_template("hello", audio_sample)

        word, confidence, n_best = recognizer.recognize(audio_sample)

        assert word == "hello"
        assert 0 <= confidence <= 1
        assert len(n_best) > 0

    def test_recognize_no_templates(self, recognizer: TemplateMatchingRecognizer, audio_sample: AudioSample) -> None:
        """Test recognition fails with no templates."""
        with pytest.raises(RecognitionError):
            recognizer.recognize(audio_sample)

    def test_recognize_multiple_templates(
        self, recognizer: TemplateMatchingRecognizer, audio_sample: AudioSample
    ) -> None:
        """Test recognition with multiple templates."""
        recognizer.enroll_template("hello", audio_sample)

        # Create different audio
        sample_rate = 16000
        duration = 0.5
        t = np.arange(0, duration, 1 / sample_rate)
        audio2 = AudioSample(
            data=np.sin(2 * np.pi * 150 * t).astype(np.float32),
            sample_rate=sample_rate,
        )

        recognizer.enroll_template("goodbye", audio2)

        word, confidence, _ = recognizer.recognize(audio_sample)

        assert word in ["hello", "goodbye"]

    def test_get_alignment(self, recognizer: TemplateMatchingRecognizer, audio_sample: AudioSample) -> None:
        """Test alignment retrieval."""
        recognizer.enroll_template("hello", audio_sample)

        distance, path = recognizer.get_alignment(audio_sample, "hello")

        assert distance >= 0
        assert len(path) > 0

    def test_get_alignment_unknown_word(
        self, recognizer: TemplateMatchingRecognizer, audio_sample: AudioSample
    ) -> None:
        """Test alignment fails for unknown word."""
        with pytest.raises(RecognitionError):
            recognizer.get_alignment(audio_sample, "unknown")

    def test_recognize_top_n(self, recognizer: TemplateMatchingRecognizer, audio_sample: AudioSample) -> None:
        """Test N-best recognition."""
        recognizer.enroll_template("hello", audio_sample)
        recognizer.enroll_template("hi", audio_sample)
        recognizer.enroll_template("hey", audio_sample)

        _, _, n_best = recognizer.recognize(audio_sample, top_n=3)

        assert len(n_best) <= 3


class TestBigramLanguageModel:
    """Tests for BigramLanguageModel class."""

    @pytest.fixture
    def lm(self) -> BigramLanguageModel:
        """Create language model."""
        return BigramLanguageModel()

    def test_train_model(self, lm: BigramLanguageModel) -> None:
        """Test training language model."""
        sequences = [
            ["hello", "world"],
            ["hello", "there"],
        ]

        lm.train(sequences)

        assert lm.total_unigrams > 0
        assert lm.vocab_size > 0

    def test_get_probability(self, lm: BigramLanguageModel) -> None:
        """Test probability calculation."""
        sequences = [["hello", "world"]]
        lm.train(sequences)

        prob = lm.get_probability("hello", "world")

        assert 0 <= prob <= 1

    def test_get_probability_unseen_bigram(self, lm: BigramLanguageModel) -> None:
        """Test probability of unseen bigram."""
        sequences = [["hello", "world"]]
        lm.train(sequences)

        prob = lm.get_probability("hello", "universe")

        assert prob > 0

    def test_get_probability_unknown_word(self, lm: BigramLanguageModel) -> None:
        """Test probability of unknown word."""
        sequences = [["hello", "world"]]
        lm.train(sequences)

        prob = lm.get_probability("hello", "xyz")

        assert prob > 0


class TestBeamSearchDecoder:
    """Tests for BeamSearchDecoder class."""

    @pytest.fixture
    def decoder(self) -> BeamSearchDecoder:
        """Create beam search decoder."""
        return BeamSearchDecoder(beam_width=5)

    def test_decode(self, decoder: BeamSearchDecoder) -> None:
        """Test beam search decoding."""
        frame_scores = np.random.randn(10, 5)
        vocab = ["hello", "world", "test", "hi", "bye"]

        hypotheses = decoder.decode(frame_scores, vocab)

        assert len(hypotheses) > 0
        assert all(isinstance(h, tuple) for h in hypotheses)

    def test_decode_with_language_model(self, decoder: BeamSearchDecoder) -> None:
        """Test decoding with language model."""
        frame_scores = np.random.randn(10, 5)
        vocab = ["hello", "world", "test", "hi", "bye"]

        lm = BigramLanguageModel()
        lm.train([["hello", "world"], ["hi", "there"]])

        hypotheses = decoder.decode(frame_scores, vocab, lm)

        assert len(hypotheses) > 0


class TestSpeechRecognizer:
    """Tests for SpeechRecognizer class."""

    @pytest.fixture
    def recognizer(self) -> SpeechRecognizer:
        """Create speech recognizer."""
        return SpeechRecognizer()

    @pytest.fixture
    def audio_sample(self) -> AudioSample:
        """Create test audio sample."""
        sample_rate = 16000
        duration = 0.5
        t = np.arange(0, duration, 1 / sample_rate)
        data = np.sin(2 * np.pi * 200 * t).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    def test_recognize(self, recognizer: SpeechRecognizer, audio_sample: AudioSample) -> None:
        """Test speech recognition."""
        # Enroll a template first
        recognizer.template_recognizer.enroll_template("hello", audio_sample)

        result = recognizer.recognize(audio_sample)

        assert isinstance(result, TranscriptionResult)
        assert result.text is not None
        assert 0 <= result.confidence <= 1

    def test_recognize_returns_utterance(self, recognizer: SpeechRecognizer, audio_sample: AudioSample) -> None:
        """Test that recognition returns utterances."""
        recognizer.template_recognizer.enroll_template("hello", audio_sample)

        result = recognizer.recognize(audio_sample)

        assert len(result.utterances) > 0

    def test_calculate_wer_identical_sequences(self, recognizer: SpeechRecognizer) -> None:
        """Test WER for identical sequences."""
        hypothesis = ["hello", "world"]
        reference = ["hello", "world"]

        wer = recognizer.calculate_word_error_rate(hypothesis, reference)

        assert wer == 0.0

    def test_calculate_wer_completely_different(self, recognizer: SpeechRecognizer) -> None:
        """Test WER for completely different sequences."""
        hypothesis = ["foo", "bar"]
        reference = ["hello", "world"]

        wer = recognizer.calculate_word_error_rate(hypothesis, reference)

        assert wer > 0

    def test_calculate_wer_empty_reference(self, recognizer: SpeechRecognizer) -> None:
        """Test WER with empty reference."""
        hypothesis = ["hello"]
        reference: list = []

        wer = recognizer.calculate_word_error_rate(hypothesis, reference)

        assert wer == float("inf")

    def test_calculate_wer_insertion(self, recognizer: SpeechRecognizer) -> None:
        """Test WER with insertion error."""
        hypothesis = ["hello", "there", "world"]
        reference = ["hello", "world"]

        wer = recognizer.calculate_word_error_rate(hypothesis, reference)

        assert wer > 0

    def test_calculate_wer_deletion(self, recognizer: SpeechRecognizer) -> None:
        """Test WER with deletion error."""
        hypothesis = ["hello"]
        reference = ["hello", "there", "world"]

        wer = recognizer.calculate_word_error_rate(hypothesis, reference)

        assert wer > 0

    def test_calculate_wer_substitution(self, recognizer: SpeechRecognizer) -> None:
        """Test WER with substitution error."""
        hypothesis = ["hello", "universe"]
        reference = ["hello", "world"]

        wer = recognizer.calculate_word_error_rate(hypothesis, reference)

        assert wer > 0
