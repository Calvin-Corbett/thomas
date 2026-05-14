"""
Signal synthesis and generation.

Provides waveform generators (sine, square, sawtooth, triangle), noise generators,
modulation, and ADSR envelope.
"""

from __future__ import annotations

import numpy as np

from thomas.marketplace.signal_proc._exceptions import SignalError
from thomas.marketplace.signal_proc._types import Signal


def sine_wave(
    frequency: float,
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
    phase: float = 0.0,
) -> Signal:
    """
    Generate sine wave.

    Args:
        frequency: Frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).
        phase: Initial phase in radians (default: 0).

    Returns:
        Signal object.
    """
    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    samples = amplitude * np.sin(2 * np.pi * frequency * t + phase)

    return Signal(samples, sample_rate)


def square_wave(
    frequency: float,
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
    duty_cycle: float = 0.5,
) -> Signal:
    """
    Generate square wave using additive synthesis (harmonics).

    Args:
        frequency: Fundamental frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).
        duty_cycle: Duty cycle (0 to 1, default: 0.5 for perfect square).

    Returns:
        Signal object.
    """
    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    # Fourier series for square wave (odd harmonics only)
    y = np.zeros(n_samples)
    max_harmonic = int(sample_rate / (2 * frequency))

    for k in range(1, max_harmonic, 2):
        harmonic = k
        # Amplitude scales as 4/(pi*k) for odd harmonics
        a_k = (4.0 / (np.pi * harmonic)) * amplitude

        if duty_cycle != 0.5:
            # General pulse train formula
            a_k *= np.sin(np.pi * harmonic * duty_cycle) / (np.pi * harmonic * duty_cycle)

        y += a_k * np.sin(2 * np.pi * harmonic * frequency * t)

    return Signal(y, sample_rate)


def sawtooth_wave(
    frequency: float,
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
) -> Signal:
    """
    Generate sawtooth wave (additive synthesis).

    Args:
        frequency: Fundamental frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).

    Returns:
        Signal object.
    """
    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    # Fourier series for sawtooth wave (all harmonics)
    y = np.zeros(n_samples)
    max_harmonic = int(sample_rate / (2 * frequency))

    for k in range(1, max_harmonic):
        # Amplitude scales as -2/(pi*k) for sawtooth
        a_k = (-2.0 / (np.pi * k)) * amplitude
        y += a_k * np.sin(2 * np.pi * k * frequency * t)

    return Signal(y, sample_rate)


def triangle_wave(
    frequency: float,
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
) -> Signal:
    """
    Generate triangle wave (additive synthesis).

    Args:
        frequency: Fundamental frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).

    Returns:
        Signal object.
    """
    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    # Fourier series for triangle wave (odd harmonics only)
    y = np.zeros(n_samples)
    max_harmonic = int(sample_rate / (2 * frequency))

    for k in range(1, max_harmonic, 2):
        harmonic = k
        # Amplitude scales as 8/(pi^2*k^2) for odd harmonics
        a_k = (8.0 / (np.pi**2 * harmonic**2)) * amplitude
        y += a_k * np.sin(2 * np.pi * harmonic * frequency * t)

    return Signal(y, sample_rate)


def white_noise(
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
    seed: int | None = None,
) -> Signal:
    """
    Generate white noise (flat frequency spectrum).

    Args:
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).
        seed: Random seed (for reproducibility).

    Returns:
        Signal object.
    """
    if seed is not None:
        np.random.seed(seed)

    n_samples = int(np.ceil(duration * sample_rate))
    samples = amplitude * np.random.randn(n_samples)

    return Signal(samples, sample_rate)


def pink_noise(
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
    seed: int | None = None,
) -> Signal:
    """
    Generate pink noise (1/f spectrum) using filtering.

    Args:
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).
        seed: Random seed.

    Returns:
        Signal object.
    """
    if seed is not None:
        np.random.seed(seed)

    n_samples = int(np.ceil(duration * sample_rate))

    # Generate white noise
    white = np.random.randn(n_samples)

    # Simple pink noise filter: apply 1st-order lowpass iteratively
    pink = white.copy()
    alpha = 0.99

    for i in range(1, n_samples):
        pink[i] = alpha * pink[i - 1] + (1 - alpha) * white[i]

    # Normalize
    pink = amplitude * pink / np.std(pink)

    return Signal(pink, sample_rate)


def chirp(
    start_freq: float,
    end_freq: float,
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
    chirp_type: str = "linear",
) -> Signal:
    """
    Generate chirp signal (frequency sweep).

    Args:
        start_freq: Starting frequency in Hz.
        end_freq: Ending frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).
        chirp_type: 'linear' or 'logarithmic'.

    Returns:
        Signal object.

    Raises:
        SignalError: If chirp_type is unknown.
    """
    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    if chirp_type == "linear":
        # Linear frequency change
        freq_rate = (end_freq - start_freq) / duration
        phase = 2 * np.pi * (start_freq * t + 0.5 * freq_rate * t**2)

    elif chirp_type == "logarithmic":
        # Exponential frequency change
        k = (end_freq / start_freq) ** (1.0 / duration)
        phase = 2 * np.pi * (start_freq * (k**t - 1) / np.log(k))

    else:
        raise SignalError(f"Unknown chirp type: {chirp_type}")

    samples = amplitude * np.sin(phase)

    return Signal(samples, sample_rate)


def am_modulation(
    carrier_freq: float,
    modulator_freq: float,
    sample_rate: float,
    duration: float,
    modulation_depth: float = 0.5,
) -> Signal:
    """
    Generate amplitude-modulated (AM) signal.

    Args:
        carrier_freq: Carrier frequency in Hz.
        modulator_freq: Modulating signal frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        modulation_depth: Modulation index (0 to 1).

    Returns:
        Signal object.
    """
    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    # Modulating signal
    modulator = 1 + modulation_depth * np.sin(2 * np.pi * modulator_freq * t)

    # Carrier
    carrier = np.sin(2 * np.pi * carrier_freq * t)

    # AM signal
    samples = modulator * carrier

    return Signal(samples, sample_rate)


def fm_modulation(
    carrier_freq: float,
    modulator_freq: float,
    sample_rate: float,
    duration: float,
    frequency_deviation: float = 100.0,
) -> Signal:
    """
    Generate frequency-modulated (FM) signal.

    Args:
        carrier_freq: Carrier frequency in Hz.
        modulator_freq: Modulating signal frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        frequency_deviation: Frequency deviation in Hz.

    Returns:
        Signal object.
    """
    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    # Modulating signal
    np.sin(2 * np.pi * modulator_freq * t)

    # FM phase
    phase = 2 * np.pi * carrier_freq * t + 2 * np.pi * (frequency_deviation / modulator_freq) * (
        -np.cos(2 * np.pi * modulator_freq * t)
    )

    samples = np.sin(phase)

    return Signal(samples, sample_rate)


def adsr_envelope(
    attack_time: float,
    decay_time: float,
    sustain_level: float,
    release_time: float,
    sample_rate: float,
    total_time: float | None = None,
) -> np.ndarray:
    """
    Generate ADSR (Attack, Decay, Sustain, Release) envelope.

    Args:
        attack_time: Attack time in seconds.
        decay_time: Decay time in seconds.
        sustain_level: Sustain level (0 to 1).
        release_time: Release time in seconds.
        sample_rate: Sample rate in Hz.
        total_time: Total envelope duration. If None, uses attack + decay + release.

    Returns:
        Envelope samples.
    """
    if total_time is None:
        total_time = attack_time + decay_time + release_time

    n_samples = int(np.ceil(total_time * sample_rate))

    envelope = np.ones(n_samples, dtype=np.float64)

    attack_samples = int(np.ceil(attack_time * sample_rate))
    decay_samples = int(np.ceil(decay_time * sample_rate))
    release_samples = int(np.ceil(release_time * sample_rate))
    sustain_start = attack_samples + decay_samples

    # Attack
    if attack_samples > 0:
        envelope[:attack_samples] = np.linspace(0, 1, attack_samples)

    # Decay
    if decay_samples > 0:
        decay_range = np.linspace(0, 1, decay_samples)
        decay_vals = 1 - decay_range * (1 - sustain_level)
        envelope[attack_samples : attack_samples + decay_samples] = decay_vals

    # Sustain
    sustain_end = sustain_start + (n_samples - sustain_start - release_samples)
    if sustain_end > sustain_start:
        envelope[sustain_start:sustain_end] = sustain_level

    # Release
    if release_samples > 0:
        release_range = np.linspace(0, 1, release_samples)
        release_vals = sustain_level * (1 - release_range)
        envelope[sustain_end : sustain_end + release_samples] = release_vals

    return envelope


def wavetable_synthesis(
    wavetable: np.ndarray,
    frequency: float,
    sample_rate: float,
    duration: float,
    amplitude: float = 1.0,
) -> Signal:
    """
    Synthesize signal from wavetable lookup.

    Args:
        wavetable: Wavetable samples (one period).
        frequency: Frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Amplitude (default: 1.0).

    Returns:
        Signal object.
    """
    wavetable = np.asarray(wavetable, dtype=np.float64)

    if len(wavetable) < 2:
        raise SignalError("Wavetable must have at least 2 samples")

    n_samples = int(np.ceil(duration * sample_rate))
    t = np.arange(n_samples) / sample_rate

    # Phase (0 to 1 range)
    phase = (frequency * t) % 1.0

    # Index into wavetable (with linear interpolation)
    phase_idx = phase * (len(wavetable) - 1)
    idx_low = np.floor(phase_idx).astype(int)
    idx_high = np.ceil(phase_idx).astype(int)
    frac = phase_idx - idx_low

    # Interpolate
    samples = (1 - frac) * wavetable[idx_low] + frac * wavetable[idx_high % len(wavetable)]
    samples = amplitude * samples

    return Signal(samples, sample_rate)
