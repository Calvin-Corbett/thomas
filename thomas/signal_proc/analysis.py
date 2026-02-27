"""
Signal analysis tools.

Provides feature extraction (zero-crossing rate, energy, peak detection),
fundamental frequency estimation, signal statistics, and envelope detection.
"""

from __future__ import annotations

import numpy as np

from thomas.signal_proc._exceptions import SignalError


def zero_crossing_rate(x: np.ndarray, frame_length: int | None = None) -> np.ndarray | float:
    """
    Compute zero-crossing rate (ZCR).

    Useful for detecting voiced/unvoiced segments in speech.

    Args:
        x: Input signal.
        frame_length: If specified, compute ZCR in frames of this length.
                     Otherwise, compute ZCR over entire signal.

    Returns:
        Zero-crossing rate (scalar or array of frame ZCRs).
    """
    x = np.asarray(x, dtype=np.float64)

    if frame_length is None:
        # Full signal ZCR
        sign_changes = np.sum(np.abs(np.diff(np.sign(x)))) / 2
        zcr = sign_changes / len(x)
        return float(zcr)

    else:
        # Frame-based ZCR
        n_frames = (len(x) - frame_length) // frame_length + 1
        zcr = np.zeros(n_frames, dtype=np.float64)

        for i in range(n_frames):
            start = i * frame_length
            frame = x[start : start + frame_length]
            sign_changes = np.sum(np.abs(np.diff(np.sign(frame)))) / 2
            zcr[i] = sign_changes / frame_length

        return zcr


def rms_energy(x: np.ndarray, frame_length: int | None = None) -> np.ndarray | float:
    """
    Compute RMS energy.

    Args:
        x: Input signal.
        frame_length: If specified, compute RMS in frames.

    Returns:
        RMS energy (scalar or array).
    """
    x = np.asarray(x, dtype=np.float64)

    if frame_length is None:
        return float(np.sqrt(np.mean(x**2)))

    else:
        n_frames = (len(x) - frame_length) // frame_length + 1
        energy = np.zeros(n_frames, dtype=np.float64)

        for i in range(n_frames):
            start = i * frame_length
            frame = x[start : start + frame_length]
            energy[i] = np.sqrt(np.mean(frame**2))

        return energy


def peak_detect(
    x: np.ndarray,
    threshold: float | None = None,
    min_distance: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Detect local maxima (peaks) in signal.

    Args:
        x: Input signal.
        threshold: Minimum peak height (default: median + std).
        min_distance: Minimum distance between peaks in samples.

    Returns:
        Tuple of (peak indices, peak values).
    """
    x = np.asarray(x, dtype=np.float64)

    if threshold is None:
        threshold = np.median(x) + np.std(x)

    # Find local maxima
    peaks = []
    for i in range(1, len(x) - 1):
        if x[i] > x[i - 1] and x[i] > x[i + 1] and x[i] > threshold:
            peaks.append(i)

    # Apply minimum distance constraint
    if len(peaks) > 0:
        peaks = np.array(peaks)
        valid_peaks = [peaks[0]]

        for peak in peaks[1:]:
            if peak - valid_peaks[-1] >= min_distance:
                valid_peaks.append(peak)

        peaks = np.array(valid_peaks)
    else:
        peaks = np.array([], dtype=int)

    peak_values = x[peaks] if len(peaks) > 0 else np.array([])

    return peaks, peak_values


def fundamental_frequency(
    x: np.ndarray,
    sample_rate: float,
    min_freq: float = 50.0,
    max_freq: float = 500.0,
) -> float:
    """
    Estimate fundamental frequency using autocorrelation method.

    Args:
        x: Input signal.
        sample_rate: Sample rate in Hz.
        min_freq: Minimum frequency to search in Hz.
        max_freq: Maximum frequency to search in Hz.

    Returns:
        Estimated fundamental frequency in Hz.
    """
    x = np.asarray(x, dtype=np.float64)

    # Compute autocorrelation
    acf = np.correlate(x, x, mode="full")
    acf = acf[len(acf) // 2 :]

    # Convert frequency bounds to lag values
    lag_min = int(sample_rate / max_freq)
    lag_max = int(sample_rate / min_freq)

    # Find peak in autocorrelation within frequency range
    if lag_max > len(acf):
        lag_max = len(acf) - 1

    lag_range = acf[lag_min:lag_max]
    peak_lag = np.argmax(lag_range) + lag_min

    # Convert lag to frequency
    f0 = sample_rate / peak_lag

    return float(f0)


def snr(
    signal: np.ndarray,
    noise: np.ndarray | None = None,
) -> float:
    """
    Compute Signal-to-Noise Ratio (SNR) in dB.

    Args:
        signal: Input signal.
        noise: Noise samples. If None, assumes signal is [-1, 0] and estimates noise from power dip.

    Returns:
        SNR in dB.
    """
    signal = np.asarray(signal, dtype=np.float64)

    if noise is None:
        # Simple estimate: assume quieter portion is noise
        power = signal**2
        threshold = np.median(power)
        noise_est = signal[power < threshold]

        if len(noise_est) == 0:
            noise_est = signal * 0.1

        noise = noise_est

    noise = np.asarray(noise, dtype=np.float64)

    signal_power = np.mean(signal**2)
    noise_power = np.mean(noise**2)

    if noise_power == 0:
        return float("inf")

    snr_db = 10 * np.log10(signal_power / noise_power)

    return float(snr_db)


def signal_stats(x: np.ndarray) -> dict:
    """
    Compute comprehensive signal statistics.

    Args:
        x: Input signal.

    Returns:
        Dictionary of statistics.
    """
    x = np.asarray(x, dtype=np.float64)

    mean = float(np.mean(x))
    variance = float(np.var(x))
    std_dev = float(np.std(x))

    min_val = float(np.min(x))
    max_val = float(np.max(x))
    peak_to_peak = max_val - min_val

    rms = float(np.sqrt(np.mean(x**2)))
    crest_factor = peak_to_peak / (2 * rms) if rms > 0 else 0.0

    skewness = float(np.mean(((x - mean) / std_dev) ** 3)) if std_dev > 0 else 0.0
    kurtosis = float(np.mean(((x - mean) / std_dev) ** 4)) if std_dev > 0 else 0.0

    return {
        "mean": mean,
        "variance": variance,
        "std_dev": std_dev,
        "min": min_val,
        "max": max_val,
        "peak_to_peak": peak_to_peak,
        "rms": rms,
        "crest_factor": crest_factor,
        "skewness": skewness,
        "kurtosis": kurtosis,
    }


def envelope_detect(x: np.ndarray, method: str = "hilbert") -> np.ndarray:
    """
    Detect signal envelope (amplitude modulation).

    Args:
        x: Input signal.
        method: 'hilbert' (analytic signal magnitude) or 'peak' (peak detection and interpolation).

    Returns:
        Envelope signal.

    Raises:
        SignalError: If method is unknown.
    """
    x = np.asarray(x, dtype=np.float64)

    if method == "hilbert":
        from thomas.signal_proc.transforms import hilbert_transform

        analytic = hilbert_transform(x)
        envelope = np.abs(analytic)

        return envelope

    elif method == "peak":
        # Peak detection and interpolation
        from scipy.interpolate import interp1d

        peaks, _ = peak_detect(np.abs(x))

        if len(peaks) < 2:
            return np.abs(x)

        # Interpolate between peaks
        f = interp1d(
            peaks,
            np.abs(x[peaks]),
            kind="cubic",
            fill_value="extrapolate",
            bounds_error=False,
        )

        envelope = f(np.arange(len(x)))
        envelope = np.maximum(envelope, 0)

        return envelope

    else:
        raise SignalError(f"Unknown envelope detection method: {method}")


def unwrap_phase(phase: np.ndarray, discontinuity: float = np.pi) -> np.ndarray:
    """
    Unwrap phase (remove discontinuities greater than pi).

    Args:
        phase: Phase in radians.
        discontinuity: Threshold for discontinuity detection (default: pi).

    Returns:
        Unwrapped phase.
    """
    phase = np.asarray(phase, dtype=np.float64)

    unwrapped = phase.copy()
    offset = 0

    for i in range(1, len(phase)):
        delta = unwrapped[i] - unwrapped[i - 1]

        if delta > discontinuity:
            offset -= 2 * np.pi
        elif delta < -discontinuity:
            offset += 2 * np.pi

        unwrapped[i] += offset

    return unwrapped


def spectral_centroid_time(
    x: np.ndarray,
    sample_rate: float,
    frame_length: int = 512,
) -> np.ndarray:
    """
    Compute spectral centroid over time (per frame).

    Args:
        x: Input signal.
        sample_rate: Sample rate in Hz.
        frame_length: Frame length in samples.

    Returns:
        Spectral centroid values over time.
    """
    from thomas.signal_proc.fft import fft, frequency_bins, magnitude_spectrum

    x = np.asarray(x, dtype=np.float64)
    n_frames = (len(x) - frame_length) // (frame_length // 2) + 1

    centroids = np.zeros(n_frames, dtype=np.float64)

    for i in range(n_frames):
        start = i * (frame_length // 2)
        frame = x[start : start + frame_length]

        if len(frame) < frame_length:
            frame = np.pad(frame, (0, frame_length - len(frame)), mode="constant")

        X = fft(frame)
        mag = magnitude_spectrum(X)
        freqs = frequency_bins(frame_length, sample_rate)

        if np.sum(mag) > 0:
            centroid = np.sum(freqs * mag) / np.sum(mag)
        else:
            centroid = 0.0

        centroids[i] = centroid

    return centroids
