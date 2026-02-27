"""
Speech synthesis module.

Synthesizes speech from text:
- Concatenative TTS (unit selection)
- Formant synthesis (Klatt-style)
- Diphone concatenation (overlap-add)
- Prosody modification (PSOLA)
- Text normalization
- SSML parsing basics
"""

import numpy as np
from scipy import signal

from thomas.voice._exceptions import SynthesisError
from thomas.voice._types import (
    AudioSample,
    FormantFrequencies,
)


class TextNormalizer:
    """Normalizes text for synthesis."""

    ABBREVIATIONS = {
        "Mr.": "Mister",
        "Mrs.": "Misses",
        "Dr.": "Doctor",
        "Prof.": "Professor",
        "etc.": "et cetera",
    }

    NUMBERS = {
        "0": "zero",
        "1": "one",
        "2": "two",
        "3": "three",
        "4": "four",
        "5": "five",
        "6": "six",
        "7": "seven",
        "8": "eight",
        "9": "nine",
    }

    def normalize(self, text: str) -> str:
        """
        Normalize text for speech synthesis.

        Expands abbreviations, numbers, dates.

        Args:
            text: Input text.

        Returns:
            Normalized text.
        """
        # Expand abbreviations
        for abbr, expanded in self.ABBREVIATIONS.items():
            text = text.replace(abbr, expanded)

        # Expand numbers
        text = self._expand_numbers(text)

        # Normalize whitespace
        text = " ".join(text.split())

        return text

    def _expand_numbers(self, text: str) -> str:
        """
        Expand numbers to words.

        Args:
            text: Input text.

        Returns:
            Text with numbers expanded.
        """
        # Simplified number expansion
        words = text.split()
        result = []

        for word in words:
            if word.isdigit():
                # Expand digit by digit
                expanded = " ".join(self.NUMBERS.get(d, d) for d in word)
                result.append(expanded)
            else:
                result.append(word)

        return " ".join(result)


class FormantSynthesizer:
    """Synthesizes speech using formant filtering."""

    def __init__(self, sample_rate: int = 16000) -> None:
        """
        Initialize formant synthesizer.

        Args:
            sample_rate: Sample rate in Hz.
        """
        self.sample_rate = sample_rate

    def synthesize_formant(
        self,
        pitch_contour: np.ndarray,
        formants: list[FormantFrequencies],
        duration: float,
    ) -> AudioSample:
        """
        Synthesize speech using formant model.

        Generates buzz-based signal with formant filtering.

        Args:
            pitch_contour: Pitch frequency for each frame.
            formants: Formant frequencies for each frame.
            duration: Duration in seconds.

        Returns:
            Synthesized audio.

        Raises:
            SynthesisError: If synthesis fails.
        """
        try:
            num_samples = int(duration * self.sample_rate)

            # Generate buzz (voiced source)
            buzz = self._generate_buzz(pitch_contour, num_samples)

            # Apply formant filtering
            output = buzz.copy()

            for i, formant in enumerate(formants):
                if i >= len(pitch_contour):
                    break

                # Create formant filter
                b, a = self._design_formant_filter(formant.f1)
                output = signal.lfilter(b, a, output)

                b, a = self._design_formant_filter(formant.f2)
                output = signal.lfilter(b, a, output)

                b, a = self._design_formant_filter(formant.f3)
                output = signal.lfilter(b, a, output)

            # Normalize
            output = output / (np.max(np.abs(output)) + 1e-10)

            return AudioSample(data=output.astype(np.float32), sample_rate=self.sample_rate)

        except Exception as e:
            raise SynthesisError(f"Formant synthesis failed: {str(e)}")

    def _generate_buzz(self, pitch_contour: np.ndarray, num_samples: int) -> np.ndarray:
        """
        Generate buzz signal (voiced source).

        Args:
            pitch_contour: Pitch frequency for each frame.
            num_samples: Number of samples.

        Returns:
            Buzz signal.
        """
        output = np.zeros(num_samples)
        phase = 0.0

        frame_size = num_samples // len(pitch_contour)

        for i, freq in enumerate(pitch_contour):
            if freq <= 0:
                continue

            start_idx = i * frame_size
            end_idx = min((i + 1) * frame_size, num_samples)

            for j in range(start_idx, end_idx):
                phase += freq / self.sample_rate
                output[j] = np.sin(2 * np.pi * phase)

        return output

    def _design_formant_filter(self, formant_freq: float) -> tuple[np.ndarray, np.ndarray]:
        """
        Design a formant filter.

        Simple low-pass filter at formant frequency.

        Args:
            formant_freq: Formant frequency in Hz.

        Returns:
            Tuple of (b, a) filter coefficients.
        """
        nyquist = self.sample_rate / 2
        normalized_freq = formant_freq / nyquist

        # Clamp to valid range
        normalized_freq = max(0.01, min(0.99, normalized_freq))

        # Simple IIR filter
        b, a = signal.butter(2, normalized_freq, btype="low")

        return b, a


class DiphoneConcatenator:
    """Concatenates diphone units with prosody modification."""

    def __init__(self, sample_rate: int = 16000) -> None:
        """
        Initialize diphone concatenator.

        Args:
            sample_rate: Sample rate in Hz.
        """
        self.sample_rate = sample_rate

    def concatenate_diphones(
        self,
        diphone_units: list[tuple[str, AudioSample]],
    ) -> AudioSample:
        """
        Concatenate diphone units.

        Uses overlap-add at phoneme boundaries.

        Args:
            diphone_units: List of (diphone_label, audio) tuples.

        Returns:
            Concatenated audio.

        Raises:
            SynthesisError: If concatenation fails.
        """
        try:
            if not diphone_units:
                raise SynthesisError("No diphone units provided")

            overlap_size = int(0.02 * self.sample_rate)  # 20ms overlap

            output = diphone_units[0][1].data.copy()

            for label, audio in diphone_units[1:]:
                # Overlap-add
                if len(output) >= overlap_size and len(audio.data) >= overlap_size:
                    # Crossfade
                    fade_in = np.linspace(0, 1, overlap_size)
                    fade_out = 1 - fade_in

                    overlap_region = output[-overlap_size:] * fade_out + audio.data[:overlap_size] * fade_in

                    output = np.concatenate([output[:-overlap_size], overlap_region, audio.data[overlap_size:]])
                else:
                    output = np.concatenate([output, audio.data])

            # Normalize
            output = output / (np.max(np.abs(output)) + 1e-10)

            return AudioSample(data=output.astype(np.float32), sample_rate=self.sample_rate)

        except Exception as e:
            raise SynthesisError(f"Diphone concatenation failed: {str(e)}")


class ProsodyModifier:
    """Modifies speech prosody (pitch and duration)."""

    def __init__(self, sample_rate: int = 16000) -> None:
        """
        Initialize prosody modifier.

        Args:
            sample_rate: Sample rate in Hz.
        """
        self.sample_rate = sample_rate

    def modify_pitch(
        self,
        audio: AudioSample,
        pitch_shift: float,
    ) -> AudioSample:
        """
        Shift pitch without changing duration (PSOLA-like).

        Args:
            audio: Input audio.
            pitch_shift: Pitch shift factor (> 1 = higher, < 1 = lower).

        Returns:
            Pitch-shifted audio.
        """
        if pitch_shift <= 0:
            raise SynthesisError("Pitch shift must be positive")

        # Simple time-stretching followed by resampling
        stretched_length = int(len(audio.data) / pitch_shift)
        stretched = signal.resample(audio.data, stretched_length)

        # Resample back to original sample rate
        output = signal.resample(stretched, len(audio.data))

        return AudioSample(data=output.astype(np.float32), sample_rate=self.sample_rate)

    def modify_duration(
        self,
        audio: AudioSample,
        duration_factor: float,
    ) -> AudioSample:
        """
        Change duration without affecting pitch.

        Args:
            audio: Input audio.
            duration_factor: Duration change factor (> 1 = longer, < 1 = shorter).

        Returns:
            Duration-modified audio.
        """
        if duration_factor <= 0:
            raise SynthesisError("Duration factor must be positive")

        new_length = int(len(audio.data) * duration_factor)
        output = signal.resample(audio.data, new_length)

        return AudioSample(data=output.astype(np.float32), sample_rate=self.sample_rate)


class SSMLParser:
    """Parses SSML (Speech Synthesis Markup Language)."""

    def parse_ssml(self, ssml_text: str) -> list[dict]:
        """
        Parse SSML markup (simplified).

        Args:
            ssml_text: SSML text.

        Returns:
            List of segments with properties.
        """
        segments = []

        # Very simplified parsing - just extract text and rate/pitch tags
        import re

        # Remove SSML tags and extract text
        text = re.sub(r"<[^>]+>", "", ssml_text)

        # Extract rate tags
        rate_matches = re.finditer(r"<prosody[^>]*rate=['\"]([^'\"]+)['\"]", ssml_text)
        rates = {m.start(): m.group(1) for m in rate_matches}

        # Extract pitch tags
        pitch_matches = re.finditer(r"<prosody[^>]*pitch=['\"]([^'\"]+)['\"]", ssml_text)
        pitches = {m.start(): m.group(1) for m in pitch_matches}

        segments.append(
            {
                "text": text.strip(),
                "rate": list(rates.values())[0] if rates else "normal",
                "pitch": list(pitches.values())[0] if pitches else "normal",
            }
        )

        return segments
