"""
Audio mixer with multi-channel support, pan, effects, and automation.

Implements professional audio mixing capabilities with metering.
"""

import math
from typing import Optional

import numpy as np
from numpy.typing import NDArray

from thomas.marketplace.audio_engine._types import AudioBus, Effect, MixerChannel, PanLaw


class Mixer:
    """Multi-channel audio mixer with effects, automation, and metering.

    Attributes:
        num_channels: Number of input channels
        sample_rate: Sample rate in Hz
        channels: List of mixer channels
        master_bus: Master output bus
    """

    def __init__(self, num_channels: int = 8, sample_rate: int = 44100, pan_law: PanLaw = PanLaw.EQUAL_POWER) -> None:
        """Initialize mixer.

        Args:
            num_channels: Number of input channels
            sample_rate: Sample rate in Hz
            pan_law: Stereo pan law
        """
        self.num_channels = num_channels
        self.sample_rate = sample_rate
        self.pan_law = pan_law
        self.channels: list[MixerChannel] = [MixerChannel(f"Channel {i+1}") for i in range(num_channels)]
        self.master_bus = AudioBus("Master", 2)
        self.input_buffer: dict[int, list[NDArray[np.float32]]] = {i: [] for i in range(num_channels)}
        self.automation_enabled = False

    def set_channel_volume(self, channel: int, volume: float) -> None:
        """Set channel volume.

        Args:
            channel: Channel index
            volume: Volume (0.0-2.0)
        """
        if 0 <= channel < len(self.channels):
            self.channels[channel].volume = volume

    def set_channel_pan(self, channel: int, pan: float) -> None:
        """Set channel pan.

        Args:
            channel: Channel index
            pan: Pan (-1.0 left to 1.0 right)
        """
        if 0 <= channel < len(self.channels):
            self.channels[channel].pan = np.clip(pan, -1.0, 1.0)

    def set_channel_mute(self, channel: int, mute: bool) -> None:
        """Set channel mute state.

        Args:
            channel: Channel index
            mute: Mute state
        """
        if 0 <= channel < len(self.channels):
            self.channels[channel].mute = mute

    def set_channel_solo(self, channel: int, solo: bool) -> None:
        """Set channel solo state.

        Args:
            channel: Channel index
            solo: Solo state
        """
        if 0 <= channel < len(self.channels):
            self.channels[channel].solo = solo

    def get_solo_channels(self) -> list[int]:
        """Get list of solo channel indices.

        Returns:
            List of solo channel indices
        """
        return [i for i, ch in enumerate(self.channels) if ch.solo]

    def add_channel_effect(self, channel: int, effect: "Effect") -> None:
        """Add effect to channel.

        Args:
            channel: Channel index
            effect: Effect to add
        """
        if 0 <= channel < len(self.channels):
            self.channels[channel].effects.append(effect)

    def input_samples(self, channel: int, samples: NDArray[np.float32]) -> None:
        """Input samples to channel.

        Args:
            channel: Channel index
            samples: Audio samples (num_samples,) or (num_samples, num_channels)
        """
        if 0 <= channel < len(self.channels):
            # Ensure stereo
            if samples.ndim == 1:
                samples = np.column_stack([samples, samples])
            self.input_buffer[channel].append(samples)

    def mix(self, num_samples: int) -> NDArray[np.float32]:
        """Mix all channels to stereo output.

        Args:
            num_samples: Number of samples to process

        Returns:
            Stereo output (num_samples, 2)
        """
        output = np.zeros((num_samples, 2), dtype=np.float32)
        solo_channels = self.get_solo_channels()

        for ch_idx, channel in enumerate(self.channels):
            if ch_idx not in self.input_buffer or not self.input_buffer[ch_idx]:
                continue

            # Get input samples
            ch_samples = self.input_buffer[ch_idx].pop(0)[:num_samples]

            # Ensure correct length
            if len(ch_samples) < num_samples:
                pad = np.zeros((num_samples - len(ch_samples), 2), dtype=np.float32)
                ch_samples = np.vstack([ch_samples, pad])

            # Process through channel effects
            for effect in channel.effects:
                if effect.enabled:
                    ch_samples = effect.process(ch_samples)

            # Apply mute/solo
            if channel.mute or solo_channels and ch_idx not in solo_channels:
                ch_samples = np.zeros_like(ch_samples)

            # Apply volume
            ch_samples = ch_samples * channel.volume

            # Apply pan
            ch_samples = self._apply_pan(ch_samples, channel.pan)

            # Mix to output
            output += ch_samples

        # Apply master bus effects
        for effect in self.master_bus.effects:
            if effect.enabled:
                output = effect.process(output)

        # Apply master volume
        output = output * self.master_bus.volume

        # Soft clipping to prevent distortion
        output = np.tanh(output)

        return output

    def _apply_pan(self, samples: NDArray[np.float32], pan: float) -> NDArray[np.float32]:
        """Apply stereo pan to samples.

        Args:
            samples: Stereo samples (num_samples, 2)
            pan: Pan value (-1.0 left to 1.0 right)

        Returns:
            Panned samples
        """
        if self.pan_law == PanLaw.LINEAR:
            left_gain = 1.0 - (pan + 1.0) / 2.0
            right_gain = (pan + 1.0) / 2.0
        elif self.pan_law == PanLaw.EQUAL_POWER:
            # Equal power panning
            angle = (pan + 1.0) / 2.0 * np.pi / 2.0
            left_gain = np.cos(angle)
            right_gain = np.sin(angle)
        else:  # MINUS_4_5DB
            # -4.5dB law
            left_gain = np.sqrt(1.0 - (pan + 1.0) / 2.0)
            right_gain = np.sqrt((pan + 1.0) / 2.0)

        panned = samples.copy()
        panned[:, 0] *= left_gain
        panned[:, 1] *= right_gain
        return panned

    def reset(self) -> None:
        """Reset mixer state."""
        for ch_buffer in self.input_buffer.values():
            ch_buffer.clear()


class VUMeter:
    """VU meter with peak and RMS metering with ballistics.

    Attributes:
        sample_rate: Sample rate in Hz
        rms_window: RMS calculation window size
        attack_time: Attack time in seconds
        release_time: Release time in seconds
    """

    def __init__(self, sample_rate: int = 44100, attack_time: float = 0.01, release_time: float = 0.5) -> None:
        """Initialize VU meter.

        Args:
            sample_rate: Sample rate in Hz
            attack_time: Attack time in seconds
            release_time: Release time in seconds
        """
        self.sample_rate = sample_rate
        self.attack_time = attack_time
        self.release_time = release_time
        self.rms_window = sample_rate // 10  # 100ms window
        self.peak_level = 0.0
        self.rms_level = 0.0
        self.peak_hold_time = 0.0
        self.peak_hold_duration = 2.0  # Hold peak for 2 seconds

    def process(self, samples: NDArray[np.float32]) -> tuple[float, float]:
        """Process samples and return metering data.

        Args:
            samples: Audio samples (num_samples,) or (num_samples, num_channels)

        Returns:
            Tuple of (peak_level_db, rms_level_db)
        """
        # Flatten to mono if multichannel
        if samples.ndim > 1:
            samples = np.mean(samples, axis=1)

        # Peak detection
        peak = np.max(np.abs(samples))
        if peak > self.peak_level:
            self.peak_level = peak
            self.peak_hold_time = self.peak_hold_duration
        else:
            self.peak_hold_time -= len(samples) / self.sample_rate
            if self.peak_hold_time <= 0:
                self.peak_level = peak

        # RMS calculation with ballistics
        rms = np.sqrt(np.mean(samples**2))
        attack_coeff = math.exp(-1.0 / (self.attack_time * self.sample_rate))
        release_coeff = math.exp(-1.0 / (self.release_time * self.sample_rate))

        if rms > self.rms_level:
            self.rms_level = attack_coeff * self.rms_level + (1.0 - attack_coeff) * rms
        else:
            self.rms_level = release_coeff * self.rms_level + (1.0 - release_coeff) * rms

        # Convert to dB
        peak_db = 20.0 * np.log10(max(self.peak_level, 1e-6))
        rms_db = 20.0 * np.log10(max(self.rms_level, 1e-6))

        return float(peak_db), float(rms_db)

    def reset(self) -> None:
        """Reset meter state."""
        self.peak_level = 0.0
        self.rms_level = 0.0
        self.peak_hold_time = 0.0


class SendReturn:
    """Send/return bus for aux sends and processing.

    Attributes:
        name: Bus name
        send_level: Send level (0.0-1.0)
        return_level: Return level (0.0-2.0)
        effect: Effect applied to bus
    """

    def __init__(self, name: str, effect: Optional["Effect"] = None) -> None:
        """Initialize send/return bus.

        Args:
            name: Bus name
            effect: Effect to apply
        """
        self.name = name
        self.send_level = 0.0
        self.return_level = 1.0
        self.effect = effect
        self.buffer = np.array([], dtype=np.float32)

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Process send/return chain.

        Args:
            samples: Input samples

        Returns:
            Return signal
        """
        if self.effect is None:
            return samples * self.send_level * self.return_level

        processed = self.effect.process(samples)
        return processed * self.return_level


class MixerAutomation:
    """Automation for mixer parameters with interpolation.

    Attributes:
        target_value: Target value for automation
        current_value: Current automation value
        duration: Automation duration in samples
    """

    def __init__(
        self,
        target_value: float,
        duration: int,
        curve: str = "linear",
        start_value: float = 0.0,
    ) -> None:
        """Initialize automation.

        Args:
            target_value: Target value
            duration: Duration in samples
            curve: Interpolation curve ("linear" or "exponential")
            start_value: Initial value at sample 0
        """
        self.target_value = target_value
        self.start_value = start_value
        self.current_value = start_value
        self.duration = duration
        self.curve = curve
        self.samples_elapsed = 0

    def process(self, num_samples: int) -> NDArray[np.float32]:
        """Generate automation curve.

        Args:
            num_samples: Number of samples

        Returns:
            Automation values
        """
        output = np.zeros(num_samples, dtype=np.float32)

        for i in range(num_samples):
            progress = min(1.0, self.samples_elapsed / max(self.duration, 1))

            if self.curve == "exponential":
                # Exponential curve
                factor = math.exp(progress * 5.0 - 5.0)
            else:
                # Linear
                factor = progress

            output[i] = self.start_value + (self.target_value - self.start_value) * factor
            self.samples_elapsed += 1

        if num_samples > 0:
            self.current_value = float(output[-1])

        return output
