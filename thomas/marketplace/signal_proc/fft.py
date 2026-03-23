"""
Fast Fourier Transform (FFT) implementation.

Provides Cooley-Tukey radix-2 FFT (recursive and iterative),
inverse FFT, DFT reference, and related utilities.
"""

from __future__ import annotations

import numpy as np

from thomas.marketplace.signal_proc._exceptions import FFTError


def zero_pad_to_power2(signal: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Zero-pad signal to next power of 2.

    Args:
        signal: Input signal array.

    Returns:
        Tuple of (padded signal, original length).
    """
    original_length = len(signal)
    next_power = 2 ** np.ceil(np.log2(original_length)).astype(int)
    padded = np.zeros(next_power, dtype=np.complex128)
    padded[:original_length] = signal
    return padded, original_length


def _bit_reverse(n: int, k: int) -> int:
    """
    Reverse the bits of k in n-bit representation.

    Args:
        n: Number of bits.
        k: Value to reverse.

    Returns:
        Bit-reversed value.
    """
    result = 0
    for i in range(n):
        result = (result << 1) | (k & 1)
        k >>= 1
    return result


def fft_recursive(x: np.ndarray) -> np.ndarray:
    """
    Compute FFT using recursive Cooley-Tukey radix-2 algorithm.

    Args:
        x: Input signal (length must be power of 2).

    Returns:
        FFT coefficients.

    Raises:
        FFTError: If length is not a power of 2.
    """
    n = len(x)

    if n <= 1:
        return x.copy()

    if n & (n - 1) != 0:
        raise FFTError("Input length must be a power of 2")

    # Divide
    even = fft_recursive(x[0::2])
    odd = fft_recursive(x[1::2])

    # Combine
    result = np.zeros(n, dtype=np.complex128)
    for k in range(n // 2):
        w = np.exp(-2j * np.pi * k / n)
        result[k] = even[k] + w * odd[k]
        result[k + n // 2] = even[k] - w * odd[k]

    return result


def fft_iterative(x: np.ndarray) -> np.ndarray:
    """
    Compute FFT using iterative Cooley-Tukey radix-2 algorithm with bit reversal.

    Args:
        x: Input signal (length must be power of 2).

    Returns:
        FFT coefficients.

    Raises:
        FFTError: If length is not a power of 2.
    """
    n = len(x)

    if n <= 1:
        return x.copy()

    if n & (n - 1) != 0:
        raise FFTError("Input length must be a power of 2")

    # Bit reversal permutation
    x_reordered = np.zeros(n, dtype=np.complex128)
    bits = int(np.log2(n))
    for i in range(n):
        j = _bit_reverse(bits, i)
        x_reordered[j] = x[i]

    # Cooley-Tukey stages
    x_out = x_reordered.copy()
    stage_size = 2

    while stage_size <= n:
        half_stage = stage_size // 2

        for start in range(0, n, stage_size):
            for k in range(half_stage):
                idx1 = start + k
                idx2 = start + k + half_stage

                w = np.exp(-2j * np.pi * k / stage_size)
                t = w * x_out[idx2]
                x_out[idx2] = x_out[idx1] - t
                x_out[idx1] = x_out[idx1] + t

        stage_size *= 2

    return x_out


def fft(x: np.ndarray, use_iterative: bool = True) -> np.ndarray:
    """
    Compute Fast Fourier Transform.

    Uses Cooley-Tukey radix-2 algorithm. Input is automatically zero-padded
    to the nearest power of 2.

    Args:
        x: Input signal (real or complex).
        use_iterative: Use iterative algorithm (default True). If False, uses recursive.

    Returns:
        FFT coefficients.
    """
    x = np.asarray(x, dtype=np.complex128)

    if len(x) == 0:
        raise FFTError("Input signal cannot be empty")

    # Zero-pad to power of 2
    x_padded, _ = zero_pad_to_power2(x)

    if use_iterative:
        return fft_iterative(x_padded)
    else:
        return fft_recursive(x_padded)


def ifft(X: np.ndarray) -> np.ndarray:
    """
    Compute Inverse Fast Fourier Transform.

    Uses the conjugate property: IFFT(X) = conj(FFT(conj(X))) / N.

    Args:
        X: FFT coefficients.

    Returns:
        Time-domain signal.
    """
    X = np.asarray(X, dtype=np.complex128)
    n = len(X)

    # Conjugate property: IFFT(X) = conj(FFT(conj(X))) / n
    x_conj = fft(np.conj(X))
    x = np.conj(x_conj) / n

    return x


def dft(x: np.ndarray) -> np.ndarray:
    """
    Compute Discrete Fourier Transform (naive O(N^2) implementation).

    Provided for reference and validation. For production, use FFT.

    Args:
        x: Input signal.

    Returns:
        DFT coefficients.
    """
    x = np.asarray(x, dtype=np.complex128)
    n = len(x)
    X = np.zeros(n, dtype=np.complex128)

    for k in range(n):
        for n_idx in range(n):
            X[k] += x[n_idx] * np.exp(-2j * np.pi * k * n_idx / n)

    return X


def idft(X: np.ndarray) -> np.ndarray:
    """
    Compute Inverse Discrete Fourier Transform (naive O(N^2) implementation).

    Args:
        X: DFT coefficients.

    Returns:
        Time-domain signal.
    """
    X = np.asarray(X, dtype=np.complex128)
    n = len(X)
    x = np.zeros(n, dtype=np.complex128)

    for n_idx in range(n):
        for k in range(n):
            x[n_idx] += X[k] * np.exp(2j * np.pi * k * n_idx / n)
        x[n_idx] /= n

    return x


def real_fft(x: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Compute FFT optimized for real-valued inputs.

    Returns only positive frequencies (N/2 + 1 values).

    Args:
        x: Real-valued input signal.

    Returns:
        Tuple of (FFT coefficients for positive frequencies, original length).
    """
    x = np.asarray(x, dtype=np.float64)
    original_length = len(x)

    # Compute full FFT
    X_full = fft(x)

    # Return only positive frequencies
    n_positive = original_length // 2 + 1
    X_real = X_full[:n_positive]

    return X_real, original_length


def magnitude_spectrum(X: np.ndarray) -> np.ndarray:
    """
    Compute magnitude spectrum from FFT coefficients.

    Args:
        X: FFT coefficients.

    Returns:
        Magnitude values.
    """
    return np.abs(X)


def phase_spectrum(X: np.ndarray) -> np.ndarray:
    """
    Compute phase spectrum from FFT coefficients.

    Args:
        X: FFT coefficients.

    Returns:
        Phase values in radians [-pi, pi].
    """
    return np.angle(X)


def power_spectrum(X: np.ndarray, normalize: bool = True) -> np.ndarray:
    """
    Compute power spectrum from FFT coefficients.

    Args:
        X: FFT coefficients.
        normalize: If True, normalize by N^2 for one-sided spectrum interpretation.

    Returns:
        Power values.
    """
    n = len(X)
    power = np.abs(X) ** 2

    if normalize:
        power = power / (n**2)

    return power


def frequency_bins(
    n_samples: int,
    sample_rate: float,
    positive_only: bool = False,
) -> np.ndarray:
    """
    Compute frequency bins for FFT output.

    Args:
        n_samples: Number of time-domain samples.
        sample_rate: Sample rate in Hz.
        positive_only: If True, return only positive frequencies.

    Returns:
        Frequency values in Hz.
    """
    if positive_only:
        n_freq = n_samples // 2 + 1
        freqs = np.arange(n_freq) * sample_rate / n_samples
    else:
        freqs = np.fft.fftfreq(n_samples, 1.0 / sample_rate)

    return freqs


def fft_shift(X: np.ndarray) -> np.ndarray:
    """
    Shift zero-frequency component to center of spectrum.

    This is useful for visualization, centering DC at the middle.

    Args:
        X: FFT coefficients or magnitude/power spectrum.

    Returns:
        Shifted spectrum with DC component at center.
    """
    return np.fft.fftshift(X)


def ifft_shift(X: np.ndarray) -> np.ndarray:
    """
    Inverse FFT shift (undo fft_shift).

    Args:
        X: Shifted spectrum.

    Returns:
        Unshifted spectrum ready for IFFT.
    """
    return np.fft.ifftshift(X)


def spectral_centroid(
    frequencies: np.ndarray,
    magnitudes: np.ndarray,
) -> float:
    """
    Compute spectral centroid (center of mass of spectrum).

    Args:
        frequencies: Frequency bins in Hz.
        magnitudes: Magnitude spectrum.

    Returns:
        Spectral centroid in Hz.
    """
    magnitudes = np.asarray(magnitudes, dtype=np.float64)
    frequencies = np.asarray(frequencies, dtype=np.float64)

    if np.sum(magnitudes) == 0:
        return 0.0

    centroid = np.sum(frequencies * magnitudes) / np.sum(magnitudes)
    return float(centroid)


def verify_parseval(
    x: np.ndarray,
    X: np.ndarray,
) -> tuple[float, float]:
    """
    Verify Parseval's theorem: energy in time domain equals frequency domain.

    Args:
        x: Time-domain signal.
        X: FFT coefficients.

    Returns:
        Tuple of (time-domain energy, frequency-domain energy).
    """
    x = np.asarray(x, dtype=np.complex128)
    X = np.asarray(X, dtype=np.complex128)

    # Time-domain energy
    energy_time = np.sum(np.abs(x) ** 2)

    # Frequency-domain energy
    energy_freq = np.sum(np.abs(X) ** 2) / len(x)

    return float(energy_time), float(energy_freq)
