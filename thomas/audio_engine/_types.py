"""
Type definitions for the audio engine.

Includes enums, dataclasses, and type aliases for audio processing.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray


class AudioFormat(str, Enum):
    """Audio data format types."""

    PCM = "pcm"
    WAV = "wav"
    AIFF = "aiff"
    RAW = "raw"


class SampleRate(int, Enum):
    """Standard sample rates in Hz."""

    RATE_8000 = 8000
    RATE_16000 = 16000
    RATE_22050 = 22050
    RATE_44100 = 44100
    RATE_48000 = 48000
    RATE_96000 = 96000
    RATE_192000 = 192000


class BitDepth(int, Enum):
    """Audio bit depths."""

    BIT_8 = 8
    BIT_16 = 16
    BIT_24 = 24
    BIT_32 = 32


class Channel(str, Enum):
    """Audio channel configurations."""

    MONO = "mono"
    STEREO = "stereo"
    QUAD = "quad"
    SURROUND_5_1 = "5.1"
    SURROUND_7_1 = "7.1"


class WaveformType(str, Enum):
    """Oscillator waveform types."""

    SINE = "sine"
    SQUARE = "square"
    SAWTOOTH = "sawtooth"
    TRIANGLE = "triangle"
    NOISE_WHITE = "noise_white"
    NOISE_PINK = "noise_pink"
    NOISE_BROWN = "noise_brown"


class FilterType(str, Enum):
    """Audio filter types."""

    LOWPASS = "lowpass"
    HIGHPASS = "highpass"
    BANDPASS = "bandpass"
    NOTCH = "notch"
    ALLPASS = "allpass"
    PEAKING = "peaking"
    LOW_SHELF = "low_shelf"
    HIGH_SHELF = "high_shelf"


class PanLaw(str, Enum):
    """Stereo panning laws."""

    LINEAR = "linear"
    EQUAL_POWER = "equal_power"
    MINUS_4_5DB = "minus_4_5db"


@dataclass
class AudioFrame:
    """Single audio frame with timestamp and metadata.

    Attributes:
        samples: Audio samples (num_samples, num_channels)
        sample_rate: Sample rate in Hz
        timestamp: Frame timestamp in seconds
    """

    samples: NDArray[np.float32]
    sample_rate: int
    timestamp: float = 0.0


@dataclass
class EnvelopePoint:
    """A point in an ADSR envelope.

    Attributes:
        time: Time in seconds
        level: Amplitude level (0.0-1.0)
        curve: Curve type ("linear" or "exponential")
    """

    time: float
    level: float
    curve: str = "linear"


@dataclass
class AudioBuffer:
    """Circular audio buffer for real-time processing.

    Attributes:
        capacity: Buffer capacity in samples
        channels: Number of audio channels
        write_pos: Current write position
        read_pos: Current read position
        data: Actual audio data (capacity, channels)
    """

    capacity: int
    channels: int
    write_pos: int = 0
    read_pos: int = 0
    data: NDArray[np.float32] = field(default_factory=lambda: np.array([], dtype=np.float32))

    def __post_init__(self) -> None:
        """Initialize buffer data if not provided."""
        if self.data.size == 0:
            self.data = np.zeros((self.capacity, self.channels), dtype=np.float32)


@dataclass
class AudioClip:
    """Immutable audio clip.

    Attributes:
        data: Audio data (num_samples, num_channels)
        sample_rate: Sample rate in Hz
        duration: Duration in seconds
        format: Audio format
    """

    data: NDArray[np.float32]
    sample_rate: int
    duration: float
    format: AudioFormat = AudioFormat.PCM

    @property
    def num_samples(self) -> int:
        """Number of samples in the clip."""
        return len(self.data)

    @property
    def num_channels(self) -> int:
        """Number of audio channels."""
        return self.data.shape[1] if self.data.ndim > 1 else 1


@dataclass
class MixerChannel:
    """Mixer channel with volume, pan, and effects.

    Attributes:
        name: Channel name
        volume: Channel gain (0.0-2.0)
        pan: Stereo pan (-1.0 left to 1.0 right)
        mute: Mute state
        solo: Solo state
        effects: List of effects to apply
    """

    name: str
    volume: float = 1.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    effects: list[Any] = field(default_factory=list)


@dataclass
class AudioBus:
    """Audio bus for mixing multiple channels.

    Attributes:
        name: Bus name
        channels: Number of output channels
        volume: Bus volume
        effects: List of effects applied to bus
    """

    name: str
    channels: int = 2
    volume: float = 1.0
    effects: list[Any] = field(default_factory=list)


@dataclass
class Effect:
    """Base effect class.

    Attributes:
        name: Effect name
        enabled: Whether effect is active
        dry: Dry signal level (0.0-1.0)
        wet: Wet signal level (0.0-1.0)
    """

    name: str
    enabled: bool = True
    dry: float = 0.0
    wet: float = 1.0

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Process audio samples.

        Args:
            samples: Input samples (num_samples, num_channels)

        Returns:
            Processed samples
        """
        raise NotImplementedError


@dataclass
class EffectChain:
    """Chain of effects applied in series.

    Attributes:
        name: Chain name
        effects: List of effects in chain
        bypass: Whether chain is bypassed
    """

    name: str
    effects: list[Effect] = field(default_factory=list)
    bypass: bool = False

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        """Process samples through all effects.

        Args:
            samples: Input samples

        Returns:
            Processed samples
        """
        if self.bypass:
            return samples

        output = samples.copy()
        for effect in self.effects:
            if effect.enabled:
                output = effect.process(output)
        return output

    def add_effect(self, effect: Effect) -> None:
        """Add effect to chain.

        Args:
            effect: Effect to add
        """
        self.effects.append(effect)

    def remove_effect(self, index: int) -> None:
        """Remove effect at index.

        Args:
            index: Effect index
        """
        if 0 <= index < len(self.effects):
            del self.effects[index]


@dataclass
class AudioTrack:
    """Audio track in a timeline.

    Attributes:
        name: Track name
        clip: Audio clip to play
        start_time: Start time in seconds
        volume: Track volume
        pan: Stereo pan
    """

    name: str
    clip: AudioClip | None = None
    start_time: float = 0.0
    volume: float = 1.0
    pan: float = 0.0

    def get_samples_at(self, time: float, duration: float, sample_rate: int) -> NDArray[np.float32] | None:
        """Get samples at a specific time.

        Args:
            time: Time in seconds
            duration: Duration in seconds
            sample_rate: Sample rate in Hz

        Returns:
            Audio samples or None if outside clip range
        """
        if self.clip is None:
            return None

        if time < self.start_time or time >= self.start_time + self.clip.duration:
            return None

        clip_time = time - self.start_time
        num_samples = int(duration * sample_rate)
        start_sample = int(clip_time * self.clip.sample_rate)

        if start_sample >= len(self.clip.data):
            return None

        end_sample = min(start_sample + num_samples, len(self.clip.data))
        return self.clip.data[start_sample:end_sample]


@dataclass
class BiquadCoefficients:
    """Coefficients for biquad filter.

    Attributes:
        b0, b1, b2: Numerator coefficients
        a1, a2: Denominator coefficients (a0 normalized to 1)
    """

    b0: float
    b1: float
    b2: float
    a1: float
    a2: float


@dataclass
class EqualizerBand:
    """Single band in parametric EQ.

    Attributes:
        frequency: Center frequency in Hz
        gain: Gain in dB
        q: Q factor (bandwidth)
    """

    frequency: float
    gain: float
    q: float = 1.0


@dataclass
class SpatialPosition:
    """3D spatial position.

    Attributes:
        x: X position in meters
        y: Y position in meters
        z: Z position in meters
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def distance_to(self, other: "SpatialPosition") -> float:
        """Calculate distance to another position.

        Args:
            other: Other position

        Returns:
            Distance in meters
        """
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return float(np.sqrt(dx * dx + dy * dy + dz * dz))
