"""MIDI processing - file I/O, event parsing, quantization, transposition."""

from __future__ import annotations

import io
import struct
from typing import BinaryIO

from thomas.music._exceptions import MidiError, MidiFileError
from thomas.music._types import MidiEvent, MidiTrack, Tempo

# ============================================================================
# MIDI Constants
# ============================================================================

MIDI_FILE_HEADER = b"MThd"
MIDI_TRACK_HEADER = b"MTrk"

META_EVENT_SEQUENCE_NUMBER = 0x00
META_EVENT_TEXT = 0x01
META_EVENT_COPYRIGHT = 0x02
META_EVENT_SEQUENCE_NAME = 0x03
META_EVENT_INSTRUMENT_NAME = 0x04
META_EVENT_LYRIC = 0x05
META_EVENT_MARKER = 0x06
META_EVENT_CUE_POINT = 0x07
META_EVENT_CHANNEL_PREFIX = 0x20
META_EVENT_TRACK_END = 0x2F
META_EVENT_SET_TEMPO = 0x51
META_EVENT_SMPTE_OFFSET = 0x54
META_EVENT_TIME_SIGNATURE = 0x58
META_EVENT_KEY_SIGNATURE = 0x59
META_EVENT_SEQUENCER_SPECIFIC = 0x7F

MIDI_NOTE_OFF = 0x80
MIDI_NOTE_ON = 0x90
MIDI_POLYPHONIC_KEY_PRESSURE = 0xA0
MIDI_CONTROL_CHANGE = 0xB0
MIDI_PROGRAM_CHANGE = 0xC0
MIDI_CHANNEL_KEY_PRESSURE = 0xD0
MIDI_PITCH_BEND = 0xE0


# ============================================================================
# Variable-Length Quantity
# ============================================================================


def encode_varint(value: int) -> bytes:
    """Encode integer as MIDI variable-length quantity.

    Args:
        value: Integer to encode.

    Returns:
        Variable-length bytes.
    """
    if value == 0:
        return b"\x00"

    bytes_list: list[int] = []

    while value > 0:
        bytes_list.insert(0, value & 0x7F)
        value >>= 7

    for i in range(len(bytes_list) - 1):
        bytes_list[i] |= 0x80

    return bytes(bytes_list)


def decode_varint(data: BinaryIO) -> tuple[int, int]:
    """Decode MIDI variable-length quantity.

    Args:
        data: Binary stream.

    Returns:
        Tuple of (value, bytes_read).
    """
    value = 0
    bytes_read = 0

    while True:
        byte_data = data.read(1)
        if not byte_data:
            break

        byte = byte_data[0]
        bytes_read += 1

        value = (value << 7) | (byte & 0x7F)

        if (byte & 0x80) == 0:
            break

    return (value, bytes_read)


# ============================================================================
# MIDI File I/O
# ============================================================================


class MidiFile:
    """Represents a MIDI file (format 0 or 1)."""

    def __init__(self, format: int = 0, ticks_per_beat: int = 480):
        """Initialize MIDI file.

        Args:
            format: MIDI format (0 or 1).
            ticks_per_beat: Ticks per beat (timing resolution).
        """
        self.format = format
        self.ticks_per_beat = ticks_per_beat
        self.tracks: list[MidiTrack] = []

    def add_track(self, track: MidiTrack) -> None:
        """Add a track to the file.

        Args:
            track: MidiTrack to add.
        """
        self.tracks.append(track)

    def write(self, filename: str) -> None:
        """Write MIDI file to disk.

        Args:
            filename: Output filename.

        Raises:
            MidiFileError: If write fails.
        """
        try:
            with open(filename, "wb") as f:
                self._write_header(f)

                for track in self.tracks:
                    self._write_track(f, track)
        except OSError as e:
            raise MidiFileError(f"Failed to write MIDI file: {e}")

    def _write_header(self, f: BinaryIO) -> None:
        """Write MIDI header chunk.

        Args:
            f: Output stream.
        """
        num_tracks = len(self.tracks)

        header_data = struct.pack(">HHH", self.format, num_tracks, self.ticks_per_beat)

        f.write(MIDI_FILE_HEADER)
        f.write(struct.pack(">I", 6))
        f.write(header_data)

    def _write_track(self, f: BinaryIO, track: MidiTrack) -> None:
        """Write a MIDI track chunk.

        Args:
            f: Output stream.
            track: Track to write.
        """
        track_data = io.BytesIO()

        current_time = 0

        if track.name:
            name_bytes = track.name.encode("utf-8")
            track_data.write(encode_varint(0))
            track_data.write(bytes([0xFF, META_EVENT_SEQUENCE_NAME]))
            track_data.write(encode_varint(len(name_bytes)))
            track_data.write(name_bytes)

        for event in track.events:
            delta_time = event.delta_time - current_time
            track_data.write(encode_varint(delta_time))

            current_time += delta_time

            if event.event_type == "note_on":
                status = MIDI_NOTE_ON | event.channel
                note, velocity = event.data
                track_data.write(bytes([status, note, velocity]))

            elif event.event_type == "note_off":
                status = MIDI_NOTE_OFF | event.channel
                note, velocity = event.data
                track_data.write(bytes([status, note, velocity]))

            elif event.event_type == "program_change":
                status = MIDI_PROGRAM_CHANGE | event.channel
                program = event.data[0]
                track_data.write(bytes([status, program]))

            elif event.event_type == "control_change":
                status = MIDI_CONTROL_CHANGE | event.channel
                controller, value = event.data
                track_data.write(bytes([status, controller, value]))

            elif event.event_type == "pitch_bend":
                status = MIDI_PITCH_BEND | event.channel
                lsb, msb = event.data
                track_data.write(bytes([status, lsb, msb]))

            elif event.event_type == "meta_tempo":
                track_data.write(b"\xff\x51\x03")
                tempo_us = event.data[0]
                track_data.write(struct.pack(">I", tempo_us)[1:])

            elif event.event_type == "meta_end_of_track":
                track_data.write(b"\xff\x2f\x00")

        track_data.write(b"\xff\x2f\x00")

        track_data_bytes = track_data.getvalue()

        f.write(MIDI_TRACK_HEADER)
        f.write(struct.pack(">I", len(track_data_bytes)))
        f.write(track_data_bytes)

    @staticmethod
    def read(filename: str) -> MidiFile:
        """Read MIDI file from disk.

        Args:
            filename: Input filename.

        Returns:
            MidiFile object.

        Raises:
            MidiFileError: If read fails.
        """
        try:
            with open(filename, "rb") as f:
                return MidiFile._read_file(f)
        except OSError as e:
            raise MidiFileError(f"Failed to read MIDI file: {e}")

    @staticmethod
    def _read_file(f: BinaryIO) -> MidiFile:
        """Read MIDI file from stream.

        Args:
            f: Input stream.

        Returns:
            MidiFile object.
        """
        header = f.read(4)
        if header != MIDI_FILE_HEADER:
            raise MidiFileError("Invalid MIDI file header")

        header_length = struct.unpack(">I", f.read(4))[0]
        header_data = f.read(header_length)

        fmt, num_tracks, ticks_per_beat = struct.unpack(">HHH", header_data)

        midi_file = MidiFile(fmt, ticks_per_beat)

        for _ in range(num_tracks):
            track_header = f.read(4)
            if track_header != MIDI_TRACK_HEADER:
                raise MidiFileError("Invalid track header")

            track_length = struct.unpack(">I", f.read(4))[0]
            track_data = io.BytesIO(f.read(track_length))

            track = MidiFile._read_track(track_data, ticks_per_beat)
            midi_file.add_track(track)

        return midi_file

    @staticmethod
    def _read_track(f: BinaryIO, ticks_per_beat: int) -> MidiTrack:
        """Read a MIDI track from stream.

        Args:
            f: Input stream.
            ticks_per_beat: Ticks per beat resolution.

        Returns:
            MidiTrack object.
        """
        track = MidiTrack()
        current_time = 0
        running_status = 0

        while True:
            delta_time, _ = decode_varint(f)
            current_time += delta_time

            status_byte_data = f.read(1)
            if not status_byte_data:
                break

            status_byte = status_byte_data[0]

            if status_byte == 0xFF:
                meta_type = int.from_bytes(f.read(1), "big")
                meta_length, _ = decode_varint(f)
                meta_data = f.read(meta_length)

                if meta_type == META_EVENT_TRACK_END:
                    break
                if meta_type == META_EVENT_SEQUENCE_NAME:
                    track.name = meta_data.decode("utf-8", errors="replace")

                running_status = 0

            elif status_byte & 0x80:
                running_status = status_byte
                channel = status_byte & 0x0F
                event_type = status_byte & 0xF0

                if event_type in [MIDI_NOTE_ON, MIDI_NOTE_OFF]:
                    note = int.from_bytes(f.read(1), "big")
                    velocity = int.from_bytes(f.read(1), "big")

                    if event_type == MIDI_NOTE_ON and velocity > 0:
                        evt_type = "note_on"
                    else:
                        evt_type = "note_off"

                    event = MidiEvent(current_time, evt_type, channel, (note, velocity))
                    track.add_event(event)

                elif event_type == MIDI_PROGRAM_CHANGE:
                    program = int.from_bytes(f.read(1), "big")
                    event = MidiEvent(current_time, "program_change", channel, (program,))
                    track.add_event(event)

                elif event_type == MIDI_CONTROL_CHANGE:
                    controller = int.from_bytes(f.read(1), "big")
                    value = int.from_bytes(f.read(1), "big")
                    event = MidiEvent(current_time, "control_change", channel, (controller, value))
                    track.add_event(event)

        return track


# ============================================================================
# MIDI Event Processing
# ============================================================================


def delta_ticks_to_seconds(delta_ticks: int, ticks_per_beat: int, tempo: Tempo) -> float:
    """Convert delta ticks to seconds.

    Args:
        delta_ticks: Time in ticks.
        ticks_per_beat: Ticks per quarter note.
        tempo: Current tempo.

    Returns:
        Time in seconds.
    """
    quarter_notes = delta_ticks / ticks_per_beat
    return quarter_notes * tempo.seconds_per_quarter_note()


def seconds_to_delta_ticks(seconds: float, ticks_per_beat: int, tempo: Tempo) -> int:
    """Convert seconds to delta ticks.

    Args:
        seconds: Time in seconds.
        ticks_per_beat: Ticks per quarter note.
        tempo: Current tempo.

    Returns:
        Time in ticks.
    """
    quarter_notes = seconds / tempo.seconds_per_quarter_note()
    return int(quarter_notes * ticks_per_beat)


# ============================================================================
# MIDI Quantization
# ============================================================================


def quantize_midi_events(
    events: list[MidiEvent], ticks_per_beat: int, quantize_to: str = "sixteenth"
) -> list[MidiEvent]:
    """Quantize MIDI events to a grid.

    Args:
        events: List of MIDI events.
        ticks_per_beat: Ticks per beat.
        quantize_to: Grid level ('quarter', 'eighth', 'sixteenth', 'triplet').

    Returns:
        Quantized events.
    """
    grid_map = {
        "quarter": ticks_per_beat,
        "eighth": ticks_per_beat // 2,
        "sixteenth": ticks_per_beat // 4,
        "triplet": ticks_per_beat // 3,
    }

    grid_size = grid_map.get(quantize_to, ticks_per_beat // 4)

    quantized: list[MidiEvent] = []

    for event in events:
        quantized_time = round(event.delta_time / grid_size) * grid_size

        new_event = MidiEvent(quantized_time, event.event_type, event.channel, event.data)
        quantized.append(new_event)

    return quantized


# ============================================================================
# MIDI Transposition
# ============================================================================


def transpose_midi_notes(events: list[MidiEvent], semitones: int) -> list[MidiEvent]:
    """Transpose all notes in MIDI events.

    Args:
        events: List of MIDI events.
        semitones: Semitones to transpose (positive = up, negative = down).

    Returns:
        Transposed events.

    Raises:
        MidiError: If transposition goes out of range.
    """
    transposed: list[MidiEvent] = []

    for event in events:
        if event.event_type in ["note_on", "note_off"]:
            note, velocity = event.data
            new_note = note + semitones

            if not (0 <= new_note <= 127):
                raise MidiError(f"Transposed note {new_note} out of MIDI range")

            new_event = MidiEvent(event.delta_time, event.event_type, event.channel, (new_note, velocity))
            transposed.append(new_event)
        else:
            transposed.append(event)

    return transposed


# ============================================================================
# MIDI Velocity
# ============================================================================


def apply_velocity_curve(events: list[MidiEvent], curve_type: str = "exponential") -> list[MidiEvent]:
    """Apply velocity curve to MIDI events.

    Args:
        events: List of MIDI events.
        curve_type: Type of curve ('linear', 'exponential', 'logarithmic').

    Returns:
        Events with modified velocities.
    """
    curved: list[MidiEvent] = []

    for event in events:
        if event.event_type == "note_on":
            note, velocity = event.data

            if curve_type == "exponential":
                normalized = velocity / 127.0
                new_velocity = int((normalized**2) * 127)
            elif curve_type == "logarithmic":
                normalized = velocity / 127.0
                import math

                new_velocity = int(math.log(normalized + 1) / math.log(2) * 127)
            else:
                new_velocity = velocity

            new_event = MidiEvent(event.delta_time, event.event_type, event.channel, (note, new_velocity))
            curved.append(new_event)
        else:
            curved.append(event)

    return curved
