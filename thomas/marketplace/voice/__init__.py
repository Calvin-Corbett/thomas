"""
Thomas Voice Processing Engine

A comprehensive speech/voice processing module providing:
- Audio feature extraction (MFCC, formants, zero-crossing rate)
- Voice Activity Detection (VAD)
- Pitch detection and tracking
- Speaker recognition and identification
- Phonetics and phoneme analysis
- Prosody analysis and intonation modeling
- Speech synthesis (concatenative and formant-based)
- Speech recognition (template matching and HMM-based)
- Speech emotion recognition
"""

from thomas.marketplace.voice._exceptions import (
    AudioProcessingError,
    EmotionRecognitionError,
    FeatureExtractionError,
    PhoneticsError,
    PitchDetectionError,
    ProsodyError,
    RecognitionError,
    SpeakerError,
    SynthesisError,
    VADError,
    VoiceProcessingError,
)
from thomas.marketplace.voice._types import (
    AlignmentResult,
    AudioSample,
    EmotionLabel,
    FormantFrequencies,
    MFCCFeatures,
    Phoneme,
    PhonemeType,
    PitchContour,
    ProsodicFeature,
    SpeakerModel,
    SpeechFrame,
    TranscriptionResult,
    Utterance,
    VoiceActivitySegment,
    VoiceProfile,
    Word,
)

__all__ = [
    # Types
    "AudioSample",
    "SpeechFrame",
    "PhonemeType",
    "Phoneme",
    "Word",
    "Utterance",
    "VoiceProfile",
    "PitchContour",
    "FormantFrequencies",
    "MFCCFeatures",
    "SpeakerModel",
    "TranscriptionResult",
    "AlignmentResult",
    "EmotionLabel",
    "ProsodicFeature",
    "VoiceActivitySegment",
    # Exceptions
    "VoiceProcessingError",
    "AudioProcessingError",
    "FeatureExtractionError",
    "VADError",
    "PitchDetectionError",
    "SpeakerError",
    "PhoneticsError",
    "ProsodyError",
    "SynthesisError",
    "RecognitionError",
    "EmotionRecognitionError",
]

__version__ = "1.0.0"
