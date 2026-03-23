"""
Audio sequencer for timeline-based playback with MIDI-like events.

Implements pattern sequencing, quantization, and sample-accurate scheduling.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass
class Note:
    """MIDI-like note representation.

    Attributes:
        pitch: MIDI note number (0-127, C-1 to G9)
        velocity: Note velocity (0-127)
        start_time: Start time in beats
        duration: Duration in beats
    """

    pitch: int
    velocity: int = 100
    start_time: float = 0.0
    duration: float = 1.0

    def frequency_hz(self) -> float:
        """Convert MIDI note to frequency in Hz.

        Returns:
            Frequency in Hz
        """
        return 440.0 * (2.0 ** ((self.pitch - 69) / 12.0))

    @staticmethod
    def from_frequency(frequency: float) -> int:
        """Convert frequency to nearest MIDI note.

        Args:
            frequency: Frequency in Hz

        Returns:
            MIDI note number
        """
        note = 69 + 12 * np.log2(frequency / 440.0)
        return int(round(note))


@dataclass
class TimelineEvent:
    """Event on the audio timeline.

    Attributes:
        time_samples: Time in samples
        event_type: Type of event ("note_on", "note_off", "parameter_change")
        data: Event-specific data
    """

    time_samples: int
    event_type: str
    data: dict = field(default_factory=dict)


class PatternSequencer:
    """Loop-based pattern sequencer.

    Attributes:
        pattern_length: Pattern length in beats
        tempo_bpm: Tempo in beats per minute
        sample_rate: Sample rate in Hz
    """

    def __init__(self, pattern_length: float = 16.0, tempo_bpm: float = 120.0, sample_rate: int = 44100) -> None:
        """Initialize pattern sequencer.

        Args:
            pattern_length: Pattern length in beats
            tempo_bpm: Tempo in BPM
            sample_rate: Sample rate in Hz
        """
        self.pattern_length = pattern_length
        self.tempo_bpm = tempo_bpm
        self.sample_rate = sample_rate
        self.notes: list[Note] = []
        self.pattern_position = 0.0
        self.current_sample = 0

    def add_note(self, note: Note) -> None:
        """Add note to pattern.

        Args:
            note: Note to add
        """
        self.notes.append(note)

    def remove_note(self, index: int) -> None:
        """Remove note from pattern.

        Args:
            index: Note index
        """
        if 0 <= index < len(self.notes):
            del self.notes[index]

    def clear_pattern(self) -> None:
        """Clear all notes from pattern."""
        self.notes.clear()
        self.pattern_position = 0.0

    def get_active_notes(self, beat_position: float) -> list[Note]:
        """Get notes active at beat position.

        Args:
            beat_position: Position in beats

        Returns:
            List of active notes
        """
        active = []
        beat_pos_wrapped = beat_position % self.pattern_length

        for note in self.notes:
            note_start = note.start_time % self.pattern_length
            note_end = (note.start_time + note.duration) % self.pattern_length

            if note_end > note_start:
                if note_start <= beat_pos_wrapped < note_end:
                    active.append(note)
            else:  # Wraps around pattern boundary
                if beat_pos_wrapped >= note_start or beat_pos_wrapped < note_end:
                    active.append(note)

        return active

    def set_tempo(self, tempo_bpm: float) -> None:
        """Set sequencer tempo.

        Args:
            tempo_bpm: Tempo in BPM
        """
        self.tempo_bpm = tempo_bpm

    def _beats_to_samples(self, beats: float) -> int:
        """Convert beats to samples.

        Args:
            beats: Time in beats

        Returns:
            Time in samples
        """
        return int(beats * (60.0 / self.tempo_bpm) * self.sample_rate)


class Transport:
    """Audio transport with play, pause, stop, and seek controls.

    Attributes:
        sample_rate: Sample rate in Hz
        tempo_bpm: Tempo in BPM
        playing: Whether transport is playing
        position_samples: Current position in samples
    """

    def __init__(self, sample_rate: int = 44100, tempo_bpm: float = 120.0) -> None:
        """Initialize transport.

        Args:
            sample_rate: Sample rate in Hz
            tempo_bpm: Tempo in BPM
        """
        self.sample_rate = sample_rate
        self.tempo_bpm = tempo_bpm
        self.playing = False
        self.position_samples = 0
        self.events: list[TimelineEvent] = []
        self.tempo_changes: list[tuple[int, float]] = []
        self._event_callbacks: dict[str, Callable] = {}

    def play(self) -> None:
        """Start playback."""
        self.playing = True

    def pause(self) -> None:
        """Pause playback."""
        self.playing = False

    def stop(self) -> None:
        """Stop playback and reset position."""
        self.playing = False
        self.position_samples = 0

    def seek(self, time_samples: int) -> None:
        """Seek to position.

        Args:
            time_samples: Position in samples
        """
        self.position_samples = time_samples

    def set_tempo(self, tempo_bpm: float) -> None:
        """Set tempo.

        Args:
            tempo_bpm: Tempo in BPM
        """
        self.tempo_bpm = tempo_bpm

    def add_tempo_change(self, time_samples: int, tempo_bpm: float) -> None:
        """Schedule tempo change.

        Args:
            time_samples: Time of change in samples
            tempo_bpm: New tempo
        """
        self.tempo_changes.append((time_samples, tempo_bpm))
        self.tempo_changes.sort(key=lambda x: x[0])

    def schedule_event(self, event: TimelineEvent) -> None:
        """Schedule event on timeline.

        Args:
            event: Event to schedule
        """
        self.events.append(event)
        self.events.sort(key=lambda x: x.time_samples)

    def process(self, num_samples: int) -> list[TimelineEvent]:
        """Process transport and return due events.

        Args:
            num_samples: Number of samples to process

        Returns:
            List of events due in this frame
        """
        due_events = []

        if self.playing:
            # Find events in current frame
            frame_end = self.position_samples + num_samples

            for event in self.events:
                if self.position_samples <= event.time_samples < frame_end:
                    due_events.append(event)
                    if event.event_type in self._event_callbacks:
                        self._event_callbacks[event.event_type](event)

            # Check tempo changes
            for time, new_tempo in self.tempo_changes:
                if self.position_samples <= time < frame_end:
                    self.tempo_bpm = new_tempo

            self.position_samples += num_samples

        return due_events

    def register_callback(self, event_type: str, callback: Callable) -> None:
        """Register event callback.

        Args:
            event_type: Type of event
            callback: Function to call when event occurs
        """
        self._event_callbacks[event_type] = callback

    @property
    def position_seconds(self) -> float:
        """Current position in seconds."""
        return self.position_samples / self.sample_rate

    @property
    def position_beats(self) -> float:
        """Current position in beats."""
        return self.position_seconds * self.tempo_bpm / 60.0


class Quantizer:
    """Snap notes and events to a grid.

    Attributes:
        grid_size: Grid size in beats (e.g., 0.25 for 16th notes)
        swing: Swing amount (0.0-1.0)
    """

    def __init__(self, grid_size: float = 0.25, swing: float = 0.0) -> None:
        """Initialize quantizer.

        Args:
            grid_size: Grid size in beats
            swing: Swing amount (0.0-1.0)
        """
        self.grid_size = grid_size
        self.swing = swing

    def quantize_beat(self, beat: float) -> float:
        """Quantize beat to grid.

        Args:
            beat: Beat position

        Returns:
            Quantized beat position
        """
        quantized = round(beat / self.grid_size) * self.grid_size

        # Apply swing to odd-numbered grid positions
        grid_pos = beat / self.grid_size
        if int(grid_pos) % 2 == 1:  # Odd position
            quantized += self.grid_size * self.swing * 0.5

        return quantized

    def quantize_note(self, note: Note) -> Note:
        """Quantize note timing.

        Args:
            note: Note to quantize

        Returns:
            Quantized note
        """
        quantized_start = self.quantize_beat(note.start_time)
        quantized_duration = round(note.duration / self.grid_size) * self.grid_size

        return Note(
            pitch=note.pitch,
            velocity=note.velocity,
            start_time=quantized_start,
            duration=max(self.grid_size, quantized_duration),
        )


class LoopRecorder:
    """Record audio into looped pattern.

    Attributes:
        loop_length_samples: Length of loop in samples
        num_tracks: Number of parallel tracks
    """

    def __init__(self, loop_length_samples: int, num_tracks: int = 4) -> None:
        """Initialize loop recorder.

        Args:
            loop_length_samples: Loop length in samples
            num_tracks: Number of tracks
        """
        self.loop_length_samples = loop_length_samples
        self.num_tracks = num_tracks
        self.tracks: list[NDArray[np.float32]] = [
            np.zeros(loop_length_samples, dtype=np.float32) for _ in range(num_tracks)
        ]
        self.position = 0
        self.recording_track = 0

    def record(self, samples: NDArray[np.float32]) -> None:
        """Record samples to current track.

        Args:
            samples: Audio samples to record
        """
        num_samples = len(samples)

        # Handle wrap-around
        remaining = self.loop_length_samples - self.position

        if num_samples <= remaining:
            self.tracks[self.recording_track][self.position : self.position + num_samples] = samples
        else:
            # Split across loop boundary
            self.tracks[self.recording_track][self.position :] = samples[:remaining]
            self.tracks[self.recording_track][: num_samples - remaining] = samples[remaining:]

        self.position = (self.position + num_samples) % self.loop_length_samples

    def playback(self) -> NDArray[np.float32]:
        """Get mixed playback of all tracks.

        Returns:
            Mixed audio samples
        """
        output = np.zeros(self.loop_length_samples, dtype=np.float32)
        for track in self.tracks:
            output += track
        return output

    def clear_track(self, track_index: int) -> None:
        """Clear a track.

        Args:
            track_index: Track to clear
        """
        if 0 <= track_index < len(self.tracks):
            self.tracks[track_index].fill(0.0)

    def set_recording_track(self, track_index: int) -> None:
        """Set which track is being recorded to.

        Args:
            track_index: Track index
        """
        if 0 <= track_index < len(self.tracks):
            self.recording_track = track_index
