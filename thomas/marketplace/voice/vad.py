"""
Voice Activity Detection (VAD) module.

Detects speech vs. silence/noise:
- Energy-based VAD
- Zero-crossing rate VAD
- Spectral entropy VAD
- Hangover scheme for smooth transitions
- Noise estimation via minimum statistics
- Combined decision voting
"""

import numpy as np

from thomas.marketplace.voice._exceptions import VADError
from thomas.marketplace.voice._types import (
    AudioSample,
    VoiceActivitySegment,
)
from thomas.marketplace.voice.features import FeatureExtractor


class VoiceActivityDetector:
    """Detects voice activity in audio signals."""

    def __init__(
        self,
        frame_size: int = 512,
        hop_size: int = 160,
        energy_threshold_db: float = -40.0,
        zcr_threshold: float = 0.1,
        entropy_threshold: float = 0.5,
        hangover_duration: float = 0.3,
    ) -> None:
        """
        Initialize voice activity detector.

        Args:
            frame_size: Frame size in samples.
            hop_size: Hop size in samples.
            energy_threshold_db: Energy threshold in dB.
            zcr_threshold: Zero-crossing rate threshold.
            entropy_threshold: Spectral entropy threshold.
            hangover_duration: Hangover duration in seconds.
        """
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.energy_threshold_db = energy_threshold_db
        self.zcr_threshold = zcr_threshold
        self.entropy_threshold = entropy_threshold
        self.hangover_duration = hangover_duration
        self.feature_extractor = FeatureExtractor(frame_size=frame_size, hop_size=hop_size)

    def detect_voice_activity(
        self, audio_sample: AudioSample, method: str = "combined"
    ) -> tuple[np.ndarray, list[VoiceActivitySegment]]:
        """
        Detect voice activity in audio.

        Args:
            audio_sample: Audio sample.
            method: Detection method ('energy', 'zcr', 'entropy', 'combined').

        Returns:
            Tuple of (voice_activity_flags, speech_segments).
            Flags are True where speech is detected.

        Raises:
            VADError: If detection fails.
        """
        try:
            sample_rate = audio_sample.sample_rate

            if method == "energy":
                vad_flags = self._energy_based_vad(audio_sample)
            elif method == "zcr":
                vad_flags = self._zcr_based_vad(audio_sample)
            elif method == "entropy":
                vad_flags = self._entropy_based_vad(audio_sample)
            elif method == "combined":
                vad_flags = self._combined_vad(audio_sample)
            else:
                raise VADError(f"Unknown VAD method: {method}")

            # Apply hangover scheme
            vad_flags = self._apply_hangover(vad_flags, sample_rate)

            # Extract speech segments
            segments = self._extract_segments(audio_sample, vad_flags)

            return vad_flags, segments

        except VADError:
            raise
        except Exception as e:
            raise VADError(f"Voice activity detection failed: {str(e)}")

    def _energy_based_vad(self, audio_sample: AudioSample) -> np.ndarray:
        """
        Energy-based voice activity detection.

        Args:
            audio_sample: Audio sample.

        Returns:
            Boolean array of voice activity flags.
        """
        energy = self.feature_extractor.extract_short_time_energy(audio_sample)

        # Estimate noise energy using minimum statistics
        noise_energy = self._estimate_noise_energy(energy)

        # Adaptive threshold
        threshold = noise_energy + 10  # 10 dB above noise

        vad_flags = energy > threshold
        return vad_flags

    def _zcr_based_vad(self, audio_sample: AudioSample) -> np.ndarray:
        """
        Zero-crossing rate based voice activity detection.

        Args:
            audio_sample: Audio sample.

        Returns:
            Boolean array of voice activity flags.
        """
        zcr = self.feature_extractor.extract_zero_crossing_rate(audio_sample)

        # Estimate silence ZCR
        silence_zcr = np.percentile(zcr, 25)

        # Threshold
        threshold = silence_zcr + self.zcr_threshold

        vad_flags = zcr > threshold
        return vad_flags

    def _entropy_based_vad(self, audio_sample: AudioSample) -> np.ndarray:
        """
        Spectral entropy based voice activity detection.

        Args:
            audio_sample: Audio sample.

        Returns:
            Boolean array of voice activity flags.
        """
        mfcc = self.feature_extractor.extract_mfcc(audio_sample)

        entropy_values = np.zeros(mfcc.num_frames)

        for i in range(mfcc.num_frames):
            frame_coeff = mfcc.coefficients[i]
            # Normalize to probability-like values
            normalized = np.abs(frame_coeff) / (np.sum(np.abs(frame_coeff)) + 1e-10)
            # Shannon entropy
            entropy_values[i] = -np.sum(normalized * np.log(normalized + 1e-10))

        # Noise has lower entropy, speech has higher
        threshold = np.percentile(entropy_values, 50)
        vad_flags = entropy_values > threshold

        return vad_flags

    def _combined_vad(self, audio_sample: AudioSample) -> np.ndarray:
        """
        Combined VAD using voting from multiple methods.

        Args:
            audio_sample: Audio sample.

        Returns:
            Boolean array of voice activity flags.
        """
        energy_vad = self._energy_based_vad(audio_sample)
        zcr_vad = self._zcr_based_vad(audio_sample)
        entropy_vad = self._entropy_based_vad(audio_sample)

        # Ensure all have same length (take minimum)
        min_len = min(len(energy_vad), len(zcr_vad), len(entropy_vad))
        energy_vad = energy_vad[:min_len]
        zcr_vad = zcr_vad[:min_len]
        entropy_vad = entropy_vad[:min_len]

        # Majority voting: need at least 2 out of 3
        votes = energy_vad.astype(int) + zcr_vad.astype(int) + entropy_vad.astype(int)
        vad_flags = votes >= 2

        return vad_flags

    def _estimate_noise_energy(self, energy: np.ndarray, window_size: int = 5) -> float:
        """
        Estimate noise energy using minimum statistics.

        Args:
            energy: Energy values.
            window_size: Window size for minimum calculation.

        Returns:
            Estimated noise energy.
        """
        # Find local minima
        noise_estimate = np.percentile(energy, 10)  # Lowest 10th percentile
        return float(noise_estimate)

    def _apply_hangover(self, vad_flags: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        Apply hangover scheme to extend speech segments.

        Prevents choppy cuts and handles brief pauses within utterances.

        Args:
            vad_flags: Voice activity flags.
            sample_rate: Sample rate in Hz.

        Returns:
            Modified voice activity flags.
        """
        hangover_frames = int((self.hangover_duration * sample_rate) / self.hop_size)

        result = vad_flags.copy()
        num_frames = len(vad_flags)

        for i in range(num_frames):
            if vad_flags[i]:
                # Extend backward
                start = max(0, i - hangover_frames)
                result[start:i] = True

                # Extend forward
                end = min(num_frames, i + hangover_frames)
                result[i:end] = True

        return result

    def _extract_segments(self, audio_sample: AudioSample, vad_flags: np.ndarray) -> list[VoiceActivitySegment]:
        """
        Extract continuous speech segments.

        Args:
            audio_sample: Audio sample.
            vad_flags: Voice activity flags.

        Returns:
            List of speech segments.
        """
        segments: list[VoiceActivitySegment] = []
        sample_rate = audio_sample.sample_rate

        in_segment = False
        start_frame = 0

        for i, is_speech in enumerate(vad_flags):
            if is_speech and not in_segment:
                # Start of speech segment
                start_frame = i
                in_segment = True
            elif not is_speech and in_segment:
                # End of speech segment
                start_time = (start_frame * self.hop_size) / sample_rate
                end_time = (i * self.hop_size) / sample_rate

                # Get average energy in segment
                segment_audio = audio_sample.data[int(start_time * sample_rate) : int(end_time * sample_rate)]
                energy = float(np.mean(segment_audio**2))

                segments.append(
                    VoiceActivitySegment(
                        start_time=start_time,
                        end_time=end_time,
                        energy=energy,
                    )
                )

                in_segment = False

        # Handle trailing segment
        if in_segment:
            start_time = (start_frame * self.hop_size) / sample_rate
            end_time = len(vad_flags) * self.hop_size / sample_rate

            segment_audio = audio_sample.data[int(start_time * sample_rate) : int(end_time * sample_rate)]
            energy = float(np.mean(segment_audio**2))

            segments.append(
                VoiceActivitySegment(
                    start_time=start_time,
                    end_time=end_time,
                    energy=energy,
                )
            )

        return segments

    def get_speech_duration(self, segments: list[VoiceActivitySegment]) -> float:
        """
        Calculate total speech duration from segments.

        Args:
            segments: List of voice activity segments.

        Returns:
            Total speech duration in seconds.
        """
        return float(sum(seg.duration for seg in segments))

    def get_silence_rate(self, audio_sample: AudioSample, vad_flags: np.ndarray) -> float:
        """
        Calculate silence rate in audio.

        Args:
            audio_sample: Audio sample.
            vad_flags: Voice activity flags.

        Returns:
            Silence rate as a fraction [0, 1].
        """
        num_silence_frames = np.sum(~vad_flags)
        total_frames = len(vad_flags)

        if total_frames == 0:
            return 0.0

        return float(num_silence_frames / total_frames)
