"""
Window functions for spectral analysis and filter design.

Provides various windowing functions and utilities for reducing spectral leakage.
"""

from __future__ import annotations

import numpy as np

from thomas.marketplace.signal_proc._exceptions import SignalError


def rectangular(n: int) -> np.ndarray:
    """
    Rectangular (boxcar) window.

    Provides maximum spectral resolution but poor sidelobe suppression.

    Args:
        n: Window length.

    Returns:
        Window coefficients.
    """
    if n < 1:
        raise SignalError("Window length must be >= 1")
    return np.ones(n, dtype=np.float64)


def hanning(n: int) -> np.ndarray:
    """
    Hanning window (raised cosine).

    Good balance of main lobe width and sidelobe level.

    Args:
        n: Window length.

    Returns:
        Window coefficients.
    """
    if n < 1:
        raise SignalError("Window length must be >= 1")
    return np.hanning(n)


def hamming(n: int) -> np.ndarray:
    """
    Hamming window (modified raised cosine).

    Optimized to minimize first sidelobe level.

    Args:
        n: Window length.

    Returns:
        Window coefficients.
    """
    if n < 1:
        raise SignalError("Window length must be >= 1")
    return np.hamming(n)


def blackman(n: int) -> np.ndarray:
    """
    Blackman window (raised cosine with two terms).

    Excellent sidelobe suppression at cost of wider main lobe.

    Args:
        n: Window length.

    Returns:
        Window coefficients.
    """
    if n < 1:
        raise SignalError("Window length must be >= 1")
    return np.blackman(n)


def kaiser(n: int, beta: float = 8.6) -> np.ndarray:
    """
    Kaiser window (Bessel I_0 taper).

    Adjustable trade-off between main lobe width and sidelobe level via beta parameter.
    Higher beta = narrower main lobe, better sidelobe suppression.

    Args:
        n: Window length.
        beta: Shape parameter (typically 4-9). Higher values reduce sidelobe level.

    Returns:
        Window coefficients.
    """
    if n < 1:
        raise SignalError("Window length must be >= 1")
    return np.kaiser(n, beta)


def bartlett(n: int) -> np.ndarray:
    """
    Bartlett window (triangular).

    Simple triangular taper, equivalent to convolving two rectangular windows.

    Args:
        n: Window length.

    Returns:
        Window coefficients.
    """
    if n < 1:
        raise SignalError("Window length must be >= 1")
    return np.bartlett(n)


def flattop(n: int) -> np.ndarray:
    """
    Flat-top window.

    Nearly rectangular passband with excellent amplitude accuracy.
    Used primarily for amplitude measurements.

    Args:
        n: Window length.

    Returns:
        Window coefficients.
    """
    if n < 1:
        raise SignalError("Window length must be >= 1")

    # Flat-top window coefficients
    a = np.array([0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368])

    result = np.zeros(n, dtype=np.float64)
    for k in range(len(a)):
        result += a[k] * np.cos(2 * np.pi * k * np.arange(n) / (n - 1))

    return result


def window(name: str, n: int, **kwargs) -> np.ndarray:
    """
    Compute window function by name.

    Args:
        name: Window name ('rectangular', 'hanning', 'hamming', 'blackman', 'kaiser', 'bartlett', 'flattop').
        n: Window length.
        **kwargs: Additional arguments (e.g., beta for Kaiser window).

    Returns:
        Window coefficients.

    Raises:
        SignalError: If window name is unknown.
    """
    window_funcs = {
        "rectangular": rectangular,
        "hanning": hanning,
        "hamming": hamming,
        "blackman": blackman,
        "kaiser": kaiser,
        "bartlett": bartlett,
        "flattop": flattop,
    }

    if name not in window_funcs:
        raise SignalError(f"Unknown window type: {name}")

    if name == "kaiser":
        beta = kwargs.get("beta", 8.6)
        return window_funcs[name](n, beta)
    else:
        return window_funcs[name](n)


def apply_window(signal: np.ndarray, window_func: np.ndarray) -> np.ndarray:
    """
    Apply window function to signal.

    Args:
        signal: Input signal.
        window_func: Window coefficients (must match signal length).

    Returns:
        Windowed signal.

    Raises:
        SignalError: If lengths don't match.
    """
    signal = np.asarray(signal, dtype=np.float64)
    window_func = np.asarray(window_func, dtype=np.float64)

    if len(signal) != len(window_func):
        raise SignalError(f"Signal length {len(signal)} doesn't match window length {len(window_func)}")

    return signal * window_func


def window_properties(name: str) -> tuple[float, float]:
    """
    Get approximate properties of window function.

    Args:
        name: Window name.

    Returns:
        Tuple of (main lobe width in bins, peak sidelobe level in dB).
    """
    properties = {
        "rectangular": (4.0, -13.3),
        "hanning": (8.0, -31.5),
        "hamming": (8.0, -42.7),
        "blackman": (12.0, -58.1),
        "kaiser": (7.0, -69.0),
        "bartlett": (8.0, -26.5),
        "flattop": (12.0, -93.3),
    }

    if name not in properties:
        raise SignalError(f"Unknown window type: {name}")

    return properties[name]


def spectral_leakage_compare(
    n: int,
    freqs: np.ndarray,
) -> dict:
    """
    Compare spectral leakage for different windows.

    Args:
        n: Window length.
        freqs: Test frequencies.

    Returns:
        Dictionary of window names to spectral leakage metrics.
    """
    from thomas.marketplace.signal_proc.fft import fft, magnitude_spectrum

    window_names = ["rectangular", "hanning", "hamming", "blackman", "kaiser"]
    results = {}

    for w_name in window_names:
        w = window(w_name, n)
        # Simulate a test signal at each frequency
        leakage_values = []

        for freq in freqs:
            t = np.arange(n) / n
            signal = np.sin(2 * np.pi * freq * t)
            windowed = signal * w

            X = fft(windowed)
            mag = magnitude_spectrum(X)

            # Peak sidelobe as percentage of main peak
            peak_idx = np.argmax(mag)
            peak_value = mag[peak_idx]
            sidelobes = np.concatenate([mag[: peak_idx - 5], mag[peak_idx + 5 :]])

            if len(sidelobes) > 0:
                max_sidelobe = np.max(sidelobes)
                leakage = max_sidelobe / peak_value
            else:
                leakage = 0.0

            leakage_values.append(leakage)

        results[w_name] = np.mean(leakage_values)

    return results


class OverlapAddFramework:
    """
    Implements overlap-add framework for efficient filtering.

    Used in short-time Fourier transform and FFT-based convolution.
    """

    def __init__(self, hop_size: int, window_size: int):
        """
        Initialize overlap-add framework.

        Args:
            hop_size: Number of samples between frame centers.
            window_size: Analysis window length.
        """
        if hop_size < 1 or window_size < 1:
            raise SignalError("hop_size and window_size must be positive")

        self.hop_size = hop_size
        self.window_size = window_size
        self.buffer = np.zeros(window_size, dtype=np.float64)

    def process_frame(
        self,
        frame: np.ndarray,
        processing_func,
    ) -> np.ndarray:
        """
        Process a frame of audio using overlap-add.

        Args:
            frame: Input frame (length = hop_size).
            processing_func: Function to apply to windowed frame.

        Returns:
            Output frame (length = hop_size).
        """
        frame = np.asarray(frame, dtype=np.float64)

        if len(frame) != self.hop_size:
            raise SignalError(f"Frame length {len(frame)} doesn't match hop_size {self.hop_size}")

        # Shift buffer and add new frame
        self.buffer = np.concatenate([self.buffer[self.hop_size :], frame])

        # Apply processing function
        processed = processing_func(self.buffer)

        # Return middle portion
        start = (self.window_size - self.hop_size) // 2
        return processed[start : start + self.hop_size]
