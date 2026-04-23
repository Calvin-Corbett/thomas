"""
Spatial audio processing including panning, HRTF, distance simulation, and Doppler.

Implements 3D audio positioning and room simulation.
"""

import math

import numpy as np
from numpy.typing import NDArray

from thomas.marketplace.audio_engine._types import PanLaw, SpatialPosition


class StereoPane:
    """Stereo panning with various pan laws.

    Attributes:
        pan_law: Pan law type (linear, equal_power, minus_4_5db)
    """

    def __init__(self, pan_law: PanLaw = PanLaw.EQUAL_POWER) -> None:
        """Initialize stereo panner.

        Args:
            pan_law: Pan law type
        """
        self.pan_law = pan_law

    def process(self, samples: NDArray[np.float32], pan: float) -> NDArray[np.float32]:
        """Apply stereo pan to mono or stereo input.

        Args:
            samples: Input samples (num_samples,) or (num_samples, 2)
            pan: Pan value (-1.0 left to 1.0 right)

        Returns:
            Stereo samples (num_samples, 2)
        """
        # Ensure mono
        if samples.ndim > 1:
            samples = np.mean(samples, axis=1)

        pan = np.clip(pan, -1.0, 1.0)

        if self.pan_law == PanLaw.LINEAR:
            left_gain = 1.0 - (pan + 1.0) / 2.0
            right_gain = (pan + 1.0) / 2.0
        elif self.pan_law == PanLaw.EQUAL_POWER:
            # Constant power panning
            angle = (pan + 1.0) / 2.0 * np.pi / 2.0
            left_gain = np.cos(angle)
            right_gain = np.sin(angle)
        else:  # MINUS_4_5DB
            left_gain = np.sqrt(1.0 - (pan + 1.0) / 2.0)
            right_gain = np.sqrt((pan + 1.0) / 2.0)

        left_channel = samples * left_gain
        right_channel = samples * right_gain

        return np.column_stack([left_channel, right_channel])


class BiauralRenderer:
    """Simplified head-related transfer function (HRTF) binaural rendering.

    Implements basic head shadow model and interaural time differences.
    """

    def __init__(self, sample_rate: int = 44100, head_radius: float = 0.1) -> None:
        """Initialize binaural renderer.

        Args:
            sample_rate: Sample rate in Hz
            head_radius: Head radius in meters
        """
        self.sample_rate = sample_rate
        self.head_radius = head_radius
        self.speed_of_sound = 343.0  # m/s at 20°C

    def render(
        self, samples: NDArray[np.float32], position: SpatialPosition, listener_position: SpatialPosition = None
    ) -> NDArray[np.float32]:
        """Render binaural audio for 3D position.

        Args:
            samples: Mono audio samples
            position: Source 3D position
            listener_position: Listener position (default at origin)

        Returns:
            Stereo binaural samples
        """
        if listener_position is None:
            listener_position = SpatialPosition(0.0, 0.0, 0.0)

        # Ensure mono
        if samples.ndim > 1:
            samples = np.mean(samples, axis=1)

        # Calculate relative position
        rel_pos = SpatialPosition(
            position.x - listener_position.x, position.y - listener_position.y, position.z - listener_position.z
        )

        # Calculate ITD (interaural time difference)
        # Simplified: based on azimuth angle
        distance = rel_pos.distance_to(SpatialPosition(0, 0, 0))
        if distance > 0:
            azimuth = math.atan2(rel_pos.y, rel_pos.x)
        else:
            azimuth = 0.0

        itd_time = (self.head_radius / self.speed_of_sound) * np.sin(azimuth)
        itd_samples = int(abs(itd_time) * self.sample_rate)

        # Pad and delay appropriately
        if itd_samples > 0:
            if itd_time > 0:
                # Right ear delayed
                left = samples.copy()
                right = np.pad(samples, (itd_samples, 0))[:-itd_samples]
            else:
                # Left ear delayed
                right = samples.copy()
                left = np.pad(samples, (itd_samples, 0))[:-itd_samples]
        else:
            left = samples
            right = samples

        # Apply distance-based level difference
        if distance > 0:
            level_factor = 1.0 / (1.0 + distance)
        else:
            level_factor = 1.0

        left = left * level_factor
        right = right * level_factor

        return np.column_stack([left, right])


class SpatialSource:
    """3D audio source with position, distance attenuation, and Doppler.

    Attributes:
        position: Source position
        velocity: Source velocity for Doppler
        sample_rate: Sample rate in Hz
    """

    def __init__(self, position: SpatialPosition, sample_rate: int = 44100) -> None:
        """Initialize spatial source.

        Args:
            position: Source position
            sample_rate: Sample rate in Hz
        """
        self.position = position
        self.velocity = SpatialPosition(0.0, 0.0, 0.0)
        self.sample_rate = sample_rate
        self.speed_of_sound = 343.0

    def process(
        self,
        samples: NDArray[np.float32],
        listener_position: SpatialPosition = None,
        listener_velocity: SpatialPosition = None,
    ) -> NDArray[np.float32]:
        """Process audio with distance attenuation and Doppler effect.

        Args:
            samples: Input samples
            listener_position: Listener position
            listener_velocity: Listener velocity

        Returns:
            Processed samples
        """
        if listener_position is None:
            listener_position = SpatialPosition(0.0, 0.0, 0.0)
        if listener_velocity is None:
            listener_velocity = SpatialPosition(0.0, 0.0, 0.0)

        # Distance attenuation (inverse square law)
        distance = self.position.distance_to(listener_position)
        reference_distance = 1.0
        min_distance = 0.01

        if distance < min_distance:
            attenuation = 1.0
        else:
            attenuation = reference_distance / distance

        # Doppler effect
        relative_velocity = self._calculate_relative_velocity(listener_velocity)
        if self.speed_of_sound > abs(relative_velocity):
            doppler_factor = (self.speed_of_sound - relative_velocity) / self.speed_of_sound
        else:
            doppler_factor = 1.0

        # Apply attenuation
        output = samples * attenuation

        # Apply Doppler pitch shift (simplified via time stretching)
        if abs(doppler_factor - 1.0) > 0.01:
            output = self._apply_doppler(output, doppler_factor)

        return output

    def _calculate_relative_velocity(self, listener_velocity: SpatialPosition) -> float:
        """Calculate relative velocity along line of sight.

        Args:
            listener_velocity: Listener velocity

        Returns:
            Relative velocity
        """
        # Simplified: just sum of velocities
        return (
            self.velocity.x
            + self.velocity.y
            + self.velocity.z
            - listener_velocity.x
            - listener_velocity.y
            - listener_velocity.z
        )

    def _apply_doppler(self, samples: NDArray[np.float32], factor: float) -> NDArray[np.float32]:
        """Apply Doppler pitch shift via resampling.

        Args:
            samples: Input samples
            factor: Pitch shift factor

        Returns:
            Pitch-shifted samples
        """
        # Resample by factor
        new_length = int(len(samples) / factor)
        indices = np.linspace(0, len(samples) - 1, new_length)
        output = np.interp(indices, np.arange(len(samples)), samples)
        return output.astype(np.float32)

    def update_position(self, position: SpatialPosition) -> None:
        """Update source position.

        Args:
            position: New position
        """
        self.position = position

    def set_velocity(self, velocity: SpatialPosition) -> None:
        """Set source velocity for Doppler.

        Args:
            velocity: Velocity vector
        """
        self.velocity = velocity


class RoomSimulator:
    """Room simulation using early reflections and diffuse field.

    Attributes:
        room_dimensions: Room dimensions (width, depth, height) in meters
        absorption_coefficients: Wall absorption (0.0-1.0)
    """

    def __init__(
        self,
        room_width: float = 5.0,
        room_depth: float = 4.0,
        room_height: float = 3.0,
        absorption: float = 0.2,
        sample_rate: int = 44100,
    ) -> None:
        """Initialize room simulator.

        Args:
            room_width: Room width in meters
            room_depth: Room depth in meters
            room_height: Room height in meters
            absorption: Wall absorption coefficient
            sample_rate: Sample rate in Hz
        """
        self.room_width = room_width
        self.room_depth = room_depth
        self.room_height = room_height
        self.absorption = absorption
        self.sample_rate = sample_rate
        self.speed_of_sound = 343.0

    def simulate_early_reflections(
        self, samples: NDArray[np.float32], source_pos: SpatialPosition, listener_pos: SpatialPosition = None
    ) -> NDArray[np.float32]:
        """Simulate early reflections using image source method.

        Args:
            samples: Input samples
            source_pos: Source position
            listener_pos: Listener position

        Returns:
            Samples with early reflections
        """
        if listener_pos is None:
            listener_pos = SpatialPosition(0.0, 0.0, 0.0)

        output = samples.copy()

        # Image sources for first-order reflections (6 walls)
        image_positions = [
            # Floor and ceiling reflections
            SpatialPosition(source_pos.x, source_pos.y, -source_pos.z),
            SpatialPosition(source_pos.x, source_pos.y, 2 * self.room_height - source_pos.z),
            # Wall reflections
            SpatialPosition(-source_pos.x, source_pos.y, source_pos.z),
            SpatialPosition(2 * self.room_width - source_pos.x, source_pos.y, source_pos.z),
            SpatialPosition(source_pos.x, -source_pos.y, source_pos.z),
            SpatialPosition(source_pos.x, 2 * self.room_depth - source_pos.y, source_pos.z),
        ]

        for img_pos in image_positions:
            # Distance to image source
            distance = img_pos.distance_to(listener_pos)
            if distance > 0:
                # Time delay
                delay_time = distance / self.speed_of_sound
                delay_samples = int(delay_time * self.sample_rate)

                if delay_samples > 0 and delay_samples < len(samples):
                    # Attenuation from absorption
                    attenuation = (1.0 - self.absorption) ** 1.0
                    delayed = np.pad(samples, (delay_samples, 0))[:-delay_samples] * attenuation
                    output += delayed

        return output


class AmbisonicsEncoder:
    """First-order ambisonics B-format encoding.

    Attributes:
        sample_rate: Sample rate in Hz
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        """Initialize ambisonics encoder.

        Args:
            sample_rate: Sample rate in Hz
        """
        self.sample_rate = sample_rate

    def encode(self, samples: NDArray[np.float32], position: SpatialPosition) -> tuple[NDArray[np.float32], ...]:
        """Encode mono audio to ambisonics B-format.

        Args:
            samples: Input mono samples
            position: Source position

        Returns:
            Tuple of (W, X, Y, Z) ambisonics channels
        """
        # Normalize position
        distance = position.distance_to(SpatialPosition(0, 0, 0))
        if distance > 0:
            x_norm = position.x / distance
            y_norm = position.y / distance
            z_norm = position.z / distance
        else:
            x_norm = y_norm = z_norm = 0.0

        # W channel (omnidirectional)
        w = samples * (1.0 / np.sqrt(2.0))

        # X, Y, Z channels (directional)
        x = samples * x_norm * np.sqrt(3.0 / 2.0)
        y = samples * y_norm * np.sqrt(3.0 / 2.0)
        z = samples * z_norm * np.sqrt(3.0 / 2.0)

        return w, x, y, z


class AmbisonicsDecoder:
    """First-order ambisonics B-format decoder to stereo.

    Attributes:
        sample_rate: Sample rate in Hz
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        """Initialize ambisonics decoder.

        Args:
            sample_rate: Sample rate in Hz
        """
        self.sample_rate = sample_rate

    def decode(
        self, w: NDArray[np.float32], x: NDArray[np.float32], y: NDArray[np.float32], z: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """Decode ambisonics to stereo.

        Args:
            w, x, y, z: Ambisonics channels

        Returns:
            Stereo samples (num_samples, 2)
        """
        # Basic stereo decode: W + X mix
        left = (w + x) * 0.5
        right = (w - x) * 0.5

        return np.column_stack([left, right])
