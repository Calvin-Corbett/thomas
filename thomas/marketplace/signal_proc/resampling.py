"""
Sample rate conversion and resampling.

Provides upsampling, downsampling, and various interpolation methods.
"""

from __future__ import annotations

import numpy as np

from thomas.marketplace.signal_proc._exceptions import SignalError
from thomas.marketplace.signal_proc.convolution import convolve
from thomas.marketplace.signal_proc.filters import design_lowpass_fir


def upsample(x: np.ndarray, factor: int) -> np.ndarray:
    """
    Upsample signal by inserting zeros.

    Should be followed by lowpass filtering to remove imaging artifacts.

    Args:
        x: Input signal.
        factor: Upsampling factor (insert factor-1 zeros between samples).

    Returns:
        Upsampled signal (length: len(x) * factor).
    """
    x = np.asarray(x, dtype=np.float64)

    if factor < 1:
        raise SignalError("Upsampling factor must be >= 1")

    upsampled = np.zeros(len(x) * factor, dtype=np.float64)
    upsampled[::factor] = x

    return upsampled


def downsample(x: np.ndarray, factor: int) -> np.ndarray:
    """
    Downsample signal (simple decimation).

    Should be preceded by lowpass filtering to prevent aliasing.

    Args:
        x: Input signal.
        factor: Downsampling factor (keep every factor-th sample).

    Returns:
        Downsampled signal (length: ceil(len(x) / factor)).
    """
    x = np.asarray(x, dtype=np.float64)

    if factor < 1:
        raise SignalError("Downsampling factor must be >= 1")

    return x[::factor]


def resample_rational(
    x: np.ndarray,
    sample_rate: float,
    new_sample_rate: float,
) -> np.ndarray:
    """
    Resample signal to new sample rate using rational upsampling/downsampling.

    Args:
        x: Input signal.
        sample_rate: Original sample rate in Hz.
        new_sample_rate: Target sample rate in Hz.

    Returns:
        Resampled signal.

    Raises:
        SignalError: If sample rates are invalid.
    """
    x = np.asarray(x, dtype=np.float64)

    if sample_rate <= 0 or new_sample_rate <= 0:
        raise SignalError("Sample rates must be positive")

    ratio = new_sample_rate / sample_rate

    # Find rational approximation
    from fractions import Fraction

    frac = Fraction(new_sample_rate / sample_rate).limit_denominator(100000)
    up_factor = frac.numerator
    down_factor = frac.denominator

    # Upsample
    x_up = upsample(x, up_factor)

    # Lowpass filter at half the lower sample rate
    min_rate = min(sample_rate, new_sample_rate)
    cutoff = min_rate / 2 * 0.95  # Slightly below Nyquist

    num_taps = max(101, 4 * up_factor)
    h = design_lowpass_fir(cutoff, up_factor * sample_rate, num_taps)

    x_filtered = convolve(x_up, h, mode="same")

    # Downsample
    x_resampled = downsample(x_filtered, down_factor)

    return x_resampled


def resample_linear(
    x: np.ndarray,
    sample_rate: float,
    new_sample_rate: float,
) -> np.ndarray:
    """
    Resample using linear interpolation.

    Simple but introduces aliasing. Use for moderate resampling only.

    Args:
        x: Input signal.
        sample_rate: Original sample rate in Hz.
        new_sample_rate: Target sample rate in Hz.

    Returns:
        Resampled signal.
    """
    x = np.asarray(x, dtype=np.float64)

    if sample_rate <= 0 or new_sample_rate <= 0:
        raise SignalError("Sample rates must be positive")

    ratio = new_sample_rate / sample_rate
    n_new = int(np.ceil(len(x) * ratio))

    # New time positions in old sample indices
    new_positions = np.arange(n_new) / ratio

    # Linear interpolation
    indices_low = np.floor(new_positions).astype(int)
    indices_high = np.ceil(new_positions).astype(int)
    frac = new_positions - indices_low

    # Clip indices
    indices_low = np.clip(indices_low, 0, len(x) - 1)
    indices_high = np.clip(indices_high, 0, len(x) - 1)

    x_new = (1 - frac) * x[indices_low] + frac * x[indices_high]

    return x_new


def resample_sinc(
    x: np.ndarray,
    sample_rate: float,
    new_sample_rate: float,
    num_taps: int = 64,
) -> np.ndarray:
    """
    Resample using sinc interpolation (high-quality, slow).

    Uses windowed sinc kernel for band-limited interpolation.

    Args:
        x: Input signal.
        sample_rate: Original sample rate in Hz.
        new_sample_rate: Target sample rate in Hz.
        num_taps: Sinc kernel length (higher = better but slower).

    Returns:
        Resampled signal.
    """
    x = np.asarray(x, dtype=np.float64)

    if sample_rate <= 0 or new_sample_rate <= 0:
        raise SignalError("Sample rates must be positive")

    ratio = new_sample_rate / sample_rate
    n_new = int(np.ceil(len(x) * ratio))

    # New time positions in old sample indices
    new_positions = np.arange(n_new) / ratio

    # Pad input for boundary handling
    pad_len = num_taps // 2
    x_padded = np.pad(x, (pad_len, pad_len), mode="reflect")

    x_new = np.zeros(n_new, dtype=np.float64)

    for i, pos in enumerate(new_positions):
        # Kernel centered at position
        pos_padded = pos + pad_len

        # Integer and fractional parts
        idx_center = int(np.round(pos_padded))
        frac = pos_padded - idx_center

        # Sinc kernel
        sinc_kernel = np.zeros(num_taps)

        for k in range(num_taps):
            idx = idx_center - num_taps // 2 + k

            if 0 <= idx < len(x_padded):
                delay = idx - pos_padded

                if abs(delay) < 1e-10:
                    sinc_kernel[k] = 1.0
                else:
                    sinc_kernel[k] = np.sin(np.pi * delay) / (np.pi * delay)

                    # Hamming window
                    window_val = 0.54 - 0.46 * np.cos(2 * np.pi * (k + 1) / num_taps)
                    sinc_kernel[k] *= window_val

        # Interpolation
        idx_start = max(0, idx_center - num_taps // 2)
        idx_end = min(len(x_padded), idx_center + num_taps // 2)
        kernel_valid = sinc_kernel[: idx_end - idx_start]

        x_new[i] = np.sum(x_padded[idx_start:idx_end] * kernel_valid)

    return x_new


def design_anti_aliasing_filter(
    sample_rate: float,
    new_sample_rate: float,
    filter_order: int = 51,
) -> np.ndarray:
    """
    Design anti-aliasing filter for downsampling.

    Creates a lowpass filter with cutoff at half the lower sample rate.

    Args:
        sample_rate: Original sample rate in Hz.
        new_sample_rate: Target sample rate in Hz.
        filter_order: Filter order (number of taps).

    Returns:
        Filter coefficients.
    """
    if new_sample_rate > sample_rate:
        raise SignalError("Anti-aliasing filter is for downsampling (new_rate < old_rate)")

    cutoff = new_sample_rate / 2 * 0.95

    h = design_lowpass_fir(cutoff, sample_rate, filter_order)

    return h


def optimal_resample(
    x: np.ndarray,
    sample_rate: float,
    new_sample_rate: float,
    quality: str = "high",
) -> np.ndarray:
    """
    Intelligently choose resampling method based on ratio and quality setting.

    Args:
        x: Input signal.
        sample_rate: Original sample rate in Hz.
        new_sample_rate: Target sample rate in Hz.
        quality: 'low' (linear), 'medium' (rational), or 'high' (sinc).

    Returns:
        Resampled signal.
    """
    if quality == "low":
        return resample_linear(x, sample_rate, new_sample_rate)

    elif quality == "medium":
        return resample_rational(x, sample_rate, new_sample_rate)

    elif quality == "high":
        return resample_sinc(x, sample_rate, new_sample_rate, num_taps=256)

    else:
        raise SignalError("quality must be 'low', 'medium', or 'high'")
