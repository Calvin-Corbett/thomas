"""
Exception classes for the audio engine.
"""


class AudioEngineError(Exception):
    """Base exception for audio engine errors."""

    pass


class InvalidAudioFormatError(AudioEngineError):
    """Raised when audio format is invalid."""

    pass


class BufferOverflowError(AudioEngineError):
    """Raised when buffer overflow occurs."""

    pass


class BufferUnderflowError(AudioEngineError):
    """Raised when buffer underflow occurs."""

    pass


class EffectChainError(AudioEngineError):
    """Raised when effect chain operation fails."""

    pass


class FilterError(AudioEngineError):
    """Raised when filter operation fails."""

    pass


class SynthesisError(AudioEngineError):
    """Raised when synthesis operation fails."""

    pass


class CodecError(AudioEngineError):
    """Raised when codec operation fails."""

    pass


class MixerError(AudioEngineError):
    """Raised when mixer operation fails."""

    pass


class AnalysisError(AudioEngineError):
    """Raised when analysis operation fails."""

    pass


class SpatialError(AudioEngineError):
    """Raised when spatial audio operation fails."""

    pass


class SequencerError(AudioEngineError):
    """Raised when sequencer operation fails."""

    pass


class SampleRateError(AudioEngineError):
    """Raised when sample rate is incompatible."""

    pass


class ChannelCountError(AudioEngineError):
    """Raised when channel count is incompatible."""

    pass
