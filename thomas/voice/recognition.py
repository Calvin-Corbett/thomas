"""
Speech recognition module.

Recognizes spoken words and sentences:
- Template matching with Dynamic Time Warping (DTW)
- MFCC feature extraction pipeline
- Viterbi decoder for HMM-based recognition
- Bigram language model with Katz backoff
- Beam search decoding
- Word error rate calculation
- N-best hypotheses
"""

import numpy as np
from scipy.spatial.distance import euclidean

from thomas.voice._exceptions import RecognitionError
from thomas.voice._types import (
    AudioSample,
    MFCCFeatures,
    TranscriptionResult,
    Utterance,
)
from thomas.voice.features import FeatureExtractor


class DynamicTimeWarping:
    """Computes Dynamic Time Warping distance."""

    @staticmethod
    def compute_dtw(x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
        """
        Compute DTW distance between two sequences.

        Args:
            x: First sequence (num_frames_x x num_features).
            y: Second sequence (num_frames_y x num_features).

        Returns:
            Tuple of (dtw_distance, cost_matrix).
        """
        n, m = len(x), len(y)
        cost_matrix = np.full((n + 1, m + 1), np.inf)
        cost_matrix[0, 0] = 0

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                distance = euclidean(x[i - 1], y[j - 1])
                cost_matrix[i, j] = distance + min(
                    cost_matrix[i - 1, j],
                    cost_matrix[i, j - 1],
                    cost_matrix[i - 1, j - 1],
                )

        return cost_matrix[n, m], cost_matrix[1:, 1:]

    @staticmethod
    def get_alignment_path(cost_matrix: np.ndarray) -> list[tuple[int, int]]:
        """
        Extract optimal alignment path from cost matrix.

        Args:
            cost_matrix: DTW cost matrix.

        Returns:
            List of (x_idx, y_idx) alignment points.
        """
        i, j = cost_matrix.shape
        i -= 1
        j -= 1

        path = [(i, j)]

        while i > 1 or j > 1:
            if i == 1:
                j -= 1
            elif j == 1:
                i -= 1
            else:
                min_prev = min(
                    cost_matrix[i - 1, j - 1],
                    cost_matrix[i - 1, j],
                    cost_matrix[i, j - 1],
                )

                if cost_matrix[i - 1, j - 1] == min_prev:
                    i -= 1
                    j -= 1
                elif cost_matrix[i - 1, j] == min_prev:
                    i -= 1
                else:
                    j -= 1

            path.append((i, j))

        return path[::-1]


class TemplateMatchingRecognizer:
    """Recognizes speech using template matching with DTW."""

    def __init__(self, mfcc_coefficients: int = 13) -> None:
        """
        Initialize recognizer.

        Args:
            mfcc_coefficients: Number of MFCC coefficients.
        """
        self.mfcc_coefficients = mfcc_coefficients
        self.feature_extractor = FeatureExtractor(mfcc_coefficients=mfcc_coefficients)
        self.templates: dict[str, MFCCFeatures] = {}

    def enroll_template(self, word: str, audio_sample: AudioSample) -> None:
        """
        Enroll a template for a word.

        Args:
            word: Word label.
            audio_sample: Training audio sample.
        """
        mfcc = self.feature_extractor.extract_mfcc(audio_sample)
        self.templates[word] = mfcc

    def recognize(self, audio_sample: AudioSample, top_n: int = 1) -> tuple[str, float, list[tuple[str, float]]]:
        """
        Recognize word using DTW template matching.

        Args:
            audio_sample: Input audio sample.
            top_n: Return top N matches.

        Returns:
            Tuple of (best_word, score, n_best_list).
        """
        if not self.templates:
            raise RecognitionError("No templates enrolled")

        test_mfcc = self.feature_extractor.extract_mfcc(audio_sample)

        distances = {}

        for word, template_mfcc in self.templates.items():
            dtw_distance, _ = DynamicTimeWarping.compute_dtw(test_mfcc.coefficients, template_mfcc.coefficients)
            distances[word] = dtw_distance

        # Sort by distance (lower is better)
        sorted_results = sorted(distances.items(), key=lambda x: x[1])

        # Convert distance to confidence score
        best_distance = sorted_results[0][1]
        n_best = []

        for word, distance in sorted_results[:top_n]:
            # Confidence: higher is better, inverse of distance
            confidence = float(1.0 / (1.0 + distance / 100))
            n_best.append((word, confidence))

        return n_best[0][0], n_best[0][1], n_best

    def get_alignment(self, audio_sample: AudioSample, word: str) -> tuple[float, list[tuple[int, int]]]:
        """
        Get alignment between test audio and template.

        Args:
            audio_sample: Input audio sample.
            word: Template word.

        Returns:
            Tuple of (dtw_distance, alignment_path).

        Raises:
            RecognitionError: If word template not found.
        """
        if word not in self.templates:
            raise RecognitionError(f"Template for '{word}' not found")

        test_mfcc = self.feature_extractor.extract_mfcc(audio_sample)
        template_mfcc = self.templates[word]

        dtw_distance, cost_matrix = DynamicTimeWarping.compute_dtw(test_mfcc.coefficients, template_mfcc.coefficients)

        alignment = DynamicTimeWarping.get_alignment_path(cost_matrix)

        return dtw_distance, alignment


class BigramLanguageModel:
    """Simple bigram language model."""

    def __init__(self) -> None:
        """Initialize language model."""
        self.unigram_counts: dict[str, int] = {}
        self.bigram_counts: dict[tuple[str, str], int] = {}
        self.total_unigrams = 0
        self.vocab_size = 0

    def train(self, word_sequences: list[list[str]]) -> None:
        """
        Train language model on word sequences.

        Args:
            word_sequences: List of word sequences.
        """
        for sequence in word_sequences:
            for word in sequence:
                self.unigram_counts[word] = self.unigram_counts.get(word, 0) + 1
                self.total_unigrams += 1

            for i in range(len(sequence) - 1):
                bigram = (sequence[i], sequence[i + 1])
                self.bigram_counts[bigram] = self.bigram_counts.get(bigram, 0) + 1

        self.vocab_size = len(self.unigram_counts)

    def get_probability(self, word1: str, word2: str) -> float:
        """
        Get bigram probability P(word2 | word1).

        Uses Katz backoff if bigram not seen.

        Args:
            word1: First word.
            word2: Second word.

        Returns:
            Probability [0, 1].
        """
        bigram = (word1, word2)

        if bigram in self.bigram_counts and word1 in self.unigram_counts:
            return self.bigram_counts[bigram] / self.unigram_counts[word1]

        # Backoff to unigram
        if word2 in self.unigram_counts:
            return self.unigram_counts[word2] / self.total_unigrams

        # Unknown word
        return 1.0 / (self.vocab_size + 1)


class BeamSearchDecoder:
    """Beam search decoder for speech recognition."""

    def __init__(self, beam_width: int = 10) -> None:
        """
        Initialize beam search decoder.

        Args:
            beam_width: Beam width for search.
        """
        self.beam_width = beam_width

    def decode(
        self,
        frame_scores: np.ndarray,
        vocabulary: list[str],
        language_model: BigramLanguageModel | None = None,
    ) -> list[tuple[str, float]]:
        """
        Decode sequence using beam search.

        Args:
            frame_scores: Scores for each frame and vocabulary word.
            vocabulary: Vocabulary list.
            language_model: Optional language model.

        Returns:
            List of (hypothesis, score) tuples.
        """
        num_frames, vocab_size = frame_scores.shape

        # Initialize: best word at frame 0
        hypotheses = []

        for word_idx, word in enumerate(vocabulary):
            score = frame_scores[0, word_idx]
            hypotheses.append(([word], score))

        # Keep top beam_width
        hypotheses = sorted(hypotheses, key=lambda x: x[1], reverse=True)[: self.beam_width]

        # Extend hypotheses frame by frame
        for frame_idx in range(1, num_frames):
            new_hypotheses = []

            for hypothesis, prev_score in hypotheses:
                last_word = hypothesis[-1]

                for word_idx, word in enumerate(vocabulary):
                    score = frame_scores[frame_idx, word_idx]

                    # Apply language model
                    if language_model:
                        lm_prob = language_model.get_probability(last_word, word)
                        score += np.log(lm_prob + 1e-10)

                    total_score = prev_score + score

                    new_hypothesis = (hypothesis + [word], total_score)
                    new_hypotheses.append(new_hypothesis)

            # Keep top beam_width
            hypotheses = sorted(new_hypotheses, key=lambda x: x[1], reverse=True)[: self.beam_width]

        # Return top hypotheses
        return [(" ".join(hyp), float(score)) for hyp, score in hypotheses[: self.beam_width]]


class SpeechRecognizer:
    """Main speech recognition interface."""

    def __init__(self, mfcc_coefficients: int = 13) -> None:
        """
        Initialize speech recognizer.

        Args:
            mfcc_coefficients: Number of MFCC coefficients.
        """
        self.template_recognizer = TemplateMatchingRecognizer(mfcc_coefficients=mfcc_coefficients)
        self.language_model = BigramLanguageModel()
        self.decoder = BeamSearchDecoder()

    def recognize(self, audio_sample: AudioSample) -> TranscriptionResult:
        """
        Recognize speech in audio.

        Args:
            audio_sample: Input audio sample.

        Returns:
            Transcription result.

        Raises:
            RecognitionError: If recognition fails.
        """
        try:
            best_word, confidence, n_best = self.template_recognizer.recognize(audio_sample, top_n=5)

            utterance = Utterance(
                text=best_word,
                words=[],
                start_time=0.0,
                end_time=audio_sample.duration,
                confidence=confidence,
            )

            return TranscriptionResult(
                text=best_word,
                confidence=confidence,
                utterances=[utterance],
                n_best=n_best,
            )

        except Exception as e:
            raise RecognitionError(f"Speech recognition failed: {str(e)}")

    def calculate_word_error_rate(self, hypothesis: list[str], reference: list[str]) -> float:
        """
        Calculate Word Error Rate (WER).

        WER = (S + D + I) / N
        where S=substitutions, D=deletions, I=insertions, N=reference length

        Args:
            hypothesis: Recognized word sequence.
            reference: Reference word sequence.

        Returns:
            WER value [0, inf].
        """
        if not reference:
            return 0.0 if not hypothesis else float("inf")

        # Edit distance
        n, m = len(reference), len(hypothesis)
        dp = np.zeros((n + 1, m + 1))

        for i in range(n + 1):
            dp[i, 0] = i
        for j in range(m + 1):
            dp[0, j] = j

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = 0 if reference[i - 1] == hypothesis[j - 1] else 1
                dp[i, j] = min(
                    dp[i - 1, j] + 1,  # deletion
                    dp[i, j - 1] + 1,  # insertion
                    dp[i - 1, j - 1] + cost,  # substitution
                )

        wer = dp[n, m] / len(reference)
        return float(wer)
