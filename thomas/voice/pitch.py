"""
Pitch detection and tracking module.

Detects and tracks fundamental frequency:
- Autocorrelation method with parabolic interpolation
- Harmonic Product Spectrum (HPS)
- Cepstral pitch detection
- Pitch tracking via dynamic programming
- Octave jump correction
- Pitch contour smoothing
"""

import numpy as np

from thomas.voice._exceptions import PitchDetectionError
from thomas.voice._types import (
    AudioSample,
    PitchContour,
)
from thomas.voice.features import FeatureExtractor


class PitchDetector:
    """Detects and tracks pitch (fundamental frequency)."""

    DEFAULT_MIN_PITCH: float = 50.0
    DEFAULT_MAX_PITCH: float = 500.0
    DEFAULT_FRAME_SIZE: int = 512
    DEFAULT_HOP_SIZE: int = 160

    def __init__(
        self,
        min_pitch: float = DEFAULT_MIN_PITCH,
        max_pitch: float = DEFAULT_MAX_PITCH,
        frame_size: int = DEFAULT_FRAME_SIZE,
        hop_size: int = DEFAULT_HOP_SIZE,
    ) -> None:
        """
        Initialize pitch detector.

        Args:
            min_pitch: Minimum expected pitch in Hz.
            max_pitch: Maximum expected pitch in Hz.
            frame_size: Frame size in samples.
            hop_size: Hop size in samples.
        """
        self.min_pitch = min_pitch
        self.max_pitch = max_pitch
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.feature_extractor = FeatureExtractor(frame_size=frame_size, hop_size=hop_size)

    def detect_pitch(self, audio_sample: AudioSample, method: str = "autocorrelation") -> PitchContour:
        """
        Detect pitch throughout audio.

        Args:
            audio_sample: Audio sample.
            method: Detection method ('autocorrelation', 'hps', 'cepstral').

        Returns:
            Pitch contour with frequency, timing, and voicing.

        Raises:
            PitchDetectionError: If detection fails.
        """
        try:
            sample_rate = audio_sample.sample_rate

            if method == "autocorrelation":
                pitch_freq, voicing = self._autocorrelation_pitch(audio_sample)
            elif method == "hps":
                pitch_freq, voicing = self._hps_pitch(audio_sample)
            elif method == "cepstral":
                pitch_freq, voicing = self._cepstral_pitch(audio_sample)
            else:
                raise PitchDetectionError(f"Unknown pitch method: {method}")

            # Track and smooth pitch contour
            pitch_freq = self._track_pitch_contour(pitch_freq, voicing, sample_rate)
            pitch_freq = self._smooth_contour(pitch_freq, voicing)

            # Generate timestamps
            num_frames = len(pitch_freq)
            timestamps = np.arange(num_frames) * self.hop_size / sample_rate

            return PitchContour(
                frequency=pitch_freq,
                timestamp=timestamps,
                voicing=voicing,
            )

        except PitchDetectionError:
            raise
        except Exception as e:
            raise PitchDetectionError(f"Pitch detection failed: {str(e)}")

    def _autocorrelation_pitch(self, audio_sample: AudioSample) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect pitch using autocorrelation method.

        Args:
            audio_sample: Audio sample.

        Returns:
            Tuple of (pitch_frequency, voicing_probability).
        """
        audio = audio_sample.data
        sample_rate = audio_sample.sample_rate

        # Apply pre-emphasis
        emphasized = audio.copy()
        emphasized[1:] -= 0.97 * audio[:-1]

        # Frame blocking
        frames = self._frame_audio(emphasized, sample_rate)

        pitch_freq = np.zeros(len(frames))
        voicing = np.zeros(len(frames))

        for i, frame in enumerate(frames):
            # Autocorrelation
            autocorr = self._autocorrelation(frame)

            # Find lag of fundamental
            min_lag = int(sample_rate / self.max_pitch)
            max_lag = int(sample_rate / self.min_pitch)

            # Normalized autocorrelation
            normalized_acf = autocorr / (autocorr[0] + 1e-10)

            # Find peaks in ACF
            peak_region = normalized_acf[min_lag:max_lag]

            if len(peak_region) > 0:
                peak_idx = np.argmax(peak_region) + min_lag

                # Parabolic interpolation for sub-sample accuracy
                if min_lag < peak_idx < max_lag - 1:
                    y1 = normalized_acf[peak_idx - 1]
                    y2 = normalized_acf[peak_idx]
                    y3 = normalized_acf[peak_idx + 1]

                    # Parabolic peak interpolation
                    offset = (y3 - y1) / (2 * (2 * y2 - y1 - y3) + 1e-10)
                    peak_idx = peak_idx + offset

                pitch_freq[i] = sample_rate / peak_idx
                voicing[i] = min(1.0, max(0.0, normalized_acf[int(peak_idx)]))
            else:
                pitch_freq[i] = 0.0
                voicing[i] = 0.0

        return pitch_freq, voicing

    def _hps_pitch(self, audio_sample: AudioSample) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect pitch using Harmonic Product Spectrum.

        Args:
            audio_sample: Audio sample.

        Returns:
            Tuple of (pitch_frequency, voicing_probability).
        """
        audio = audio_sample.data
        sample_rate = audio_sample.sample_rate

        frames = self._frame_audio(audio, sample_rate)

        pitch_freq = np.zeros(len(frames))
        voicing = np.zeros(len(frames))

        for i, frame in enumerate(frames):
            # FFT
            fft = np.abs(np.fft.fft(frame))
            fft = fft[: len(frame) // 2 + 1]

            # HPS: multiply spectrum with downsampled versions
            hps = fft.copy()

            for harmonic in range(2, 4):
                downsampled = np.zeros(len(fft))
                for j in range(len(fft) // harmonic):
                    downsampled[j * harmonic] = fft[j]
                hps *= downsampled + 1e-10

            # Find peak (fundamental frequency)
            min_bin = int(sample_rate / self.max_pitch / (sample_rate / len(frame)))
            max_bin = int(sample_rate / self.min_pitch / (sample_rate / len(frame)))

            if min_bin < max_bin and max_bin < len(hps):
                peak_bin = np.argmax(hps[min_bin:max_bin]) + min_bin
                pitch_freq[i] = peak_bin * sample_rate / len(frame)
                voicing[i] = min(1.0, hps[peak_bin] / np.max(hps + 1e-10))
            else:
                pitch_freq[i] = 0.0
                voicing[i] = 0.0

        return pitch_freq, voicing

    def _cepstral_pitch(self, audio_sample: AudioSample) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect pitch using cepstral analysis.

        Args:
            audio_sample: Audio sample.

        Returns:
            Tuple of (pitch_frequency, voicing_probability).
        """
        audio = audio_sample.data
        sample_rate = audio_sample.sample_rate

        frames = self._frame_audio(audio, sample_rate)

        pitch_freq = np.zeros(len(frames))
        voicing = np.zeros(len(frames))

        for i, frame in enumerate(frames):
            # Power spectrum
            fft = np.abs(np.fft.fft(frame))
            power = fft**2

            # Log magnitude spectrum
            log_power = np.log(power + 1e-10)

            # Cepstrum (inverse FFT of log spectrum)
            cepstrum = np.fft.ifft(log_power).real

            # Lifter to suppress low cepstral coefficients (remove formants)
            min_lag = int(sample_rate / self.max_pitch)
            max_lag = int(sample_rate / self.min_pitch)

            if max_lag < len(cepstrum):
                peak_region = cepstrum[min_lag:max_lag]
                peak_lag = np.argmax(peak_region) + min_lag

                pitch_freq[i] = sample_rate / peak_lag
                voicing[i] = min(1.0, peak_region.max() / (np.std(cepstrum) + 1e-10))
            else:
                pitch_freq[i] = 0.0
                voicing[i] = 0.0

        return pitch_freq, voicing

    def _frame_audio(self, audio: np.ndarray, sample_rate: int) -> list[np.ndarray]:
        """
        Frame audio signal.

        Args:
            audio: Audio signal.
            sample_rate: Sample rate in Hz.

        Returns:
            List of audio frames.
        """
        frames = []
        for i in range(0, len(audio) - self.frame_size + 1, self.hop_size):
            frame = audio[i : i + self.frame_size]
            frames.append(frame)
        return frames

    def _autocorrelation(self, signal: np.ndarray, max_lag: int | None = None) -> np.ndarray:
        """
        Calculate autocorrelation of signal.

        Args:
            signal: Input signal.
            max_lag: Maximum lag to compute.

        Returns:
            Autocorrelation values.
        """
        if max_lag is None:
            max_lag = len(signal)

        autocorr = np.zeros(max_lag)
        for lag in range(max_lag):
            autocorr[lag] = np.sum(signal[: -lag or None] * signal[lag:])

        return autocorr

    def _track_pitch_contour(self, pitch_freq: np.ndarray, voicing: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        Track pitch contour using dynamic programming.

        Corrects octave jumps and smooths transitions.

        Args:
            pitch_freq: Pitch frequency contour.
            voicing: Voicing probability.
            sample_rate: Sample rate in Hz.

        Returns:
            Corrected pitch contour.
        """
        result = pitch_freq.copy()

        # Octave jump correction
        for i in range(1, len(result)):
            if result[i] > 0 and result[i - 1] > 0:
                # Check for octave jumps
                ratio = result[i] / (result[i - 1] + 1e-10)

                if ratio > 1.5:  # Jump up
                    # Try octave down
                    if result[i] / 2 > self.min_pitch:
                        result[i] = result[i] / 2
                elif ratio < 0.67:  # Jump down
                    # Try octave up
                    if result[i] * 2 < self.max_pitch:
                        result[i] = result[i] * 2

        return result

    def _smooth_contour(self, pitch_freq: np.ndarray, voicing: np.ndarray, window: int = 5) -> np.ndarray:
        """
        Smooth pitch contour using median filtering.

        Args:
            pitch_freq: Pitch frequency contour.
            voicing: Voicing probability.
            window: Filter window size.

        Returns:
            Smoothed pitch contour.
        """
        result = pitch_freq.copy()

        for i in range(len(result)):
            if voicing[i] > 0.5:  # Only smooth voiced frames
                start = max(0, i - window // 2)
                end = min(len(result), i + window // 2 + 1)

                voiced_region = result[start:end]
                voiced_region = voiced_region[voiced_region > 0]

                if len(voiced_region) > 0:
                    result[i] = np.median(voiced_region)

        return result

    def get_pitch_statistics(self, pitch_contour: PitchContour) -> dict:
        """
        Calculate statistics from pitch contour.

        Args:
            pitch_contour: Pitch contour.

        Returns:
            Dictionary of statistics (mean, range, jitter, etc.).
        """
        voiced = pitch_contour.get_voiced_frames(threshold=0.5)

        if len(voiced) == 0:
            return {
                "mean": 0.0,
                "min": 0.0,
                "max": 0.0,
                "range": 0.0,
                "std": 0.0,
                "jitter": 0.0,
            }

        freqs = pitch_contour.frequency[voiced]

        # Jitter: frame-to-frame pitch variations
        pitch_diffs = np.abs(np.diff(freqs))
        jitter = float(np.mean(pitch_diffs) / np.mean(freqs + 1e-10))

        return {
            "mean": float(np.mean(freqs)),
            "min": float(np.min(freqs)),
            "max": float(np.max(freqs)),
            "range": float(np.max(freqs) - np.min(freqs)),
            "std": float(np.std(freqs)),
            "jitter": jitter,
        }
