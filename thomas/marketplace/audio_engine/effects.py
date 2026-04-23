"""
Audio effects: delay, reverb, chorus, flanger, distortion, compression, tremolo.

Implements high-quality audio effects with real-time processing capability.
"""

import math

import numpy as np
from numpy.typing import NDArray

from thomas.marketplace.audio_engine._types import Effect
from thomas.marketplace.audio_engine.buffer import RingBuffer


class Delay(Effect):
    """Delay effect with feedback and wet/dry mix.

    Attributes:
        delay_time: Delay time in seconds
        feedback: Feedback amount (0.0-1.0)
        dry: Dry signal level
        wet: Wet signal level
    """

    def __init__(self, delay_time: float = 0.5, feedback: float = 0.3, sample_rate: int = 44100) -> None:
        """Initialize delay effect.

        Args:
            delay_time: Delay time in seconds
            feedback: Feedback amount (0.0-1.0)
            sample_rate: Sample rate in Hz
        """
        super().__init__("Delay", dry=0.5, wet=0.5)
        self.delay_time = delay_time
        self.feedback = feedback
        self.sample_rate = sample_rate
        delay_samples = int(delay_time * sample_rate)
        self.buffer = RingBuffer(delay_samples * 2, 2)

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply delay effect.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Processed samples
        """
        if not self.enabled:
            return samples

        output = np.zeros_like(samples)
        num_samples = len(samples)
        delay_samples = int(self.delay_time * self.sample_rate)

        for i in range(num_samples):
            # Read delayed sample
            if self.buffer.available_read >= 1:
                delayed = self.buffer.peek(1)[0]
            else:
                delayed = np.zeros(samples.shape[1])

            # Mix dry and wet
            output[i] = self.dry * samples[i] + self.wet * delayed

            # Write to buffer with feedback
            input_with_feedback = samples[i] + self.feedback * delayed
            self.buffer.write(input_with_feedback.reshape(1, -1))

        return output


class Reverb(Effect):
    """Schroeder reverb: 4 comb filters + 2 allpass filters.

    Attributes:
        room_size: Room size parameter (0.0-1.0)
        damping: Damping parameter (0.0-1.0)
        width: Stereo width (0.0-1.0)
        dry: Dry signal level
        wet: Wet signal level
    """

    def __init__(
        self, room_size: float = 0.5, damping: float = 0.5, width: float = 1.0, sample_rate: int = 44100
    ) -> None:
        """Initialize reverb effect.

        Args:
            room_size: Room size (0.0-1.0)
            damping: Damping (0.0-1.0)
            width: Stereo width (0.0-1.0)
            sample_rate: Sample rate in Hz
        """
        super().__init__("Reverb", dry=0.3, wet=0.7)
        self.room_size = float(np.clip(room_size, 0.0, 1.0))
        self.damping = float(np.clip(damping, 0.0, 1.0))
        self.width = float(np.clip(width, 0.0, 1.0))
        self.sample_rate = sample_rate

        # Delay scale ties room size to reverb time/character.
        delay_scale = 0.6 + 0.8 * self.room_size

        # Comb filter delay lines and state (stereo).
        comb_tunings = [1116, 1188, 1277, 1356]
        self._comb_lines = [np.zeros((max(1, int(delay * delay_scale)), 2), dtype=np.float32) for delay in comb_tunings]
        self._comb_pos = [0 for _ in self._comb_lines]
        self.comb_state = np.zeros((len(self._comb_lines), 2), dtype=np.float32)

        # Allpass filter delay lines (stereo).
        allpass_tunings = [556, 441]
        self._allpass_lines = [
            np.zeros((max(1, int(delay * delay_scale)), 2), dtype=np.float32) for delay in allpass_tunings
        ]
        self._allpass_pos = [0 for _ in self._allpass_lines]

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply reverb effect.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Processed samples
        """
        if not self.enabled:
            return samples

        # Internal algorithm is stereo; mono inputs are duplicated and folded back.
        input_was_mono = samples.ndim == 1
        if input_was_mono:
            work = np.column_stack([samples, samples]).astype(np.float32, copy=False)
        else:
            work = samples.astype(np.float32, copy=False)

        output = np.zeros_like(work)
        comb_feedback = 0.7 + 0.25 * self.room_size
        allpass_feedback = 0.5

        for i in range(len(work)):
            x = work[i]

            # Parallel comb filters with simple damping in feedback path.
            comb_out = np.zeros(2, dtype=np.float32)
            for j, line in enumerate(self._comb_lines):
                pos = self._comb_pos[j]
                delayed = line[pos]
                filtered = delayed * (1.0 - self.damping) + self.comb_state[j] * self.damping
                self.comb_state[j] = filtered
                line[pos] = x + comb_feedback * filtered
                self._comb_pos[j] = (pos + 1) % line.shape[0]
                comb_out += filtered

            comb_out /= float(len(self._comb_lines))

            # Series allpass diffusion.
            allpass_out = comb_out
            for j, line in enumerate(self._allpass_lines):
                pos = self._allpass_pos[j]
                delayed = line[pos]
                y = -allpass_feedback * allpass_out + delayed
                line[pos] = allpass_out + allpass_feedback * y
                self._allpass_pos[j] = (pos + 1) % line.shape[0]
                allpass_out = y

            # Mid/side width control on wet signal.
            mid = 0.5 * (allpass_out[0] + allpass_out[1])
            side = 0.5 * (allpass_out[0] - allpass_out[1]) * self.width
            wet = np.array([mid + side, mid - side], dtype=np.float32)

            output[i] = self.dry * x + self.wet * wet

        if input_was_mono:
            return output[:, 0].astype(samples.dtype, copy=False)
        return output.astype(samples.dtype, copy=False)


class Chorus(Effect):
    """Chorus effect using modulated delay.

    Attributes:
        rate: LFO rate in Hz
        depth: Modulation depth in milliseconds
        dry: Dry signal level
        wet: Wet signal level
    """

    def __init__(self, rate: float = 1.5, depth: float = 3.0, sample_rate: int = 44100) -> None:
        """Initialize chorus effect.

        Args:
            rate: LFO rate in Hz
            depth: Modulation depth in milliseconds
            sample_rate: Sample rate in Hz
        """
        super().__init__("Chorus", dry=0.5, wet=0.5)
        self.rate = rate
        self.depth = depth
        self.sample_rate = sample_rate
        self.lfo_phase = 0.0

        # Delay buffer
        max_delay = int(0.05 * sample_rate)  # 50ms max
        self.buffer = RingBuffer(max_delay, 2)

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply chorus effect.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Processed samples
        """
        if not self.enabled:
            return samples

        output = np.zeros_like(samples)
        lfo_inc = self.rate / self.sample_rate
        base_delay = int(0.02 * self.sample_rate)  # 20ms base

        for i in range(len(samples)):
            # LFO modulation
            lfo = np.sin(2.0 * np.pi * self.lfo_phase)
            delay_mod = base_delay + lfo * self.depth * self.sample_rate / 1000.0

            # Delay line read with linear interpolation
            if self.buffer.available_read >= 1:
                delayed = self.buffer.read(1)[0]
            else:
                delayed = np.zeros(samples.shape[1])

            output[i] = self.dry * samples[i] + self.wet * delayed

            self.buffer.write(samples[i].reshape(1, -1))
            self.lfo_phase += lfo_inc
            if self.lfo_phase >= 1.0:
                self.lfo_phase -= 1.0

        return output


class Flanger(Effect):
    """Flanger effect: modulated delay with feedback.

    Attributes:
        rate: LFO rate in Hz
        depth: Modulation depth in samples
        feedback: Feedback amount
    """

    def __init__(self, rate: float = 0.5, depth: float = 5.0, feedback: float = 0.7, sample_rate: int = 44100) -> None:
        """Initialize flanger effect.

        Args:
            rate: LFO rate in Hz
            depth: Modulation depth in samples
            feedback: Feedback amount
            sample_rate: Sample rate in Hz
        """
        super().__init__("Flanger", dry=0.5, wet=0.5)
        self.rate = rate
        self.depth = depth
        self.feedback = feedback
        self.sample_rate = sample_rate
        self.lfo_phase = 0.0
        self.buffer = RingBuffer(int(0.02 * sample_rate), 2)

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply flanger effect.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Processed samples
        """
        if not self.enabled:
            return samples

        output = np.zeros_like(samples)
        lfo_inc = self.rate / self.sample_rate

        for i in range(len(samples)):
            lfo = np.sin(2.0 * np.pi * self.lfo_phase)
            delayed = np.zeros(samples.shape[1])

            if self.buffer.available_read >= 1:
                delayed = self.buffer.read(1)[0]

            output[i] = self.dry * samples[i] + self.wet * delayed
            input_with_feedback = samples[i] + self.feedback * delayed
            self.buffer.write(input_with_feedback.reshape(1, -1))

            self.lfo_phase += lfo_inc
            if self.lfo_phase >= 1.0:
                self.lfo_phase -= 1.0

        return output


class Distortion(Effect):
    """Distortion effect with soft/hard clipping and waveshaping.

    Attributes:
        drive: Drive amount (1.0-10.0)
        tone: Tone control (0.0-1.0)
        type: "soft", "hard", or "waveshaper"
    """

    def __init__(self, drive: float = 2.0, tone: float = 0.5, distortion_type: str = "soft") -> None:
        """Initialize distortion effect.

        Args:
            drive: Drive amount
            tone: Tone control
            distortion_type: Type of distortion
        """
        super().__init__("Distortion", dry=0.0, wet=1.0)
        self.drive = drive
        self.tone = tone
        self.type = distortion_type

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply distortion effect.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Processed samples
        """
        if not self.enabled:
            return samples

        driven = samples * self.drive

        if self.type == "soft":
            # Soft clipping using tanh
            output = np.tanh(driven)
        elif self.type == "hard":
            # Hard clipping
            output = np.clip(driven, -1.0, 1.0)
        else:
            # Waveshaper
            output = self._waveshaper(driven)

        return output

    @staticmethod
    def _waveshaper(x: NDArray[np.float32]) -> NDArray[np.float32]:
        """Waveshaper distortion.

        Args:
            x: Input samples

        Returns:
            Shaped samples
        """
        return (3.0 * x - x**3) / (1.0 + np.abs(x)) ** 2


class Compressor(Effect):
    """Dynamic range compressor with RMS detection.

    Attributes:
        threshold: Threshold in dB
        ratio: Compression ratio
        attack: Attack time in seconds
        release: Release time in seconds
        knee: Knee width in dB
    """

    def __init__(
        self,
        threshold: float = -20.0,
        ratio: float = 4.0,
        attack: float = 0.005,
        release: float = 0.1,
        knee: float = 2.0,
        sample_rate: int = 44100,
    ) -> None:
        """Initialize compressor.

        Args:
            threshold: Threshold in dB
            ratio: Compression ratio
            attack: Attack time in seconds
            release: Release time in seconds
            knee: Knee width in dB
            sample_rate: Sample rate in Hz
        """
        super().__init__("Compressor", dry=1.0, wet=1.0)
        self.threshold = threshold
        self.ratio = ratio
        self.attack = attack
        self.release = release
        self.knee = knee
        self.sample_rate = sample_rate
        self.envelope = 0.0

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply compression.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Compressed samples
        """
        if not self.enabled:
            return samples

        output = np.zeros_like(samples)
        rms_window = 1024

        for i in range(len(samples)):
            # Calculate RMS
            window_end = min(i + rms_window, len(samples))
            window_start = max(0, i - rms_window)
            rms = np.sqrt(np.mean(samples[window_start:window_end] ** 2))
            rms_db = 20.0 * np.log10(max(rms, 1e-6))

            # Calculate gain reduction
            if rms_db > self.threshold:
                gain_reduction_db = (rms_db - self.threshold) * (1.0 - 1.0 / self.ratio)
            else:
                gain_reduction_db = 0.0

            gain_reduction = 10.0 ** (-gain_reduction_db / 20.0)

            # Attack/release envelope
            attack_coeff = math.exp(-1.0 / (self.attack * self.sample_rate))
            release_coeff = math.exp(-1.0 / (self.release * self.sample_rate))

            if gain_reduction < self.envelope:
                self.envelope = attack_coeff * self.envelope + (1.0 - attack_coeff) * gain_reduction
            else:
                self.envelope = release_coeff * self.envelope + (1.0 - release_coeff) * gain_reduction

            output[i] = samples[i] * self.envelope

        return output


class Limiter(Effect):
    """Brick-wall limiter to prevent clipping.

    Attributes:
        threshold: Threshold in dB
        attack: Attack time in seconds
        release: Release time in seconds
    """

    def __init__(
        self, threshold: float = 0.0, attack: float = 0.001, release: float = 0.05, sample_rate: int = 44100
    ) -> None:
        """Initialize limiter.

        Args:
            threshold: Threshold in dB
            attack: Attack time in seconds
            release: Release time in seconds
            sample_rate: Sample rate in Hz
        """
        super().__init__("Limiter", dry=1.0, wet=1.0)
        self.threshold = threshold
        self.attack = attack
        self.release = release
        self.sample_rate = sample_rate
        self.envelope = 0.0

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply limiting.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Limited samples
        """
        if not self.enabled:
            return samples

        threshold_linear = 10.0 ** (self.threshold / 20.0)
        output = np.zeros_like(samples)

        for i in range(len(samples)):
            # Peak detection
            peak = np.max(np.abs(samples[i]))
            gain_reduction = min(1.0, threshold_linear / (peak + 1e-6))

            # Attack/release
            attack_coeff = math.exp(-1.0 / (self.attack * self.sample_rate))
            release_coeff = math.exp(-1.0 / (self.release * self.sample_rate))

            if gain_reduction < self.envelope:
                self.envelope = attack_coeff * self.envelope + (1.0 - attack_coeff) * gain_reduction
            else:
                self.envelope = release_coeff * self.envelope + (1.0 - release_coeff) * gain_reduction

            output[i] = samples[i] * self.envelope

        return output


class Tremolo(Effect):
    """Tremolo: amplitude modulation using LFO.

    Attributes:
        rate: LFO rate in Hz
        depth: Modulation depth (0.0-1.0)
    """

    def __init__(self, rate: float = 5.0, depth: float = 0.5, sample_rate: int = 44100) -> None:
        """Initialize tremolo.

        Args:
            rate: LFO rate in Hz
            depth: Modulation depth (0.0-1.0)
            sample_rate: Sample rate in Hz
        """
        super().__init__("Tremolo", dry=0.0, wet=1.0)
        self.rate = rate
        self.depth = depth
        self.sample_rate = sample_rate
        self.lfo_phase = 0.0

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Apply tremolo effect.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Processed samples
        """
        if not self.enabled:
            return samples

        output = np.zeros_like(samples)
        lfo_inc = self.rate / self.sample_rate

        for i in range(len(samples)):
            # LFO creates amplitude modulation
            lfo = 0.5 + 0.5 * np.sin(2.0 * np.pi * self.lfo_phase)
            modulation = 1.0 - self.depth + self.depth * lfo
            output[i] = samples[i] * modulation

            self.lfo_phase += lfo_inc
            if self.lfo_phase >= 1.0:
                self.lfo_phase -= 1.0

        return output
