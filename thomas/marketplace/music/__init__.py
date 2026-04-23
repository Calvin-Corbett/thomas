"""Thomas Music Module - Music theory, composition, and MIDI processing engine.

A comprehensive library for:
  - Music theory (intervals, scales, keys, frequencies)
  - Chord construction and analysis
  - Harmony and voice leading
  - Rhythm and time signatures
  - Melody generation and analysis
  - MIDI file reading/writing
  - Arrangement and orchestration
  - Music notation (ABC, MusicXML, LilyPond)
"""

from thomas.marketplace.music import analysis, arrangement, chords, harmony, melody, midi, notation, rhythm, theory
from thomas.marketplace.music._exceptions import (
    InvalidChordError,
    InvalidIntervalError,
    InvalidNoteError,
    InvalidScaleError,
    InvalidTimeSignatureError,
    MidiError,
    MusicError,
)
from thomas.marketplace.music._types import (
    Accidental,
    Articulation,
    Chord,
    Clef,
    Duration,
    Dynamics,
    Interval,
    Key,
    Measure,
    MidiEvent,
    MidiTrack,
    Note,
    Part,
    Pitch,
    Rest,
    Scale,
    Score,
    Tempo,
    TimeSignature,
    Voice,
)

__all__ = [
    "Note",
    "Pitch",
    "Interval",
    "Scale",
    "Chord",
    "Key",
    "TimeSignature",
    "Tempo",
    "Duration",
    "Rest",
    "Measure",
    "Voice",
    "Part",
    "Score",
    "MidiEvent",
    "MidiTrack",
    "Dynamics",
    "Articulation",
    "Clef",
    "Accidental",
    "MusicError",
    "InvalidNoteError",
    "InvalidIntervalError",
    "InvalidScaleError",
    "InvalidChordError",
    "InvalidTimeSignatureError",
    "MidiError",
    "theory",
    "chords",
    "harmony",
    "rhythm",
    "melody",
    "midi",
    "arrangement",
    "analysis",
    "notation",
]

__version__ = "0.1.0"
