#!/usr/bin/env python3
&quot;&quot;&quot;Voice Agent: Sets up STT/TTS loop using thomas/realtime/.&quot;&quot;&quot;
import sys
import subprocess
import os

def setup_voice():
    print(&quot;🔊 Voice Agent: Installing deps...&quot;)
    # Install whisper for STT (local)
    subprocess.check_call([sys.executable, &quot;-m&quot;, &quot;pip&quot;, &quot;install&quot;, &quot;-q&quot;, &quot;openai-whisper&quot;, &quot;pyaudio&quot;])
    # Edge TTS for Windows (no key needed)
    subprocess.check_call([sys.executable, &quot;-m&quot;, &quot;pip&quot;, &quot;install&quot;, &quot;-q&quot;, &quot;edge-tts&quot;])
    
    print(&quot;✅ Deps ready. Run realtime server: thomas serve --realtime&quot;)
    print(&quot;Voice loop: Mic → STT → Brain → TTS → Speakers&quot;)
    # Test STT
    print(&quot;🧪 Test: Say something...&quot;)
    # Placeholder for full loop - integrate with thomas/realtime/stt.py tts.py

if __name__ == &quot;__main__&quot;:
    setup_voice()
