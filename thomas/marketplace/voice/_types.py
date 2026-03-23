"""
Core type definitions for voice processing module.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class PhonemeType(Enum):
    """Classification of phoneme types."""

    VOWEL = "vowel"
    CONSONANT = "consonant"


class PlaceOfArticulation(Enum):
    """Place of articulation for consonants."""

    BILABIAL = "bilabial"
    LABIODENTAL = "labiodental"
    DENTAL = "dental"
    ALVEOLAR = "alveolar"
    POSTALVEOLAR = "postalveolar"
    RETROFLEX = "retroflex"
    PALATAL = "palatal"
    VELAR = "velar"
    GLOTTAL = "glottal"
    LABIALVELAR = "labialvelar"


class MannerOfArticulation(Enum):
    """Manner of articulation for consonants."""

    STOP = "stop"
    AFFRICATE = "affricate"
    FRICATIVE = "fricative"
    APPROXIMANT = "approximant"
    TAP = "tap"
    TRILL = "trill"
    NASAL = "nasal"


class VowelHeight(Enum):
    """Height classification for vowels."""

    CLOSE = "close"
    NEAR_CLOSE = "near_close"
    CLOSE_MID = "close_mid"
    MID = "mid"
    OPEN_MID = "open_mid"
    NEAR_OPEN = "near_open"
    OPEN = "open"


class VowelFrontness(Enum):
    """Frontness classification for vowels."""

    FRONT = "front"
    NEAR_FRONT = "near_front"
    CENTRAL = "central"
    NEAR_BACK = "near_back"
    BACK = "back"


class EmotionLabel(Enum):
    """Basic emotion categories (Ekman)."""

    NEUTRAL = "neutral"
    HAPPINESS = "happiness"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"


class StressLevel(Enum):
    """Lexical stress levels."""

    PRIMARY = 1
    SECONDARY = 2
    UNSTRESSED = 0


@dataclass
class AudioSample:
    """Represents a raw audio sample."""

    data: np.ndarray
    """Audio data (1D array of samples)."""
    sample_rate: int
    """Sample rate in Hz (e.g., 16000)."""
    duration: float = field(init=False)
    """Duration in seconds."""

    def __post_init__(self) -> None:
        """Calculate duration from data and sample rate."""
        self.duration = len(self.data) / self.sample_rate

    def get_time_axis(self) -> np.ndarray:
        """Get time axis for the audio in seconds."""
        return np.arange(len(self.data)) / self.sample_rate


@dataclass
class SpeechFrame:
    """Represents a single frame of speech."""

    frame_data: np.ndarray
    """Frame audio samples."""
    frame_index: int
    """Frame index in the utterance."""
    timestamp: float
    """Frame center time in seconds."""
    duration: float
    """Frame duration in seconds."""
    sample_rate: int
    """Sample rate in Hz."""

    def get_power(self) -> float:
        """Calculate frame power (energy)."""
        return float(np.mean(self.frame_data**2))


@dataclass
class Phoneme:
    """Represents a phoneme with phonetic properties."""

    arpabet: str
    """ARPAbet representation (e.g., 'AA', 'AE')."""
    phoneme_type: PhonemeType
    """Type: vowel or consonant."""
    start_time: float
    """Start time in seconds."""
    end_time: float
    """End time in seconds."""
    place_of_articulation: PlaceOfArticulation | None = None
    """Place of articulation (for consonants)."""
    manner_of_articulation: MannerOfArticulation | None = None
    """Manner of articulation (for consonants)."""
    vowel_height: VowelHeight | None = None
    """Vowel height (for vowels)."""
    vowel_frontness: VowelFrontness | None = None
    """Vowel frontness (for vowels)."""
    is_voiced: bool = True
    """Whether the phoneme is voiced."""
    confidence: float = 1.0
    """Confidence score [0, 1]."""

    @property
    def duration(self) -> float:
        """Duration of the phoneme in seconds."""
        return self.end_time - self.start_time


@dataclass
class Word:
    """Represents a word with its phonetic breakdown."""

    text: str
    """Word text."""
    phonemes: list[Phoneme]
    """List of phonemes in the word."""
    start_time: float
    """Start time in seconds."""
    end_time: float
    """End time in seconds."""
    stress_pattern: list[StressLevel] = field(default_factory=list)
    """Stress levels for each syllable."""
    confidence: float = 1.0
    """Confidence score [0, 1]."""

    @property
    def duration(self) -> float:
        """Duration of the word in seconds."""
        return self.end_time - self.start_time


@dataclass
class Utterance:
    """Represents a complete utterance (sentence/phrase)."""

    text: str
    """Utterance text."""
    words: list[Word]
    """List of words in the utterance."""
    start_time: float
    """Start time in seconds."""
    end_time: float
    """End time in seconds."""
    speaker_id: str | None = None
    """Speaker identifier if known."""
    confidence: float = 1.0
    """Confidence score [0, 1]."""

    @property
    def duration(self) -> float:
        """Duration of the utterance in seconds."""
        return self.end_time - self.start_time

    @property
    def phonemes(self) -> list[Phoneme]:
        """Get all phonemes in the utterance."""
        return [ph for word in self.words for ph in word.phonemes]


@dataclass
class FormantFrequencies:
    """Represents formant frequencies in Hz."""

    f1: float
    """First formant frequency."""
    f2: float
    """Second formant frequency."""
    f3: float
    """Third formant frequency."""
    f4: float | None = None
    """Fourth formant frequency (optional)."""
    f5: float | None = None
    """Fifth formant frequency (optional)."""
    bandwidths: list[float] | None = None
    """Formant bandwidths in Hz."""
    timestamp: float = 0.0
    """Time in seconds."""

    def get_first_three(self) -> tuple[float, float, float]:
        """Get the first three formants as a tuple."""
        return (self.f1, self.f2, self.f3)


@dataclass
class MFCCFeatures:
    """Mel-Frequency Cepstral Coefficients."""

    coefficients: np.ndarray
    """MFCC coefficients (num_frames x num_coefficients)."""
    delta: np.ndarray | None = None
    """Delta coefficients (first derivative)."""
    delta_delta: np.ndarray | None = None
    """Delta-delta coefficients (second derivative)."""
    num_frames: int = field(init=False)
    """Number of frames."""
    num_coefficients: int = field(init=False)
    """Number of MFCC coefficients."""
    frame_rate: float = 100.0
    """Frame rate in Hz."""

    def __post_init__(self) -> None:
        """Initialize computed fields."""
        self.num_frames = self.coefficients.shape[0]
        self.num_coefficients = self.coefficients.shape[1]

    def get_frame(self, frame_idx: int) -> np.ndarray:
        """Get MFCC vector for a specific frame."""
        return self.coefficients[frame_idx]

    def get_mean_vector(self) -> np.ndarray:
        """Get mean MFCC vector across all frames."""
        return np.mean(self.coefficients, axis=0)

    def get_covariance_matrix(self) -> np.ndarray:
        """Get covariance matrix of MFCC features."""
        return np.cov(self.coefficients.T)


@dataclass
class PitchContour:
    """Represents pitch tracking over time."""

    frequency: np.ndarray
    """Pitch frequency in Hz for each frame."""
    timestamp: np.ndarray
    """Timestamp in seconds for each frame."""
    voicing: np.ndarray
    """Voicing probability for each frame [0, 1]."""
    confidence: np.ndarray | None = None
    """Confidence score for each pitch estimate."""

    @property
    def num_frames(self) -> int:
        """Number of frames."""
        return len(self.frequency)

    def get_voiced_frames(self, threshold: float = 0.5) -> np.ndarray:
        """Get indices of voiced frames."""
        return np.where(self.voicing > threshold)[0]

    def get_mean_pitch(self) -> float:
        """Get mean pitch of voiced frames."""
        voiced = self.get_voiced_frames()
        if len(voiced) == 0:
            return 0.0
        return float(np.mean(self.frequency[voiced]))

    def get_pitch_range(self) -> tuple[float, float]:
        """Get min and max pitch."""
        voiced = self.get_voiced_frames()
        if len(voiced) == 0:
            return (0.0, 0.0)
        return (float(np.min(self.frequency[voiced])), float(np.max(self.frequency[voiced])))


@dataclass
class ProsodicFeature:
    """Represents prosodic features at a time point."""

    timestamp: float
    """Time in seconds."""
    pitch: float | None = None
    """Pitch frequency in Hz."""
    energy: float | None = None
    """Frame energy (dB)."""
    duration: float | None = None
    """Duration of phoneme/word in seconds."""
    is_stressed: bool = False
    """Whether this segment is stressed."""
    intonation_type: str | None = None
    """Intonation pattern: 'rising', 'falling', 'rise-fall', etc."""


@dataclass
class VoiceActivitySegment:
    """Represents a speech activity segment."""

    start_time: float
    """Start time in seconds."""
    end_time: float
    """End time in seconds."""
    energy: float
    """Average energy in the segment."""
    confidence: float = 1.0
    """Confidence score [0, 1]."""

    @property
    def duration(self) -> float:
        """Duration of the segment in seconds."""
        return self.end_time - self.start_time


@dataclass
class SpeakerModel:
    """Represents a speaker model for verification/identification."""

    speaker_id: str
    """Unique speaker identifier."""
    mean_vector: np.ndarray
    """Mean MFCC feature vector."""
    covariance_matrix: np.ndarray
    """Covariance matrix of MFCC features."""
    num_utterances: int = 0
    """Number of utterances used in enrollment."""
    enrollment_date: str | None = None
    """Date of enrollment."""
    gmm_weights: np.ndarray | None = None
    """GMM component weights."""
    gmm_means: np.ndarray | None = None
    """GMM component means."""
    gmm_covariances: np.ndarray | None = None
    """GMM component covariances."""

    def get_feature_dimension(self) -> int:
        """Get the feature dimension."""
        return len(self.mean_vector)


@dataclass
class TranscriptionResult:
    """Represents a speech recognition result."""

    text: str
    """Recognized text."""
    confidence: float
    """Overall confidence score [0, 1]."""
    utterances: list[Utterance]
    """Utterance-level details."""
    n_best: list[tuple[str, float]] | None = None
    """N-best hypotheses (text, confidence)."""
    word_confidence: list[float] | None = None
    """Confidence for each word."""
    timing: list[tuple[str, float, float]] | None = None
    """Word timing (word, start, end)."""


@dataclass
class AlignmentResult:
    """Represents audio-text alignment."""

    phonemes: list[Phoneme]
    """Phonemes with aligned timestamps."""
    words: list[Word]
    """Words with aligned timestamps."""
    alignment_score: float
    """Quality of alignment [0, 1]."""
    dtw_cost: float = 0.0
    """DTW distance if applicable."""


@dataclass
class VoiceProfile:
    """Comprehensive voice profile for a speaker."""

    speaker_id: str
    """Speaker identifier."""
    speaker_model: SpeakerModel
    """Speaker model for recognition."""
    pitch_statistics: dict[str, float]
    """Pitch statistics (mean, range, jitter, etc.)."""
    formant_statistics: dict[str, Any]
    """Formant statistics."""
    voice_quality_metrics: dict[str, float]
    """Voice quality metrics (shimmer, HNR, etc.)."""
    speech_rate: float
    """Average speech rate in words/minute."""
    pronunciation_variants: dict[str, list[str]]
    """Known pronunciation variants."""
    accent_features: dict[str, float] | None = None
    """Accent-specific features."""
