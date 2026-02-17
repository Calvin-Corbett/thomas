from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class QualityMetrics:
    # Approximate conversational quality metrics (actionable, not academic)
    barge_in_events: int = 0
    assistant_canceled: int = 0
    stt_duplicates: int = 0
    vad_false_starts: int = 0
    vad_false_ends: int = 0
    ws_reconnects: int = 0
    audio_underruns: int = 0
    partial_transcripts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
