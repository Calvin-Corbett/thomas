"""
Digital filter design and implementation.

Provides FIR filters (windowed-sinc method) and IIR filters (Butterworth bilinear),
as well as specialized filters like moving average and median filter.
"""

from __future__ import annotations

import numpy as np

from thomas.marketplace.signal_proc._exceptions import FilterError
from thomas.marketplace.signal_proc.windows import window


def design_lowpass_fir(
    cutoff: float,
    sample_rate: float,
    num_taps: int = 101,
    window_type: str = "hamming",
) -> np.ndarray:
    """
    Design FIR lowpass filter using windowed-sinc method.

    Args:
        cutoff: Cutoff frequency in Hz.
        sample_rate: Sample rate in Hz.
        num_taps: Number of filter coefficients (must be odd for symmetry).
        window_type: Window function name.

    Returns:
        FIR filter coefficients.

    Raises:
        FilterError: If cutoff frequency is invalid.
    """
    if cutoff <= 0 or cutoff >= sample_rate / 2:
        raise FilterError(f"Cutoff frequency must be between 0 and {sample_rate / 2} Hz")

    if num_taps < 1:
        raise FilterError("Number of taps must be >= 1")

    # Normalized cutoff frequency
    omega_c = 2 * np.pi * cutoff / sample_rate

    # Sinc kernel
    np.arange(num_taps)
    center = num_taps // 2

    h = np.zeros(num_taps)
    h[center] = omega_c / np.pi  # DC gain

    for i in range(num_taps):
        if i != center:
            n_shifted = i - center
            h[i] = np.sin(omega_c * n_shifted) / (np.pi * n_shifted)

    # Apply window
    w = window(window_type, num_taps)
    h = h * w

    # Normalize
    h = h / np.sum(h)

    return h


def design_highpass_fir(
    cutoff: float,
    sample_rate: float,
    num_taps: int = 101,
    window_type: str = "hamming",
) -> np.ndarray:
    """
    Design FIR highpass filter using windowed-sinc method.

    Uses spectral inversion: H_hp(w) = delta(w) - H_lp(w).

    Args:
        cutoff: Cutoff frequency in Hz.
        sample_rate: Sample rate in Hz.
        num_taps: Number of filter coefficients.
        window_type: Window function name.

    Returns:
        FIR filter coefficients.
    """
    h_lp = design_lowpass_fir(cutoff, sample_rate, num_taps, window_type)

    # Spectral inversion
    h_hp = -h_lp.copy()
    h_hp[num_taps // 2] += 1.0

    return h_hp


def design_bandpass_fir(
    low_freq: float,
    high_freq: float,
    sample_rate: float,
    num_taps: int = 101,
    window_type: str = "hamming",
) -> np.ndarray:
    """
    Design FIR bandpass filter.

    Computed as: H_bp(w) = H_lp(w_high) - H_lp(w_low).

    Args:
        low_freq: Lower cutoff frequency in Hz.
        high_freq: Upper cutoff frequency in Hz.
        sample_rate: Sample rate in Hz.
        num_taps: Number of filter coefficients.
        window_type: Window function name.

    Returns:
        FIR filter coefficients.

    Raises:
        FilterError: If frequencies are invalid.
    """
    if not (0 < low_freq < high_freq < sample_rate / 2):
        raise FilterError(f"Frequencies must satisfy 0 < f_low < f_high < {sample_rate / 2} Hz")

    h_lp_high = design_lowpass_fir(high_freq, sample_rate, num_taps, window_type)
    h_lp_low = design_lowpass_fir(low_freq, sample_rate, num_taps, window_type)

    h_bp = h_lp_high - h_lp_low
    h_bp = h_bp / np.sum(np.abs(h_bp))

    return h_bp


def design_bandstop_fir(
    low_freq: float,
    high_freq: float,
    sample_rate: float,
    num_taps: int = 101,
    window_type: str = "hamming",
) -> np.ndarray:
    """
    Design FIR bandstop (notch) filter.

    Uses spectral inversion of bandpass: H_bs(w) = delta(w) - H_bp(w).

    Args:
        low_freq: Lower stopband frequency in Hz.
        high_freq: Upper stopband frequency in Hz.
        sample_rate: Sample rate in Hz.
        num_taps: Number of filter coefficients.
        window_type: Window function name.

    Returns:
        FIR filter coefficients.
    """
    h_bp = design_bandpass_fir(low_freq, high_freq, sample_rate, num_taps, window_type)

    h_bs = -h_bp.copy()
    h_bs[num_taps // 2] += 1.0

    return h_bs


class FIRFilter:
    """
    Finite Impulse Response (FIR) filter.

    Implements direct form convolution-based filtering.
    """

    def __init__(self, coefficients: np.ndarray):
        """
        Initialize FIR filter.

        Args:
            coefficients: Filter coefficients (impulse response).
        """
        self.coefficients = np.asarray(coefficients, dtype=np.float64)
        if len(self.coefficients) == 0:
            raise FilterError("Coefficients cannot be empty")

    def filter(self, x: np.ndarray) -> np.ndarray:
        """
        Apply FIR filter to signal.

        Args:
            x: Input signal.

        Returns:
            Filtered signal (same length as input).
        """
        x = np.asarray(x, dtype=np.float64)
        n = len(x)
        m = len(self.coefficients)

        y = np.zeros(n, dtype=np.float64)

        for i in range(n):
            for j in range(min(i + 1, m)):
                y[i] += self.coefficients[j] * x[i - j]

        return y

    def frequency_response(
        self,
        frequencies: np.ndarray,
        sample_rate: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute frequency response (magnitude and phase).

        Args:
            frequencies: Frequency values in Hz.
            sample_rate: Sample rate in Hz.

        Returns:
            Tuple of (magnitude, phase in radians).
        """
        frequencies = np.asarray(frequencies, dtype=np.float64)
        omega = 2 * np.pi * frequencies / sample_rate

        h = self.coefficients
        n = len(h)
        m = len(frequencies)

        H = np.zeros(m, dtype=np.complex128)
        for i, w in enumerate(omega):
            H[i] = np.sum(h * np.exp(-1j * w * np.arange(n)))

        magnitude = np.abs(H)
        phase = np.angle(H)

        return magnitude, phase


class IIRFilter:
    """
    Infinite Impulse Response (IIR) filter.

    Implements cascaded biquad sections for numerical stability.
    """

    def __init__(self, sections: list[tuple[np.ndarray, np.ndarray]]):
        """
        Initialize IIR filter from cascaded biquad sections.

        Args:
            sections: List of (b, a) coefficient tuples for each section.
                     b and a are numerator and denominator coefficients.
        """
        self.sections = [(np.asarray(b, dtype=np.float64), np.asarray(a, dtype=np.float64)) for b, a in sections]

        for b, a in self.sections:
            if a[0] == 0:
                raise FilterError("Denominator leading coefficient cannot be zero")

    def filter(self, x: np.ndarray) -> np.ndarray:
        """
        Apply IIR filter to signal using cascaded biquad sections.

        Args:
            x: Input signal.

        Returns:
            Filtered signal.
        """
        y = np.asarray(x, dtype=np.float64).copy()

        for b, a in self.sections:
            y = self._apply_biquad(y, b, a)

        return y

    @staticmethod
    def _apply_biquad(x: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
        """
        Apply single biquad section (2nd order IIR filter).

        Args:
            x: Input signal.
            b: Numerator coefficients.
            a: Denominator coefficients.

        Returns:
            Filtered signal.
        """
        x = np.asarray(x, dtype=np.float64)
        n = len(x)
        y = np.zeros(n, dtype=np.float64)

        # Normalize by a[0]
        b = b / a[0]
        a = a / a[0]

        for i in range(n):
            y[i] = b[0] * x[i]

            if i >= 1:
                y[i] += b[1] * x[i - 1] - a[1] * y[i - 1]

            if i >= 2:
                y[i] += b[2] * x[i - 2] - a[2] * y[i - 2]

        return y

    def frequency_response(
        self,
        frequencies: np.ndarray,
        sample_rate: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute frequency response of cascaded sections.

        Args:
            frequencies: Frequency values in Hz.
            sample_rate: Sample rate in Hz.

        Returns:
            Tuple of (magnitude, phase in radians).
        """
        frequencies = np.asarray(frequencies, dtype=np.float64)
        omega = 2 * np.pi * frequencies / sample_rate

        H_total = np.ones(len(frequencies), dtype=np.complex128)

        for b, a in self.sections:
            # Evaluate transfer function at each frequency
            b0, b1, b2 = b[0], b[1] if len(b) > 1 else 0, b[2] if len(b) > 2 else 0
            a0, a1, a2 = a[0], a[1] if len(a) > 1 else 0, a[2] if len(a) > 2 else 0

            for i, w in enumerate(omega):
                num = b0 + b1 * np.exp(-1j * w) + b2 * np.exp(-2j * w)
                den = a0 + a1 * np.exp(-1j * w) + a2 * np.exp(-2j * w)
                H_total[i] *= num / den

        magnitude = np.abs(H_total)
        phase = np.angle(H_total)

        return magnitude, phase

    def is_stable(self) -> bool:
        """
        Check stability (all poles inside unit circle).

        Returns:
            True if filter is stable.
        """
        for b, a in self.sections:
            # Poles are roots of denominator
            poles = np.roots(a)
            if np.any(np.abs(poles) >= 1.0):
                return False
        return True


def design_butterworth_lowpass(
    cutoff: float,
    sample_rate: float,
    order: int = 4,
) -> IIRFilter:
    """
    Design Butterworth lowpass IIR filter using bilinear transform.

    Args:
        cutoff: Cutoff frequency (-3dB) in Hz.
        sample_rate: Sample rate in Hz.
        order: Filter order (must be even for cascaded biquads).

    Returns:
        IIRFilter object.

    Raises:
        FilterError: If cutoff frequency is invalid.
    """
    if cutoff <= 0 or cutoff >= sample_rate / 2:
        raise FilterError(f"Cutoff frequency must be between 0 and {sample_rate / 2} Hz")

    if order < 1:
        raise FilterError("Order must be >= 1")

    # Analog prototype cutoff = 1 rad/s
    # Normalized digital frequency
    2 * cutoff / sample_rate
    tan_half = np.tan(np.pi * cutoff / sample_rate)

    sections = []

    # Design biquad sections for each pole pair
    n_sections = (order + 1) // 2
    for i in range(n_sections):
        # Pole angle in analog prototype
        pole_angle = np.pi * (2 * i + 1) / (2 * order)
        pole_s = np.exp(1j * (np.pi / 2 + pole_angle))  # Pole in s-plane

        # Bilinear transform: s = 2/Ts * (z-1)/(z+1)
        a_s = 1  # Real part of pole
        b_s = np.imag(pole_s)  # Imaginary part

        # Transform coefficients
        alpha = 1 + a_s * tan_half + b_s * tan_half
        beta = 1 - a_s * tan_half - b_s * tan_half

        b0 = tan_half**2
        b1 = 2 * tan_half**2
        b2 = tan_half**2

        a0 = alpha + b_s * tan_half
        a1 = 2 * (tan_half**2 - (a_s * tan_half + b_s * tan_half))
        a2 = beta - b_s * tan_half

        # Normalize
        b = np.array([b0, b1, b2]) / a0
        a = np.array([1.0, a1 / a0, a2 / a0])

        sections.append((b, a))

    return IIRFilter(sections)


def design_butterworth_highpass(
    cutoff: float,
    sample_rate: float,
    order: int = 4,
) -> IIRFilter:
    """
    Design Butterworth highpass IIR filter using bilinear transform.

    Args:
        cutoff: Cutoff frequency (-3dB) in Hz.
        sample_rate: Sample rate in Hz.
        order: Filter order.

    Returns:
        IIRFilter object.

    Raises:
        FilterError: If cutoff frequency is invalid.
    """
    if cutoff <= 0 or cutoff >= sample_rate / 2:
        raise FilterError(f"Cutoff frequency must be between 0 and {sample_rate / 2} Hz")

    # Design lowpass then apply spectral transformation
    lp_filter = design_butterworth_lowpass(cutoff, sample_rate, order)

    # Transform sections from lowpass to highpass
    sections = []
    for b_lp, a_lp in lp_filter.sections:
        # Highpass transformation
        b = [b_lp[2], -2 * b_lp[2], b_lp[2]]
        a = [a_lp[2], -2 * a_lp[2], a_lp[2]]

        sections.append((np.array(b), np.array(a)))

    return IIRFilter(sections)


class MovingAverageFilter:
    """
    Simple moving average (box car) filter.

    Efficient lowpass filter with rectangular frequency response.
    """

    def __init__(self, window_size: int):
        """
        Initialize moving average filter.

        Args:
            window_size: Number of samples to average.
        """
        if window_size < 1:
            raise FilterError("Window size must be >= 1")
        self.window_size = window_size

    def filter(self, x: np.ndarray) -> np.ndarray:
        """
        Apply moving average filter.

        Args:
            x: Input signal.

        Returns:
            Filtered signal.
        """
        x = np.asarray(x, dtype=np.float64)
        n = len(x)
        y = np.zeros(n, dtype=np.float64)

        cumsum = np.cumsum(x)

        for i in range(n):
            start_idx = max(0, i - self.window_size + 1)
            if start_idx == 0:
                y[i] = cumsum[i] / (i + 1)
            else:
                y[i] = (cumsum[i] - cumsum[start_idx - 1]) / self.window_size

        return y


class MedianFilter:
    """
    Median filter for non-linear signal processing.

    Effective for impulse noise removal.
    """

    def __init__(self, window_size: int):
        """
        Initialize median filter.

        Args:
            window_size: Number of samples for median computation.
        """
        if window_size < 1 or window_size % 2 == 0:
            raise FilterError("Window size must be odd and >= 1")
        self.window_size = window_size

    def filter(self, x: np.ndarray) -> np.ndarray:
        """
        Apply median filter.

        Args:
            x: Input signal.

        Returns:
            Filtered signal.
        """
        x = np.asarray(x, dtype=np.float64)
        n = len(x)
        y = np.zeros(n, dtype=np.float64)

        half_window = self.window_size // 2

        for i in range(n):
            start = max(0, i - half_window)
            end = min(n, i + half_window + 1)
            window = x[start:end]
            y[i] = np.median(window)

        return y
