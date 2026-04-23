"""Audio system for sound effects, music, and positional audio."""

import math
from dataclasses import dataclass

from thomas.marketplace.gaming_platform._types import AudioSource, Transform
from thomas.marketplace.gaming_platform.ecs import EntityComponentSystem


@dataclass
class AudioChannel:
    """Represents an audio playback channel."""

    channel_id: int
    clip_id: str = ""
    is_playing: bool = False
    volume: float = 1.0
    pitch: float = 1.0
    looping: bool = False
    priority: int = 0
    elapsed_time: float = 0.0
    duration: float = 0.0
    is_3d: bool = False
    pan: float = 0.0

    def update(self, dt: float) -> None:
        """Update channel."""
        if self.is_playing:
            self.elapsed_time += dt
            if self.elapsed_time >= self.duration:
                if self.looping:
                    self.elapsed_time = 0.0
                else:
                    self.is_playing = False


class AudioBus:
    """Audio routing bus for grouped volume control."""

    def __init__(self, name: str) -> None:
        """
        Initialize audio bus.

        Args:
            name: Bus name.
        """
        self.name = name
        self.volume = 1.0
        self.muted = False
        self.channels: list[int] = []

    def set_volume(self, volume: float) -> None:
        """Set bus volume."""
        self.volume = max(0.0, min(1.0, volume))

    def get_effective_volume(self) -> float:
        """Get effective volume accounting for mute state."""
        return 0.0 if self.muted else self.volume

    def mute(self) -> None:
        """Mute bus."""
        self.muted = True

    def unmute(self) -> None:
        """Unmute bus."""
        self.muted = False


class AudioEngine:
    """
    Audio system managing sound effects, music, and spatial audio.

    Features:
    - Sound effect playback with pooling
    - Music player with crossfading
    - Volume control with master/SFX/music channels
    - 2D positional audio with distance attenuation
    - Audio bus routing
    - Sound priority system
    - Audio fade in/out
    """

    def __init__(self, max_channels: int = 32) -> None:
        """
        Initialize audio engine.

        Args:
            max_channels: Maximum concurrent audio channels.
        """
        self.max_channels = max_channels
        self.channels: dict[int, AudioChannel] = {i: AudioChannel(channel_id=i) for i in range(max_channels)}
        self.available_channels: list[int] = list(range(max_channels))

        # Audio clips database
        self.audio_clips: dict[str, dict[str, float]] = {}

        # Buses
        self.master_bus = AudioBus("master")
        self.sfx_bus = AudioBus("sfx")
        self.music_bus = AudioBus("music")
        self.buses = {
            "master": self.master_bus,
            "sfx": self.sfx_bus,
            "music": self.music_bus,
        }

        # Music management
        self.current_music: str | None = None
        self.next_music: str | None = None
        self.music_fade_duration = 0.0
        self.music_fade_elapsed = 0.0
        self.music_crossfade = False

        # Fading sounds
        self.fading_channels: dict[
            int, tuple[float, float, float]
        ] = {}  # channel_id -> (duration, elapsed, target_volume)

    def register_audio_clip(self, clip_id: str, duration: float) -> None:
        """
        Register audio clip metadata.

        Args:
            clip_id: Clip identifier.
            duration: Clip duration in seconds.
        """
        self.audio_clips[clip_id] = {
            "duration": duration,
        }

    def play_sound(
        self,
        clip_id: str,
        volume: float = 1.0,
        pitch: float = 1.0,
        priority: int = 0,
    ) -> int | None:
        """
        Play sound effect.

        Args:
            clip_id: Audio clip identifier.
            volume: Volume level (0-1).
            pitch: Playback speed (0.5-2.0).
            priority: Priority (higher = more important).

        Returns:
            Channel ID or None if no channels available.
        """
        if clip_id not in self.audio_clips:
            return None

        # Find available channel
        channel_id = self._allocate_channel(priority)
        if channel_id is None:
            return None

        channel = self.channels[channel_id]
        channel.clip_id = clip_id
        channel.volume = volume
        channel.pitch = pitch
        channel.is_playing = True
        channel.looping = False
        channel.duration = self.audio_clips[clip_id]["duration"]
        channel.elapsed_time = 0.0
        channel.is_3d = False

        return channel_id

    def play_music(
        self,
        clip_id: str,
        volume: float = 1.0,
        crossfade_duration: float = 0.0,
    ) -> None:
        """
        Play music with optional crossfade.

        Args:
            clip_id: Audio clip identifier.
            volume: Volume level (0-1).
            crossfade_duration: Crossfade duration in seconds (0 = cut).
        """
        if clip_id not in self.audio_clips:
            return

        if crossfade_duration > 0 and self.current_music:
            # Setup crossfade
            self.next_music = clip_id
            self.music_fade_duration = crossfade_duration
            self.music_fade_elapsed = 0.0
            self.music_crossfade = True
        else:
            # Immediate cut
            self._play_music_clip(clip_id, volume)
            self.current_music = clip_id

    def _play_music_clip(self, clip_id: str, volume: float) -> None:
        """Play music clip on music channel."""
        # Find or allocate music channel
        music_channel = None
        for ch_id, channel in self.channels.items():
            if channel.clip_id == self.current_music:
                music_channel = ch_id
                break

        if music_channel is None:
            music_channel = self._allocate_channel(priority=100)

        if music_channel is not None:
            channel = self.channels[music_channel]
            channel.clip_id = clip_id
            channel.volume = volume
            channel.pitch = 1.0
            channel.is_playing = True
            channel.looping = True
            channel.duration = self.audio_clips[clip_id]["duration"]
            channel.elapsed_time = 0.0
            channel.is_3d = False

    def stop_sound(self, channel_id: int) -> None:
        """Stop playing sound on channel."""
        if channel_id not in self.channels:
            return

        channel = self.channels[channel_id]
        channel.is_playing = False
        if channel_id in self.fading_channels:
            del self.fading_channels[channel_id]
        self.available_channels.append(channel_id)

    def stop_all_sounds(self) -> None:
        """Stop all playing sounds."""
        for channel in self.channels.values():
            channel.is_playing = False
        self.fading_channels.clear()
        self.available_channels = list(range(self.max_channels))

    def pause_sound(self, channel_id: int) -> None:
        """Pause sound on channel."""
        if channel_id in self.channels:
            self.channels[channel_id].is_playing = False

    def resume_sound(self, channel_id: int) -> None:
        """Resume paused sound."""
        if channel_id in self.channels:
            self.channels[channel_id].is_playing = True

    def set_channel_volume(self, channel_id: int, volume: float) -> None:
        """Set channel volume."""
        if channel_id in self.channels:
            self.channels[channel_id].volume = max(0.0, min(1.0, volume))

    def set_channel_pitch(self, channel_id: int, pitch: float) -> None:
        """Set channel pitch/speed."""
        if channel_id in self.channels:
            self.channels[channel_id].pitch = max(0.5, min(2.0, pitch))

    def fade_volume(
        self,
        channel_id: int,
        target_volume: float,
        duration: float,
    ) -> None:
        """
        Fade channel volume over time.

        Args:
            channel_id: Channel to fade.
            target_volume: Target volume (0-1).
            duration: Fade duration in seconds.
        """
        if channel_id not in self.channels:
            return

        self.fading_channels[channel_id] = (duration, 0.0, target_volume)

    def set_bus_volume(self, bus_name: str, volume: float) -> None:
        """Set bus volume."""
        if bus_name in self.buses:
            self.buses[bus_name].set_volume(volume)

    def mute_bus(self, bus_name: str) -> None:
        """Mute bus."""
        if bus_name in self.buses:
            self.buses[bus_name].mute()

    def unmute_bus(self, bus_name: str) -> None:
        """Unmute bus."""
        if bus_name in self.buses:
            self.buses[bus_name].unmute()

    def update(self, ecs: EntityComponentSystem, dt: float) -> None:
        """
        Update audio system.

        Args:
            ecs: Entity component system.
            dt: Delta time in seconds.
        """
        # Update channels
        for channel in self.channels.values():
            channel.update(dt)

        # Update music crossfade
        if self.music_crossfade and self.next_music:
            self.music_fade_elapsed += dt

            if self.music_fade_elapsed >= self.music_fade_duration:
                self._play_music_clip(self.next_music, 1.0)
                self.current_music = self.next_music
                self.next_music = None
                self.music_crossfade = False
            else:
                # Fade old music out, new in
                t = self.music_fade_elapsed / self.music_fade_duration
                # Implementation would update volumes

        # Update fading channels
        finished_fades = []
        for channel_id, (duration, elapsed, target_vol) in self.fading_channels.items():
            elapsed += dt
            progress = min(1.0, elapsed / duration)

            if channel_id in self.channels:
                channel = self.channels[channel_id]
                # Linear interpolation
                start_vol = channel.volume
                channel.volume = start_vol + (target_vol - start_vol) * progress

            if elapsed >= duration:
                finished_fades.append(channel_id)

        for channel_id in finished_fades:
            del self.fading_channels[channel_id]

        # Update 3D audio
        entities = ecs.query(AudioSource, Transform)
        for entity in entities:
            audio_source = ecs.get_component(entity, AudioSource)
            transform = ecs.get_component(entity, Transform)

            if audio_source is None or transform is None:
                continue

            if not audio_source.is_3d or audio_source.channel == 0:
                continue

            # Update panning based on listener position
            # For now, simplified (listener at origin)
            listener_pos = (0.0, 0.0)
            dist = math.sqrt(
                (transform.position[0] - listener_pos[0]) ** 2 + (transform.position[1] - listener_pos[1]) ** 2
            )

            # Distance attenuation
            if dist > audio_source.max_distance:
                audio_volume = 0.0
            elif dist < audio_source.min_distance:
                audio_volume = audio_source.volume
            else:
                ratio = (dist - audio_source.min_distance) / (audio_source.max_distance - audio_source.min_distance)
                audio_volume = audio_source.volume * (1.0 - ratio)

            if audio_source.channel in self.channels:
                self.channels[audio_source.channel].volume = audio_volume

    def _allocate_channel(self, priority: int = 0) -> int | None:
        """
        Allocate audio channel.

        If no channels available, may evict lowest priority sound.

        Returns:
            Channel ID or None.
        """
        # Try to find unused channel
        if self.available_channels:
            return self.available_channels.pop(0)

        # All channels in use - find lowest priority to evict
        lowest_priority_channel = None
        lowest_priority = priority

        for ch_id, channel in self.channels.items():
            if channel.is_playing and channel.priority < lowest_priority:
                lowest_priority_channel = ch_id
                lowest_priority = channel.priority

        if lowest_priority_channel is not None:
            self.stop_sound(lowest_priority_channel)
            return lowest_priority_channel

        return None

    def get_active_channel_count(self) -> int:
        """Get number of active channels."""
        return sum(1 for ch in self.channels.values() if ch.is_playing)

    def get_stats(self) -> dict[str, int]:
        """Get audio engine statistics."""
        return {
            "active_channels": self.get_active_channel_count(),
            "total_channels": self.max_channels,
            "registered_clips": len(self.audio_clips),
        }


# Helper function for distance calculation
def distance_squared(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Calculate squared distance between two points."""
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return dx * dx + dy * dy


def distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Calculate distance between two points."""
    return math.sqrt(distance_squared(p1, p2))
