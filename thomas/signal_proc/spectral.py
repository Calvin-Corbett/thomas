"""
Spectral analysis tools.

Provides STFT, Welch's method, cepstrum, and spectral features (centroid, bandwidth, etc.).
"""

from __future__ import annotations

import numpy as np

from thomas.signal_proc._exceptions import SignalError
from thomas.signal_proc._types import Signal, Spectrogram
from thomas.signal_proc.fft import fft, frequency_bins, magnitude_spectrum, phase_spectrum
from thomas.signal_proc.windows import window


def stft(
    signal: np.ndarray | Signal,
    window_size: int = 1024,
    hop_size: int | None = None,
    window_type: str = "hanning",
    sample_rate: float = 1.0,
) -> Spectrogram:
    """
    Short-Time Fourier Transform (STFT).

    Args:
        signal: Input signal (array or Signal object).
        window_size: Analysis window length.
        hop_size: Hop size between frames (default: window_size // 4).
        window_type: Window function name.
        sample_rate: Sample rate in Hz (used for frequency/time axes).

    Returns:
        Spectrogram object.

    Raises:
        SignalError: If signal is empty or hop_size is invalid.
    """
    if isinstance(signal, Signal):
        samples = signal.samples
        sample_rate = signal.sample_rate
    else:
        samples = np.asarray(signal, dtype=np.float64)

    if len(samples) == 0:
        raise SignalError("Signal cannot be empty")

    if hop_size is None:
        hop_size = window_size // 4

    if hop_size < 1:
        raise SignalError("hop_size must be >= 1")

    # Get window
    w = window(window_type, window_size)

    n_frames = 1 + int(np.floor((len(samples) - window_size) / hop_size))

    if n_frames < 1:
        raise SignalError(f"Signal too short for window_size={window_size}, hop_size={hop_size}")

    # Allocate output
    n_freq = window_size // 2 + 1
    magnitude = np.zeros((n_frames, n_freq), dtype=np.float64)
    phase = np.zeros((n_frames, n_freq), dtype=np.float64)

    # Process frames
    for frame_idx in range(n_frames):
        start = frame_idx * hop_size
        end = start + window_size

        if end > len(samples):
            # Pad last frame
            frame = np.pad(
                samples[start:],
                (0, end - len(samples)),
                mode="constant",
            )
        else:
            frame = samples[start:end]

        # Apply window
        windowed = frame * w

        # FFT
        X = fft(windowed)

        # Positive frequencies only
        X_pos = X[:n_freq]

        magnitude[frame_idx, :] = magnitude_spectrum(X_pos)
        phase[frame_idx, :] = phase_spectrum(X_pos)

    # Time and frequency axes
    time_frames = np.arange(n_frames) * hop_size / sample_rate
    frequencies = frequency_bins(window_size, sample_rate, positive_only=True)

    return Spectrogram(time_frames, frequencies, magnitude, phase)


def spectrogram(
    signal: np.ndarray | Signal,
    window_size: int = 1024,
    hop_size: int | None = None,
    window_type: str = "hanning",
    sample_rate: float = 1.0,
) -> Spectrogram:
    """
    Compute spectrogram (magnitude STFT).

    Alias for stft() for convenience.

    Args:
        signal: Input signal.
        window_size: Analysis window length.
        hop_size: Hop size between frames.
        window_type: Window function name.
        sample_rate: Sample rate in Hz.

    Returns:
        Spectrogram object.
    """
    return stft(signal, window_size, hop_size, window_type, sample_rate)


def welch_psd(
    signal: np.ndarray | Signal,
    nperseg: int = 256,
    noverlap: int | None = None,
    window_type: str = "hanning",
    sample_rate: float = 1.0,
    scaling: str = "density",
) -> tuple[np.ndarray, np.ndarray]:
    """
    Power Spectral Density (PSD) using Welch's method.

    Averaging periodograms reduces variance.

    Args:
        signal: Input signal.
        nperseg: Length of each segment.
        noverlap: Overlap between segments (default: nperseg // 2).
        window_type: Window function.
        sample_rate: Sample rate in Hz.
        scaling: 'density' (V^2/Hz) or 'spectrum' (V^2).

    Returns:
        Tuple of (frequencies, PSD values).
    """
    if isinstance(signal, Signal):
        samples = signal.samples
        sample_rate = signal.sample_rate
    else:
        samples = np.asarray(signal, dtype=np.float64)

    if noverlap is None:
        noverlap = nperseg // 2

    # Compute stft
    spec = stft(
        samples,
        window_size=nperseg,
        hop_size=nperseg - noverlap,
        window_type=window_type,
        sample_rate=sample_rate,
    )

    # Average power over time
    power = spec.power
    psd = np.mean(power, axis=0)

    # Scaling
    if scaling == "density":
        psd = psd / sample_rate
    elif scaling != "spectrum":
        raise SignalError("scaling must be 'density' or 'spectrum'")

    return spec.frequencies, psd


def cepstrum(X: np.ndarray) -> np.ndarray:
    """
    Compute cepstrum (log spectrum → inverse FFT).

    Useful for pitch detection and formant analysis.

    Args:
        X: FFT coefficients.

    Returns:
        Cepstral coefficients.
    """
    X = np.asarray(X, dtype=np.complex128)

    # Log magnitude spectrum
    log_mag = np.log(np.maximum(np.abs(X), 1e-10))

    # Inverse FFT
    cepstrum_vals = np.real(np.fft.ifft(log_mag))

    return cepstrum_vals


def spectral_centroid(
    frequencies: np.ndarray,
    magnitude_spectrum: np.ndarray,
) -> float:
    """
    Compute spectral centroid (center of mass).

    Args:
        frequencies: Frequency bins in Hz.
        magnitude_spectrum: Magnitude spectrum.

    Returns:
        Spectral centroid in Hz.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    mag = np.asarray(magnitude_spectrum, dtype=np.float64)

    if np.sum(mag) == 0:
        return 0.0

    centroid = np.sum(frequencies * mag) / np.sum(mag)
    return float(centroid)


def spectral_bandwidth(
    frequencies: np.ndarray,
    magnitude_spectrum: np.ndarray,
) -> float:
    """
    Compute spectral bandwidth (spread around centroid).

    Args:
        frequencies: Frequency bins in Hz.
        magnitude_spectrum: Magnitude spectrum.

    Returns:
        Spectral bandwidth in Hz.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    mag = np.asarray(magnitude_spectrum, dtype=np.float64)

    centroid = spectral_centroid(frequencies, mag)

    if np.sum(mag) == 0:
        return 0.0

    bandwidth = np.sqrt(np.sum(mag * (frequencies - centroid) ** 2) / np.sum(mag))
    return float(bandwidth)


def spectral_rolloff(
    frequencies: np.ndarray,
    magnitude_spectrum: np.ndarray,
    percentile: float = 0.99,
) -> float:
    """
    Compute spectral rolloff (frequency containing given percentage of energy).

    Args:
        frequencies: Frequency bins in Hz.
        magnitude_spectrum: Magnitude spectrum.
        percentile: Energy percentile (default: 0.99).

    Returns:
        Rolloff frequency in Hz.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    mag = np.asarray(magnitude_spectrum, dtype=np.float64)

    cumsum = np.cumsum(mag)
    cumsum = cumsum / cumsum[-1]

    idx = np.where(cumsum >= percentile)[0]
    if len(idx) > 0:
        rolloff = frequencies[idx[0]]
    else:
        rolloff = frequencies[-1]

    return float(rolloff)


def spectral_flatness(magnitude_spectrum: np.ndarray) -> float:
    """
    Compute spectral flatness (Wiener entropy).

    Ratio of geometric mean to arithmetic mean. Values close to 1 indicate noise-like.

    Args:
        magnitude_spectrum: Magnitude spectrum.

    Returns:
        Flatness (0 to 1).
    """
    mag = np.asarray(magnitude_spectrum, dtype=np.float64)

    if np.any(mag <= 0):
        mag = np.maximum(mag, 1e-10)

    geometric_mean = np.exp(np.mean(np.log(mag)))
    arithmetic_mean = np.mean(mag)

    flatness = geometric_mean / (arithmetic_mean + 1e-10)

    return float(np.clip(flatness, 0, 1))


def hz_to_mel(frequencies: np.ndarray) -> np.ndarray:
    """
    Convert frequency from Hz to Mel scale.

    Uses common formula: mel = 2595 * log10(1 + f/700).

    Args:
        frequencies: Frequencies in Hz.

    Returns:
        Frequencies in Mel.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    mel = 2595 * np.log10(1 + frequencies / 700)
    return mel


def mel_to_hz(mel_frequencies: np.ndarray) -> np.ndarray:
    """
    Convert frequency from Mel to Hz.

    Args:
        mel_frequencies: Frequencies in Mel.

    Returns:
        Frequencies in Hz.
    """
    mel_frequencies = np.asarray(mel_frequencies, dtype=np.float64)
    hz = 700 * (10 ** (mel_frequencies / 2595) - 1)
    return hz


def mel_spectrogram(
    signal: np.ndarray | Signal,
    n_mels: int = 128,
    window_size: int = 1024,
    hop_size: int | None = None,
    window_type: str = "hanning",
    sample_rate: float = 1.0,
) -> Spectrogram:
    """
    Compute Mel-scale spectrogram.

    Args:
        signal: Input signal.
        n_mels: Number of Mel bands.
        window_size: Analysis window length.
        hop_size: Hop size between frames.
        window_type: Window function name.
        sample_rate: Sample rate in Hz.

    Returns:
        Spectrogram with Mel-scale frequencies.
    """
    if isinstance(signal, Signal):
        sample_rate = signal.sample_rate

    # Compute linear spectrogram
    spec = stft(signal, window_size, hop_size, window_type, sample_rate)

    # Mel filter bank
    nyquist = sample_rate / 2
    mel_freqs = hz_to_mel(np.linspace(0, nyquist, n_mels + 2))
    hz_freqs = mel_to_hz(mel_freqs)

    # Create triangular filters
    mel_filterbank = np.zeros((n_mels, len(spec.frequencies)))

    for i in range(n_mels):
        left = hz_freqs[i]
        center = hz_freqs[i + 1]
        right = hz_freqs[i + 2]

        # Left slope
        left_slope = (spec.frequencies - left) / (center - left)
        # Right slope
        right_slope = (right - spec.frequencies) / (right - center)

        # Triangle
        mel_filterbank[i, :] = np.maximum(0, np.minimum(left_slope, right_slope))

    # Apply filterbank
    mel_magnitude = np.dot(spec.magnitude, mel_filterbank.T)

    # Update with Mel frequencies
    mel_frequencies = hz_freqs[1:-1]

    return Spectrogram(spec.time_frames, mel_frequencies, mel_magnitude, spec.phase)


def harmonic_percussive_separation(
    spec: Spectrogram,
    margin: float = 1.0,
) -> tuple[Spectrogram, Spectrogram]:
    """
    Separate spectrogram into harmonic and percussive components.

    Uses median filtering along time and frequency.

    Args:
        spec: Input spectrogram.
        margin: Margin parameter for soft masking (0 = hard mask, >1 = softer).

    Returns:
        Tuple of (harmonic spectrogram, percussive spectrogram).
    """
    from scipy import ndimage

    magnitude = spec.magnitude

    # Median filtering
    harmonic = ndimage.median_filter(magnitude, size=(5, 1))
    percussive = ndimage.median_filter(magnitude, size=(1, 5))

    # Soft masking
    H_energy = harmonic**margin
    P_energy = percussive**margin
    total_energy = H_energy + P_energy

    total_energy = np.maximum(total_energy, 1e-10)

    H_mask = H_energy / total_energy
    P_mask = P_energy / total_energy

    harmonic_spec = Spectrogram(
        spec.time_frames,
        spec.frequencies,
        magnitude * H_mask,
        spec.phase,
    )

    percussive_spec = Spectrogram(
        spec.time_frames,
        spec.frequencies,
        magnitude * P_mask,
        spec.phase,
    )

    return harmonic_spec, percussive_spec
