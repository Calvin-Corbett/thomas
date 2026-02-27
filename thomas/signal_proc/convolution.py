"""
Convolution operations (time-domain and frequency-domain).

Provides linear convolution, fast FFT-based convolution (overlap-add/overlap-save),
correlation, deconvolution, and matched filtering.
"""

from __future__ import annotations

import numpy as np

from thomas.signal_proc._exceptions import SignalError
from thomas.signal_proc.fft import fft, ifft


def convolve(x: np.ndarray, h: np.ndarray, mode: str = "full") -> np.ndarray:
    """
    Linear convolution in time domain.

    Args:
        x: Input signal.
        h: Filter kernel.
        mode: 'full' (full convolution), 'same' (same size as x), 'valid' (no zero-padding).

    Returns:
        Convolution result.

    Raises:
        SignalError: If mode is invalid.
    """
    x = np.asarray(x, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)

    if mode not in ["full", "same", "valid"]:
        raise SignalError("mode must be 'full', 'same', or 'valid'")

    n_x = len(x)
    n_h = len(h)

    # Full convolution (time-domain O(N*M))
    y = np.zeros(n_x + n_h - 1, dtype=np.float64)

    for i in range(n_x):
        for j in range(n_h):
            y[i + j] += x[i] * h[j]

    if mode == "same":
        # Center the output, same size as x
        start = n_h // 2
        y = y[start : start + n_x]
    elif mode == "valid":
        # Only where input and kernel fully overlap
        y = y[n_h - 1 : n_x]

    return y


def convolve_fft(x: np.ndarray, h: np.ndarray, mode: str = "full") -> np.ndarray:
    """
    Fast convolution using FFT (Overlap-Add method).

    Efficient for long signals and long filters.

    Args:
        x: Input signal.
        h: Filter kernel.
        mode: 'full', 'same', or 'valid'.

    Returns:
        Convolution result.
    """
    x = np.asarray(x, dtype=np.complex128)
    h = np.asarray(h, dtype=np.complex128)

    n_x = len(x)
    n_h = len(h)

    # Zero-pad to power of 2 for FFT efficiency
    n_fft = 2 ** np.ceil(np.log2(n_x + n_h - 1)).astype(int)

    X = fft(np.pad(x, (0, n_fft - n_x), mode="constant"))
    H = fft(np.pad(h, (0, n_fft - n_h), mode="constant"))

    Y = X * H
    y = np.real(ifft(Y))

    # Trim to appropriate length
    if mode == "full":
        y = y[: n_x + n_h - 1]
    elif mode == "same":
        start = n_h // 2
        y = y[start : start + n_x]
    elif mode == "valid":
        y = y[n_h - 1 : n_x]

    return y


def correlate(x: np.ndarray, h: np.ndarray, mode: str = "full") -> np.ndarray:
    """
    Cross-correlation (time-domain).

    Equivalent to convolution with reversed kernel.

    Args:
        x: First signal.
        h: Second signal (template).
        mode: 'full', 'same', or 'valid'.

    Returns:
        Cross-correlation.
    """
    h_reversed = np.asarray(h, dtype=np.float64)[::-1]
    return convolve(x, h_reversed, mode=mode)


def xcorr(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Cross-correlation with lag information.

    Args:
        x: First signal.
        y: Second signal.

    Returns:
        Tuple of (correlation values, lag indices).
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    corr = correlate(x, y, mode="full")
    lags = np.arange(-len(y) + 1, len(x))

    return corr, lags


def autocorr(x: np.ndarray, max_lag: int | None = None) -> np.ndarray:
    """
    Autocorrelation function.

    Args:
        x: Input signal.
        max_lag: Maximum lag to compute (default: length of signal).

    Returns:
        Autocorrelation values.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)

    if max_lag is None:
        max_lag = n

    max_lag = min(max_lag, n - 1)

    # Compute autocorrelation via FFT
    X = fft(np.pad(x, (0, n), mode="constant"))
    S = np.abs(X) ** 2
    acf = np.real(ifft(S))[: max_lag + 1]

    # Normalize
    acf = acf / acf[0]

    return acf


def deconvolve(
    y: np.ndarray,
    h: np.ndarray,
    regularization: float = 1e-6,
) -> np.ndarray:
    """
    Deconvolution via spectral division (Wiener filter approach).

    Args:
        y: Observed signal.
        h: Known filter.
        regularization: Regularization parameter for numerical stability.

    Returns:
        Estimated original signal.
    """
    y = np.asarray(y, dtype=np.complex128)
    h = np.asarray(h, dtype=np.complex128)

    # Pad to same length
    max_len = max(len(y), len(h))
    y_pad = np.pad(y, (0, max_len - len(y)), mode="constant")
    h_pad = np.pad(h, (0, max_len - len(h)), mode="constant")

    # FFT
    Y = fft(y_pad)
    H = fft(h_pad)

    # Spectral division with regularization
    H_conj = np.conj(H)
    H_power = np.abs(H) ** 2

    X = Y * H_conj / (H_power + regularization)

    # Inverse FFT
    x = np.real(ifft(X))

    return x[: len(y)]


def matched_filter(
    signal: np.ndarray,
    template: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Matched filtering for signal detection.

    Returns correlation of signal with template and detection confidence.

    Args:
        signal: Input signal.
        template: Template to match (typically shorter).

    Returns:
        Tuple of (correlation output, normalized correlation).
    """
    signal = np.asarray(signal, dtype=np.float64)
    template = np.asarray(template, dtype=np.float64)

    # Compute correlation
    corr = correlate(signal, template, mode="same")

    # Normalize by template energy
    template_energy = np.sqrt(np.sum(template**2))
    if template_energy > 0:
        normalized = corr / template_energy
    else:
        normalized = corr

    return corr, normalized


def overlap_add(
    x: np.ndarray,
    h: np.ndarray,
    hop_size: int | None = None,
) -> np.ndarray:
    """
    Efficient filtering using overlap-add method.

    Useful for real-time or streaming applications.

    Args:
        x: Input signal.
        h: Filter kernel.
        hop_size: Processing hop size (default: len(h)).

    Returns:
        Filtered signal.
    """
    x = np.asarray(x, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)

    if hop_size is None:
        hop_size = len(h)

    n_h = len(h)
    n_x = len(x)
    n_frames = int(np.ceil(n_x / hop_size))

    # Output buffer with padding for overlap
    output = np.zeros(n_x + n_h - 1, dtype=np.float64)

    for frame_idx in range(n_frames):
        start = frame_idx * hop_size
        end = min(start + hop_size, n_x)

        # Zero-pad frame
        frame = np.pad(x[start:end], (0, hop_size - (end - start)), mode="constant")

        # Convolve frame
        filtered = convolve_fft(frame, h, mode="full")

        # Add to output with overlap
        output[start : start + len(filtered)] += filtered[: n_x + n_h - 1 - start]

    return output[:n_x]


def overlap_save(
    x: np.ndarray,
    h: np.ndarray,
    hop_size: int | None = None,
) -> np.ndarray:
    """
    Filtering using overlap-save method.

    Alternative to overlap-add, useful for frequency-domain processing.

    Args:
        x: Input signal.
        h: Filter kernel.
        hop_size: Processing hop size (default: len(h)).

    Returns:
        Filtered signal.
    """
    x = np.asarray(x, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)

    if hop_size is None:
        hop_size = len(h)

    n_h = len(h)
    n_x = len(x)
    n_fft = hop_size + n_h - 1

    # Pad input with zeros at start (for circular convolution wrap)
    x_padded = np.pad(x, (n_h - 1, n_h - 1), mode="constant")

    output = np.zeros(n_x, dtype=np.float64)
    out_idx = 0

    # FFT of filter
    H = fft(np.pad(h, (0, n_fft - n_h), mode="constant"))

    for frame_idx in range(0, len(x_padded) - n_h + 1, hop_size):
        frame = x_padded[frame_idx : frame_idx + n_fft]

        if len(frame) < n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)), mode="constant")

        # FFT convolution
        X = fft(frame)
        Y = X * H
        y_frame = np.real(ifft(Y))

        # Keep only valid part (discard first n_h-1 samples)
        valid_start = n_h - 1
        valid_end = n_h - 1 + hop_size
        valid_samples = y_frame[valid_start:valid_end]

        out_len = min(len(valid_samples), n_x - out_idx)
        output[out_idx : out_idx + out_len] = valid_samples[:out_len]
        out_idx += out_len

    return output
