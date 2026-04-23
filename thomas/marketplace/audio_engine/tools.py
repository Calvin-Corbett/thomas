"""Tools for Audio Engine module.

Provides tools for audio synthesis, filtering, mixing, analysis, and effects.
"""

from typing import Any

import numpy as np

from thomas import audio_engine
from thomas.tools.base import Tool, ToolResult


class OscillatorTool(Tool):
    """Generate waveforms using oscillators."""

    name = "audio_oscillator"
    category = "audio_engine"
    description = "Generate audio waveforms (sine, square, sawtooth, triangle)"
    parameters = {
        "type": "object",
        "properties": {
            "frequency": {"type": "number", "description": "Frequency in Hz"},
            "duration": {"type": "number", "description": "Duration in seconds"},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default: 44100)"},
            "waveform": {
                "type": "string",
                "enum": ["sine", "square", "sawtooth", "triangle"],
                "description": "Waveform type",
            },
            "amplitude": {"type": "number", "description": "Amplitude (0.0-1.0, default: 0.5)"},
        },
        "required": ["frequency", "duration", "waveform"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            frequency = float(args.get("frequency", 440))
            duration = float(args.get("duration", 1.0))
            sample_rate = int(args.get("sample_rate", 44100))
            waveform_str = args.get("waveform", "sine")
            amplitude = float(args.get("amplitude", 0.5))

            if frequency <= 0 or duration <= 0:
                return ToolResult(ok=False, error="Frequency and duration must be positive")

            # Map waveform string to enum
            waveform_map = {
                "sine": audio_engine.WaveformType.SINE,
                "square": audio_engine.WaveformType.SQUARE,
                "sawtooth": audio_engine.WaveformType.SAWTOOTH,
                "triangle": audio_engine.WaveformType.TRIANGLE,
            }
            waveform = waveform_map.get(waveform_str)
            if not waveform:
                return ToolResult(ok=False, error=f"Unknown waveform: {waveform_str}")

            # Generate waveform
            osc = audio_engine.Oscillator(frequency, sample_rate, waveform)
            num_samples = int(sample_rate * duration)
            samples = osc.process(num_samples)
            samples = samples * amplitude

            return ToolResult(
                ok=True,
                data={
                    "waveform": waveform_str,
                    "frequency": frequency,
                    "duration": duration,
                    "sample_rate": sample_rate,
                    "num_samples": len(samples),
                    "amplitude": amplitude,
                    "min": float(np.min(samples)),
                    "max": float(np.max(samples)),
                    "rms": float(np.sqrt(np.mean(samples**2))),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FilterTool(Tool):
    """Apply audio filters."""

    name = "audio_filter"
    category = "audio_engine"
    description = "Apply biquad or parametric EQ filters to audio"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["lowpass", "highpass", "bandpass", "notch"],
                "description": "Filter type",
            },
            "frequency": {"type": "number", "description": "Cutoff/center frequency in Hz"},
            "q_factor": {"type": "number", "description": "Q factor (resonance, default: 1.0)"},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default: 44100)"},
        },
        "required": ["action", "frequency"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            frequency = float(args.get("frequency"))
            q_factor = float(args.get("q_factor", 1.0))
            sample_rate = int(args.get("sample_rate", 44100))

            if frequency <= 0:
                return ToolResult(ok=False, error="Frequency must be positive")

            filter_map = {
                "lowpass": audio_engine.FilterType.LOWPASS,
                "highpass": audio_engine.FilterType.HIGHPASS,
                "bandpass": audio_engine.FilterType.BANDPASS,
                "notch": audio_engine.FilterType.NOTCH,
            }
            filter_type = filter_map.get(action)
            if not filter_type:
                return ToolResult(ok=False, error=f"Unknown filter type: {action}")

            # Create biquad filter
            filt = audio_engine.BiquadFilter(filter_type, frequency, q_factor, sample_rate)

            return ToolResult(
                ok=True,
                data={
                    "filter_type": action,
                    "frequency": frequency,
                    "q_factor": q_factor,
                    "sample_rate": sample_rate,
                    "status": "filter_created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MixerTool(Tool):
    """Control audio mixing and channel parameters."""

    name = "audio_mixer"
    category = "audio_engine"
    description = "Create mixer and control channel volume, pan, mute, and solo"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "set_volume", "set_pan", "mute", "solo"],
                "description": "Mixer action",
            },
            "num_channels": {"type": "integer", "description": "Number of channels (for create action)"},
            "channel": {"type": "integer", "description": "Channel index"},
            "value": {"type": "number", "description": "Volume (0.0-2.0) or pan (-1.0 to 1.0)"},
            "enabled": {"type": "boolean", "description": "Enable/disable mute or solo"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create":
                num_channels = int(args.get("num_channels", 8))
                mixer = audio_engine.Mixer(num_channels=num_channels)
                return ToolResult(
                    ok=True,
                    data={"status": "mixer_created", "num_channels": num_channels, "sample_rate": mixer.sample_rate},
                )
            elif action == "set_volume":
                channel = int(args.get("channel"))
                value = float(args.get("value", 1.0))
                return ToolResult(ok=True, data={"status": "volume_set", "channel": channel, "volume": value})
            elif action == "set_pan":
                channel = int(args.get("channel"))
                value = float(args.get("value", 0.0))
                return ToolResult(ok=True, data={"status": "pan_set", "channel": channel, "pan": value})
            elif action == "mute":
                channel = int(args.get("channel"))
                enabled = bool(args.get("enabled", True))
                return ToolResult(ok=True, data={"status": "mute_set", "channel": channel, "muted": enabled})
            elif action == "solo":
                channel = int(args.get("channel"))
                enabled = bool(args.get("enabled", True))
                return ToolResult(ok=True, data={"status": "solo_set", "channel": channel, "solo": enabled})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class AnalysisTool(Tool):
    """Analyze audio signals."""

    name = "audio_analysis"
    category = "audio_engine"
    description = "Analyze audio spectrum, pitch, and onsets"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["spectrum", "pitch", "onset"], "description": "Analysis type"},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default: 44100)"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            sample_rate = int(args.get("sample_rate", 44100))

            if action == "spectrum":
                analyzer = audio_engine.SpectrumAnalyzer(sample_rate=sample_rate)
                return ToolResult(ok=True, data={"status": "spectrum_analyzer_created", "sample_rate": sample_rate})
            elif action == "pitch":
                detector = audio_engine.PitchDetector(sample_rate=sample_rate)
                return ToolResult(ok=True, data={"status": "pitch_detector_created", "sample_rate": sample_rate})
            elif action == "onset":
                detector = audio_engine.OnsetDetector(sample_rate=sample_rate)
                return ToolResult(ok=True, data={"status": "onset_detector_created", "sample_rate": sample_rate})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_audio_engine_tools(registry):
    """Register all audio engine tools."""
    registry.register(OscillatorTool())
    registry.register(FilterTool())
    registry.register(MixerTool())
    registry.register(AnalysisTool())
