# Module: voice

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (DSP/recognition code exists, agent_mode placeholder) |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | partially — voice tools wired, agent_mode not          |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | agent_mode.py is placeholder                           |

## What This Is

Voice processing system — speech recognition, synthesis, emotion detection,
prosody analysis, phonetics, pitch tracking, speaker identification, and
voice activity detection. 4,134 lines across 14 files.

This module has two layers:
1. **DSP/recognition engine** (the bulk) — low-level signal processing with
   MFCC features, DTW matching, Viterbi decoding, HMM recognition, bigram
   language models, beam search. Uses numpy/scipy. This is real, substantial
   audio engineering code.
2. **Voice tools bridge** (`tools.py`, in `thomas/tools/voice.py`) — higher
   level integration supporting multiple STT/TTS providers (OpenAI Whisper,
   Google, local pyttsx3).

## What Actually Works

- `recognition.py` (393 lines) — DTW template matching, MFCC pipeline,
  Viterbi decoder, beam search, WER calculation. Real DSP code.
- `synthesis.py` (374 lines) — Speech synthesis. Real code.
- `emotion.py` (336 lines) — Emotion detection from voice. Real code.
- `prosody.py` (334 lines) — Prosody (rhythm/intonation) analysis. Real.
- `phonetics.py` (376 lines) — Phonetic analysis. Real.
- `pitch.py` (379 lines) — Pitch tracking. Real.
- `speaker.py` (325 lines) — Speaker identification. Real.
- `vad.py` (326 lines) — Voice activity detection. Real.
- `features.py` (456 lines) — Feature extraction pipeline. Real.
- `_types.py` (420 lines) — Type definitions. Real.
- `tools.py` (259 lines) — Voice tool wrappers. Real.

## What Is Placeholder

- `agent_mode.py` (7 lines) — **PLACEHOLDER.** Voice agent mode — the thing
  that would let you have a full voice conversation with Thomas. Not
  implemented.

## Architecture Notes

The DSP layer is self-contained and uses numpy/scipy. The voice tools
bridge in `thomas/tools/voice.py` provides the higher-level API that
the agent loop calls. Voice agent mode (continuous voice conversation)
is the missing top layer.

## Known Gaps

- agent_mode.py not implemented (voice conversation mode)
- Unclear if DSP recognition engine is wired end-to-end or standalone
- No real-time streaming voice conversation
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- The DSP files (recognition, synthesis, features, etc.) are substantial
  engineering. Don't refactor without understanding the signal processing.
