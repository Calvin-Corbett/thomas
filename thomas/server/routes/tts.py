"""
TTS API routes
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import logging

from thomas.server.tts_service import get_tts_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    speed: float = 1.0
    format: str = "mp3"


@router.post("/synthesize")
async def synthesize_speech(request: TTSRequest):
    """
    Synthesize speech from text
    
    Returns audio file in requested format
    """
    try:
        tts = get_tts_service()
        
        audio_data = await tts.synthesize(
            text=request.text,
            voice=request.voice,
            speed=request.speed,
            output_format=request.format
        )
        
        # Determine MIME type
        mime_types = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "opus": "audio/opus",
            "ogg": "audio/ogg"
        }
        mime_type = mime_types.get(request.format, "audio/mpeg")
        
        return Response(
            content=audio_data,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'inline; filename="speech.{request.format}"'
            }
        )
        
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/voices")
async def list_voices():
    """List available voices"""
    try:
        tts = get_tts_service()
        voices = await tts.list_voices()
        return {"voices": voices, "backend": tts.backend}
    except Exception as e:
        logger.error(f"Failed to list voices: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def tts_status():
    """Get TTS service status"""
    tts = get_tts_service()
    return {
        "initialized": tts._initialized,
        "backend": tts.backend,
        "device": tts.device
    }


@router.post("/initialize")
async def initialize_tts(
    backend: str = Query("auto", description="TTS backend to use"),
    device: str = Query("auto", description="Device (cpu/cuda)")
):
    """Manually initialize TTS backend"""
    try:
        tts = get_tts_service()
        await tts.initialize(backend=backend, device=device)
        return {
            "status": "initialized",
            "backend": tts.backend,
            "device": tts.device
        }
    except Exception as e:
        logger.error(f"TTS initialization failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
