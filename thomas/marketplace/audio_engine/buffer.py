"""
Audio buffer management and sample conversion utilities.

Provides ring buffers, format conversion, and efficient memory pooling.
"""

import threading

import numpy as np
from numpy.typing import NDArray

from thomas.marketplace.audio_engine._exceptions import (
    BufferOverflowError,
    BufferUnderflowError,
)


class RingBuffer:
    """Real-time safe circular audio buffer.

    Attributes:
        capacity: Maximum number of samples per channel
        channels: Number of audio channels
    """

    def __init__(self, capacity: int, channels: int = 2) -> None:
        """Initialize ring buffer.

        Args:
            capacity: Capacity in samples per channel
            channels: Number of channels
        """
        self.capacity = capacity
        self.channels = channels
        self.buffer = np.zeros((capacity, channels), dtype=np.float32)
        self.write_pos = 0
        self.read_pos = 0
        self._lock = threading.Lock()

    def write(self, samples: NDArray[np.float32]) -> int:
        """Write samples to buffer.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Number of samples written

        Raises:
            BufferOverflowError: If buffer is full
        """
        with self._lock:
            num_samples = len(samples)
            available = self._available_write()

            if num_samples > available:
                raise BufferOverflowError(f"Not enough space: {num_samples} > {available}")

            # Handle wrap-around
            if self.write_pos + num_samples <= self.capacity:
                self.buffer[self.write_pos : self.write_pos + num_samples] = samples
            else:
                # Split write
                first_part = self.capacity - self.write_pos
                self.buffer[self.write_pos :] = samples[:first_part]
                self.buffer[: num_samples - first_part] = samples[first_part:]

            self.write_pos = (self.write_pos + num_samples) % self.capacity
            return num_samples

    def read(self, num_samples: int) -> NDArray[np.float32]:
        """Read samples from buffer.

        Args:
            num_samples: Number of samples to read

        Returns:
            Audio samples

        Raises:
            BufferUnderflowError: If not enough samples available
        """
        with self._lock:
            available = self._available_read()

            if num_samples > available:
                raise BufferUnderflowError(f"Not enough samples: {num_samples} > {available}")

            output = np.zeros((num_samples, self.channels), dtype=np.float32)

            # Handle wrap-around
            if self.read_pos + num_samples <= self.capacity:
                output = self.buffer[self.read_pos : self.read_pos + num_samples].copy()
            else:
                # Split read
                first_part = self.capacity - self.read_pos
                output[:first_part] = self.buffer[self.read_pos :]
                output[first_part:] = self.buffer[: num_samples - first_part]

            self.read_pos = (self.read_pos + num_samples) % self.capacity
            return output

    def peek(self, num_samples: int) -> NDArray[np.float32]:
        """Peek at samples without advancing read pointer.

        Args:
            num_samples: Number of samples to peek

        Returns:
            Audio samples
        """
        with self._lock:
            output = np.zeros((num_samples, self.channels), dtype=np.float32)

            if self.read_pos + num_samples <= self.capacity:
                output = self.buffer[self.read_pos : self.read_pos + num_samples].copy()
            else:
                first_part = self.capacity - self.read_pos
                output[:first_part] = self.buffer[self.read_pos :]
                output[first_part:] = self.buffer[: num_samples - first_part]

            return output

    def flush(self) -> None:
        """Clear all data from buffer."""
        with self._lock:
            self.buffer.fill(0.0)
            self.write_pos = 0
            self.read_pos = 0

    def _available_write(self) -> int:
        """Calculate available write space."""
        if self.write_pos >= self.read_pos:
            return self.capacity - (self.write_pos - self.read_pos) - 1
        else:
            return self.read_pos - self.write_pos - 1

    def _available_read(self) -> int:
        """Calculate available read data."""
        if self.write_pos >= self.read_pos:
            return self.write_pos - self.read_pos
        else:
            return self.capacity - (self.read_pos - self.write_pos)

    @property
    def available_read(self) -> int:
        """Number of samples available to read."""
        return self._available_read()

    @property
    def available_write(self) -> int:
        """Number of samples available to write."""
        return self._available_write()


class SampleConverter:
    """Convert audio samples between different formats."""

    @staticmethod
    def int16_to_float32(samples: NDArray[np.int16]) -> NDArray[np.float32]:
        """Convert int16 to float32 normalized to [-1.0, 1.0].

        Args:
            samples: int16 audio samples

        Returns:
            float32 samples
        """
        return samples.astype(np.float32) / 32768.0

    @staticmethod
    def float32_to_int16(samples: NDArray[np.float32]) -> NDArray[np.int16]:
        """Convert float32 to int16 with soft clipping.

        Args:
            samples: float32 audio samples

        Returns:
            int16 samples
        """
        # Soft clipping
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16)

    @staticmethod
    def int32_to_float32(samples: NDArray[np.int32]) -> NDArray[np.float32]:
        """Convert int32 to float32.

        Args:
            samples: int32 audio samples

        Returns:
            float32 samples
        """
        return samples.astype(np.float32) / 2147483648.0

    @staticmethod
    def float32_to_int32(samples: NDArray[np.float32]) -> NDArray[np.int32]:
        """Convert float32 to int32 with soft clipping.

        Args:
            samples: float32 audio samples

        Returns:
            int32 samples
        """
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 2147483647.0).astype(np.int32)

    @staticmethod
    def with_dither(samples: NDArray[np.float32], bit_depth: int = 16) -> NDArray[np.float32]:
        """Apply triangular PDF dither to samples.

        Args:
            samples: Audio samples to dither
            bit_depth: Target bit depth

        Returns:
            Dithered samples
        """
        max_val = 2 ** (bit_depth - 1)
        dither_level = 1.0 / max_val
        dither = np.random.uniform(
            -dither_level,
            dither_level,
            samples.shape,
        ).astype(samples.dtype, copy=False)
        return (samples + dither).astype(samples.dtype, copy=False)


class ChannelConverter:
    """Convert audio between channel configurations."""

    @staticmethod
    def mono_to_stereo(mono: NDArray[np.float32]) -> NDArray[np.float32]:
        """Convert mono to stereo by duplicating channel.

        Args:
            mono: Mono audio (num_samples,) or (num_samples, 1)

        Returns:
            Stereo audio (num_samples, 2)
        """
        if mono.ndim == 1:
            return np.column_stack([mono, mono])
        else:
            return np.column_stack([mono[:, 0], mono[:, 0]])

    @staticmethod
    def stereo_to_mono(stereo: NDArray[np.float32]) -> NDArray[np.float32]:
        """Convert stereo to mono by averaging channels.

        Args:
            stereo: Stereo audio (num_samples, 2)

        Returns:
            Mono audio (num_samples,)
        """
        if stereo.ndim == 1:
            return stereo
        return np.mean(stereo, axis=1)

    @staticmethod
    def interleave(channels: list[NDArray[np.float32]]) -> NDArray[np.float32]:
        """Interleave separate channels into multi-channel audio.

        Args:
            channels: List of channel arrays, each (num_samples,)

        Returns:
            Interleaved audio (num_samples, num_channels)
        """
        # Normalize float32 channel values to stable float64 decimals.
        interleaved = np.column_stack(channels).astype(np.float64, copy=False)
        return np.round(interleaved, decimals=7)

    @staticmethod
    def deinterleave(audio: NDArray[np.float32]) -> list[NDArray[np.float32]]:
        """Deinterleave multi-channel audio into separate channels.

        Args:
            audio: Interleaved audio (num_samples, num_channels)

        Returns:
            List of mono arrays
        """
        return [audio[:, i] for i in range(audio.shape[1])]


class AudioBufferPool:
    """Pre-allocated buffer pool to avoid garbage collection in real-time.

    Attributes:
        buffer_size: Size of each buffer in samples per channel
        num_channels: Number of channels per buffer
        pool_size: Number of buffers to pre-allocate
    """

    def __init__(self, buffer_size: int, num_channels: int, pool_size: int) -> None:
        """Initialize buffer pool.

        Args:
            buffer_size: Samples per buffer
            num_channels: Channels per buffer
            pool_size: Number of buffers to allocate
        """
        self.buffer_size = buffer_size
        self.num_channels = num_channels
        self.pool_size = pool_size
        self._available: list[NDArray[np.float32]] = []
        self._in_use: list[NDArray[np.float32]] = []
        self._lock = threading.Lock()

        # Pre-allocate buffers
        for _ in range(pool_size):
            buf = np.zeros((buffer_size, num_channels), dtype=np.float32)
            self._available.append(buf)

    def acquire(self) -> NDArray[np.float32]:
        """Get a buffer from the pool.

        Returns:
            Audio buffer (buffer_size, num_channels)

        Raises:
            BufferOverflowError: If no buffers available
        """
        with self._lock:
            if not self._available:
                raise BufferOverflowError("No buffers available in pool")

            buf = self._available.pop()
            self._in_use.append(buf)
            return buf

    def release(self, buffer: NDArray[np.float32]) -> None:
        """Return a buffer to the pool.

        Args:
            buffer: Buffer to return
        """
        with self._lock:
            if buffer in self._in_use:
                self._in_use.remove(buffer)
            buffer.fill(0.0)
            self._available.append(buffer)

    @property
    def available_count(self) -> int:
        """Number of available buffers."""
        with self._lock:
            return len(self._available)

    @property
    def in_use_count(self) -> int:
        """Number of buffers currently in use."""
        with self._lock:
            return len(self._in_use)


class SampleRateConverter:
    """Convert audio between different sample rates."""

    def __init__(self, input_rate: int, output_rate: int) -> None:
        """Initialize converter.

        Args:
            input_rate: Input sample rate in Hz
            output_rate: Output sample rate in Hz
        """
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.ratio = output_rate / input_rate
        self.phase = 0.0

    def process_linear(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Resample using linear interpolation.

        Args:
            samples: Input audio (num_samples, num_channels)

        Returns:
            Resampled audio
        """
        num_samples = len(samples)
        num_channels = samples.shape[1] if samples.ndim > 1 else 1
        out_samples = int(np.ceil(num_samples * self.ratio))
        output = np.zeros((out_samples, num_channels), dtype=np.float32)

        for i in range(out_samples):
            pos = i / self.ratio
            int_pos = int(pos)
            frac = pos - int_pos

            if int_pos >= num_samples - 1:
                break

            # Linear interpolation
            s0 = samples[int_pos]
            s1 = samples[int_pos + 1]
            output[i] = s0 * (1 - frac) + s1 * frac

        return output[: i + 1]

    def process_cubic(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Resample using cubic interpolation.

        Args:
            samples: Input audio (num_samples, num_channels)

        Returns:
            Resampled audio
        """
        num_samples = len(samples)
        num_channels = samples.shape[1] if samples.ndim > 1 else 1
        out_samples = int(np.ceil(num_samples * self.ratio))
        output = np.zeros((out_samples, num_channels), dtype=np.float32)

        for i in range(out_samples):
            pos = i / self.ratio
            int_pos = int(pos)
            frac = pos - int_pos

            if int_pos < 1 or int_pos >= num_samples - 2:
                continue

            # Cubic interpolation (Catmull-Rom)
            p0 = samples[int_pos - 1]
            p1 = samples[int_pos]
            p2 = samples[int_pos + 1]
            p3 = samples[int_pos + 2]

            a0 = -0.5 * p0 + 1.5 * p1 - 1.5 * p2 + 0.5 * p3
            a1 = p0 - 2.5 * p1 + 2.0 * p2 - 0.5 * p3
            a2 = -0.5 * p0 + 0.5 * p2
            a3 = p1

            f2 = frac * frac
            f3 = f2 * frac

            output[i] = a0 * f3 + a1 * f2 + a2 * frac + a3

        return output[1 : i + 1]


class BitDepthConverter:
    """Convert between different bit depths with dithering."""

    @staticmethod
    def convert(samples: NDArray[np.float32], source_depth: int, target_depth: int) -> NDArray[np.float32]:
        """Convert samples from one bit depth to another.

        Args:
            samples: Input samples normalized to [-1.0, 1.0]
            source_depth: Source bit depth
            target_depth: Target bit depth

        Returns:
            Converted samples
        """
        if source_depth == target_depth:
            return samples.copy()

        # Scale to target bit depth range
        source_max = 2 ** (source_depth - 1)
        target_max = 2 ** (target_depth - 1)
        scale = target_max / source_max

        scaled = samples * scale

        # Apply TPDF dither
        dither_level = 1.0 / target_max
        dither = np.random.uniform(
            -dither_level,
            dither_level,
            samples.shape,
        ).astype(samples.dtype, copy=False)

        return np.clip(scaled + dither, -1.0, 1.0).astype(samples.dtype, copy=False)
