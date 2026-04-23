"""Tests for music.midi module."""

import os
import tempfile

import pytest

from thomas.marketplace.music import midi
from thomas.marketplace.music._types import MidiEvent, MidiTrack, Tempo


class TestVariableIntegerEncoding:
    """Test MIDI variable-length integer encoding."""

    def test_encode_varint_zero(self) -> None:
        """Test encoding zero."""
        result = midi.encode_varint(0)
        assert result == b"\x00"

    def test_encode_varint_one(self) -> None:
        """Test encoding one."""
        result = midi.encode_varint(1)
        assert result == b"\x01"

    def test_encode_varint_127(self) -> None:
        """Test encoding 127 (max single byte)."""
        result = midi.encode_varint(127)
        assert result == b"\x7f"

    def test_encode_varint_128(self) -> None:
        """Test encoding 128 (needs two bytes)."""
        result = midi.encode_varint(128)
        assert result == b"\x81\x00"

    def test_encode_varint_large(self) -> None:
        """Test encoding large value."""
        result = midi.encode_varint(0x1FFFFF)
        assert len(result) == 3

    def test_encode_varint_roundtrip(self) -> None:
        """Test encode/decode roundtrip."""
        import io

        original = 12345

        encoded = midi.encode_varint(original)
        stream = io.BytesIO(encoded)

        decoded, _ = midi.decode_varint(stream)

        assert decoded == original


class TestMidiFileIO:
    """Test MIDI file reading/writing."""

    def test_create_midi_file(self) -> None:
        """Test creating a MIDI file."""
        midi_file = midi.MidiFile()

        assert midi_file.format == 0
        assert midi_file.ticks_per_beat == 480
        assert len(midi_file.tracks) == 0

    def test_add_track_to_file(self) -> None:
        """Test adding track to MIDI file."""
        midi_file = midi.MidiFile()
        track = MidiTrack("Test Track")

        midi_file.add_track(track)

        assert len(midi_file.tracks) == 1
        assert midi_file.tracks[0].name == "Test Track"

    def test_write_and_read_midi_file(self) -> None:
        """Test writing and reading MIDI file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.mid")

            midi_file = midi.MidiFile()
            track = MidiTrack("Test Track")

            event1 = MidiEvent(0, "note_on", 0, (60, 100))
            event2 = MidiEvent(480, "note_off", 0, (60, 0))

            track.add_event(event1)
            track.add_event(event2)

            midi_file.add_track(track)
            midi_file.write(filepath)

            assert os.path.exists(filepath)
            assert os.path.getsize(filepath) > 0

            loaded_file = midi.MidiFile.read(filepath)

            assert len(loaded_file.tracks) == 1
            assert loaded_file.tracks[0].name == "Test Track"

    def test_program_change_event(self) -> None:
        """Test MIDI program change event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "program_change.mid")

            midi_file = midi.MidiFile()
            track = MidiTrack("Test", program=5)

            event = MidiEvent(0, "program_change", 0, (5,))
            track.add_event(event)

            midi_file.add_track(track)
            midi_file.write(filepath)

            loaded_file = midi.MidiFile.read(filepath)

            assert len(loaded_file.tracks) > 0


class TestMidiEventProcessing:
    """Test MIDI event processing."""

    def test_delta_ticks_to_seconds(self) -> None:
        """Test converting delta ticks to seconds."""
        tempo = Tempo(120)
        ticks_per_beat = 480

        seconds = midi.delta_ticks_to_seconds(480, ticks_per_beat, tempo)

        assert abs(seconds - 0.5) < 0.01

    def test_seconds_to_delta_ticks(self) -> None:
        """Test converting seconds to delta ticks."""
        tempo = Tempo(120)
        ticks_per_beat = 480

        ticks = midi.seconds_to_delta_ticks(0.5, ticks_per_beat, tempo)

        assert ticks == 480

    def test_delta_ticks_to_seconds_faster_tempo(self) -> None:
        """Test timing with faster tempo."""
        tempo = Tempo(240)
        ticks_per_beat = 480

        seconds = midi.delta_ticks_to_seconds(480, ticks_per_beat, tempo)

        assert abs(seconds - 0.25) < 0.01


class TestMidiQuantization:
    """Test MIDI quantization."""

    def test_quantize_to_sixteenth(self) -> None:
        """Test quantizing events to sixteenth notes."""
        events = [
            MidiEvent(10, "note_on", 0, (60, 100)),
            MidiEvent(490, "note_off", 0, (60, 0)),
        ]

        quantized = midi.quantize_midi_events(events, 480, "sixteenth")

        assert len(quantized) == 2
        assert quantized[0].delta_time == 0
        assert quantized[1].delta_time == 480

    def test_quantize_to_quarter(self) -> None:
        """Test quantizing to quarter notes."""
        events = [
            MidiEvent(119, "note_on", 0, (60, 100)),
            MidiEvent(600, "note_off", 0, (60, 0)),
        ]

        quantized = midi.quantize_midi_events(events, 480, "quarter")

        assert quantized[0].delta_time == 0
        assert quantized[1].delta_time == 480


class TestMidiTransposition:
    """Test MIDI transposition."""

    def test_transpose_notes_up(self) -> None:
        """Test transposing notes up."""
        events = [
            MidiEvent(0, "note_on", 0, (60, 100)),
            MidiEvent(480, "note_off", 0, (60, 0)),
        ]

        transposed = midi.transpose_midi_notes(events, 2)

        assert transposed[0].data == (62, 100)
        assert transposed[1].data == (62, 0)

    def test_transpose_notes_down(self) -> None:
        """Test transposing notes down."""
        events = [
            MidiEvent(0, "note_on", 0, (64, 100)),
            MidiEvent(480, "note_off", 0, (64, 0)),
        ]

        transposed = midi.transpose_midi_notes(events, -2)

        assert transposed[0].data == (62, 100)

    def test_transpose_out_of_range(self) -> None:
        """Test transposition out of MIDI range raises error."""
        events = [MidiEvent(0, "note_on", 0, (120, 100))]

        with pytest.raises(Exception):
            midi.transpose_midi_notes(events, 20)


class TestMidiVelocity:
    """Test MIDI velocity operations."""

    def test_apply_velocity_curve_exponential(self) -> None:
        """Test applying exponential velocity curve."""
        events = [
            MidiEvent(0, "note_on", 0, (60, 64)),
            MidiEvent(480, "note_off", 0, (60, 0)),
        ]

        curved = midi.apply_velocity_curve(events, "exponential")

        assert curved[0].event_type == "note_on"
        assert curved[0].data[1] < 64

    def test_velocity_curve_preserves_non_note_events(self) -> None:
        """Test that velocity curve preserves non-note events."""
        events = [
            MidiEvent(0, "program_change", 0, (5,)),
            MidiEvent(480, "note_on", 0, (60, 100)),
        ]

        curved = midi.apply_velocity_curve(events, "exponential")

        assert curved[0].event_type == "program_change"
        assert curved[0].data == (5,)
