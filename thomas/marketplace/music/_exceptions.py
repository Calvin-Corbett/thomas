"""Exception classes for the music module."""


class MusicError(Exception):
    """Base exception for all music module errors."""

    pass


class InvalidNoteError(MusicError):
    """Raised when an invalid note is created or used."""

    pass


class InvalidIntervalError(MusicError):
    """Raised when an invalid interval is created or calculated."""

    pass


class InvalidScaleError(MusicError):
    """Raised when an invalid scale is created or used."""

    pass


class InvalidChordError(MusicError):
    """Raised when an invalid chord is created or analyzed."""

    pass


class InvalidKeyError(MusicError):
    """Raised when an invalid key is specified."""

    pass


class InvalidTimeSignatureError(MusicError):
    """Raised when an invalid time signature is created."""

    pass


class InvalidTempoError(MusicError):
    """Raised when invalid tempo values are provided."""

    pass


class MidiError(MusicError):
    """Raised when MIDI processing fails."""

    pass


class MidiFileError(MidiError):
    """Raised when MIDI file reading/writing fails."""

    pass


class VoiceLeadingError(MusicError):
    """Raised when voice leading rules are violated."""

    pass


class NotationError(MusicError):
    """Raised when notation parsing/writing fails."""

    pass


class HarmonyError(MusicError):
    """Raised when harmony rules are violated."""

    pass


class RhythmError(MusicError):
    """Raised when rhythm processing fails."""

    pass
