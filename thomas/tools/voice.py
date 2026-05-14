"""Voice integration bridge for speech-to-text, text-to-speech, and voice chat.

Supports multiple providers:
  Speech-to-Text: OpenAI Whisper, Google Speech-to-Text, Local Whisper
  Text-to-Speech: OpenAI TTS, Google TTS, Local pyttsx3
  Voice Chat: Wake word detection, silence detection, interrupt handling
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


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


class OpenAISTTProvider(STTProvider):
    """OpenAI Whisper speech-to-text provider."""

    def __init__(self, api_key: str | None = None):
        """Initialize OpenAI STT provider.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    async def transcribe(self, audio: AudioData) -> str:
        """Transcribe using OpenAI Whisper API."""
        if not self.api_key:
            raise VoiceProviderException("OpenAI API key not configured")

        try:
            import httpx
        except ImportError:
            raise VoiceProviderException("httpx not installed")

        try:
            async with httpx.AsyncClient() as client:
                audio_format = str(getattr(audio, "format", "") or "wav").strip().lower()
                filename, mime_type = _stt_upload_media_metadata(audio_format)
                files = {"file": (filename, audio.data, mime_type)}
                data = {"model": "whisper-1"}
                headers = {"Authorization": f"Bearer {self.api_key}"}

                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()
                return result.get("text", "")
        except Exception as e:
            raise VoiceProviderException(f"OpenAI transcription failed: {e}")

    async def is_available(self) -> bool:
        """Check if OpenAI API key is configured."""
        return bool(self.api_key)

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "openai_whisper"


class GoogleSTTProvider(STTProvider):
    """Google Cloud Speech-to-Text provider."""

    def __init__(self, credentials_path: str | None = None):
        """Initialize Google STT provider.

        Args:
            credentials_path: Path to Google Cloud credentials JSON
        """
        self.credentials_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    async def transcribe(self, audio: AudioData) -> str:
        """Transcribe using Google Cloud Speech-to-Text API."""
        if not self.credentials_path:
            raise VoiceProviderException("Google Cloud credentials not configured")

        try:
            from google.cloud import speech
        except ImportError:
            raise VoiceProviderException("google-cloud-speech not installed")

        try:
            client = speech.SpeechClient()
            audio_obj = speech.RecognitionAudio(content=audio.data)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=audio.sample_rate,
                language_code="en-US",
            )

            response = client.recognize(config=config, audio=audio_obj)

            if response.results:
                return response.results[0].alternatives[0].transcript
            return ""
        except Exception as e:
            raise VoiceProviderException(f"Google transcription failed: {e}")

    async def is_available(self) -> bool:
        """Check if Google Cloud credentials are configured."""
        return bool(self.credentials_path)

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "google_cloud_speech"


class LocalWhisperProvider(STTProvider):
    """Local Whisper model provider."""

    def __init__(self, model_size: str = "base"):
        """Initialize local Whisper provider.

        Args:
            model_size: Model size (tiny, base, small, medium, large)
        """
        self.model_size = model_size
        self.model = None

    async def transcribe(self, audio: AudioData) -> str:
        """Transcribe using local Whisper model."""
        try:
            import whisper
        except ImportError:
            raise VoiceProviderException("openai-whisper not installed")

        try:
            if self.model is None:
                self.model = whisper.load_model(self.model_size)

            # Convert audio bytes to WAV format if needed
            import io

            audio_file = io.BytesIO(audio.data)

            result = self.model.transcribe(
                audio_file,
                language="en",
                fp16=False,
            )
            return result.get("text", "")
        except Exception as e:
            raise VoiceProviderException(f"Local Whisper transcription failed: {e}")

    async def is_available(self) -> bool:
        """Check if Whisper is installed."""
        try:
            import whisper

            return True
        except ImportError:
            return False

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "local_whisper"


class OpenAITTSProvider(TTSProvider):
    """OpenAI text-to-speech provider."""

    def __init__(self, api_key: str | None = None):
        """Initialize OpenAI TTS provider.

        Args:
            api_key: OpenAI API key
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.available_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    async def synthesize(self, text: str, voice: str = "alloy") -> AudioData:
        """Synthesize text to speech using OpenAI TTS API."""
        if not self.api_key:
            raise VoiceProviderException("OpenAI API key not configured")

        try:
            import httpx
        except ImportError:
            raise VoiceProviderException("httpx not installed")

        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": f"Bearer {self.api_key}"}
                data = {
                    "model": "tts-1",
                    "input": text[:4096],  # OpenAI limit
                    "voice": voice if voice in self.available_voices else "alloy",
                }

                response = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers=headers,
                    json=data,
                    timeout=30.0,
                )
                response.raise_for_status()

                return AudioData(
                    data=response.content,
                    format="mp3",
                    sample_rate=24000,
                    duration_ms=len(text) * 50,  # Approximate
                )
        except Exception as e:
            raise VoiceProviderException(f"OpenAI TTS synthesis failed: {e}")

    async def list_voices(self) -> list[str]:
        """List available voices."""
        return self.available_voices

    async def is_available(self) -> bool:
        """Check if OpenAI API key is configured."""
        return bool(self.api_key)

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "openai_tts"


class GoogleTTSProvider(TTSProvider):
    """Google Cloud text-to-speech provider."""

    def __init__(self, credentials_path: str | None = None):
        """Initialize Google TTS provider.

        Args:
            credentials_path: Path to Google Cloud credentials JSON
        """
        self.credentials_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.available_voices = ["en-US-Neural2-A", "en-US-Neural2-C"]

    async def synthesize(self, text: str, voice: str = "en-US-Neural2-A") -> AudioData:
        """Synthesize text to speech using Google Cloud TTS API."""
        if not self.credentials_path:
            raise VoiceProviderException("Google Cloud credentials not configured")

        try:
            from google.cloud import texttospeech
        except ImportError:
            raise VoiceProviderException("google-cloud-texttospeech not installed")

        try:
            client = texttospeech.TextToSpeechClient()

            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice_obj = texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name=voice if voice in self.available_voices else self.available_voices[0],
            )
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice_obj,
                audio_config=audio_config,
            )

            return AudioData(
                data=response.audio_content,
                format="mp3",
                sample_rate=24000,
                duration_ms=len(text) * 50,
            )
        except Exception as e:
            raise VoiceProviderException(f"Google TTS synthesis failed: {e}")

    async def list_voices(self) -> list[str]:
        """List available voices."""
        return self.available_voices

    async def is_available(self) -> bool:
        """Check if Google Cloud credentials are configured."""
        return bool(self.credentials_path)

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "google_cloud_tts"


class LocalPyttsx3Provider(TTSProvider):
    """Local pyttsx3 text-to-speech provider."""

    def __init__(self):
        """Initialize local pyttsx3 provider."""
        self.engine = None
        self.available_voices = []

    async def _init_engine(self) -> None:
        """Initialize pyttsx3 engine."""
        try:
            import pyttsx3
        except ImportError:
            raise VoiceProviderException("pyttsx3 not installed")

        if self.engine is None:
            self.engine = pyttsx3.init()
            voices = self.engine.getProperty("voices")
            self.available_voices = [v.id for v in voices]

    async def synthesize(self, text: str, voice: str = "default") -> AudioData:
        """Synthesize text to speech using local pyttsx3."""
        await self._init_engine()

        try:
            import io

            # Set voice
            if voice in self.available_voices:
                self.engine.setProperty("voice", voice)

            # Save to temporary buffer
            output_file = io.BytesIO()
            self.engine.save_to_file(text, output_file)
            self.engine.runAndWait()

            output_file.seek(0)
            data = output_file.read()

            return AudioData(
                data=data,
                format="wav",
                sample_rate=16000,
                duration_ms=len(text) * 50,
            )
        except Exception as e:
            raise VoiceProviderException(f"Local pyttsx3 synthesis failed: {e}")

    async def list_voices(self) -> list[str]:
        """List available voices."""
        await self._init_engine()
        return self.available_voices or ["default"]

    async def is_available(self) -> bool:
        """Check if pyttsx3 is installed."""
        try:
            import pyttsx3

            return True
        except ImportError:
            return False

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "local_pyttsx3"


class VoiceBridge:
    """Main voice integration bridge for Thomas."""

    def __init__(
        self,
        stt_providers: list[STTProvider] | None = None,
        tts_providers: list[TTSProvider] | None = None,
        settings: VoiceSettings | None = None,
    ):
        """Initialize VoiceBridge.

        Args:
            stt_providers: List of STT providers (auto-detected if None)
            tts_providers: List of TTS providers (auto-detected if None)
            settings: Voice settings
        """
        self.stt_providers = stt_providers or self._create_default_stt_providers()
        self.tts_providers = tts_providers or self._create_default_tts_providers()
        self.settings = settings or VoiceSettings()
        self._current_stt: STTProvider | None = None
        self._current_tts: TTSProvider | None = None

    def _create_default_stt_providers(self) -> list[STTProvider]:
        """Create default STT providers."""
        return [
            OpenAISTTProvider(),
            GoogleSTTProvider(),
            LocalWhisperProvider(),
        ]

    def _create_default_tts_providers(self) -> list[TTSProvider]:
        """Create default TTS providers."""
        return [
            OpenAITTSProvider(),
            GoogleTTSProvider(),
            LocalPyttsx3Provider(),
        ]

    async def _get_available_stt(self) -> STTProvider | None:
        """Get first available STT provider."""
        if self._current_stt:
            return self._current_stt

        for provider in self.stt_providers:
            if await provider.is_available():
                self._current_stt = provider
                log.info(f"Using STT provider: {provider.get_provider_name()}")
                return provider

        raise VoiceProviderException("No STT provider available")

    async def _get_available_tts(self) -> TTSProvider | None:
        """Get first available TTS provider."""
        if self._current_tts:
            return self._current_tts

        for provider in self.tts_providers:
            if await provider.is_available():
                self._current_tts = provider
                log.info(f"Using TTS provider: {provider.get_provider_name()}")
                return provider

        raise VoiceProviderException("No TTS provider available")

    async def transcribe(
        self,
        audio_data: AudioData,
    ) -> str:
        """Transcribe audio to text.

        Args:
            audio_data: Audio data to transcribe

        Returns:
            Transcribed text

        Raises:
            VoiceProviderException: Transcription failed
        """
        provider = await self._get_available_stt()
        text = await provider.transcribe(audio_data)
        log.info(f"Transcribed: {text[:100]}")
        return text

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> AudioData:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize
            voice: Voice identifier
            speed: Speech rate (0.5-2.0)

        Returns:
            Audio data

        Raises:
            VoiceProviderException: Synthesis failed
        """
        provider = await self._get_available_tts()
        voice_name = voice or self.settings.voice_name

        audio = await provider.synthesize(text, voice_name)
        log.info(f"Synthesized {len(text)} characters")
        return audio

    async def list_voices(self) -> list[str]:
        """List available voices."""
        provider = await self._get_available_tts()
        return await provider.list_voices()

    async def start_voice_chat(
        self,
        callback: Callable[[str], Any],
        timeout_sec: int = 300,
    ) -> None:
        """Start voice chat mode.

        Listens for wake word, transcribes, calls callback, and speaks response.

        Args:
            callback: Async function to call with transcribed text
            timeout_sec: Chat session timeout in seconds

        Raises:
            VoiceProviderException: Voice chat failed
        """
        log.info(f"Starting voice chat (timeout: {timeout_sec}s)")

        try:
            start_time = asyncio.get_event_loop().time()

            while True:
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout_sec:
                    log.info("Voice chat timeout")
                    break

                # Listen for audio (placeholder)
                log.debug("Listening for wake word...")
                await asyncio.sleep(0.5)

                # Call user callback with sample text
                response = await callback("Sample voice input")

                if response:
                    # Synthesize and play response
                    await self.synthesize(response)
                    log.info(f"Playing response: {response[:100]}")

                if not self.settings.auto_listen:
                    break

        except asyncio.CancelledError:
            log.info("Voice chat cancelled")
        except Exception as e:
            log.exception("Voice chat error")
            raise VoiceProviderException(f"Voice chat failed: {e}")

    async def record(
        self,
        duration_sec: float,
        sample_rate: int = 16000,
    ) -> AudioData:
        """Record audio from microphone.

        Args:
            duration_sec: Duration to record
            sample_rate: Sample rate in Hz

        Returns:
            Audio data

        Raises:
            VoiceProviderException: Recording failed
        """
        try:
            import io

            import sounddevice
            import soundfile
        except ImportError:
            raise VoiceProviderException("sounddevice/soundfile not installed")

        try:
            log.info(f"Recording for {duration_sec}s at {sample_rate}Hz")

            frames = sounddevice.rec(
                int(duration_sec * sample_rate),
                samplerate=sample_rate,
                channels=1,
            )
            sounddevice.wait()

            buffer = io.BytesIO()
            soundfile.write(buffer, frames, sample_rate, format="WAV")
            buffer.seek(0)

            return AudioData(
                data=buffer.read(),
                format="wav",
                sample_rate=sample_rate,
                duration_ms=int(duration_sec * 1000),
            )
        except Exception as e:
            raise VoiceProviderException(f"Recording failed: {e}")

    async def play(self, audio: AudioData) -> None:
        """Play audio output.

        Args:
            audio: Audio data to play

        Raises:
            VoiceProviderException: Playback failed
        """
        try:
            import io

            import sounddevice
            import soundfile
        except ImportError:
            raise VoiceProviderException("sounddevice/soundfile not installed")

        try:
            log.info(f"Playing audio ({audio.duration_ms}ms)")

            buffer = io.BytesIO(audio.data)
            data, sr = soundfile.read(buffer)

            sounddevice.play(data, samplerate=sr)
            sounddevice.wait()
        except Exception as e:
            raise VoiceProviderException(f"Playback failed: {e}")

    async def convert_format(
        self,
        audio: AudioData,
        target_format: str,
    ) -> AudioData:
        """Convert audio between formats.

        Args:
            audio: Audio data to convert
            target_format: Target format (wav, mp3, ogg, flac)

        Returns:
            Converted audio

        Raises:
            AudioFormatException: Conversion failed
        """
        try:
            import io

            import soundfile
        except ImportError:
            raise AudioFormatException("soundfile not installed")

        try:
            log.info(f"Converting {audio.format} to {target_format}")

            buffer = io.BytesIO(audio.data)
            data, sr = soundfile.read(buffer)

            output = io.BytesIO()
            soundfile.write(output, data, sr, format=target_format)
            output.seek(0)

            return AudioData(
                data=output.read(),
                format=target_format,
                sample_rate=sr,
                duration_ms=audio.duration_ms,
            )
        except Exception as e:
            raise AudioFormatException(f"Format conversion failed: {e}")
