"""
Exception classes for voice processing module.
"""


class VoiceProcessingError(Exception):
    """Base exception for all voice processing errors."""

    pass


class AudioProcessingError(VoiceProcessingError):
    """Raised when audio processing fails."""

    pass


class FeatureExtractionError(VoiceProcessingError):
    """Raised when speech feature extraction fails."""

    pass


class VADError(VoiceProcessingError):
    """Raised when voice activity detection fails."""

    pass


class PitchDetectionError(VoiceProcessingError):
    """Raised when pitch detection fails."""

    pass


class SpeakerError(VoiceProcessingError):
    """Raised when speaker recognition fails."""

    pass


class PhoneticsError(VoiceProcessingError):
    """Raised when phonetics processing fails."""

    pass


class ProsodyError(VoiceProcessingError):
    """Raised when prosody analysis fails."""

    pass


class SynthesisError(VoiceProcessingError):
    """Raised when speech synthesis fails."""

    pass


class RecognitionError(VoiceProcessingError):
    """Raised when speech recognition fails."""

    pass


class EmotionRecognitionError(VoiceProcessingError):
    """Raised when emotion recognition fails."""

    pass
