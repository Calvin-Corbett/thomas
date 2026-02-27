"""
Prosody analysis module.

Analyzes prosodic features of speech:
- Intonation pattern detection
- Stress detection
- Speech rate calculation
- Pause detection and classification
- Rhythm analysis (PVI)
- ToBI-style annotation
- Emphasis detection
"""

import numpy as np

from thomas.voice._types import (
    AudioSample,
    PitchContour,
    ProsodicFeature,
)
from thomas.voice.features import FeatureExtractor
from thomas.voice.pitch import PitchDetector
from thomas.voice.vad import VoiceActivityDetector


class ProsodyAnalyzer:
    """Analyzes prosodic features of speech."""

    def __init__(
        self,
        frame_size: int = 512,
        hop_size: int = 160,
    ) -> None:
        """
        Initialize prosody analyzer.

        Args:
            frame_size: Frame size in samples.
            hop_size: Hop size in samples.
        """
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.feature_extractor = FeatureExtractor(frame_size=frame_size, hop_size=hop_size)
        self.pitch_detector = PitchDetector(frame_size=frame_size, hop_size=hop_size)
        self.vad_detector = VoiceActivityDetector(frame_size=frame_size, hop_size=hop_size)

    def analyze_intonation(self, pitch_contour: PitchContour) -> list[str]:
        """
        Detect intonation patterns.

        Patterns: rising, falling, rise-fall, fall-rise.

        Args:
            pitch_contour: Pitch contour.

        Returns:
            List of intonation patterns.
        """
        patterns = []

        voiced = pitch_contour.get_voiced_frames()
        if len(voiced) < 3:
            return patterns

        freqs = pitch_contour.frequency[voiced]

        # Overall trend
        first_third = np.mean(freqs[: len(freqs) // 3])
        last_third = np.mean(freqs[-len(freqs) // 3 :])

        if last_third > first_third * 1.1:
            patterns.append("rising")
        elif last_third < first_third * 0.9:
            patterns.append("falling")

        # Complex patterns
        mid = np.mean(freqs[len(freqs) // 3 : 2 * len(freqs) // 3])

        if first_third < mid > last_third:
            patterns.append("rise-fall")
        elif first_third > mid < last_third:
            patterns.append("fall-rise")

        return patterns

    def detect_stress(self, pitch_contour: PitchContour, audio_sample: AudioSample) -> list[tuple[float, float]]:
        """
        Detect stressed syllables.

        Uses pitch, energy, and duration features.

        Args:
            pitch_contour: Pitch contour.
            audio_sample: Audio sample.

        Returns:
            List of (start_time, end_time) tuples for stressed regions.
        """
        sample_rate = audio_sample.sample_rate

        # Extract energy
        energy = self.feature_extractor.extract_short_time_energy(audio_sample)

        # Normalize energy
        energy_norm = (energy - np.mean(energy)) / (np.std(energy) + 1e-10)

        # Normalize pitch
        voiced = pitch_contour.get_voiced_frames()
        if len(voiced) > 0:
            pitch_norm = (pitch_contour.frequency[voiced] - np.mean(pitch_contour.frequency[voiced])) / (
                np.std(pitch_contour.frequency[voiced]) + 1e-10
            )
        else:
            pitch_norm = np.array([])

        # Combined stress score
        stress_regions = []

        for i in range(len(energy_norm)):
            stress_score = energy_norm[i]

            # Add pitch contribution if available
            if i < len(pitch_contour.frequency) and pitch_contour.voicing[i] > 0.5:
                idx = np.where(voiced == i)[0]
                if len(idx) > 0:
                    pitch_contrib = pitch_norm[idx[0]]
                    stress_score += 0.3 * pitch_contrib

            # Mark high stress
            if stress_score > 0.5:
                start_time = (i * self.hop_size) / sample_rate
                end_time = ((i + 1) * self.hop_size) / sample_rate
                stress_regions.append((start_time, end_time))

        # Merge adjacent regions
        if not stress_regions:
            return []

        merged = [stress_regions[0]]
        for start, end in stress_regions[1:]:
            if start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))

        return merged

    def calculate_speech_rate(self, audio_sample: AudioSample, num_syllables: int | None = None) -> float:
        """
        Calculate speech rate.

        Default: syllables per second based on formant transitions.
        Can specify number of syllables for exact calculation.

        Args:
            audio_sample: Audio sample.
            num_syllables: Number of syllables (optional).

        Returns:
            Speech rate in words per minute (assuming 1.5 syllables/word).
        """
        vad_flags, segments = self.vad_detector.detect_voice_activity(audio_sample)
        speech_duration = self.vad_detector.get_speech_duration(segments)

        if speech_duration == 0:
            return 0.0

        if num_syllables is None:
            # Estimate syllables from phoneme transitions
            num_syllables = self._estimate_syllables(audio_sample)

        syllables_per_second = num_syllables / speech_duration
        words_per_minute = syllables_per_second * 60 / 1.5  # Avg 1.5 syllables/word

        return float(words_per_minute)

    def detect_pauses(
        self,
        audio_sample: AudioSample,
        min_pause_duration: float = 0.1,
    ) -> list[tuple[float, float, str]]:
        """
        Detect pauses in speech.

        Classifies as: breath pause, hesitation, syntactic.

        Args:
            audio_sample: Audio sample.
            min_pause_duration: Minimum pause duration in seconds.

        Returns:
            List of (start_time, end_time, pause_type) tuples.
        """
        vad_flags, segments = self.vad_detector.detect_voice_activity(audio_sample)

        pauses = []
        sample_rate = audio_sample.sample_rate

        # Gaps between speech segments
        for i in range(len(segments) - 1):
            gap_start = segments[i].end_time
            gap_end = segments[i + 1].start_time
            gap_duration = gap_end - gap_start

            if gap_duration >= min_pause_duration:
                # Classify pause type (simplified)
                if gap_duration < 0.3:
                    pause_type = "breath"
                elif gap_duration < 0.8:
                    pause_type = "hesitation"
                else:
                    pause_type = "syntactic"

                pauses.append((gap_start, gap_end, pause_type))

        return pauses

    def analyze_rhythm(self, audio_sample: AudioSample) -> float:
        """
        Analyze speech rhythm using PVI (Pairwise Variability Index).

        PVI measures consonant-vowel timing patterns.

        Args:
            audio_sample: Audio sample.

        Returns:
            PVI score (lower = more regular rhythm).
        """
        # Estimate durations of consonant-vowel sequences
        vad_flags, segments = self.vad_detector.detect_voice_activity(audio_sample)

        if not segments:
            return 0.0

        # Simplified: measure energy variations
        energy = self.feature_extractor.extract_short_time_energy(audio_sample)

        # Calculate variability
        if len(energy) < 2:
            return 0.0

        diffs = np.abs(np.diff(energy))
        pvi = float(np.mean(diffs))

        return pvi

    def get_prosodic_features(self, audio_sample: AudioSample) -> list[ProsodicFeature]:
        """
        Extract prosodic features for each time frame.

        Args:
            audio_sample: Audio sample.

        Returns:
            List of prosodic features.
        """
        sample_rate = audio_sample.sample_rate

        # Extract pitch
        pitch_contour = self.pitch_detector.detect_pitch(audio_sample)

        # Extract energy
        energy = self.feature_extractor.extract_short_time_energy(audio_sample)

        # Detect stress regions
        stress_regions = self.detect_stress(pitch_contour, audio_sample)

        features: list[ProsodicFeature] = []

        for i in range(len(pitch_contour.frequency)):
            timestamp = pitch_contour.timestamp[i]
            pitch = pitch_contour.frequency[i] if pitch_contour.voicing[i] > 0.5 else None

            is_stressed = any(start <= timestamp <= end for start, end in stress_regions)

            intonation = None
            if i == 0:
                intonation_patterns = self.analyze_intonation(pitch_contour)
                if intonation_patterns:
                    intonation = intonation_patterns[0]

            feature = ProsodicFeature(
                timestamp=timestamp,
                pitch=pitch,
                energy=energy[i] if i < len(energy) else None,
                is_stressed=is_stressed,
                intonation_type=intonation,
            )

            features.append(feature)

        return features

    def _estimate_syllables(self, audio_sample: AudioSample) -> int:
        """
        Estimate number of syllables in audio.

        Args:
            audio_sample: Audio sample.

        Returns:
            Estimated number of syllables.
        """
        # Count peaks in energy
        energy = self.feature_extractor.extract_short_time_energy(audio_sample)

        # Find peaks
        threshold = np.mean(energy) + np.std(energy)
        peaks = 0

        for i in range(1, len(energy) - 1):
            if energy[i] > energy[i - 1] and energy[i] > energy[i + 1]:
                if energy[i] > threshold:
                    peaks += 1

        return max(1, peaks)

    def detect_emphasis(self, audio_sample: AudioSample) -> list[tuple[float, float]]:
        """
        Detect emphasized words or syllables.

        Args:
            audio_sample: Audio sample.

        Returns:
            List of (start_time, end_time) tuples for emphasized regions.
        """
        stress_regions = self.detect_stress(self.pitch_detector.detect_pitch(audio_sample), audio_sample)

        # Emphasized regions have very high stress
        emphasized = [region for region in stress_regions if (region[1] - region[0]) > 0.1]

        return emphasized
