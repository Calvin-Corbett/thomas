"""
Thomas TTS Service
Provides GPU-accelerated text-to-speech using local models (Coqui TTS, Piper, etc.)
with cloud API fallbacks (ElevenLabs, Azure, etc.)
"""

import os
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional, Literal
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Model backends
TTS_BACKEND = Literal["coqui", "piper", "styletts2", "elevenlabs", "azure"]

class TTSService:
    """Manages TTS model loading and inference"""
    
    def __init__(self):
        self.backend: Optional[str] = None
        self.model = None
        self.device = "cpu"
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._initialized = False
        
    async def initialize(self, backend: str = "auto", device: str = "auto"):
        """Initialize TTS backend"""
        if self._initialized:
            return
            
        if device == "auto":
            self.device = self._detect_device()
        else:
            self.device = device
            
        if backend == "auto":
            backend = self._detect_best_backend()
            
        logger.info(f"Initializing TTS backend: {backend} on {self.device}")
        
        try:
            if backend == "coqui":
                await self._init_coqui()
            elif backend == "piper":
                await self._init_piper()
            elif backend == "styletts2":
                await self._init_styletts2()
            elif backend == "elevenlabs":
                await self._init_elevenlabs()
            elif backend == "azure":
                await self._init_azure()
            else:
                raise ValueError(f"Unknown backend: {backend}")
                
            self.backend = backend
            self._initialized = True
            logger.info(f"TTS backend {backend} initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize {backend}: {e}")
            # Try fallback
            if backend != "elevenlabs":
                logger.info("Attempting ElevenLabs fallback...")
                await self._init_elevenlabs()
                self.backend = "elevenlabs"
                self._initialized = True
    
    def _detect_device(self) -> str:
        """Detect best available device"""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"
    
    def _detect_best_backend(self) -> str:
        """Auto-detect best available backend"""
        # Try local GPU models first
        try:
            import TTS
            return "coqui"
        except ImportError:
            pass
            
        try:
            import piper
            return "piper"
        except ImportError:
            pass
        
        # Fall back to cloud
        if os.getenv("ELEVENLABS_API_KEY"):
            return "elevenlabs"
        if os.getenv("AZURE_SPEECH_KEY"):
            return "azure"
            
        # Default to coqui and install on demand
        return "coqui"
    
    async def _init_coqui(self):
        """Initialize Coqui TTS (XTTS-v2 or similar)"""
        try:
            from TTS.api import TTS as CoquiTTS
        except ImportError:
            logger.info("Installing Coqui TTS...")
            import subprocess
            subprocess.check_call(["pip", "install", "TTS"])
            from TTS.api import TTS as CoquiTTS
        
        # Use XTTS-v2 for best quality multilingual voice cloning
        model_name = "tts_models/multilingual/multi-dataset/xtts_v2"
        
        loop = asyncio.get_event_loop()
        self.model = await loop.run_in_executor(
            self.executor,
            lambda: CoquiTTS(model_name).to(self.device)
        )
        
    async def _init_piper(self):
        """Initialize Piper TTS (fast, lightweight)"""
        try:
            import piper
        except ImportError:
            logger.info("Installing Piper TTS...")
            import subprocess
            subprocess.check_call(["pip", "install", "piper-tts"])
            import piper
        
        # Download a good quality voice
        model_path = Path.home() / ".local" / "share" / "piper" / "en_US-lessac-medium.onnx"
        if not model_path.exists():
            logger.info("Downloading Piper voice model...")
            # TODO: Download model
            
        self.model = {"type": "piper", "path": str(model_path)}
    
    async def _init_styletts2(self):
        """Initialize StyleTTS2 (high quality, slower)"""
        # TODO: Implement StyleTTS2
        raise NotImplementedError("StyleTTS2 not yet implemented")
    
    async def _init_elevenlabs(self):
        """Initialize ElevenLabs API"""
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")
        
        try:
            from elevenlabs import ElevenLabs
        except ImportError:
            logger.info("Installing ElevenLabs SDK...")
            import subprocess
            subprocess.check_call(["pip", "install", "elevenlabs"])
            from elevenlabs import ElevenLabs
        
        self.model = ElevenLabs(api_key=api_key)
    
    async def _init_azure(self):
        """Initialize Azure Speech Services"""
        key = os.getenv("AZURE_SPEECH_KEY")
        region = os.getenv("AZURE_SPEECH_REGION", "eastus")
        
        if not key:
            raise ValueError("AZURE_SPEECH_KEY not set")
        
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError:
            logger.info("Installing Azure Speech SDK...")
            import subprocess
            subprocess.check_call(["pip", "install", "azure-cognitiveservices-speech"])
            import azure.cognitiveservices.speech as speechsdk
        
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        self.model = {"config": speech_config}
    
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        output_format: str = "mp3"
    ) -> bytes:
        """
        Synthesize speech from text
        
        Args:
            text: Text to synthesize
            voice: Voice ID/name (backend-specific)
            speed: Speech rate (0.5 - 2.0)
            output_format: Output format (mp3, wav, opus)
            
        Returns:
            Audio bytes
        """
        if not self._initialized:
            await self.initialize()
        
        if self.backend == "coqui":
            return await self._synthesize_coqui(text, voice, speed, output_format)
        elif self.backend == "piper":
            return await self._synthesize_piper(text, voice, speed, output_format)
        elif self.backend == "elevenlabs":
            return await self._synthesize_elevenlabs(text, voice, speed, output_format)
        elif self.backend == "azure":
            return await self._synthesize_azure(text, voice, speed, output_format)
        else:
            raise ValueError(f"Backend {self.backend} not implemented")
    
    async def _synthesize_coqui(self, text: str, voice: Optional[str], speed: float, fmt: str) -> bytes:
        """Synthesize with Coqui TTS"""
        loop = asyncio.get_event_loop()
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            # Run synthesis in thread pool
            await loop.run_in_executor(
                self.executor,
                lambda: self.model.tts_to_file(
                    text=text,
                    file_path=tmp_path,
                    speaker_wav=voice if voice else None,
                    language="en",
                    speed=speed
                )
            )
            
            # Read audio file
            with open(tmp_path, "rb") as f:
                audio_data = f.read()
            
            # Convert format if needed
            if fmt != "wav":
                audio_data = await self._convert_audio(audio_data, "wav", fmt)
            
            return audio_data
            
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    async def _synthesize_piper(self, text: str, voice: Optional[str], speed: float, fmt: str) -> bytes:
        """Synthesize with Piper TTS"""
        # TODO: Implement Piper synthesis
        raise NotImplementedError("Piper synthesis not yet implemented")
    
    async def _synthesize_elevenlabs(self, text: str, voice: Optional[str], speed: float, fmt: str) -> bytes:
        """Synthesize with ElevenLabs"""
        from elevenlabs import VoiceSettings
        
        voice_id = voice or "21m00Tcm4TlvDq8ikWAM"  # Default: Rachel
        
        loop = asyncio.get_event_loop()
        audio_generator = await loop.run_in_executor(
            self.executor,
            lambda: self.model.generate(
                text=text,
                voice=voice_id,
                model="eleven_turbo_v2",
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    speed=speed
                )
            )
        )
        
        # Collect audio chunks
        audio_bytes = b"".join(audio_generator)
        
        # ElevenLabs returns MP3 by default
        if fmt != "mp3":
            audio_bytes = await self._convert_audio(audio_bytes, "mp3", fmt)
        
        return audio_bytes
    
    async def _synthesize_azure(self, text: str, voice: Optional[str], speed: float, fmt: str) -> bytes:
        """Synthesize with Azure Speech"""
        import azure.cognitiveservices.speech as speechsdk
        
        voice_name = voice or "en-US-JennyNeural"
        
        # Create synthesizer
        audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=False)
        speech_config = self.model["config"]
        speech_config.speech_synthesis_voice_name = voice_name
        
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config
        )
        
        # Build SSML with speed control
        ssml = f"""
        <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
            <voice name="{voice_name}">
                <prosody rate="{speed}">
                    {text}
                </prosody>
            </voice>
        </speak>
        """
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self.executor,
            lambda: synthesizer.speak_ssml(ssml)
        )
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            
            # Azure returns WAV by default
            if fmt != "wav":
                audio_data = await self._convert_audio(audio_data, "wav", fmt)
            
            return audio_data
        else:
            raise Exception(f"Azure TTS failed: {result.reason}")
    
    async def _convert_audio(self, audio_data: bytes, from_fmt: str, to_fmt: str) -> bytes:
        """Convert audio format using ffmpeg"""
        import subprocess
        
        with tempfile.NamedTemporaryFile(suffix=f".{from_fmt}", delete=False) as tmp_in:
            tmp_in.write(audio_data)
            tmp_in_path = tmp_in.name
        
        with tempfile.NamedTemporaryFile(suffix=f".{to_fmt}", delete=False) as tmp_out:
            tmp_out_path = tmp_out.name
        
        try:
            subprocess.run(
                ["ffmpeg", "-i", tmp_in_path, "-y", tmp_out_path],
                check=True,
                capture_output=True
            )
            
            with open(tmp_out_path, "rb") as f:
                return f.read()
                
        finally:
            if os.path.exists(tmp_in_path):
                os.unlink(tmp_in_path)
            if os.path.exists(tmp_out_path):
                os.unlink(tmp_out_path)
    
    async def list_voices(self) -> list[dict]:
        """List available voices for current backend"""
        if not self._initialized:
            await self.initialize()
        
        if self.backend == "elevenlabs":
            loop = asyncio.get_event_loop()
            voices = await loop.run_in_executor(
                self.executor,
                lambda: self.model.voices.get_all()
            )
            return [{"id": v.voice_id, "name": v.name} for v in voices.voices]
        
        elif self.backend == "azure":
            # Return common Azure neural voices
            return [
                {"id": "en-US-JennyNeural", "name": "Jenny (US Female)"},
                {"id": "en-US-GuyNeural", "name": "Guy (US Male)"},
                {"id": "en-US-AriaNeural", "name": "Aria (US Female)"},
                {"id": "en-GB-SoniaNeural", "name": "Sonia (UK Female)"},
                {"id": "en-GB-RyanNeural", "name": "Ryan (UK Male)"},
            ]
        
        elif self.backend == "coqui":
            return [{"id": "default", "name": "Default Voice"}]
        
        return []
    
    def shutdown(self):
        """Clean up resources"""
        self.executor.shutdown(wait=False)
        self.model = None
        self._initialized = False


# Global singleton
_tts_service: Optional[TTSService] = None

def get_tts_service() -> TTSService:
    """Get or create global TTS service instance"""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
