"""
Audio analysis including FFT, spectrogram, pitch detection, and onset detection.

Implements frequency domain analysis with various detection algorithms.
"""

import numpy as np
from numpy.typing import NDArray


class SpectrumAnalyzer:
    """FFT-based spectrum analyzer with windowing.

    Attributes:
        fft_size: FFT size in samples
        window_type: Window function ("hann", "hamming", "blackman")
        sample_rate: Sample rate in Hz
    """

    def __init__(self, fft_size: int = 2048, window_type: str = "hann", sample_rate: int = 44100) -> None:
        """Initialize spectrum analyzer.

        Args:
            fft_size: FFT size
            window_type: Window function type
            sample_rate: Sample rate in Hz
        """
        self.fft_size = fft_size
        self.window_type = window_type
        self.sample_rate = sample_rate
        self.window = self._create_window()

    def _create_window(self) -> NDArray[np.float32]:
        """Create window function.

        Returns:
            Window values
        """
        if self.window_type == "hann":
            return np.hanning(self.fft_size).astype(np.float32)
        elif self.window_type == "hamming":
            return np.hamming(self.fft_size).astype(np.float32)
        elif self.window_type == "blackman":
            return np.blackman(self.fft_size).astype(np.float32)
        else:
            return np.ones(self.fft_size, dtype=np.float32)

    def analyze(self, samples: NDArray[np.float32]) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """Analyze spectrum of samples.

        Args:
            samples: Audio samples

        Returns:
            Tuple of (frequencies, magnitudes_db)
        """
        # Ensure correct length
        if len(samples) < self.fft_size:
            samples = np.pad(samples, (0, self.fft_size - len(samples)))
        else:
            samples = samples[: self.fft_size]

        # Apply window
        windowed = samples * self.window

        # FFT
        spectrum = np.fft.rfft(windowed)
        magnitude = np.abs(spectrum)
        magnitude_db = 20.0 * np.log10(magnitude + 1e-6)

        # Frequencies
        frequencies = np.fft.rfftfreq(self.fft_size, 1.0 / self.sample_rate)

        return frequencies, magnitude_db

    def find_peaks(
        self,
        magnitude_db: NDArray[np.float32],
        threshold_db: float = -40.0,
        threshold: float | None = None,
    ) -> list[int]:
        """Find peaks in frequency spectrum.

        Args:
            magnitude_db: Magnitude spectrum in dB
            threshold_db: Threshold in dB
            threshold: Backward-compatible alias for threshold_db

        Returns:
            List of peak bin indices
        """
        if threshold is not None:
            threshold_db = threshold

        peaks = []
        for i in range(1, len(magnitude_db) - 1):
            if (
                magnitude_db[i] > threshold_db
                and magnitude_db[i] > magnitude_db[i - 1]
                and magnitude_db[i] > magnitude_db[i + 1]
            ):
                peaks.append(i)
        return peaks


class SpectrogramAnalyzer:
    """Spectrogram analyzer for time-frequency analysis.

    Attributes:
        fft_size: FFT size
        hop_size: Hop size between frames
        sample_rate: Sample rate in Hz
    """

    def __init__(self, fft_size: int = 2048, hop_size: int = 512, sample_rate: int = 44100) -> None:
        """Initialize spectrogram analyzer.

        Args:
            fft_size: FFT size
            hop_size: Hop size
            sample_rate: Sample rate in Hz
        """
        self.fft_size = fft_size
        self.hop_size = hop_size
        self.sample_rate = sample_rate
        self.analyzer = SpectrumAnalyzer(fft_size, "hann", sample_rate)

    def analyze(
        self, samples: NDArray[np.float32]
    ) -> tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.float32]]:
        """Generate spectrogram.

        Args:
            samples: Audio samples

        Returns:
            Tuple of (times, frequencies, spectrogram)
        """
        num_frames = 1 + (len(samples) - self.fft_size) // self.hop_size
        num_freq_bins = self.fft_size // 2 + 1

        spectrogram = np.zeros((num_freq_bins, num_frames), dtype=np.float32)

        for frame_idx in range(num_frames):
            start = frame_idx * self.hop_size
            end = start + self.fft_size
            frame = samples[start:end]

            if len(frame) < self.fft_size:
                frame = np.pad(frame, (0, self.fft_size - len(frame)))

            frequencies, magnitude_db = self.analyzer.analyze(frame)
            spectrogram[:, frame_idx] = magnitude_db

        times = np.arange(num_frames) * self.hop_size / self.sample_rate
        return times, frequencies, spectrogram


class PitchDetector:
    """Pitch detector using autocorrelation and parabolic interpolation.

    Attributes:
        sample_rate: Sample rate in Hz
        min_freq: Minimum frequency to detect
        max_freq: Maximum frequency to detect
    """

    def __init__(self, sample_rate: int = 44100, min_freq: float = 50.0, max_freq: float = 500.0) -> None:
        """Initialize pitch detector.

        Args:
            sample_rate: Sample rate in Hz
            min_freq: Minimum frequency to detect
            max_freq: Maximum frequency to detect
        """
        self.sample_rate = sample_rate
        self.min_freq = min_freq
        self.max_freq = max_freq

    def detect(self, samples: NDArray[np.float32]) -> tuple[float, float]:
        """Detect pitch using autocorrelation.

        Args:
            samples: Audio samples

        Returns:
            Tuple of (frequency_hz, confidence)
        """
        # Autocorrelation
        autocorr = self._autocorrelation(samples)

        # Find lag with highest autocorrelation
        min_lag = int(self.sample_rate / self.max_freq)
        max_lag = int(self.sample_rate / self.min_freq)

        if max_lag >= len(autocorr):
            max_lag = len(autocorr) - 1

        search_region = autocorr[min_lag:max_lag]
        if len(search_region) == 0:
            return 0.0, 0.0

        max_idx = np.argmax(search_region)
        lag = min_lag + max_idx

        # Parabolic interpolation for finer pitch estimate
        if lag > 0 and lag < len(autocorr) - 1:
            a = autocorr[lag - 1]
            b = autocorr[lag]
            c = autocorr[lag + 1]

            # Parabolic peak finding
            denom = 2.0 * (a - 2.0 * b + c)
            if abs(denom) > 1e-6:
                offset = (a - c) / denom * 0.5
                lag = lag + offset

        frequency = self.sample_rate / lag if lag > 0 else 0.0
        confidence = autocorr[int(lag)] if 0 <= int(lag) < len(autocorr) else 0.0

        return frequency, float(confidence)

    @staticmethod
    def _autocorrelation(samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Calculate autocorrelation.

        Args:
            samples: Input samples

        Returns:
            Autocorrelation values
        """
        # Normalize samples
        samples = samples - np.mean(samples)
        if np.max(np.abs(samples)) > 0:
            samples = samples / np.max(np.abs(samples))

        # Autocorrelation via FFT
        fft_size = 2 * len(samples)
        fft = np.fft.fft(samples, fft_size)
        power_spectrum = np.abs(fft) ** 2
        autocorr = np.fft.ifft(power_spectrum).real[: len(samples)]

        # Normalize
        if autocorr[0] > 0:
            autocorr = autocorr / autocorr[0]

        return autocorr.astype(np.float32)


class OnsetDetector:
    """Onset (attack) detector using spectral flux.

    Attributes:
        sample_rate: Sample rate in Hz
        hop_size: Hop size for frame analysis
    """

    def __init__(self, sample_rate: int = 44100, hop_size: int = 512) -> None:
        """Initialize onset detector.

        Args:
            sample_rate: Sample rate in Hz
            hop_size: Hop size in samples
        """
        self.sample_rate = sample_rate
        self.hop_size = hop_size
        self.analyzer = SpectrumAnalyzer(2048, "hann", sample_rate)
        self.prev_magnitude = None

    def detect_onsets(self, samples: NDArray[np.float32], threshold: float = 0.5) -> list[float]:
        """Detect onsets in audio.

        Args:
            samples: Audio samples
            threshold: Detection threshold

        Returns:
            List of onset times in seconds
        """
        onsets = []
        num_frames = 1 + (len(samples) - self.analyzer.fft_size) // self.hop_size

        for frame_idx in range(num_frames):
            start = frame_idx * self.hop_size
            end = start + self.analyzer.fft_size
            frame = samples[start:end]

            if len(frame) < self.analyzer.fft_size:
                frame = np.pad(frame, (0, self.analyzer.fft_size - len(frame)))

            frequencies, magnitude_db = self.analyzer.analyze(frame)
            magnitude = 10.0 ** (magnitude_db / 20.0)

            if self.prev_magnitude is not None:
                # Spectral flux
                flux = np.sum(np.maximum(0, magnitude - self.prev_magnitude))

                if flux > threshold:
                    onsets.append(frame_idx * self.hop_size / self.sample_rate)

            self.prev_magnitude = magnitude

        return onsets


class BeatDetector:
    """Beat detector using autocorrelation on onset function.

    Attributes:
        sample_rate: Sample rate in Hz
        min_bpm: Minimum BPM to detect
        max_bpm: Maximum BPM to detect
    """

    def __init__(self, sample_rate: int = 44100, min_bpm: float = 60.0, max_bpm: float = 180.0) -> None:
        """Initialize beat detector.

        Args:
            sample_rate: Sample rate in Hz
            min_bpm: Minimum BPM
            max_bpm: Maximum BPM
        """
        self.sample_rate = sample_rate
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.onset_detector = OnsetDetector(sample_rate)

    def detect_tempo(self, samples: NDArray[np.float32]) -> tuple[float, float]:
        """Detect tempo from audio.

        Args:
            samples: Audio samples

        Returns:
            Tuple of (tempo_bpm, confidence)
        """
        # Get onset times
        onsets = self.onset_detector.detect_onsets(samples)

        if len(onsets) < 2:
            return 0.0, 0.0

        # Convert to onset intervals
        intervals = np.diff(onsets)
        intervals = intervals[np.isfinite(intervals)]

        if len(intervals) == 0:
            return 0.0, 0.0

        # Degenerate interval sets (all the same value) can make histogram
        # edge generation fail with fixed high bin counts.
        interval_span = float(np.max(intervals) - np.min(intervals))
        if interval_span <= 1e-9:
            dominant_interval = float(intervals[0])
            base_confidence = 1.0
        else:
            # Keep bin count bounded by available samples to avoid zero-width bins.
            bins = int(min(50, max(2, len(intervals))))
            hist, bin_edges = np.histogram(intervals, bins=bins)
            max_idx = int(np.argmax(hist))
            dominant_interval = float((bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2.0)
            base_confidence = float(hist[max_idx]) / float(len(intervals))

        # Convert interval to BPM
        if dominant_interval > 0:
            tempo = 60.0 / dominant_interval
        else:
            tempo = 0.0

        # Clamp to expected range
        if self.min_bpm <= tempo <= self.max_bpm:
            confidence = base_confidence
        else:
            confidence = 0.0

        return tempo, confidence


class LoudnessAnalyzer:
    """Loudness measurement using ITU-R BS.1770 simplified method.

    Attributes:
        sample_rate: Sample rate in Hz
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        """Initialize loudness analyzer.

        Args:
            sample_rate: Sample rate in Hz
        """
        self.sample_rate = sample_rate

    def measure(self, samples: NDArray[np.float32]) -> float:
        """Measure loudness in LUFS.

        Args:
            samples: Audio samples (mono or stereo)

        Returns:
            Loudness in LUFS
        """
        # Flatten to mono if stereo
        if samples.ndim > 1:
            samples = np.mean(samples, axis=1)

        # Mean square
        mean_square = np.mean(samples**2)

        # Convert to LUFS
        reference = 1.0
        loudness = -0.691 + 10.0 * np.log10(mean_square / reference)

        return float(loudness)

    def measure_true_peak(self, samples: NDArray[np.float32]) -> float:
        """Measure true peak level.

        Args:
            samples: Audio samples

        Returns:
            Peak level in dBFS
        """
        peak = np.max(np.abs(samples))
        peak_db = 20.0 * np.log10(max(peak, 1e-6))
        return float(peak_db)


class ZeroCrossingRate:
    """Zero-crossing rate analyzer.

    Attributes:
        sample_rate: Sample rate in Hz
        hop_size: Hop size in samples
    """

    def __init__(self, sample_rate: int = 44100, hop_size: int = 512) -> None:
        """Initialize zero-crossing rate analyzer.

        Args:
            sample_rate: Sample rate in Hz
            hop_size: Hop size
        """
        self.sample_rate = sample_rate
        self.hop_size = hop_size

    def analyze(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Calculate zero-crossing rate over time.

        Args:
            samples: Audio samples

        Returns:
            Zero-crossing rates
        """
        num_frames = 1 + (len(samples) - 1) // self.hop_size
        zcr = np.zeros(num_frames, dtype=np.float32)

        for frame_idx in range(num_frames):
            start = frame_idx * self.hop_size
            end = min(start + self.hop_size, len(samples))
            frame = samples[start:end]

            if len(frame) > 1:
                # Count zero crossings
                crossings = np.sum(np.abs(np.diff(np.sign(frame)))) / 2.0
                zcr[frame_idx] = crossings / len(frame)

        return zcr
