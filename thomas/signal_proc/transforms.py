"""
Signal transforms.

Provides Hilbert transform, DCT, STFT, wavelet transform, and Z-transform evaluation.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from thomas.signal_proc._exceptions import SignalError
from thomas.signal_proc.fft import fft, ifft


def hilbert_transform(x: np.ndarray) -> np.ndarray:
    """
    Compute analytic signal via Hilbert transform.

    Returns the complex envelope (analytic signal) where the imaginary part
    is the Hilbert transform of the input.

    Args:
        x: Real-valued input signal.

    Returns:
        Complex analytic signal.
    """
    x = np.asarray(x, dtype=np.complex128)
    n = len(x)

    # FFT
    X = fft(x)

    # Create Hilbert filter: 1 for positive frequencies, -1 for negative, 0 for DC and Nyquist
    h = np.zeros(n, dtype=np.float64)
    if n % 2 == 0:
        h[1 : n // 2] = 2
    else:
        h[1 : (n + 1) // 2] = 2

    # Apply filter
    X_analytic = X * h

    # IFFT
    analytic = ifft(X_analytic)

    return analytic


def dct(x: np.ndarray, kind: int = 2) -> np.ndarray:
    """
    Discrete Cosine Transform.

    Args:
        x: Input signal.
        kind: DCT type (1-4, default: 2 which is most common).

    Returns:
        DCT coefficients.

    Raises:
        SignalError: If kind is invalid.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)

    if kind == 2:
        # DCT-II (most common)
        # C[k] = sum_{j=0}^{n-1} x[j] * cos(pi * (j + 0.5) * k / n)

        result = np.zeros(n, dtype=np.float64)
        for k in range(n):
            for j in range(n):
                result[k] += x[j] * np.cos(np.pi * (j + 0.5) * k / n)

        # Normalization
        result[0] *= 0.5
        result *= np.sqrt(2.0 / n)

        return result

    elif kind == 1:
        # DCT-I
        result = np.zeros(n, dtype=np.float64)
        for k in range(n):
            result[k] += x[0] * (-1) ** k + x[-1] * (-1) ** (k * (n - 1))

            for j in range(1, n - 1):
                result[k] += 2 * x[j] * np.cos(np.pi * j * k / (n - 1))

        result *= np.sqrt(1.0 / (2 * (n - 1)))

        return result

    else:
        raise SignalError(f"DCT kind {kind} not supported (use 1 or 2)")


def idct(X: np.ndarray, kind: int = 2) -> np.ndarray:
    """
    Inverse Discrete Cosine Transform.

    Args:
        X: DCT coefficients.
        kind: DCT type (must match forward transform).

    Returns:
        Time-domain signal.
    """
    X = np.asarray(X, dtype=np.float64)
    n = len(X)

    if kind == 2:
        # IDCT-II
        result = np.zeros(n, dtype=np.float64)

        for j in range(n):
            result[j] += X[0] * 0.5

            for k in range(1, n):
                result[j] += X[k] * np.cos(np.pi * (j + 0.5) * k / n)

        result *= np.sqrt(2.0 / n)

        return result

    elif kind == 1:
        # IDCT-I
        result = np.zeros(n, dtype=np.float64)

        for j in range(n):
            result[j] += X[0] + X[-1] * (-1) ** j

            for k in range(1, n - 1):
                result[j] += 2 * X[k] * np.cos(np.pi * j * k / (n - 1))

        result *= np.sqrt(1.0 / (2 * (n - 1)))

        return result

    else:
        raise SignalError(f"IDCT kind {kind} not supported (use 1 or 2)")


def wavelet_transform(
    x: np.ndarray,
    wavelet: str = "haar",
    level: int = 1,
) -> tuple[np.ndarray, list]:
    """
    Wavelet decomposition (dyadic decomposition).

    Args:
        x: Input signal.
        wavelet: Wavelet name ('haar', 'db4' for Daubechies-4).
        level: Decomposition level.

    Returns:
        Tuple of (approximation coefficients, list of detail coefficients at each level).
    """
    x = np.asarray(x, dtype=np.float64)

    if wavelet == "haar":
        # Haar wavelet
        h_lo = np.array([1, 1]) / np.sqrt(2)
        h_hi = np.array([1, -1]) / np.sqrt(2)
    elif wavelet == "db4":
        # Daubechies-4 wavelet
        sqrt_3 = np.sqrt(3)
        h_lo = np.array([1 + sqrt_3, 3 + sqrt_3, 3 - sqrt_3, 1 - sqrt_3]) / (4 * np.sqrt(2))
        h_hi = np.array([1 - sqrt_3, -3 + sqrt_3, 3 + sqrt_3, -1 - sqrt_3]) / (4 * np.sqrt(2))
    else:
        raise SignalError(f"Unknown wavelet: {wavelet}")

    approximation = x.copy()
    details = []

    for _ in range(level):
        # Lowpass filter (approximation)
        c_a = np.convolve(approximation, h_lo, mode="valid")
        # Downsample
        c_a = c_a[::2]

        # Highpass filter (details)
        c_d = np.convolve(approximation, h_hi, mode="valid")
        # Downsample
        c_d = c_d[::2]

        details.append(c_d)
        approximation = c_a

    return approximation, details


def inverse_wavelet_transform(
    approximation: np.ndarray,
    details: list,
    wavelet: str = "haar",
) -> np.ndarray:
    """
    Inverse wavelet decomposition (reconstruction).

    Args:
        approximation: Approximation coefficients at finest level.
        details: List of detail coefficients from coarsest to finest.
        wavelet: Wavelet name.

    Returns:
        Reconstructed signal.
    """
    if wavelet == "haar":
        # Reconstruction filters (transpose of analysis filters)
        g_lo = np.array([1, 1]) / np.sqrt(2)
        g_hi = np.array([1, -1]) / np.sqrt(2)
    elif wavelet == "db4":
        sqrt_3 = np.sqrt(3)
        g_lo = np.array([1 - sqrt_3, -3 + sqrt_3, 3 + sqrt_3, -1 - sqrt_3]) / (4 * np.sqrt(2))
        g_hi = np.array([1 + sqrt_3, 3 + sqrt_3, 3 - sqrt_3, 1 - sqrt_3]) / (4 * np.sqrt(2))
    else:
        raise SignalError(f"Unknown wavelet: {wavelet}")

    signal = approximation.copy()

    # Reverse the details list (finest to coarsest)
    for detail in reversed(details):
        # Upsample
        n_signal = len(signal)
        n_detail = len(detail)

        signal_up = np.zeros(2 * n_signal)
        detail_up = np.zeros(2 * n_detail)

        signal_up[::2] = signal
        detail_up[::2] = detail

        # Reconstruct
        approx_recon = np.convolve(signal_up, g_lo, mode="same")
        detail_recon = np.convolve(detail_up, g_hi, mode="same")

        signal = approx_recon + detail_recon

    return signal


def z_transform(
    h: np.ndarray,
    z_values: np.ndarray | complex,
) -> np.ndarray | complex:
    """
    Evaluate Z-transform at given z values.

    H(z) = sum_{n=0}^{N-1} h[n] * z^(-n)

    Args:
        h: Filter coefficients.
        z_values: Points in z-plane where to evaluate (complex or array).

    Returns:
        Transfer function values at z_values.
    """
    h = np.asarray(h, dtype=np.complex128)

    if np.isscalar(z_values):
        z = np.complex128(z_values)
        result = 0.0j

        for n, h_n in enumerate(h):
            result += h_n * (z ** (-n))

        return result

    else:
        z_values = np.asarray(z_values, dtype=np.complex128)
        result = np.zeros_like(z_values, dtype=np.complex128)

        for n, h_n in enumerate(h):
            result += h_n * (z_values ** (-n))

        return result


def short_time_fourier_transform(
    x: np.ndarray,
    window_func: Callable,
    window_size: int,
    hop_size: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Short-time Fourier transform (manual implementation).

    Args:
        x: Input signal.
        window_func: Window function (callable that takes n and returns window).
        window_size: Analysis window size.
        hop_size: Hop size between frames (default: window_size // 4).

    Returns:
        Tuple of (magnitude spectrogram, phase spectrogram, time frames).
    """
    x = np.asarray(x, dtype=np.float64)

    if hop_size is None:
        hop_size = window_size // 4

    n_frames = 1 + (len(x) - window_size) // hop_size

    if n_frames < 1:
        raise SignalError("Signal too short for given window and hop size")

    w = window_func(window_size)

    magnitude = np.zeros((n_frames, window_size // 2 + 1), dtype=np.float64)
    phase = np.zeros((n_frames, window_size // 2 + 1), dtype=np.float64)

    for frame_idx in range(n_frames):
        start = frame_idx * hop_size
        frame = x[start : start + window_size]

        if len(frame) < window_size:
            frame = np.pad(frame, (0, window_size - len(frame)), mode="constant")

        windowed = frame * w

        X = fft(windowed)
        X_pos = X[: window_size // 2 + 1]

        magnitude[frame_idx, :] = np.abs(X_pos)
        phase[frame_idx, :] = np.angle(X_pos)

    time_frames = np.arange(n_frames) * hop_size

    return magnitude, phase, time_frames
