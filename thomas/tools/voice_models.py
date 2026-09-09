"""Shared speech data and provider contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class VoiceException(Exception):
    """Base exception for voice operations."""

    pass


class VoiceProviderException(VoiceException):
    """Voice provider operation failed."""

    pass


class AudioFormatException(VoiceException):
    """Audio format not supported."""

    pass


class SilenceDetectedException(VoiceException):
    """Silence detected during audio capture."""

    pass


class WakeWordNotDetectedException(VoiceException):
    """Wake word not detected in audio."""

    pass


class AudioFormat(str, Enum):
    """Supported audio formats."""

    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"
    FLAC = "flac"


@dataclass
class AudioData:
    """Audio data with metadata."""

    data: bytes
    format: str
    sample_rate: int
    duration_ms: int
    language: str = ""


@dataclass
class VoiceSettings:
    """Voice chat settings."""

    language: str = "en-US"
    voice_name: str = "default"
    speech_rate: float = 1.0
    wake_word: str = "hey thomas"
    auto_listen: bool = True
    silence_timeout_ms: int = 1000


class STTProvider(ABC):
    """Abstract base class for speech-to-text providers."""

    @abstractmethod
    async def transcribe(self, audio: AudioData) -> str:
        """Transcribe audio to text.

        Args:
            audio: Audio data to transcribe

        Returns:
            Transcribed text

        Raises:
            VoiceProviderException: Transcription failed
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if provider is available and configured."""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get provider name."""
        pass


class TTSProvider(ABC):
    """Abstract base class for text-to-speech providers."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str = "default") -> AudioData:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize
            voice: Voice identifier

        Returns:
            Audio data

        Raises:
            VoiceProviderException: Synthesis failed
        """
        pass

    @abstractmethod
    async def list_voices(self) -> list[str]:
        """List available voices."""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if provider is available and configured."""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get provider name."""
        pass
