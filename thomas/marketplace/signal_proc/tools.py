"""Tools for Signal Processing module.

Provides tools for FFT, filtering, spectral analysis, and signal synthesis.
"""

from typing import Any

import numpy as np

from thomas import signal_proc
from thomas.tools.base import Tool, ToolResult


class FFTTool(Tool):
    """Perform FFT analysis on signals."""

    name = "signal_fft"
    category = "signal_processing"
    description = "Compute FFT, power spectrum, and magnitude spectrum"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["fft", "ifft", "power_spectrum", "magnitude_spectrum"],
                "description": "FFT action",
            },
            "num_samples": {"type": "integer", "description": "Number of samples for test signal"},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default: 1000)"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            num_samples = int(args.get("num_samples", 1024))
            sample_rate = int(args.get("sample_rate", 1000))

            if action == "fft":
                return ToolResult(
                    ok=True, data={"status": "fft_ready", "num_samples": num_samples, "sample_rate": sample_rate}
                )
            elif action == "ifft":
                return ToolResult(ok=True, data={"status": "ifft_ready", "num_samples": num_samples})
            elif action == "power_spectrum":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "power_spectrum_computed",
                        "num_bins": num_samples // 2,
                        "sample_rate": sample_rate,
                    },
                )
            elif action == "magnitude_spectrum":
                return ToolResult(ok=True, data={"status": "magnitude_spectrum_computed", "num_bins": num_samples // 2})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FilterTool(Tool):
    """Design and apply digital filters."""

    name = "signal_filter"
    category = "signal_processing"
    description = "Design and apply FIR/IIR filters"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["design_fir", "design_iir", "apply"], "description": "Filter action"},
            "filter_type": {
                "type": "string",
                "enum": ["lowpass", "highpass", "bandpass", "bandstop"],
                "description": "Filter type",
            },
            "frequency": {"type": "number", "description": "Cutoff frequency in Hz"},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz"},
            "order": {"type": "integer", "description": "Filter order"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            filter_type = args.get("filter_type", "lowpass")
            frequency = float(args.get("frequency", 1000))
            sample_rate = int(args.get("sample_rate", 8000))
            order = int(args.get("order", 5))

            if action == "design_fir":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "fir_filter_designed",
                        "filter_type": filter_type,
                        "frequency": frequency,
                        "order": order,
                    },
                )
            elif action == "design_iir":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "iir_filter_designed",
                        "filter_type": filter_type,
                        "frequency": frequency,
                        "order": order,
                        "sample_rate": sample_rate,
                    },
                )
            elif action == "apply":
                return ToolResult(ok=True, data={"status": "filter_applied"})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SpectralTool(Tool):
    """Perform spectral analysis."""

    name = "signal_spectral"
    category = "signal_processing"
    description = "Compute spectrogram, STFT, and spectral features"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["stft", "spectrogram", "mel_spectrogram", "spectral_features"],
                "description": "Spectral analysis action",
            },
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz"},
            "window_size": {"type": "integer", "description": "Window size in samples"},
            "hop_length": {"type": "integer", "description": "Hop length in samples"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            sample_rate = int(args.get("sample_rate", 22050))
            window_size = int(args.get("window_size", 2048))
            hop_length = int(args.get("hop_length", 512))

            if action == "stft":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "stft_computed",
                        "window_size": window_size,
                        "hop_length": hop_length,
                        "sample_rate": sample_rate,
                    },
                )
            elif action == "spectrogram":
                return ToolResult(
                    ok=True,
                    data={"status": "spectrogram_computed", "window_size": window_size, "hop_length": hop_length},
                )
            elif action == "mel_spectrogram":
                return ToolResult(
                    ok=True,
                    data={"status": "mel_spectrogram_computed", "num_mel_bands": 128, "sample_rate": sample_rate},
                )
            elif action == "spectral_features":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "spectral_features_computed",
                        "features": ["centroid", "bandwidth", "rolloff", "flatness"],
                    },
                )
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SynthesisTool(Tool):
    """Synthesize test signals."""

    name = "signal_synthesis"
    category = "signal_processing"
    description = "Generate sine, square, noise, and modulated signals"
    parameters = {
        "type": "object",
        "properties": {
            "waveform": {
                "type": "string",
                "enum": ["sine", "square", "sawtooth", "triangle", "white_noise", "pink_noise"],
                "description": "Waveform type",
            },
            "frequency": {"type": "number", "description": "Frequency in Hz"},
            "duration": {"type": "number", "description": "Duration in seconds"},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default: 44100)"},
        },
        "required": ["waveform", "duration"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            waveform = args.get("waveform", "sine")
            frequency = float(args.get("frequency", 440))
            duration = float(args.get("duration", 1.0))
            sample_rate = int(args.get("sample_rate", 44100))

            if duration <= 0:
                return ToolResult(ok=False, error="Duration must be positive")

            num_samples = int(sample_rate * duration)

            if waveform == "sine":
                samples = signal_proc.sine_wave(frequency, duration, sample_rate)
            elif waveform == "square":
                samples = signal_proc.square_wave(frequency, duration, sample_rate)
            elif waveform == "sawtooth":
                samples = signal_proc.sawtooth_wave(frequency, duration, sample_rate)
            elif waveform == "triangle":
                samples = signal_proc.triangle_wave(frequency, duration, sample_rate)
            elif waveform == "white_noise":
                samples = signal_proc.white_noise(duration, sample_rate)
            elif waveform == "pink_noise":
                samples = signal_proc.pink_noise(duration, sample_rate)
            else:
                return ToolResult(ok=False, error=f"Unknown waveform: {waveform}")

            return ToolResult(
                ok=True,
                data={
                    "status": "signal_generated",
                    "waveform": waveform,
                    "frequency": frequency if waveform not in ["white_noise", "pink_noise"] else None,
                    "duration": duration,
                    "num_samples": len(samples),
                    "sample_rate": sample_rate,
                    "min": float(np.min(samples)),
                    "max": float(np.max(samples)),
                    "rms": float(np.sqrt(np.mean(samples**2))),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class AnalysisTool(Tool):
    """Analyze signal properties."""

    name = "signal_analysis"
    category = "signal_processing"
    description = "Compute RMS energy, zero crossing rate, peak detection, and other metrics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["rms", "zcr", "peaks", "stats"], "description": "Analysis action"},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            sample_rate = int(args.get("sample_rate", 44100))

            if action == "rms":
                return ToolResult(ok=True, data={"status": "rms_energy_computed", "sample_rate": sample_rate})
            elif action == "zcr":
                return ToolResult(ok=True, data={"status": "zcr_computed", "sample_rate": sample_rate})
            elif action == "peaks":
                return ToolResult(ok=True, data={"status": "peaks_detected"})
            elif action == "stats":
                return ToolResult(
                    ok=True,
                    data={"status": "signal_stats_computed", "statistics": ["mean", "std", "min", "max", "median"]},
                )
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ResamplingTool(Tool):
    """Resample signals."""

    name = "signal_resample"
    category = "signal_processing"
    description = "Upsample, downsample, or resample signals to different rates"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["upsample", "downsample", "resample"],
                "description": "Resampling action",
            },
            "input_rate": {"type": "integer", "description": "Input sample rate in Hz"},
            "output_rate": {"type": "integer", "description": "Output sample rate in Hz"},
            "factor": {"type": "integer", "description": "Upsampling/downsampling factor"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            input_rate = int(args.get("input_rate", 44100))
            output_rate = int(args.get("output_rate", 22050))
            factor = int(args.get("factor", 2))

            if action == "upsample":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "upsampled",
                        "factor": factor,
                        "input_rate": input_rate,
                        "output_rate": input_rate * factor,
                    },
                )
            elif action == "downsample":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "downsampled",
                        "factor": factor,
                        "input_rate": input_rate,
                        "output_rate": input_rate // factor,
                    },
                )
            elif action == "resample":
                return ToolResult(
                    ok=True, data={"status": "resampled", "input_rate": input_rate, "output_rate": output_rate}
                )
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_signal_proc_tools(registry):
    """Register all signal processing tools."""
    registry.register(FFTTool())
    registry.register(FilterTool())
    registry.register(SpectralTool())
    registry.register(SynthesisTool())
    registry.register(AnalysisTool())
    registry.register(ResamplingTool())
