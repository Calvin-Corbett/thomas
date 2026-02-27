"""
Speech emotion recognition module.

Recognizes emotion from speech:
- Acoustic feature extraction
- Emotion classification (6 basic emotions + neutral)
- Arousal/valence estimation (2D emotion space)
- Speaker-dependent normalization
- Emotion tracking over time
"""

import numpy as np

from thomas.voice._exceptions import EmotionRecognitionError
from thomas.voice._types import (
    AudioSample,
    EmotionLabel,
)
from thomas.voice.features import FeatureExtractor
from thomas.voice.pitch import PitchDetector
from thomas.voice.vad import VoiceActivityDetector


class EmotionRecognizer:
    """Recognizes emotion from speech."""

    # Emotion mappings to arousal/valence
    EMOTION_SPACE = {
        EmotionLabel.NEUTRAL: (0.5, 0.5),
        EmotionLabel.HAPPINESS: (0.8, 0.8),
        EmotionLabel.SADNESS: (0.3, 0.2),
        EmotionLabel.ANGER: (0.9, 0.2),
        EmotionLabel.FEAR: (0.8, 0.3),
        EmotionLabel.SURPRISE: (0.7, 0.7),
        EmotionLabel.DISGUST: (0.6, 0.2),
    }

    def __init__(
        self,
        frame_size: int = 512,
        hop_size: int = 160,
    ) -> None:
        """
        Initialize emotion recognizer.

        Args:
            frame_size: Frame size in samples.
            hop_size: Hop size in samples.
        """
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.feature_extractor = FeatureExtractor(frame_size=frame_size, hop_size=hop_size)
        self.pitch_detector = PitchDetector(frame_size=frame_size, hop_size=hop_size)
        self.vad_detector = VoiceActivityDetector(frame_size=frame_size, hop_size=hop_size)

    def recognize_emotion(self, audio_sample: AudioSample) -> tuple[EmotionLabel, float, dict[str, float]]:
        """
        Recognize emotion in audio.

        Args:
            audio_sample: Audio sample.

        Returns:
            Tuple of (emotion_label, confidence, emotion_scores).

        Raises:
            EmotionRecognitionError: If recognition fails.
        """
        try:
            # Extract features
            features = self._extract_emotion_features(audio_sample)

            # Classify emotion
            emotion_scores = self._classify_emotion(features)

            # Get best emotion
            best_emotion = max(emotion_scores.items(), key=lambda x: x[1])
            best_label = EmotionLabel[best_emotion[0].upper()]
            best_score = best_emotion[1]

            return best_label, best_score, emotion_scores

        except EmotionRecognitionError:
            raise
        except Exception as e:
            raise EmotionRecognitionError(f"Emotion recognition failed: {str(e)}")

    def estimate_arousal_valence(self, audio_sample: AudioSample) -> tuple[float, float]:
        """
        Estimate continuous arousal and valence (2D emotion space).

        Args:
            audio_sample: Audio sample.

        Returns:
            Tuple of (arousal, valence) both in [0, 1].
        """
        features = self._extract_emotion_features(audio_sample)

        # Map features to arousal/valence
        arousal = self._estimate_arousal(features)
        valence = self._estimate_valence(features)

        return arousal, valence

    def track_emotion_over_time(
        self, audio_sample: AudioSample, segment_duration: float = 1.0
    ) -> list[tuple[float, EmotionLabel, float]]:
        """
        Track emotion changes throughout audio.

        Args:
            audio_sample: Audio sample.
            segment_duration: Duration of each segment in seconds.

        Returns:
            List of (timestamp, emotion, confidence) tuples.
        """
        sample_rate = audio_sample.sample_rate
        segment_samples = int(segment_duration * sample_rate)

        emotions = []

        for start_idx in range(0, len(audio_sample.data), segment_samples):
            end_idx = min(start_idx + segment_samples, len(audio_sample.data))

            segment_data = audio_sample.data[start_idx:end_idx]
            segment_audio = AudioSample(data=segment_data, sample_rate=sample_rate)

            emotion, confidence, _ = self.recognize_emotion(segment_audio)

            timestamp = start_idx / sample_rate

            emotions.append((timestamp, emotion, confidence))

        return emotions

    def _extract_emotion_features(self, audio_sample: AudioSample) -> dict[str, float]:
        """
        Extract acoustic features for emotion recognition.

        Args:
            audio_sample: Audio sample.

        Returns:
            Dictionary of acoustic features.
        """
        # Pitch features
        pitch_contour = self.pitch_detector.detect_pitch(audio_sample)
        pitch_stats = self.pitch_detector.get_pitch_statistics(pitch_contour)

        # Energy features
        energy = self.feature_extractor.extract_short_time_energy(audio_sample)

        # Speech rate
        vad_flags, segments = self.vad_detector.detect_voice_activity(audio_sample)
        speech_duration = self.vad_detector.get_speech_duration(segments)
        num_syllables = self._estimate_syllables(audio_sample)
        speech_rate = num_syllables / speech_duration if speech_duration > 0 else 0

        # Pause patterns
        pauses = self._analyze_pause_patterns(audio_sample)

        # MFCC features
        mfcc = self.feature_extractor.extract_mfcc(audio_sample)

        return {
            "pitch_mean": pitch_stats.get("mean", 0.0),
            "pitch_std": pitch_stats.get("std", 0.0),
            "pitch_range": pitch_stats.get("range", 0.0),
            "pitch_jitter": pitch_stats.get("jitter", 0.0),
            "energy_mean": float(np.mean(energy)),
            "energy_std": float(np.std(energy)),
            "energy_max": float(np.max(energy)),
            "speech_rate": speech_rate,
            "pause_frequency": pauses["frequency"],
            "pause_duration": pauses["avg_duration"],
            "mfcc_mean": float(np.mean(mfcc.coefficients)),
            "mfcc_std": float(np.std(mfcc.coefficients)),
        }

    def _classify_emotion(self, features: dict[str, float]) -> dict[str, float]:
        """
        Classify emotion from features.

        Uses rule-based mapping to basic emotions.

        Args:
            features: Acoustic features.

        Returns:
            Dictionary of emotion probabilities.
        """
        scores = {
            "happiness": 0.0,
            "sadness": 0.0,
            "anger": 0.0,
            "fear": 0.0,
            "surprise": 0.0,
            "disgust": 0.0,
            "neutral": 0.0,
        }

        pitch_mean = features.get("pitch_mean", 0.0)
        pitch_std = features.get("pitch_std", 0.0)
        energy_mean = features.get("energy_mean", 0.0)
        speech_rate = features.get("speech_rate", 0.0)

        # Happiness: high pitch, high energy, fast speech
        if pitch_mean > 120 and energy_mean > -30 and speech_rate > 4:
            scores["happiness"] = 0.8

        # Sadness: low pitch, low energy, slow speech
        if pitch_mean < 80 and energy_mean < -35 and speech_rate < 3:
            scores["sadness"] = 0.8

        # Anger: high pitch variability, high energy, fast speech
        if pitch_std > 40 and energy_mean > -25 and speech_rate > 4:
            scores["anger"] = 0.8

        # Fear: high pitch, variable pitch, fast speech
        if pitch_mean > 100 and pitch_std > 30 and speech_rate > 4:
            scores["fear"] = 0.7

        # Surprise: high pitch, high energy
        if pitch_mean > 130 and energy_mean > -25:
            scores["surprise"] = 0.7

        # Disgust: low pitch, low energy, irregular pauses
        if pitch_mean < 85 and energy_mean < -35:
            scores["disgust"] = 0.6

        # Neutral: moderate values
        if not any(v > 0.5 for v in scores.values()):
            scores["neutral"] = 0.7

        # Normalize
        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}
        else:
            scores["neutral"] = 1.0

        return scores

    def _estimate_arousal(self, features: dict[str, float]) -> float:
        """
        Estimate arousal level (activation).

        Args:
            features: Acoustic features.

        Returns:
            Arousal value [0, 1].
        """
        pitch_mean = features.get("pitch_mean", 0.0)
        energy_mean = features.get("energy_mean", 0.0)
        speech_rate = features.get("speech_rate", 0.0)

        # Normalize features
        pitch_norm = min(1.0, pitch_mean / 250.0)
        energy_norm = (energy_mean + 50) / 50.0  # Normalize from [-50, 0]
        rate_norm = min(1.0, speech_rate / 6.0)

        # Weighted average
        arousal = 0.3 * pitch_norm + 0.4 * energy_norm + 0.3 * rate_norm

        return float(max(0.0, min(1.0, arousal)))

    def _estimate_valence(self, features: dict[str, float]) -> float:
        """
        Estimate valence (pleasantness).

        Args:
            features: Acoustic features.

        Returns:
            Valence value [0, 1].
        """
        pitch_std = features.get("pitch_std", 0.0)
        energy_std = features.get("energy_std", 0.0)
        pause_frequency = features.get("pause_frequency", 0.0)

        # Smoothness indicates positive valence
        pitch_smoothness = 1.0 / (1.0 + pitch_std / 20.0)
        energy_smoothness = 1.0 / (1.0 + energy_std / 5.0)
        pause_smoothness = 1.0 / (1.0 + pause_frequency)

        # Weighted average
        valence = 0.4 * pitch_smoothness + 0.4 * energy_smoothness + 0.2 * pause_smoothness

        return float(max(0.0, min(1.0, valence)))

    def _analyze_pause_patterns(self, audio_sample: AudioSample) -> dict[str, float]:
        """
        Analyze pause patterns in speech.

        Args:
            audio_sample: Audio sample.

        Returns:
            Dictionary with pause statistics.
        """
        vad_flags, segments = self.vad_detector.detect_voice_activity(audio_sample)

        pauses = []
        for i in range(len(segments) - 1):
            gap = segments[i + 1].start_time - segments[i].end_time
            pauses.append(gap)

        return {
            "frequency": float(len(pauses) / audio_sample.duration) if audio_sample.duration > 0 else 0.0,
            "avg_duration": float(np.mean(pauses)) if pauses else 0.0,
        }

    def _estimate_syllables(self, audio_sample: AudioSample) -> int:
        """
        Estimate number of syllables.

        Args:
            audio_sample: Audio sample.

        Returns:
            Estimated syllable count.
        """
        energy = self.feature_extractor.extract_short_time_energy(audio_sample)

        threshold = np.mean(energy) + np.std(energy)
        peaks = 0

        for i in range(1, len(energy) - 1):
            if energy[i] > energy[i - 1] and energy[i] > energy[i + 1]:
                if energy[i] > threshold:
                    peaks += 1

        return max(1, peaks)
