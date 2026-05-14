#!/usr/bin/env python3
# Scaffold voice-agent demo — installs deps for STT/TTS loop. Not imported
# by any production module.
"""Voice Agent: Sets up STT/TTS loop using thomas/realtime/."""
import subprocess
import sys


def setup_voice():
    print("🔊 Voice Agent: Installing deps...")
    # Install whisper for STT (local)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "openai-whisper", "pyaudio"])
    # Edge TTS for Windows (no key needed)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "edge-tts"])

    print("✅ Deps ready. Run realtime server: thomas serve --realtime")
    print("Voice loop: Mic → STT → Brain → TTS → Speakers")
    # Test STT
    print("🧪 Test: Say something...")
    # Placeholder for full loop - integrate with thomas/realtime/stt.py tts.py

if __name__ == "__main__":
    setup_voice()
