"""
Audio filters including biquads, EQ, and crossovers.

Implements high-quality IIR filters with various configurations.
"""

import numpy as np
from numpy.typing import NDArray

from thomas.audio_engine._types import EqualizerBand


class BiquadFilter:
    """Second-order IIR filter (biquad) in direct form II transposed.

    Attributes:
        b0, b1, b2: Numerator coefficients
        a1, a2: Denominator coefficients (a0 normalized to 1)
        z1, z2: Filter state
    """

    def __init__(self, b0: float, b1: float, b2: float, a1: float, a2: float) -> None:
        """Initialize biquad filter.

        Args:
            b0, b1, b2: Numerator coefficients
            a1, a2: Denominator coefficients
        """
        self.b0 = b0
        self.b1 = b1
        self.b2 = b2
        self.a1 = a1
        self.a2 = a2
        self.z1 = 0.0
        self.z2 = 0.0

    def process_sample(self, sample: float) -> float:
        """Process single sample using direct form II transposed.

        Args:
            sample: Input sample

        Returns:
            Filtered sample
        """
        output = self.b0 * sample + self.z1
        self.z1 = self.b1 * sample - self.a1 * output + self.z2
        self.z2 = self.b2 * sample - self.a2 * output
        return output

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Process samples.

        Args:
            samples: Input samples

        Returns:
            Filtered samples
        """
        output = np.zeros_like(samples)
        for i, sample in enumerate(samples.flat):
            output.flat[i] = self.process_sample(float(sample))
        return output

    def reset(self) -> None:
        """Reset filter state."""
        self.z1 = 0.0
        self.z2 = 0.0

    @staticmethod
    def lowpass(frequency: float, q: float, sample_rate: int) -> "BiquadFilter":
        """Create lowpass filter.

        Args:
            frequency: Cutoff frequency in Hz
            q: Q factor
            sample_rate: Sample rate in Hz

        Returns:
            Configured BiquadFilter
        """
        w0 = 2.0 * np.pi * frequency / sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2.0 * q)

        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

        return BiquadFilter(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @staticmethod
    def highpass(frequency: float, q: float, sample_rate: int) -> "BiquadFilter":
        """Create highpass filter.

        Args:
            frequency: Cutoff frequency in Hz
            q: Q factor
            sample_rate: Sample rate in Hz

        Returns:
            Configured BiquadFilter
        """
        w0 = 2.0 * np.pi * frequency / sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2.0 * q)

        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

        return BiquadFilter(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @staticmethod
    def bandpass(frequency: float, bandwidth: float, sample_rate: int) -> "BiquadFilter":
        """Create bandpass filter.

        Args:
            frequency: Center frequency in Hz
            bandwidth: Bandwidth in Hz
            sample_rate: Sample rate in Hz

        Returns:
            Configured BiquadFilter
        """
        w0 = 2.0 * np.pi * frequency / sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2.0 * bandwidth / frequency)

        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

        return BiquadFilter(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @staticmethod
    def notch(frequency: float, q: float, sample_rate: int) -> "BiquadFilter":
        """Create notch (band-stop) filter.

        Args:
            frequency: Notch frequency in Hz
            q: Q factor
            sample_rate: Sample rate in Hz

        Returns:
            Configured BiquadFilter
        """
        w0 = 2.0 * np.pi * frequency / sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2.0 * q)

        b0 = 1.0
        b1 = -2.0 * cos_w0
        b2 = 1.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

        return BiquadFilter(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @staticmethod
    def peaking(frequency: float, gain_db: float, q: float, sample_rate: int) -> "BiquadFilter":
        """Create peaking EQ filter.

        Args:
            frequency: Center frequency in Hz
            gain_db: Gain in dB
            q: Q factor
            sample_rate: Sample rate in Hz

        Returns:
            Configured BiquadFilter
        """
        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * np.pi * frequency / sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2.0 * q)

        b0 = 1.0 + alpha * A
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / A

        return BiquadFilter(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @staticmethod
    def low_shelf(frequency: float, gain_db: float, slope: float, sample_rate: int) -> "BiquadFilter":
        """Create low shelf filter.

        Args:
            frequency: Shelf frequency in Hz
            gain_db: Gain in dB
            slope: Slope factor
            sample_rate: Sample rate in Hz

        Returns:
            Configured BiquadFilter
        """
        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * np.pi * frequency / sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / slope - 1.0) + 2.0)

        b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + 2.0 * np.sqrt(A) * alpha)
        b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
        b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - 2.0 * np.sqrt(A) * alpha)
        a0 = (A + 1.0) + (A - 1.0) * cos_w0 + 2.0 * np.sqrt(A) * alpha
        a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
        a2 = (A + 1.0) + (A - 1.0) * cos_w0 - 2.0 * np.sqrt(A) * alpha

        return BiquadFilter(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @staticmethod
    def high_shelf(frequency: float, gain_db: float, slope: float, sample_rate: int) -> "BiquadFilter":
        """Create high shelf filter.

        Args:
            frequency: Shelf frequency in Hz
            gain_db: Gain in dB
            slope: Slope factor
            sample_rate: Sample rate in Hz

        Returns:
            Configured BiquadFilter
        """
        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * np.pi * frequency / sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / slope - 1.0) + 2.0)

        b0 = A * ((A + 1.0) + (A - 1.0) * cos_w0 + 2.0 * np.sqrt(A) * alpha)
        b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cos_w0)
        b2 = A * ((A + 1.0) + (A - 1.0) * cos_w0 - 2.0 * np.sqrt(A) * alpha)
        a0 = (A + 1.0) - (A - 1.0) * cos_w0 + 2.0 * np.sqrt(A) * alpha
        a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cos_w0)
        a2 = (A + 1.0) - (A - 1.0) * cos_w0 - 2.0 * np.sqrt(A) * alpha

        return BiquadFilter(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


class FilterCascade:
    """Series of biquad filters for higher-order filtering.

    Attributes:
        filters: List of biquad filters
        order: Total filter order (2 * len(filters))
    """

    def __init__(self, filters: list[BiquadFilter] | None = None) -> None:
        """Initialize filter cascade.

        Args:
            filters: List of biquad filters
        """
        self.filters = filters or []

    def add_filter(self, biquad: BiquadFilter) -> None:
        """Add biquad filter to cascade.

        Args:
            biquad: Biquad filter to add
        """
        self.filters.append(biquad)

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Process samples through all filters.

        Args:
            samples: Input samples

        Returns:
            Filtered samples
        """
        output = samples.copy()
        for filt in self.filters:
            output = filt.process(output)
        return output

    def reset(self) -> None:
        """Reset all filters."""
        for filt in self.filters:
            filt.reset()

    @property
    def order(self) -> int:
        """Filter order."""
        return len(self.filters) * 2


class ParametricEQ:
    """3-band parametric equalizer.

    Attributes:
        bands: List of EqualizerBand objects
        sample_rate: Sample rate in Hz
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        """Initialize parametric EQ.

        Args:
            sample_rate: Sample rate in Hz
        """
        self.sample_rate = sample_rate
        self.bands = [
            EqualizerBand(100.0, 0.0, 0.7),  # Low
            EqualizerBand(1000.0, 0.0, 0.7),  # Mid
            EqualizerBand(10000.0, 0.0, 0.7),  # High
        ]
        self.filters: list[BiquadFilter] = []
        self._update_filters()

    def _update_filters(self) -> None:
        """Update filter coefficients from band settings."""
        self.filters = []
        for band in self.bands:
            filt = BiquadFilter.peaking(band.frequency, band.gain, band.q, self.sample_rate)
            self.filters.append(filt)

    def set_band(self, band_index: int, frequency: float, gain: float, q: float) -> None:
        """Set parametric EQ band.

        Args:
            band_index: Band index (0-2)
            frequency: Center frequency in Hz
            gain: Gain in dB
            q: Q factor
        """
        if 0 <= band_index < len(self.bands):
            self.bands[band_index] = EqualizerBand(frequency, gain, q)
            self._update_filters()

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply EQ to samples.

        Args:
            samples: Input samples

        Returns:
            Equalized samples
        """
        output = samples.copy()
        for filt in self.filters:
            output = filt.process(output)
        return output


class CrossoverFilter:
    """Linkwitz-Riley crossover for multi-way speaker systems.

    Attributes:
        frequency: Crossover frequency in Hz
        sample_rate: Sample rate in Hz
    """

    def __init__(self, frequency: float, sample_rate: int = 44100) -> None:
        """Initialize crossover filter.

        Args:
            frequency: Crossover frequency in Hz
            sample_rate: Sample rate in Hz
        """
        self.frequency = frequency
        self.sample_rate = sample_rate

        # Linkwitz-Riley is 4th order (two cascaded biquads per path)
        self.lowpass_cascade = FilterCascade()
        self.highpass_cascade = FilterCascade()

        # Add two biquads per path for 4th order
        for _ in range(2):
            self.lowpass_cascade.add_filter(BiquadFilter.lowpass(frequency, 0.5, sample_rate))
            self.highpass_cascade.add_filter(BiquadFilter.highpass(frequency, 0.5, sample_rate))

    def split(self, samples: NDArray[np.float32]) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """Split audio into lowpass and highpass signals.

        Args:
            samples: Input samples

        Returns:
            Tuple of (lowpass_samples, highpass_samples)
        """
        lowpass = self.lowpass_cascade.process(samples)
        highpass = self.highpass_cascade.process(samples)
        return lowpass, highpass


class FrequencyResponse:
    """Calculate frequency response of filter.

    Attributes:
        filter: Filter to analyze
    """

    def __init__(self, biquad_filter: BiquadFilter) -> None:
        """Initialize frequency response calculator.

        Args:
            biquad_filter: Filter to analyze
        """
        self.filter = biquad_filter

    def magnitude_response(self, frequencies: NDArray[np.float32]) -> NDArray[np.float32]:
        """Calculate magnitude response at given frequencies.

        Args:
            frequencies: Frequency values in Hz

        Returns:
            Magnitude response in dB
        """
        response = np.zeros_like(frequencies)
        f = self.filter

        for i, freq in enumerate(frequencies):
            w = 2.0 * np.pi * freq / 44100.0
            z = np.exp(1j * w)

            numerator = f.b0 + f.b1 * z**-1 + f.b2 * z**-2
            denominator = 1.0 + f.a1 * z**-1 + f.a2 * z**-2

            h = numerator / denominator
            response[i] = 20.0 * np.log10(np.abs(h) + 1e-6)

        return response

    def phase_response(self, frequencies: NDArray[np.float32]) -> NDArray[np.float32]:
        """Calculate phase response at given frequencies.

        Args:
            frequencies: Frequency values in Hz

        Returns:
            Phase response in degrees
        """
        response = np.zeros_like(frequencies)
        f = self.filter

        for i, freq in enumerate(frequencies):
            w = 2.0 * np.pi * freq / 44100.0
            z = np.exp(1j * w)

            numerator = f.b0 + f.b1 * z**-1 + f.b2 * z**-2
            denominator = 1.0 + f.a1 * z**-1 + f.a2 * z**-2

            h = numerator / denominator
            response[i] = np.angle(h) * 180.0 / np.pi

        return response
