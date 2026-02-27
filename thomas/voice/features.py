"""
Speech feature extraction module.

Extracts acoustic features from raw audio:
- Pre-emphasis filtering
- Frame blocking with windowing
- FFT-based power spectrum
- Mel filterbank analysis
- MFCC (Mel-Frequency Cepstral Coefficients)
- Formant estimation via LPC
- Zero-crossing rate
- Short-time energy
"""

import numpy as np
from scipy import signal
from scipy.fftpack import dct

from thomas.voice._exceptions import FeatureExtractionError
from thomas.voice._types import (
    AudioSample,
    FormantFrequencies,
    MFCCFeatures,
    SpeechFrame,
)


class FeatureExtractor:
    """Extracts speech features from audio signals."""

    # Constants
    DEFAULT_FRAME_SIZE: int = 512
    DEFAULT_HOP_SIZE: int = 160
    DEFAULT_MFCC_COEFFICIENTS: int = 13
    DEFAULT_MEL_FILTERS: int = 40
    DEFAULT_LPC_ORDER: int = 10
    PRE_EMPHASIS_COEFFICIENT: float = 0.97

    def __init__(
        self,
        frame_size: int = DEFAULT_FRAME_SIZE,
        hop_size: int = DEFAULT_HOP_SIZE,
        mfcc_coefficients: int = DEFAULT_MFCC_COEFFICIENTS,
        mel_filters: int = DEFAULT_MEL_FILTERS,
        lpc_order: int = DEFAULT_LPC_ORDER,
    ) -> None:
        """
        Initialize feature extractor.

        Args:
            frame_size: Frame size in samples.
            hop_size: Hop size (frame shift) in samples.
            mfcc_coefficients: Number of MFCC coefficients to extract.
            mel_filters: Number of mel filterbank filters.
            lpc_order: Order of LPC analysis.
        """
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.mfcc_coefficients = mfcc_coefficients
        self.mel_filters = mel_filters
        self.lpc_order = lpc_order

    def _apply_pre_emphasis(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply first-order high-pass pre-emphasis filter.

        y[n] = x[n] - alpha * x[n-1]

        Args:
            audio: Audio signal.

        Returns:
            Pre-emphasized signal.
        """
        emphasized = np.zeros_like(audio)
        emphasized[0] = audio[0]
        for i in range(1, len(audio)):
            emphasized[i] = audio[i] - self.PRE_EMPHASIS_COEFFICIENT * audio[i - 1]
        return emphasized

    def _frame_blocking(self, audio: np.ndarray, sample_rate: int) -> list[SpeechFrame]:
        """
        Apply frame blocking with Hamming window.

        Args:
            audio: Audio signal.
            sample_rate: Sample rate in Hz.

        Returns:
            List of speech frames.
        """
        frames: list[SpeechFrame] = []
        hamming_window = signal.hamming(self.frame_size)

        for i in range(0, len(audio) - self.frame_size + 1, self.hop_size):
            frame_data = audio[i : i + self.frame_size]
            windowed = frame_data * hamming_window

            frame_idx = i // self.hop_size
            timestamp = (i + self.frame_size / 2) / sample_rate
            duration = self.frame_size / sample_rate

            frames.append(
                SpeechFrame(
                    frame_data=windowed,
                    frame_index=frame_idx,
                    timestamp=timestamp,
                    duration=duration,
                    sample_rate=sample_rate,
                )
            )

        return frames

    def _power_spectrum(self, frame: np.ndarray) -> np.ndarray:
        """
        Calculate power spectrum via FFT.

        Args:
            frame: Audio frame.

        Returns:
            Power spectrum.
        """
        fft = np.abs(np.fft.fft(frame)) ** 2
        return fft[: len(frame) // 2 + 1]

    def _hz_to_mel(self, hz: float) -> float:
        """
        Convert Hz to mel scale.

        mel = 2595 * log10(1 + f/700)

        Args:
            hz: Frequency in Hz.

        Returns:
            Frequency in mel scale.
        """
        return 2595 * np.log10(1 + hz / 700)

    def _mel_to_hz(self, mel: float) -> float:
        """
        Convert mel scale to Hz.

        f = 700 * (10^(mel/2595) - 1)

        Args:
            mel: Frequency in mel scale.

        Returns:
            Frequency in Hz.
        """
        return 700 * (10 ** (mel / 2595) - 1)

    def _mel_filterbank(self, power_spectrum: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        Apply mel filterbank to power spectrum.

        Creates triangular filters on mel scale.

        Args:
            power_spectrum: Power spectrum.
            sample_rate: Sample rate in Hz.

        Returns:
            Mel filterbank energies (num_filters,).
        """
        nyquist = sample_rate / 2
        mel_min = self._hz_to_mel(50)
        mel_max = self._hz_to_mel(nyquist)

        mel_points = np.linspace(mel_min, mel_max, self.mel_filters + 2)
        hz_points = np.array([self._mel_to_hz(mel) for mel in mel_points])

        bin_points = np.floor((len(power_spectrum) - 1) * hz_points / nyquist).astype(int)

        mel_energies = np.zeros(self.mel_filters)

        for m in range(self.mel_filters):
            left = bin_points[m]
            center = bin_points[m + 1]
            right = bin_points[m + 2]

            for k in range(left, center):
                if center - left > 0:
                    mel_energies[m] += power_spectrum[k] * (k - left) / (center - left)

            for k in range(center, right):
                if right - center > 0:
                    mel_energies[m] += power_spectrum[k] * (right - k) / (right - center)

        return mel_energies

    def extract_mfcc(self, audio_sample: AudioSample) -> MFCCFeatures:
        """
        Extract MFCC (Mel-Frequency Cepstral Coefficients).

        Process:
        1. Pre-emphasis filter
        2. Frame blocking with Hamming window
        3. Power spectrum via FFT
        4. Mel filterbank
        5. Log compression
        6. DCT (Discrete Cosine Transform)

        Args:
            audio_sample: Audio sample.

        Returns:
            MFCC features with optional delta and delta-delta.

        Raises:
            FeatureExtractionError: If extraction fails.
        """
        try:
            audio = audio_sample.data
            sample_rate = audio_sample.sample_rate

            # Pre-emphasis
            emphasized = self._apply_pre_emphasis(audio)

            # Frame blocking
            frames = self._frame_blocking(emphasized, sample_rate)

            # Extract MFCC for each frame
            mfcc_matrix = []

            for frame in frames:
                # Power spectrum
                power = self._power_spectrum(frame.frame_data)

                # Mel filterbank
                mel_energies = self._mel_filterbank(power, sample_rate)

                # Log compression
                log_mel = np.log(np.maximum(mel_energies, 1e-10))

                # DCT
                mfcc = dct(log_mel, type=2, norm="ortho")
                mfcc = mfcc[: self.mfcc_coefficients]

                mfcc_matrix.append(mfcc)

            coefficients = np.array(mfcc_matrix)

            # Calculate delta and delta-delta
            delta = self._calculate_delta(coefficients)
            delta_delta = self._calculate_delta(delta)

            return MFCCFeatures(
                coefficients=coefficients,
                delta=delta,
                delta_delta=delta_delta,
                frame_rate=sample_rate / self.hop_size,
            )

        except Exception as e:
            raise FeatureExtractionError(f"MFCC extraction failed: {str(e)}")

    def _calculate_delta(self, coefficients: np.ndarray, window: int = 2) -> np.ndarray:
        """
        Calculate delta (first derivative) of coefficients.

        delta[n] = (sum(t * (c[n+t] - c[n-t])) for t=1..window) / (2 * sum(t^2))

        Args:
            coefficients: Coefficient matrix (num_frames x num_coefficients).
            window: Delta window size.

        Returns:
            Delta coefficients.
        """
        num_frames, num_coefficients = coefficients.shape
        delta = np.zeros_like(coefficients)

        denominator = 2 * sum(t**2 for t in range(1, window + 1))

        for i in range(num_frames):
            numerator = np.zeros(num_coefficients)
            for t in range(1, window + 1):
                if i + t < num_frames and i - t >= 0:
                    numerator += t * (coefficients[i + t] - coefficients[i - t])
            delta[i] = numerator / denominator

        return delta

    def extract_zero_crossing_rate(self, audio_sample: AudioSample) -> np.ndarray:
        """
        Extract zero-crossing rate (ZCR).

        ZCR = (1 / N) * sum(|sign(x[n]) - sign(x[n-1])|) / 2

        Args:
            audio_sample: Audio sample.

        Returns:
            Zero-crossing rate for each frame.
        """
        audio = audio_sample.data
        frames = self._frame_blocking(audio, audio_sample.sample_rate)
        zcr = np.zeros(len(frames))

        for i, frame in enumerate(frames):
            zero_crossings = np.sum(np.abs(np.diff(np.sign(frame.frame_data)))) / (2 * len(frame.frame_data))
            zcr[i] = zero_crossings

        return zcr

    def extract_short_time_energy(self, audio_sample: AudioSample) -> np.ndarray:
        """
        Extract short-time energy.

        Energy = sum(x[n]^2) for each frame.

        Args:
            audio_sample: Audio sample.

        Returns:
            Energy for each frame (in dB).
        """
        audio = audio_sample.data
        frames = self._frame_blocking(audio, audio_sample.sample_rate)
        energy = np.zeros(len(frames))

        for i, frame in enumerate(frames):
            energy[i] = 10 * np.log10(np.maximum(np.sum(frame.frame_data**2), 1e-10))

        return energy

    def estimate_formants(self, audio_sample: AudioSample, num_formants: int = 3) -> list[FormantFrequencies]:
        """
        Estimate formant frequencies using LPC analysis.

        Process:
        1. Apply pre-emphasis
        2. Frame blocking
        3. LPC via Levinson-Durbin recursion
        4. Find roots of LPC polynomial
        5. Extract formant frequencies

        Args:
            audio_sample: Audio sample.
            num_formants: Number of formants to extract.

        Returns:
            List of formant frequencies for each frame.

        Raises:
            FeatureExtractionError: If estimation fails.
        """
        try:
            audio = audio_sample.data
            sample_rate = audio_sample.sample_rate

            emphasized = self._apply_pre_emphasis(audio)
            frames = self._frame_blocking(emphasized, sample_rate)

            formants_list: list[FormantFrequencies] = []

            for frame in frames:
                # LPC analysis
                lpc_coeffs = self._lpc_analysis(frame.frame_data, self.lpc_order)

                # Find roots and extract formants
                roots = np.roots(np.concatenate([[1], lpc_coeffs]))
                angles = np.angle(roots)
                frequencies = np.abs(angles) * sample_rate / (2 * np.pi)

                # Keep only valid formants (0 Hz to Nyquist, magnitude < 1)
                valid_freqs = []
                for i, (root, freq) in enumerate(zip(roots, frequencies)):
                    if 50 < freq < sample_rate / 2 and np.abs(root) < 1:
                        valid_freqs.append(freq)

                valid_freqs.sort()

                # Extract first 3 formants
                f1 = valid_freqs[0] if len(valid_freqs) > 0 else 0.0
                f2 = valid_freqs[1] if len(valid_freqs) > 1 else 0.0
                f3 = valid_freqs[2] if len(valid_freqs) > 2 else 0.0
                f4 = valid_freqs[3] if len(valid_freqs) > 3 else None
                f5 = valid_freqs[4] if len(valid_freqs) > 4 else None

                formants_list.append(
                    FormantFrequencies(
                        f1=f1,
                        f2=f2,
                        f3=f3,
                        f4=f4,
                        f5=f5,
                        timestamp=frame.timestamp,
                    )
                )

            return formants_list

        except Exception as e:
            raise FeatureExtractionError(f"Formant estimation failed: {str(e)}")

    def _lpc_analysis(self, frame: np.ndarray, order: int) -> np.ndarray:
        """
        Perform LPC analysis via Levinson-Durbin recursion.

        Args:
            frame: Audio frame.
            order: LPC order.

        Returns:
            LPC coefficients.
        """
        # Autocorrelation method
        autocorr = self._autocorrelation(frame, order + 1)

        # Levinson-Durbin recursion
        lpc = np.zeros(order)
        e = autocorr[0]

        if e == 0:
            return lpc

        for i in range(order):
            # Calculate reflection coefficient
            numerator = autocorr[i + 1]
            for j in range(i):
                numerator -= lpc[j] * autocorr[i - j]

            k = numerator / e

            if abs(k) > 1:
                k = np.sign(k)

            lpc[i] = k
            e *= 1 - k**2

            # Update previous coefficients
            for j in range(i):
                lpc[j] -= k * lpc[i - j - 1]

        return lpc

    def _autocorrelation(self, signal: np.ndarray, order: int) -> np.ndarray:
        """
        Calculate autocorrelation of a signal.

        Args:
            signal: Input signal.
            order: Autocorrelation order.

        Returns:
            Autocorrelation values.
        """
        autocorr = np.zeros(order)
        for lag in range(order):
            autocorr[lag] = np.sum(signal[: -lag or None] * signal[lag:])
        return autocorr
