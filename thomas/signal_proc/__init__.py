"""
Signal Processing Module - Public API

A comprehensive signal processing library with FFT, filtering, spectral analysis,
and synthesis capabilities.
"""

from thomas.signal_proc._exceptions import (
    FFTError,
    FilterError,
    SignalError,
)
from thomas.signal_proc._types import (
    FilterConfig,
    FilterType,
    FrequencySpectrum,
    Signal,
    Spectrogram,
    WindowType,
)
from thomas.signal_proc.analysis import (
    envelope_detect,
    fundamental_frequency,
    peak_detect,
    rms_energy,
    signal_stats,
    snr,
    unwrap_phase,
    zero_crossing_rate,
)
from thomas.signal_proc.convolution import (
    autocorr,
    convolve,
    correlate,
    deconvolve,
    matched_filter,
    xcorr,
)
from thomas.signal_proc.fft import (
    dft,
    fft,
    fft_shift,
    frequency_bins,
    idft,
    ifft,
    magnitude_spectrum,
    phase_spectrum,
    power_spectrum,
    real_fft,
    zero_pad_to_power2,
)
from thomas.signal_proc.filters import (
    FIRFilter,
    IIRFilter,
    MedianFilter,
    MovingAverageFilter,
    design_bandpass_fir,
    design_bandstop_fir,
    design_butterworth_highpass,
    design_butterworth_lowpass,
    design_highpass_fir,
    design_lowpass_fir,
)
from thomas.signal_proc.resampling import (
    downsample,
    resample_linear,
    resample_rational,
    resample_sinc,
    upsample,
)
from thomas.signal_proc.spectral import (
    cepstrum,
    hz_to_mel,
    mel_spectrogram,
    mel_to_hz,
    spectral_bandwidth,
    spectral_centroid,
    spectral_flatness,
    spectral_rolloff,
    spectrogram,
    stft,
    welch_psd,
)
from thomas.signal_proc.synthesis import (
    adsr_envelope,
    am_modulation,
    chirp,
    fm_modulation,
    pink_noise,
    sawtooth_wave,
    sine_wave,
    square_wave,
    triangle_wave,
    wavetable_synthesis,
    white_noise,
)
from thomas.signal_proc.transforms import (
    dct,
    hilbert_transform,
    idct,
    inverse_wavelet_transform,
    wavelet_transform,
    z_transform,
)
from thomas.signal_proc.windows import (
    apply_window,
    bartlett,
    blackman,
    flattop,
    hamming,
    hanning,
    kaiser,
    rectangular,
)

__all__ = [
    # Types
    "Signal",
    "FrequencySpectrum",
    "FilterConfig",
    "WindowType",
    "FilterType",
    "Spectrogram",
    # Exceptions
    "SignalError",
    "FilterError",
    "FFTError",
    # FFT
    "fft",
    "ifft",
    "dft",
    "idft",
    "real_fft",
    "power_spectrum",
    "magnitude_spectrum",
    "phase_spectrum",
    "frequency_bins",
    "zero_pad_to_power2",
    "fft_shift",
    # Filters
    "FIRFilter",
    "IIRFilter",
    "MovingAverageFilter",
    "MedianFilter",
    "design_lowpass_fir",
    "design_highpass_fir",
    "design_bandpass_fir",
    "design_bandstop_fir",
    "design_butterworth_lowpass",
    "design_butterworth_highpass",
    # Windows
    "rectangular",
    "hanning",
    "hamming",
    "blackman",
    "kaiser",
    "bartlett",
    "flattop",
    "apply_window",
    # Convolution
    "convolve",
    "correlate",
    "xcorr",
    "autocorr",
    "deconvolve",
    "matched_filter",
    # Spectral
    "stft",
    "spectrogram",
    "welch_psd",
    "cepstrum",
    "spectral_centroid",
    "spectral_bandwidth",
    "spectral_rolloff",
    "spectral_flatness",
    "hz_to_mel",
    "mel_to_hz",
    "mel_spectrogram",
    # Synthesis
    "sine_wave",
    "square_wave",
    "sawtooth_wave",
    "triangle_wave",
    "white_noise",
    "pink_noise",
    "chirp",
    "am_modulation",
    "fm_modulation",
    "adsr_envelope",
    "wavetable_synthesis",
    # Transforms
    "hilbert_transform",
    "dct",
    "idct",
    "wavelet_transform",
    "inverse_wavelet_transform",
    "z_transform",
    # Analysis
    "zero_crossing_rate",
    "rms_energy",
    "peak_detect",
    "fundamental_frequency",
    "snr",
    "signal_stats",
    "envelope_detect",
    "unwrap_phase",
    # Resampling
    "upsample",
    "downsample",
    "resample_rational",
    "resample_linear",
    "resample_sinc",
]

__version__ = "1.0.0"
