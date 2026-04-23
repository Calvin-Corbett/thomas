"""
Type definitions and enumerations for signal processing module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class WindowType(Enum):
    """Window function types for spectral analysis."""

    RECTANGULAR = "rectangular"
    HANNING = "hanning"
    HAMMING = "hamming"
    BLACKMAN = "blackman"
    KAISER = "kaiser"
    BARTLETT = "bartlett"
    FLATTOP = "flattop"


class FilterType(Enum):
    """Digital filter types."""

    LOWPASS = "lowpass"
    HIGHPASS = "highpass"
    BANDPASS = "bandpass"
    BANDSTOP = "bandstop"


@dataclass
class Signal:
    """
    Represents a discrete-time signal.

    Attributes:
        samples: Numpy array of signal samples (real or complex).
        sample_rate: Sample rate in Hz.
    """

    samples: np.ndarray
    sample_rate: float

    def __post_init__(self) -> None:
        """Validate signal attributes."""
        if not isinstance(self.samples, np.ndarray):
            self.samples = np.asarray(self.samples, dtype=np.float64)
        if self.sample_rate <= 0:
            raise ValueError("Sample rate must be positive")
        if len(self.samples) == 0:
            raise ValueError("Signal must contain at least one sample")

    @property
    def duration(self) -> float:
        """Duration of signal in seconds."""
        return len(self.samples) / self.sample_rate

    @property
    def time_axis(self) -> np.ndarray:
        """Time axis in seconds."""
        return np.arange(len(self.samples)) / self.sample_rate

    @property
    def nyquist_frequency(self) -> float:
        """Nyquist frequency in Hz."""
        return self.sample_rate / 2

    def __len__(self) -> int:
        """Return number of samples."""
        return len(self.samples)

    def __getitem__(self, key: int | slice) -> np.ndarray:
        """Index into samples."""
        return self.samples[key]


@dataclass
class FrequencySpectrum:
    """
    Represents a frequency-domain signal.

    Attributes:
        frequencies: Numpy array of frequency bins in Hz.
        magnitudes: Numpy array of magnitude values.
        phases: Numpy array of phase values in radians.
    """

    frequencies: np.ndarray
    magnitudes: np.ndarray
    phases: np.ndarray

    def __post_init__(self) -> None:
        """Validate spectrum attributes."""
        if not isinstance(self.frequencies, np.ndarray):
            self.frequencies = np.asarray(self.frequencies, dtype=np.float64)
        if not isinstance(self.magnitudes, np.ndarray):
            self.magnitudes = np.asarray(self.magnitudes, dtype=np.float64)
        if not isinstance(self.phases, np.ndarray):
            self.phases = np.asarray(self.phases, dtype=np.float64)

        n = len(self.frequencies)
        if len(self.magnitudes) != n or len(self.phases) != n:
            raise ValueError("Frequencies, magnitudes, and phases must have same length")

    @property
    def complex_spectrum(self) -> np.ndarray:
        """Convert to complex representation."""
        return self.magnitudes * np.exp(1j * self.phases)

    @property
    def power_spectrum(self) -> np.ndarray:
        """Power spectrum (magnitude squared)."""
        return self.magnitudes**2

    def __len__(self) -> int:
        """Return number of frequency bins."""
        return len(self.frequencies)


@dataclass
class FilterConfig:
    """
    Configuration for digital filter design.

    Attributes:
        filter_type: Type of filter (lowpass, highpass, bandpass, bandstop).
        cutoff_frequencies: Cutoff frequency or (low, high) tuple for band filters.
        order: Filter order (number of coefficients - 1).
        sample_rate: Sample rate in Hz.
        transition_width: Transition bandwidth in Hz (for FIR design).
        ripple_db: Passband ripple in dB (for Chebyshev, etc.).
    """

    filter_type: FilterType
    cutoff_frequencies: float | tuple[float, float]
    order: int
    sample_rate: float
    transition_width: float = 100.0
    ripple_db: float = 0.1

    def __post_init__(self) -> None:
        """Validate filter configuration."""
        if self.order < 1:
            raise ValueError("Filter order must be >= 1")
        if self.sample_rate <= 0:
            raise ValueError("Sample rate must be positive")
        if self.transition_width <= 0:
            raise ValueError("Transition width must be positive")

        nyquist = self.sample_rate / 2

        if isinstance(self.cutoff_frequencies, (int, float)):
            if not (0 < self.cutoff_frequencies < nyquist):
                raise ValueError(f"Cutoff frequency must be between 0 and {nyquist} Hz")
        else:
            low, high = self.cutoff_frequencies
            if not (0 < low < high < nyquist):
                raise ValueError(f"Band frequencies must satisfy 0 < f_low < f_high < {nyquist} Hz")


@dataclass
class Spectrogram:
    """
    Represents a time-frequency representation (STFT output).

    Attributes:
        time_frames: Time points for each frame.
        frequencies: Frequency bins in Hz.
        magnitude: Magnitude spectrogram (time x frequency).
        phase: Phase spectrogram (time x frequency).
    """

    time_frames: np.ndarray
    frequencies: np.ndarray
    magnitude: np.ndarray
    phase: np.ndarray

    def __post_init__(self) -> None:
        """Validate spectrogram attributes."""
        if not isinstance(self.time_frames, np.ndarray):
            self.time_frames = np.asarray(self.time_frames, dtype=np.float64)
        if not isinstance(self.frequencies, np.ndarray):
            self.frequencies = np.asarray(self.frequencies, dtype=np.float64)
        if not isinstance(self.magnitude, np.ndarray):
            self.magnitude = np.asarray(self.magnitude, dtype=np.float64)
        if not isinstance(self.phase, np.ndarray):
            self.phase = np.asarray(self.phase, dtype=np.float64)

        n_frames = len(self.time_frames)
        n_freq = len(self.frequencies)

        if self.magnitude.shape != (n_frames, n_freq):
            raise ValueError(f"Magnitude shape {self.magnitude.shape} doesn't match " f"({n_frames}, {n_freq})")
        if self.phase.shape != (n_frames, n_freq):
            raise ValueError(f"Phase shape {self.phase.shape} doesn't match ({n_frames}, {n_freq})")

    @property
    def power(self) -> np.ndarray:
        """Power spectrogram (magnitude squared)."""
        return self.magnitude**2

    @property
    def log_magnitude(self) -> np.ndarray:
        """Log-magnitude spectrogram in dB."""
        return 20 * np.log10(np.maximum(self.magnitude, 1e-10))

    def __getitem__(self, idx: int) -> tuple[np.ndarray, np.ndarray]:
        """Get spectrum at time frame index."""
        return self.magnitude[idx, :], self.phase[idx, :]
